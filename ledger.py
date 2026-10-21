"""
ledger.py - your local record of what you own and how scans performed.

Everything lives in one SQLite file (signal_ledger.db) next to the app, on your
computer only. Individual transactions are the source of truth: open positions,
average cost and profit/loss are always recalculated from them, so partial
sells, adding to a position and closing out all work without hand-editing a
"current holdings" row.

Nothing here connects to Robinhood. You type your trades in (the app has a
form); a CSV export is available for backups.
"""

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

DB_PATH = Path(__file__).with_name("signal_ledger.db")
TS_FMT = "%Y-%m-%d %H:%M:%S"

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,              -- BUY, SELL, or ADJUST (changes stop/target only)
    qty REAL NOT NULL DEFAULT 0,
    price REAL NOT NULL DEFAULT 0,
    fees REAL NOT NULL DEFAULT 0,
    strategy TEXT DEFAULT '',
    stop REAL,
    target REAL,
    notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS watchlists (
    name TEXT PRIMARY KEY,
    symbols TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS price_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,         -- above or below
    price REAL NOT NULL,
    note TEXT DEFAULT '',
    created TEXT NOT NULL,
    fired TEXT
);
CREATE TABLE IF NOT EXISTS scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    preset TEXT NOT NULL,
    interval TEXT DEFAULT '',
    criteria TEXT DEFAULT '',
    summary TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS checklist (
    day TEXT NOT NULL,
    item TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, item)
);
CREATE TABLE IF NOT EXISTS day_notes (
    day TEXT PRIMARY KEY,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS trade_lessons (
    key TEXT PRIMARY KEY,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS scan_results (
    scan_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    price REAL,
    stop REAL,
    target REAL,
    setup TEXT DEFAULT '',
    signal TEXT DEFAULT '',
    extra TEXT DEFAULT ''
);
"""


def _ts(value=None):
    t = pd.Timestamp(value) if value is not None else pd.Timestamp.now()
    if t.tzinfo is not None:
        t = t.tz_convert(None)
    return t


def _num(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else float(x)


# ------------------------------------------------------------------ pure calculations
def build_positions(tx):
    """
    Walk the transactions in time order using average cost.
    Returns {"open": DataFrame, "closed": DataFrame, "realized": DataFrame}.
    """
    open_pos, closed, realized = {}, [], []
    for r in tx.itertuples(index=False):
        s, side = r.symbol, r.side
        p = open_pos.get(s)
        stop, target = _num(r.stop), _num(r.target)
        ts = pd.Timestamp(r.ts)

        if side == "BUY":
            if p is None:
                p = dict(symbol=s, qty=0.0, cost=0.0, opened=ts, strategy=r.strategy or "", stop0=None,
                         stop=None, target=None, realized=0.0, bought_qty=0.0, bought_cost=0.0,
                         sold_qty=0.0, sold_value=0.0)
                open_pos[s] = p
            p["qty"] += r.qty
            p["cost"] += r.qty * r.price + r.fees
            p["bought_qty"] += r.qty
            p["bought_cost"] += r.qty * r.price + r.fees
            if not p["strategy"] and r.strategy:
                p["strategy"] = r.strategy
        elif side == "SELL" and p is not None:
            qty = min(r.qty, p["qty"])
            avg = p["cost"] / p["qty"]
            pnl = qty * (r.price - avg) - r.fees
            p["realized"] += pnl
            p["cost"] -= avg * qty
            p["qty"] -= qty
            p["sold_qty"] += qty
            p["sold_value"] += qty * r.price
            realized.append({"ts": ts, "symbol": s, "pnl": pnl})
        elif side != "ADJUST":
            continue

        if p is not None:
            if stop is not None:
                p["stop"] = stop
                if p["stop0"] is None:
                    p["stop0"] = stop
            if target is not None:
                p["target"] = target
            if side == "SELL" and p["qty"] <= 1e-9:
                closed.append(_close_record(p, ts))
                del open_pos[s]

    now = pd.Timestamp.now()
    open_df = pd.DataFrame([{
        "Symbol": p["symbol"], "Shares": p["qty"], "Avg cost": p["cost"] / p["qty"], "Cost basis": p["cost"],
        "Opened": p["opened"], "Days held": max((now - p["opened"]).days, 0),
        "Initial stop": p["stop0"], "Stop": p["stop"], "Target": p["target"],
        "Strategy": p["strategy"], "Realized so far": p["realized"],
    } for p in open_pos.values()], columns=[
        "Symbol", "Shares", "Avg cost", "Cost basis", "Opened", "Days held", "Initial stop", "Stop",
        "Target", "Strategy", "Realized so far"])
    closed_df = pd.DataFrame(closed, columns=[
        "Symbol", "Opened", "Closed", "Days", "Shares", "Avg entry", "Avg exit", "P&L $", "P&L %", "R", "Strategy"])
    realized_df = pd.DataFrame(realized, columns=["ts", "symbol", "pnl"])
    return {"open": open_df, "closed": closed_df, "realized": realized_df}


def _close_record(p, ts):
    avg_entry = p["bought_cost"] / p["bought_qty"]
    avg_exit = p["sold_value"] / p["sold_qty"] if p["sold_qty"] else np.nan
    risk = (avg_entry - p["stop0"]) * p["bought_qty"] if p["stop0"] else np.nan
    return {"Symbol": p["symbol"], "Opened": p["opened"], "Closed": ts,
            "Days": max((ts - p["opened"]).days, 0), "Shares": p["bought_qty"],
            "Avg entry": avg_entry, "Avg exit": avg_exit, "P&L $": p["realized"],
            "P&L %": p["realized"] / p["bought_cost"] * 100,
            "R": (p["realized"] / risk) if (risk == risk and risk > 0) else np.nan,
            "Strategy": p["strategy"]}


def value_positions(open_df, prices, account_value=0.0):
    """Add live price, P&L, risk to stop and exposure. A position with no stop counts as fully at risk."""
    d = open_df.copy()
    if d.empty:
        for col in ("Price", "Market value", "Unrealized $", "Unrealized %", "Risk to stop $",
                    "To stop %", "To target %", "Exposure %"):
            d[col] = pd.Series(dtype=float)
        return d
    d["Price"] = d["Symbol"].map(prices)
    ref = d["Price"].fillna(d["Avg cost"])
    d["Market value"] = d["Shares"] * ref
    d["Unrealized $"] = d["Market value"] - d["Cost basis"]
    d["Unrealized %"] = d["Unrealized $"] / d["Cost basis"] * 100
    d["Risk to stop $"] = np.where(d["Stop"].notna(),
                                   np.maximum(ref - d["Stop"].fillna(0), 0) * d["Shares"],
                                   d["Shares"] * ref)
    d["To stop %"] = (d["Stop"] / ref - 1) * 100
    d["To target %"] = (d["Target"] / ref - 1) * 100
    d["Exposure %"] = d["Market value"] / account_value * 100 if account_value > 0 else np.nan
    return d


def stopped_out(valued):
    """Open positions whose live price is at or below the recorded stop (the stop order would have triggered)."""
    if valued is None or valued.empty:
        return valued.iloc[0:0] if valued is not None else valued
    m = valued["Price"].notna() & valued["Stop"].notna() & (valued["Price"] <= valued["Stop"])
    return valued[m]


def portfolio_summary(valued, closed, realized, account_value=0.0, reserve=0.0, today=None):
    """Headline numbers: exposure, open risk, realized P&L today and overall, cash left to invest."""
    today = pd.Timestamp(today or pd.Timestamp.now()).date()
    mv = float(valued["Market value"].sum()) if not valued.empty else 0.0
    unreal = float(valued["Unrealized $"].sum()) if not valued.empty else 0.0
    partial = float(valued["Realized so far"].sum()) if not valued.empty else 0.0
    realized_total = (float(closed["P&L $"].sum()) if not closed.empty else 0.0) + partial
    realized_today = (float(realized.loc[realized["ts"].dt.date == today, "pnl"].sum())
                      if not realized.empty else 0.0)
    return {
        "positions": int(len(valued)),
        "market_value": mv,
        "unrealized": unreal,
        "realized_total": realized_total,
        "realized_today": realized_today,
        "open_risk": float(valued["Risk to stop $"].sum()) if not valued.empty else 0.0,
        "exposure_pct": (mv / account_value * 100) if account_value > 0 else None,
        "cash_available": max(account_value - mv - reserve, 0.0) if account_value > 0 else None,
        "largest_pct": (float(valued["Exposure %"].max()) if account_value > 0 and not valued.empty else None),
    }


def closed_trade_stats(closed):
    """Win rate, average win/loss and profit factor for finished trades."""
    if closed.empty:
        return {}
    pnl = closed["P&L $"]
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    return {
        "trades": int(len(closed)),
        "win_rate": float((pnl > 0).mean() * 100),
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "total": float(pnl.sum()),
        "avg_r": float(closed["R"].mean()) if closed["R"].notna().any() else float("nan"),
    }


def sell_urgency(sig, price=None, stop=None):
    """
    How much attention a SELL signal deserves, on a 1-10 scale (10 = look right now).
    Every point comes from something you can see, so the score is explainable:
      start at 1
      + 1 to 3  how many patterns agree (more agreement = stronger signal)
      + 0 to 2  how fresh it is (this bar = 2, within 2 bars = 1)
      + 0 to 2  trend damage (price under the 200 EMA = 2, under the 20 EMA = 1)
      + 0 to 2  how close price is to your stop (within 3% = 2, within 6% = 1)
      at or below your stop = 10
    Returns (score, drivers) where drivers is a list of (technical, plain) sentences.
    """
    drivers = []
    score = 1
    thr = float(sig.get("threshold") or 3)
    s = float(sig.get("score") or thr)
    agree = int(min(3, max(1, int(s - thr) + 1)))
    score += agree
    drivers.append((f"+{agree} patterns agreeing (signal strength {s:.0f}, needs {thr:.0f})",
                    f"+{agree} because {'several' if agree > 1 else 'a few'} different clues point the same way"))
    ago = sig.get("bars_ago")
    if ago is not None:
        fresh = 2 if ago == 0 else 1 if ago <= 2 else 0
        score += fresh
        if fresh:
            drivers.append((f"+{fresh} fresh signal ({'this bar' if ago == 0 else f'{ago} bars ago'})",
                            f"+{fresh} because it only just happened"))
    if sig.get("above200") is False:
        score += 2
        drivers.append(("+2 price is under the 200 EMA (long-term trend broken)",
                        "+2 because the long-term trend has turned down"))
    elif sig.get("above20") is False:
        score += 1
        drivers.append(("+1 price is under the 20 EMA (short-term trend weakening)",
                        "+1 because the stock slipped under its short-term average"))
    elif sig.get("above200") is True:
        drivers.append(("+0 price is still above the 200 EMA (bigger uptrend intact)",
                        "+0 because the long-term trend is still up, which lowers the worry"))
    if price is not None and stop is not None and not pd.isna(price) and not pd.isna(stop) and price > 0:
        dist = (price - stop) / price * 100
        if dist <= 0:
            return 10, [("10 price is at or below your stop", "10 because the price hit your safety exit")]
        near = 2 if dist <= 3 else 1 if dist <= 6 else 0
        score += near
        if near:
            drivers.append((f"+{near} price is {dist:.1f}% above your stop",
                            f"+{near} because the price is only {dist:.1f}% away from your safety exit"))
    return int(max(1, min(10, score))), drivers


URGENCY_BANDS = [
    (3, "Minor", "Probably an ordinary wiggle.",
     "Usually noise. Make sure your stop order is in place and keep an eye on it.",
     "Probably nothing to worry about. Check that your safety exit (stop order) is set, then carry on."),
    (5, "Worth a look", "Open the chart and see if the trend still holds.",
     "Open the chart. If the reason you bought no longer holds, think about trimming or exiting.",
     "Have a look at the chart. If the reason you bought the stock is gone, think about selling."),
    (7, "Serious", "Decide today whether to hold or sell.",
     "Decide today whether to sell or hold. If you are in profit, consider moving your stop up.",
     "Decide today: sell, or keep holding on purpose. If you are winning, think about raising your safety exit."),
    (10, "Urgent", "Check the stock and your stop order now.",
     "Check the chart and your stop order right now.",
     "Look at this one now, and make sure your safety exit (stop order) is really set."),
]


def urgency_band(score):
    for top, name, _, tech, plain in URGENCY_BANDS:
        if score <= top:
            return name, tech, plain
    return URGENCY_BANDS[-1][1], URGENCY_BANDS[-1][3], URGENCY_BANDS[-1][4]


def stop_suggestions(valued, plain=False):
    """
    Ideas for raising a stop once a trade is working, so a winner is less likely to turn into a loss.
    Uses R: 1R is what you risked at entry (entry minus your first stop).
      up 1R or more  -> move the stop to break-even (your entry price)
      up 2R or more  -> move it to lock in +1R
      up 3R or more  -> move it to lock in +2R
    Returns a list of dicts (Symbol, R now, Current stop, Suggested stop, Locks in $, text).
    """
    out = []
    if valued is None or valued.empty:
        return out
    for _, r in valued.iterrows():
        avg, stop0, stop, price, sh = r["Avg cost"], r["Initial stop"], r["Stop"], r.get("Price"), r["Shares"]
        if any(pd.isna(x) for x in (avg, stop0, price)) or stop0 >= avg or avg <= 0:
            continue
        risk = avg - stop0
        gain_r = (price - avg) / risk
        if gain_r < 1.0:
            continue
        lock_r = 2 if gain_r >= 3 else 1 if gain_r >= 2 else 0
        new = avg + lock_r * risk
        new = round(new, 2 if new >= 1 else 4)
        cur = 0.0 if pd.isna(stop) else float(stop)
        if new <= cur + 1e-9 or new >= price * 0.995:
            continue
        locked = (new - avg) * sh
        s = r["Symbol"]
        if plain:
            win = ("so if the price turns around you get your money back instead of losing" if lock_r == 0
                   else f"so even if the price turns around you keep about ${locked:,.2f} of profit")
            text = (f"{s} is winning: it is up about {gain_r:.1f} times the amount you risked. "
                    f"Raise your safety exit (stop) to ${new:,.2f}, {win}.")
        else:
            what = "break-even (your entry)" if lock_r == 0 else f"+{lock_r}R (about ${locked:,.2f} locked in)"
            text = (f"{s}: up {gain_r:.1f}R (price {price:.2f}, entry {avg:.2f}). Consider raising your stop "
                    f"from {'none' if cur == 0 else f'{cur:.2f}'} to {new:.2f}, which protects {what}.")
        out.append({"Symbol": s, "R now": round(gain_r, 2), "Current stop": None if cur == 0 else cur,
                    "Suggested stop": new, "Locks in $": round(locked, 2), "text": text})
    return out


def stop_progress(valued):
    """
    How close each position is to its next stop-raise (the same R steps as stop_suggestions: up 1R -> break-even,
    2R -> lock +1R, 3R -> lock +2R). Returns a list of dicts with Symbol, Price, Entry, Gain R, Current stop,
    Next stop, Raise at (price), Progress (0-100 or None), Ready (bool) and Status text.
    """
    out = []
    if valued is None or valued.empty:
        return out
    for _, r in valued.iterrows():
        s, avg, stop0, stop, price = r["Symbol"], r["Avg cost"], r["Initial stop"], r["Stop"], r.get("Price")
        base = {"Symbol": s, "Price": None if pd.isna(price) else float(price), "Entry": float(avg), "Gain R": None,
                "Current stop": None if pd.isna(stop) else float(stop), "Next stop": None, "Raise at": None,
                "Progress": None, "Ready": False}
        if pd.isna(stop0) or pd.isna(avg) or stop0 >= avg or avg <= 0:
            out.append({**base, "Status": "Record a stop below your entry price to track progress."})
            continue
        if pd.isna(price):
            out.append({**base, "Status": "No current price, so progress can't be measured right now."})
            continue
        risk = avg - stop0
        gain_r = (price - avg) / risk
        cur = 0.0 if pd.isna(stop) else float(stop)
        base["Gain R"] = round(float(gain_r), 2)
        step = None
        for m in (1, 2, 3):
            new = round(avg + (m - 1) * risk, 2 if avg + (m - 1) * risk >= 1 else 4)
            if new > cur + 1e-9:
                step = (m, new)
                break
        if step is None:
            out.append({**base, "Progress": 100.0, "Status": "Fully protected: your stop is already at +2R or better."})
            continue
        m, new = step
        trigger = avg + m * risk
        base.update({"Next stop": new, "Raise at": round(float(trigger), 2 if trigger >= 1 else 4)})
        if gain_r >= m and new < price * 0.995:
            out.append({**base, "Progress": 100.0, "Ready": True,
                        "Status": f"Time to raise your stop to {new:,.2f}."})
            continue
        prog = max(0.0, min(1.0, gain_r - (m - 1))) * 100
        away = (trigger / price - 1) * 100
        out.append({**base, "Progress": round(float(prog), 1),
                    "Status": f"{prog:.0f}% of the way. Raise your stop to {new:,.2f} when the price reaches {trigger:,.2f} "
                              f"({away:+.1f}% from here)."})
    return out


def position_alerts(valued, extras=None, near_pct=1.0, earnings_days=5, plain=False):
    """
    Plain-English warnings about what you own. `extras` may map symbol ->
    {"catalyst": ..., "signal": ...} (from the scanner's catalyst and signal checks).
    Returns a list of (level, text) with level in error / warning / info / success.
    Text may use Markdown. SELL signals say why and carry a 1-10 importance score.
    """
    extras = extras or {}
    out = []
    for _, r in valued.iterrows():
        s, price, stop, target = r["Symbol"], r.get("Price"), r["Stop"], r["Target"]
        if pd.isna(stop):
            out.append(("error", f"{s}: no stop is recorded. Place a stop order and record it."
                        if not plain else f"{s}: no safety exit (stop order) is recorded. Place one and record it here."))
        elif pd.notna(price):
            if price <= stop:
                out.append(("error", f"{s}: price {price:.2f} is at or below your stop {stop:.2f}. "
                                     "Check whether your stop order filled."))
            elif (price - stop) / price * 100 <= near_pct:
                out.append(("warning", f"{s}: price {price:.2f} is within {near_pct:g}% of your stop {stop:.2f}."))
        if pd.notna(target) and pd.notna(price):
            if price >= target:
                out.append(("success", f"{s}: price {price:.2f} reached your target {target:.2f}. "
                                       "Consider taking profit."))
            elif (target - price) / price * 100 <= near_pct:
                out.append(("success", f"{s}: price {price:.2f} is within {near_pct:g}% of your target {target:.2f}."))
        ex = extras.get(s)
        if ex:
            cat, sig = ex.get("catalyst") or {}, ex.get("signal") or {}
            d = cat.get("earnings_days")
            if d is not None and d <= earnings_days:
                out.append(("warning", f"{s}: earnings report in {d} day(s). Overnight gaps can jump past a stop."
                            if not plain else f"{s}: the company reports earnings in {d} day(s). Big news can make the "
                                              "price jump over your safety exit overnight."))
            if cat.get("flags"):
                out.append(("warning", f"{s}: red-flag headlines this week ({', '.join(cat['flags'])})."))
            if str(sig.get("label", "")).startswith("SELL"):
                n, drivers = sell_urgency(sig, price, stop)
                band, tech_do, plain_do = urgency_band(n)
                level = "error" if n >= 8 else "warning" if n >= 4 else "info"
                why = (sig.get("reasons_plain") if plain else sig.get("reasons_short")) or sig.get("reasons") or []
                why = [w for w in why if not w.startswith(("CAUTION", "Caution", "Careful"))][:2]
                lines = [f"**{s} · SELL signal · importance {n}/10 ({band})**",
                         f"{'What happened' if plain else 'Signal'}: {sig['label']} on the daily chart."]
                if why:
                    lines.append("Why:\n" + "\n".join(f"- {w}" for w in why))
                lines.append("What moved the score: " + "; ".join(d_[1 if plain else 0] for d_ in drivers) + ".")
                lines.append(("What to do: " + (plain_do if plain else tech_do)))
                out.append((level, "\n\n".join(lines)))
    for sug in stop_suggestions(valued, plain=plain):
        out.append(("success", sug["text"] + " Replace your stop order at Robinhood, then record it in the Portfolio tab."))
    return out


def price_alert_hits(alerts_df, prices):
    """Which saved price alerts have been crossed. Returns a list of (id, text)."""
    hits = []
    for r in alerts_df.itertuples():
        if r.fired:
            continue
        px = prices.get(r.symbol)
        if px is None:
            continue
        if (r.direction == "above" and px >= r.price) or (r.direction == "below" and px <= r.price):
            note = f" ({r.note})" if r.note else ""
            hits.append((int(r.id), f"{r.symbol} is {px:.2f}, {r.direction} your alert level {r.price:.2f}{note}."))
    return hits


def equity_curve(tx, history, today=None):
    """
    Daily profit/loss since your first trade: realized (money from finished sells, after fees) plus unrealized
    (what you still hold, valued at each day's close). `history` maps symbol -> Series of daily closes.
    A symbol with no price history is valued at what you paid, so it adds nothing until it is sold.
    Returns a DataFrame indexed by date with columns Realized, Unrealized, Total.
    """
    cols = ["Realized", "Unrealized", "Total"]
    if tx is None or tx.empty:
        return pd.DataFrame(columns=cols)
    t = tx[tx["side"].isin(["BUY", "SELL"])].copy()
    if t.empty:
        return pd.DataFrame(columns=cols)
    t["ts"] = pd.to_datetime(t["ts"])
    t = t.sort_values(["ts", "id"] if "id" in t.columns else ["ts"])
    start = t["ts"].min().normalize()
    end = pd.Timestamp(today or pd.Timestamp.now()).normalize()
    days = pd.bdate_range(start, end)
    if len(days) == 0 or days[-1] < end:       # weekend/holiday: still end on today
        days = days.append(pd.DatetimeIndex([end])) if len(days) == 0 or days[-1] != end else days
    px = {}
    for sym, ser in (history or {}).items():
        ser = pd.Series(ser).dropna()
        if ser.empty:
            continue
        idx = pd.DatetimeIndex(ser.index)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        ser.index = idx.normalize()
        ser = ser[~ser.index.duplicated(keep="last")]
        px[sym.upper()] = ser.reindex(ser.index.union(days)).ffill()
    rows, k, n = [], 0, len(t)
    recs = list(t.itertuples(index=False))
    qty, cost, realized = {}, {}, 0.0
    for d in days:
        eod = d + pd.Timedelta(days=1)
        while k < n and pd.Timestamp(recs[k].ts) < eod:
            r = recs[k]; k += 1
            q, c = qty.get(r.symbol, 0.0), cost.get(r.symbol, 0.0)
            if r.side == "BUY":
                qty[r.symbol], cost[r.symbol] = q + r.qty, c + r.qty * r.price + r.fees
            elif q > 1e-12:
                sold = min(r.qty, q)
                avg = c / q
                realized += sold * (r.price - avg) - r.fees
                qty[r.symbol], cost[r.symbol] = q - sold, c - avg * sold
        unreal = 0.0
        for sym, q in qty.items():
            if q <= 1e-12:
                continue
            ser = px.get(sym)
            price = ser.get(d) if ser is not None else None
            if price is None or pd.isna(price):
                continue                        # no price: valued at cost
            unreal += q * float(price) - cost[sym]
        rows.append((d, realized, unreal, realized + unreal))
    out = pd.DataFrame(rows, columns=["Date"] + cols).set_index("Date")
    return out


def fetch_prices(symbols):
    """Latest prices from Yahoo (can be delayed). Missing symbols are simply left out."""
    import yfinance as yf

    syms = sorted(set(symbols))
    out = {}
    try:
        import yahoo_guard as yg
    except Exception:
        yg = None
    if yg and yg.limited_until():
        return out    # Yahoo told us to back off; don't make it worse
    for s in syms:
        px = None
        try:
            px = yf.Ticker(s).fast_info["last_price"]
        except Exception as e:
            if yg and yg.note_if_limited(e):
                return out
            px = None
        if px is None or px != px or px <= 0:
            try:
                h = yf.Ticker(s).history(period="5d", interval="1d")
                px = float(h["Close"].dropna().iloc[-1])
            except Exception as e:
                if yg and yg.note_if_limited(e):
                    return out
                px = None
        if px and px == px and px > 0:
            out[s] = float(px)
    missing = [s for s in syms if s not in out]
    if missing:   # last resort: one batch download for whatever is still missing
        try:
            d = yf.download(missing, period="5d", interval="1d", progress=False, auto_adjust=True, threads=False)
            close = d["Close"]
            if hasattr(close, "columns"):
                for s in missing:
                    if s in close.columns and close[s].dropna().size:
                        out[s] = float(close[s].dropna().iloc[-1])
            elif len(missing) == 1 and close.dropna().size:
                out[missing[0]] = float(close.dropna().iloc[-1])
        except Exception:
            pass
    return out


# ------------------------------------------------------------------ the database
class Store:
    def __init__(self, path=None):
        self.path = Path(path) if path else DB_PATH
        self.con = sqlite3.connect(str(self.path), check_same_thread=False)
        self.con.executescript(SCHEMA)
        self.con.commit()

    def close(self):
        self.con.close()

    # ---- transactions
    def version(self):
        """Changes whenever transactions change; used to refresh cached portfolio numbers."""
        row = self.con.execute("SELECT COUNT(*), COALESCE(MAX(id), 0) FROM transactions").fetchone()
        return int(row[0]) * 1_000_000 + int(row[1])

    def transactions(self):
        df = pd.read_sql_query("SELECT * FROM transactions ORDER BY ts, id", self.con)
        df["ts"] = pd.to_datetime(df["ts"])
        return df

    def shares_held(self, symbol, as_of=None):
        tx = self.transactions()
        tx = tx[tx["symbol"] == symbol.upper()]
        if as_of is not None:
            tx = tx[tx["ts"] <= _ts(as_of)]
        return float(tx.loc[tx["side"] == "BUY", "qty"].sum() - tx.loc[tx["side"] == "SELL", "qty"].sum())

    def add_transaction(self, symbol, side, qty=0.0, price=0.0, ts=None, fees=0.0,
                        strategy="", stop=None, target=None, notes=""):
        symbol, side = str(symbol).strip().upper(), str(side).strip().upper()
        if not symbol:
            raise ValueError("Enter a symbol.")
        if side not in ("BUY", "SELL", "ADJUST"):
            raise ValueError("Side must be BUY, SELL or ADJUST.")
        if side in ("BUY", "SELL") and (qty <= 0 or price <= 0):
            raise ValueError("Shares and price must be greater than zero.")
        if side == "ADJUST" and stop is None and target is None:
            raise ValueError("Enter a new stop and/or target.")
        when = _ts(ts)
        if side == "SELL":
            held = self.shares_held(symbol, as_of=when)
            if qty > held + 1e-9:
                raise ValueError(f"You only hold {held:g} shares of {symbol} at that time.")
        if side == "ADJUST" and self.shares_held(symbol) <= 1e-9:
            raise ValueError(f"You don't hold {symbol}, so there is no stop or target to change.")
        cur = self.con.execute(
            "INSERT INTO transactions (ts, symbol, side, qty, price, fees, strategy, stop, target, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (when.strftime(TS_FMT), symbol, side, float(qty), float(price), float(fees), strategy,
             _num(stop), _num(target), notes))
        self.con.commit()
        return int(cur.lastrowid)

    def update_levels(self, tx_id, stop=None, target=None):
        """Fix the stop and target recorded on one trade (for a typo). None clears the value. Nothing else changes."""
        row = self.con.execute("SELECT id, side, price FROM transactions WHERE id = ?", (int(tx_id),)).fetchone()
        if row is None:
            raise ValueError("That trade no longer exists.")
        stop, target = _num(stop), _num(target)
        for name, v in (("stop", stop), ("target", target)):
            if v is not None and v <= 0:
                raise ValueError(f"The {name} must be more than zero (or left empty).")
        if row[1] == "ADJUST" and stop is None and target is None:
            raise ValueError("A stop-or-target adjustment needs at least one of them. Delete the trade instead.")
        self.con.execute("UPDATE transactions SET stop = ?, target = ? WHERE id = ?", (stop, target, int(tx_id)))
        self.con.commit()

    def delete_transaction(self, tx_id):
        """Delete one transaction, refusing if it would leave a later sell without shares."""
        tx = self.transactions()
        rest = tx[tx["id"] != int(tx_id)]
        held = {}
        for r in rest.itertuples():
            if r.side == "BUY":
                held[r.symbol] = held.get(r.symbol, 0.0) + r.qty
            elif r.side == "SELL":
                held[r.symbol] = held.get(r.symbol, 0.0) - r.qty
                if held[r.symbol] < -1e-9:
                    raise ValueError(f"Deleting that would leave a later {r.symbol} sell without shares. "
                                     "Delete the later sell first.")
        self.con.execute("DELETE FROM transactions WHERE id = ?", (int(tx_id),))
        self.con.commit()

    def open_position_tx_ids(self, symbol):
        """Ids of every transaction in the CURRENT open position for `symbol`
        (from the last time it was flat), so a whole mistaken entry can be removed."""
        tx = self.transactions()
        tx = tx[tx["symbol"] == symbol.upper()].sort_values(["ts", "id"])
        ids, qty = [], 0.0
        for r in tx.itertuples():
            if r.side == "BUY":
                qty += r.qty
            elif r.side == "SELL":
                qty -= r.qty
            if qty <= 1e-9 and r.side == "SELL":
                ids = []          # position was closed here; start counting fresh
                qty = 0.0
            else:
                ids.append(int(r.id))
        return ids

    def remove_open_position(self, symbol):
        """Delete all records of the current open position (for entries made by mistake)."""
        ids = self.open_position_tx_ids(symbol)
        if not ids:
            raise ValueError(f"No open {symbol.upper()} position to remove.")
        self.con.executemany("DELETE FROM transactions WHERE id = ?", [(i,) for i in ids])
        self.con.commit()
        return len(ids)

    def positions(self):
        return build_positions(self.transactions())

    # ---- watchlists
    def save_watchlist(self, name, symbols):
        name = name.strip()
        syms = sorted({s.strip().upper() for s in symbols if s.strip()})
        if not name or not syms:
            raise ValueError("Give the watchlist a name and at least one symbol.")
        self.con.execute("INSERT OR REPLACE INTO watchlists (name, symbols) VALUES (?, ?)",
                         (name, ",".join(syms)))
        self.con.commit()

    def watchlists(self):
        return {r[0]: [s for s in r[1].split(",") if s]
                for r in self.con.execute("SELECT name, symbols FROM watchlists ORDER BY name")}

    def delete_watchlist(self, name):
        self.con.execute("DELETE FROM watchlists WHERE name = ?", (name,))
        self.con.commit()

    # ---- daily checklist, notes and lessons
    def checklist_state(self, day):
        rows = self.con.execute("SELECT item, done FROM checklist WHERE day = ?", (str(day),)).fetchall()
        return {r[0]: bool(r[1]) for r in rows}

    def set_check(self, day, item, done):
        self.con.execute("INSERT OR REPLACE INTO checklist (day, item, done) VALUES (?,?,?)",
                         (str(day), item, 1 if done else 0))
        self.con.commit()

    def checklist_counts(self):
        """{day string: number of items ticked that day}"""
        rows = self.con.execute("SELECT day, SUM(done) FROM checklist GROUP BY day").fetchall()
        return {r[0]: int(r[1] or 0) for r in rows}

    def day_note(self, day):
        row = self.con.execute("SELECT note FROM day_notes WHERE day = ?", (str(day),)).fetchone()
        return row[0] if row else ""

    def set_day_note(self, day, note):
        self.con.execute("INSERT OR REPLACE INTO day_notes (day, note) VALUES (?,?)", (str(day), note.strip()))
        self.con.commit()

    def day_notes(self, start, end):
        rows = self.con.execute("SELECT day, note FROM day_notes WHERE day >= ? AND day < ? AND note != '' ORDER BY day",
                                (str(start), str(end))).fetchall()
        return {r[0]: r[1] for r in rows}

    def lesson(self, key):
        row = self.con.execute("SELECT note FROM trade_lessons WHERE key = ?", (key,)).fetchone()
        return row[0] if row else ""

    def set_lesson(self, key, note):
        self.con.execute("INSERT OR REPLACE INTO trade_lessons (key, note) VALUES (?,?)", (key, note.strip()))
        self.con.commit()

    # ---- price alerts
    def add_price_alert(self, symbol, direction, price, note=""):
        if direction not in ("above", "below") or price <= 0 or not symbol.strip():
            raise ValueError("Enter a symbol, a direction and a price above zero.")
        self.con.execute("INSERT INTO price_alerts (symbol, direction, price, note, created) VALUES (?,?,?,?,?)",
                         (symbol.strip().upper(), direction, float(price), note, _ts().strftime(TS_FMT)))
        self.con.commit()

    def price_alerts(self, include_fired=True):
        q = "SELECT * FROM price_alerts" + ("" if include_fired else " WHERE fired IS NULL") + " ORDER BY id"
        return pd.read_sql_query(q, self.con)

    def mark_alert_fired(self, alert_id):
        self.con.execute("UPDATE price_alerts SET fired = ? WHERE id = ?", (_ts().strftime(TS_FMT), int(alert_id)))
        self.con.commit()

    def delete_price_alert(self, alert_id):
        self.con.execute("DELETE FROM price_alerts WHERE id = ?", (int(alert_id),))
        self.con.commit()

    # ---- scan snapshots
    def save_scan(self, preset, interval, criteria, summary, results):
        """Record one scan (settings and every result) so its later performance can be measured."""
        cur = self.con.execute(
            "INSERT INTO scans (ts, preset, interval, criteria, summary) VALUES (?,?,?,?,?)",
            (_ts().strftime(TS_FMT), preset, interval, json.dumps(criteria, default=str), summary))
        scan_id = int(cur.lastrowid)
        rows = []
        for r in results.to_dict("records"):
            extra = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in r.items()
                     if k in ("RSI", "ATR %", "Rel Vol", "Day Vol x", "Float (M)", "Change %", "Catalyst",
                              "Red flags", "Earnings", "Spread %")}
            rows.append((scan_id, r["Symbol"], _num(r.get("Price")), _num(r.get("Stop")), _num(r.get("Target")),
                         str(r.get("Setup", "") or ""), str(r.get("Signal", "") or ""),
                         json.dumps(extra, default=str)))
        self.con.executemany(
            "INSERT INTO scan_results (scan_id, symbol, price, stop, target, setup, signal, extra) "
            "VALUES (?,?,?,?,?,?,?,?)", rows)
        self.con.commit()
        return scan_id

    def scan_history(self):
        return pd.read_sql_query(
            "SELECT s.id, s.ts, s.preset, s.interval, s.summary, "
            "(SELECT COUNT(*) FROM scan_results r WHERE r.scan_id = s.id) AS results "
            "FROM scans s ORDER BY s.id DESC", self.con)

    def scan_results(self, preset=None):
        q = ("SELECT s.id AS scan_id, s.ts, s.preset, r.symbol, r.price, r.stop, r.target, r.setup, r.signal "
             "FROM scan_results r JOIN scans s ON s.id = r.scan_id")
        params = ()
        if preset:
            q += " WHERE s.preset = ?"
            params = (preset,)
        df = pd.read_sql_query(q + " ORDER BY s.id DESC", self.con, params=params)
        df["ts"] = pd.to_datetime(df["ts"])
        return df


def evaluate_scan_results(results, fetch_history, horizons=(1, 5, 10), max_rows=300):
    """
    How did past scan picks do? For each saved result, look at the daily bars after the
    scan and record the price change after 1, 5 and 10 trading days, plus whether the
    suggested target or stop was reached first (stop wins ties, as in the backtest).
    `fetch_history(symbol, start_date)` must return a daily OHLC DataFrame with a date index.
    """
    rows = []
    cache = {}
    for r in results.head(max_rows).itertuples():
        scan_day = pd.Timestamp(r.ts).normalize()
        if r.symbol not in cache:
            try:
                cache[r.symbol] = fetch_history(r.symbol, scan_day)
            except Exception:
                cache[r.symbol] = None
        h = cache[r.symbol]
        if h is None or h.empty or not r.price:
            continue
        fut = h[h.index.normalize() > scan_day]
        if fut.empty:
            continue
        row = {"Scan": r.scan_id, "Scanned": scan_day.date(), "Preset": r.preset, "Symbol": r.symbol,
               "Setup": r.setup, "Signal": r.signal, "Price": r.price}
        for n in horizons:
            row[f"{n}d %"] = ((fut["Close"].iloc[n - 1] / r.price - 1) * 100) if len(fut) >= n else np.nan
        outcome = "Too early"
        if r.stop and r.target:
            outcome = "Neither yet"
            for hi, lo in zip(fut["High"].iloc[:10], fut["Low"].iloc[:10]):
                if lo <= r.stop:
                    outcome = "Stop first"
                    break
                if hi >= r.target:
                    outcome = "Target first"
                    break
            if outcome == "Neither yet" and len(fut) < 10:
                outcome = "Still open"
        row["Result"] = outcome
        rows.append(row)
    return pd.DataFrame(rows)


def summarize_evaluation(ev):
    """One row per preset: how many picks, average moves, and target-vs-stop record."""
    if ev.empty:
        return pd.DataFrame()
    out = []
    for preset, g in ev.groupby("Preset"):
        resolved = g[g["Result"].isin(["Target first", "Stop first"])]
        out.append({
            "Preset": preset, "Picks": len(g),
            "Avg 1d %": g["1d %"].mean(), "Avg 5d %": g["5d %"].mean(), "Avg 10d %": g["10d %"].mean(),
            "Up after 5d %": (g["5d %"].dropna() > 0).mean() * 100 if g["5d %"].notna().any() else np.nan,
            "Target first": int((g["Result"] == "Target first").sum()),
            "Stop first": int((g["Result"] == "Stop first").sum()),
            "Target-first rate %": (len(resolved[resolved["Result"] == "Target first"]) / len(resolved) * 100)
            if len(resolved) else np.nan,
        })
    return pd.DataFrame(out)


def payoff_table(valued, account_value=0.0):
    """
    What each open position would add to or take from your account if its stop or its target is hit.
    Measured against what you paid (average cost), so it is the profit or loss you would actually end up with on
    that position. A raised stop above your cost shows as a locked-in gain. Positions with no stop or target
    recorded get blank cells and are left out of that total.
    Returns (table, totals). totals: stop_total, target_total, missing_stop, missing_target, plus % of account.
    """
    import numpy as np
    import pandas as pd

    if valued is None or valued.empty:
        return pd.DataFrame(), {"stop_total": 0.0, "target_total": 0.0, "missing_stop": 0, "missing_target": 0,
                                "stop_pct": None, "target_pct": None}
    d = valued[["Symbol", "Shares", "Avg cost", "Price", "Stop", "Target"]].copy()
    stop = pd.to_numeric(d["Stop"], errors="coerce")
    target = pd.to_numeric(d["Target"], errors="coerce")
    stop = stop.where(stop > 0)
    target = target.where(target > 0)
    d["If stop hits $"] = ((stop - d["Avg cost"]) * d["Shares"]).round(2)
    d["If target hits $"] = ((target - d["Avg cost"]) * d["Shares"]).round(2)
    if account_value and account_value > 0:
        d["Stop, % of account"] = (d["If stop hits $"] / account_value * 100).round(1)
        d["Target, % of account"] = (d["If target hits $"] / account_value * 100).round(1)
    st_tot = float(np.nansum(d["If stop hits $"])) if d["If stop hits $"].notna().any() else 0.0
    tg_tot = float(np.nansum(d["If target hits $"])) if d["If target hits $"].notna().any() else 0.0
    totals = {"stop_total": round(st_tot, 2), "target_total": round(tg_tot, 2),
              "missing_stop": int(d["If stop hits $"].isna().sum()), "missing_target": int(d["If target hits $"].isna().sum()),
              "stop_pct": round(st_tot / account_value * 100, 1) if account_value and account_value > 0 else None,
              "target_pct": round(tg_tot / account_value * 100, 1) if account_value and account_value > 0 else None}
    return d.drop(columns=["Price"]), totals

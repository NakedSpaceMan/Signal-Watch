"""
backtest.py - a more honest test of the swing setups on past daily data.

How it differs from the quick "price N bars later" look:
  * You can only act AFTER a signal bar closes, so entry is the NEXT bar's open.
  * Stop and target are simulated bar by bar. If a bar opens beyond your stop
    (an overnight gap), the exit happens at that worse open price, not at the stop.
  * If one bar touches both stop and target, the stop is assumed to hit first.
  * A round-trip cost (fees and slippage) is subtracted from every trade.
  * Only one trade per stock at a time (no overlapping entries in the same stock).
  * Results are shown in R (multiples of the risk you took) as well as percent.
  * An optional date split reports "before" and "after" results separately, so you
    can check whether rules that look good on old data still work on newer data.

Known limits (it does not model): earnings-date avoidance, bid/ask spreads on
thin stocks, halts, dividends, or stocks that were delisted (survivorship bias:
only stocks that exist today can be downloaded). Treat results as a sanity check,
not a promise.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

import signal_overlay as so


@dataclass
class BTParams:
    setups: tuple = ("pullback", "breakout", "bounce")
    stop_atr_mult: float = 2.0
    reward_risk: float = 2.0
    max_hold: int = 15          # trading days before a stale trade is closed at the close
    cost_pct: float = 0.2       # round-trip fees + slippage, percent of the position


def simulate_trade(df, i, atr, p):
    """
    Enter at the open of bar i+1 (the bar after the signal). Returns a dict, or None
    if there is no next bar or the numbers are unusable.
    """
    n = len(df)
    if i + 1 >= n or not atr or atr <= 0 or np.isnan(atr):
        return None
    o, h, l, c = (df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    entry = o[i + 1]
    stop = entry - p.stop_atr_mult * atr
    risk = entry - stop
    if risk <= 0 or stop <= 0:
        return None
    target = entry + p.reward_risk * risk
    last = min(i + p.max_hold, n - 1)

    exit_px, reason, j = c[last], "Time limit", last
    for k in range(i + 1, last + 1):
        if k > i + 1 and o[k] <= stop:                 # gapped through the stop
            exit_px, reason, j = o[k], "Stop (gap)", k
            break
        if l[k] <= stop:
            exit_px, reason, j = stop, "Stop", k
            break
        if k > i + 1 and o[k] >= target:               # gapped past the target
            exit_px, reason, j = o[k], "Target (gap)", k
            break
        if h[k] >= target:
            exit_px, reason, j = target, "Target", k
            break
    if reason == "Time limit" and last == n - 1 and (n - 1 - i) < p.max_hold:
        reason = "Still open"

    gross = exit_px / entry - 1
    net = gross - p.cost_pct / 100
    return {"entry_date": df.index[i + 1], "exit_date": df.index[j], "entry": entry, "stop": stop,
            "target": target, "exit": exit_px, "reason": reason, "days": j - i,
            "pnl_pct": net * 100, "r": net * entry / risk, "signal_idx": i}


def backtest_symbol(df, flags, p, min_price=0.0, weekday=None):
    """All trades for one stock. `df` must have indicators; `flags` from scanner.swing_setup_flags."""
    trades, busy_until = [], -1
    keys = [k for k in ("pullback", "breakout", "bounce") if k in p.setups]
    if not keys:
        return trades
    hit = np.zeros(len(df), bool)
    for k in keys:
        hit |= flags[k].to_numpy(bool)
    hit &= flags["filters_ok"].to_numpy(bool)
    if weekday is not None:                       # only signals on this weekday (0=Mon ... 4=Fri), e.g. Fridays
        hit &= np.asarray(pd.DatetimeIndex(df.index).weekday == weekday)
    atr = flags["atr"].to_numpy(float)
    for i in np.flatnonzero(hit):
        if i <= busy_until:
            continue
        t = simulate_trade(df, int(i), atr[i], p)
        if t is None:
            continue
        t["setup"] = ", ".join(k.capitalize() for k in keys if bool(flags[k].iloc[i]))
        trades.append(t)
        busy_until = i + t["days"]
    return trades


def run_backtest(frames, criteria, p, progress=None, weekday=None):
    """
    frames: {symbol: daily OHLCV DataFrame}. criteria: a scanner.SwingCriteria
    (liquidity and ATR filters). Returns a DataFrame with one row per trade.
    """
    import scanner as sc

    rows = []
    for n, (sym, d) in enumerate(frames.items()):
        if progress:
            progress(n / max(len(frames), 1), sym)
        if len(d) < so.MIN_BARS + 20:
            continue
        df = so.add_indicators(d)
        flags = sc.swing_setup_flags(df, criteria)
        for t in backtest_symbol(df, flags, p, weekday=weekday):
            t["symbol"] = sym
            rows.append(t)
    cols = ["symbol", "setup", "entry_date", "exit_date", "days", "entry", "stop", "target", "exit",
            "reason", "pnl_pct", "r"]
    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=cols)
    return out[cols + [c for c in out.columns if c not in cols]].sort_values("entry_date").reset_index(drop=True)


def metrics(t):
    """Summary numbers for a set of trades (rows with an 'Still open' exit are excluded)."""
    t = t[t["reason"] != "Still open"] if not t.empty else t
    if t.empty:
        return {"trades": 0}
    r = t["r"]
    wins, losses = r[r > 0], r[r <= 0]
    ordered = t.sort_values("exit_date")
    equity = ordered["r"].cumsum()
    drawdown = float((equity - equity.cummax()).min())
    # busiest moment: most trades open at the same time
    ev = pd.concat([pd.Series(1, index=t["entry_date"]), pd.Series(-1, index=t["exit_date"])]).sort_index()
    concurrent = int(ev.groupby(level=0).sum().cumsum().max())
    return {
        "trades": int(len(t)),
        "win_rate": float((r > 0).mean() * 100),
        "avg_r": float(r.mean()),
        "avg_win_r": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss_r": float(losses.mean()) if len(losses) else 0.0,
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "avg_pnl_pct": float(t["pnl_pct"].mean()),
        "avg_days": float(t["days"].mean()),
        "max_drawdown_r": drawdown,
        "total_r": float(r.sum()),
        "max_concurrent": concurrent,
        "gap_stops": int((t["reason"] == "Stop (gap)").sum()),
    }


def split_metrics(t, split_date):
    """Metrics before and after a date, to check the rules on data not used to pick them."""
    split = pd.Timestamp(split_date)
    return metrics(t[t["entry_date"] < split]), metrics(t[t["entry_date"] >= split])


def load_daily(symbols, period="5y", chunk=60):
    """Download daily bars for many symbols. Returns {symbol: DataFrame}. Finished sessions only."""
    import yfinance as yf

    out = {}
    symbols = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
    for i in range(0, len(symbols), chunk):
        part = symbols[i:i + chunk]
        try:
            raw = yf.download(part, period=period, interval="1d", group_by="ticker",
                              auto_adjust=True, progress=False, threads=True)
        except Exception:
            continue
        if raw is None or raw.empty:
            continue
        for s in part:
            try:
                d = raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw
                d = d[["Open", "High", "Low", "Close", "Volume"]].dropna()
            except KeyError:
                continue
            if len(d) and so.daily_bar_in_progress(d.index[-1]):
                d = d.iloc[:-1]
            if len(d):
                out[s] = d
    return out

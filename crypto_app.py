"""
crypto_app.py - the Crypto side of Signal Watch. signal_app.py hands control here when you pick "Crypto" on the start screen.

Same ideas as the stock side (swing setups, Score, range cone, risk-sized positions, ledger, backtest, Learn), adapted for a
market that never closes and moves much more. Your crypto trades are kept in their own file (signal_crypto.db) and your crypto
settings in crypto_settings.json, completely separate from your stocks.

Nothing here connects to Robinhood or places orders: you type your trades in. Not financial advice.
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import backtest as bt
import crypto as cr
import shared as sh
import forecast as fc
import ledger as lg
import learn
import quality as ql
import scanner as sc
import signal_overlay as so
import swing_chart as swc

HERE = Path(__file__).parent
SETTINGS = HERE / "crypto_settings.json"
DB = HERE / "signal_crypto.db"
STRETCH_ROOM = 1.6
WEATHER_MIN_SCORE = {"Sunny": 0, "Partly cloudy": 50, "Stormy": 65}

TIPS = {
    "Score": "Setup quality from 0 to 100: how this setup did on this coin before (30%), whether the target is inside the coin's "
             "usual range (25%), strength against Bitcoin (20%), trend strength (15%) and volume (10%). A starting guess, not a promise.",
    "Room x": "Target distance divided by the coin's usual 15-day move. Under about 1: inside the usual range. Above 1.5: a stretch.",
    "vs BTC 3mo %": "How much the coin beat (+) or lagged (-) Bitcoin over about 3 months.",
    "Past setups": "How many times this same kind of setup showed up on this coin before (next-day entry, your stop and target). "
                   "Few means a small sample. Blank below 3.",
    "Past hit target %": "Of those past setups, how often price reached the target before the stop or time limit. With a 2-to-1 "
                         "target, a bit over a third is break-even.",
    "Past avg R": "Average result per past trade on this coin in R (1R = what you risked). Above 0 made money on average there.",
    "ATR %": "Average daily swing as a percent of price. Crypto is often 4-10%, which is why stops are wider and positions smaller.",
    "R after fees": "Your real reward-to-risk once the round-trip fee is counted: (reward % minus fee) divided by (risk % plus fee). "
                    "A '2-to-1' setup is lower than 2 here, and the smaller the move, the more fees hurt.",
    "Vol x": "Latest day's trading volume compared with its recent average.",
    "Buy $": "How many dollars of the coin to buy so a stop-out loses about your 'max loss per trade' (capped by your biggest-position limit).",
    "Units": "How much of the coin that dollar amount buys.",
    "Risk $": "About what you lose if the stop fills at its price. A fast drop can fill lower.",
    "Why": "Plain-English reason this coin is on the list.",
}


# ------------------------------------------------------------------ small helpers
def _load():
    try:
        return json.loads(SETTINGS.read_text())
    except Exception:
        return {}


def _save(d):
    try:
        SETTINGS.write_text(json.dumps(d, indent=1))
    except Exception:
        pass


def table(df, tips=None, price_cols=()):
    d = df.copy()
    for c in price_cols:
        if c in d.columns:
            d[c] = d[c].map(lambda v: cr.nice(v) if pd.notna(v) else v)
    cfg = {}
    if tips:
        try:
            cfg = {c: st.column_config.Column(c, help=tips[c]) for c in d.columns if c in tips}
        except Exception:
            cfg = {}
    for c in price_cols:
        if c in d.columns:
            try:
                cfg[c] = st.column_config.NumberColumn(c, help=(tips or {}).get(c), format="%.6g")
            except Exception:
                pass
    try:
        st.dataframe(d, hide_index=True, width="stretch", column_config=cfg)
    except TypeError:
        st.dataframe(d, hide_index=True, use_container_width=True, column_config=cfg)


def money(x):
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"


def esc(t):
    return str(t).replace("$", "\\$")


@st.cache_data(ttl=900, show_spinner=False)
def cached_frames(coins, period="2y"):
    return cr.load_with_resolution(list(coins), period)


@st.cache_data(ttl=900, show_spinner=False)
def cached_weather():
    try:
        frames, _, _ = cr.load_with_resolution(["BTC"], "2y")
        return cr.weather(frames["BTC-USD"])
    except Exception:
        return None


@st.cache_data(ttl=60, show_spinner=False)
def cached_prices(symbols):
    return lg.fetch_prices(list(symbols))


@st.cache_resource
def get_store(path):
    return lg.Store(path)


# ------------------------------------------------------------------ the app
def run():
    saved = _load()
    sb = st.sidebar
    if sb.button("← Back to start screen", key="cx_back"):
        st.session_state["app_mode"] = None
        st.rerun()
    sb.header("Crypto")
    sb.caption("Your crypto trades and settings are kept separately from your stocks.")
    sb.header("Account & risk")
    shared_acct, s_reserve = sh.stock_account()
    acct = sb.number_input("Account value ($, shared with stocks)", min_value=0.0, step=10.0,
                           value=float(shared_acct if shared_acct > 0 else saved.get("acct", 100.0)), key="cx_acct",
                           help="Your whole Robinhood account: cash plus stocks plus coins. Stocks and crypto share this one pool of money, "
                                "so changing it here changes it on the stocks side too. Cash for a crypto plan is this, minus what you "
                                "hold in stocks and coins.")
    if abs(acct - shared_acct) > 1e-9:
        sh.save_account(acct)
    risk_pct = sb.number_input("Max loss per trade (% of account)", min_value=0.1, max_value=10.0, step=0.1,
                               value=float(saved.get("risk_pct", 1.0)),
                               help="If a stop is hit, you lose about this share of your crypto account.")
    max_pos = sb.number_input("Biggest single position (% of account)", min_value=5.0, max_value=100.0, step=5.0,
                              value=float(saved.get("max_pos", 50.0)))
    max_new = sb.number_input("Most new positions per plan", min_value=1, max_value=10, value=int(saved.get("max_new", 2)))
    sb.header("Trade rules")
    stop_mult = sb.number_input("Stop distance (ATRs below entry)", min_value=0.5, max_value=6.0, step=0.5,
                                value=float(saved.get("stop_mult", 2.0)),
                                help="Coins swing more than stocks. 2 is a starting point; wider means fewer shake-outs and smaller positions.")
    rr = sb.number_input("Target (times your risk)", min_value=1.0, max_value=6.0, step=0.5, value=float(saved.get("rr", 2.0)))
    cost = sb.number_input("Round-trip fee (%)", min_value=0.0, max_value=5.0, step=0.1, value=float(saved.get("cost", cr.DEFAULT_COST_PCT)),
                           help="What buying and then selling costs you in total. At Robinhood's lowest volume tier: 0.95% per market or stop order, "
                                "0.50% per limit order. A limit buy plus a stop sell is about 1.45%; market both ways about 1.9%. See the Guide tab.")
    sb.header("Weekend Warrior")
    ww = sb.checkbox("Weekend Warrior mode", value=bool(saved.get("ww", False)), key="cx_ww",
                     help="This mode makes a plan that prioritizes you taking a trade on Friday night and selling by Sunday night, "
                          "so your cash is available for regular stock trading when the market opens again Monday (6:30 AM Pacific). "
                          "It uses a tighter stop and a nearer target, since there are only about two days to work with.")
    if ww:
        stop_mult, rr = cr.WW["stop_atr_mult"], cr.WW["reward_risk"]
        sb.caption(f"Using a {stop_mult:g}-ATR stop and a {rr:g}-to-1 target for the weekend. The trade rules above are ignored while this is on.")
    new = dict(acct=acct, risk_pct=risk_pct, max_pos=max_pos, max_new=int(max_new), stop_mult=saved.get("stop_mult", 2.0) if ww else stop_mult,
               rr=saved.get("rr", 2.0) if ww else rr, cost=cost, ww=ww)
    if new != {k: saved.get(k) for k in new}:
        _save({**saved, **new})
    risk_dollars = round(acct * risk_pct / 100, 2)

    st.title("Signal Watch: Crypto")
    st.caption("Crypto trades 24/7, weekends included. Daily candles close at midnight UTC (5 PM Pacific in summer, 4 PM in winter). "
               "The scanner uses finished candles only, so run it after the daily close for fresh setups.")
    w = cached_weather()
    if w:
        getattr(st, w["level"])(f"**Crypto market weather: {w['label']}** ({w['score']}/{w['max']}). {w['text']} "
                                f"Bitcoin ${w['close']:,.0f}, {w['chg7']:+.1f}% over 7 days, "
                                f"{'above' if w['above200'] else 'below'} its 200-day average.")
    else:
        st.caption("Bitcoin data couldn't be loaded, so market weather is unavailable right now.")

    store = get_store(str(DB))
    tx = store.transactions()
    pos = lg.build_positions(tx)
    px = cached_prices(tuple(sorted(pos["open"]["Symbol"]))) if not pos["open"].empty else {}
    valued = lg.value_positions(pos["open"], px, acct)
    psum = lg.portfolio_summary(valued, pos["closed"], pos["realized"], acct, 0.0)
    invested = psum["market_value"]

    t_scan, t_chart, t_port, t_bt, t_learn, t_guide = st.tabs(
        ["Scanner", "Chart", "Portfolio", "Backtest", "Learn", "Guide"])
    with t_scan:
        scanner_tab(acct, risk_dollars, max_pos, int(max_new), stop_mult, rr, w, invested, cost, ww)
    with t_chart:
        chart_tab(stop_mult, rr, valued, ww)
    with t_port:
        portfolio_tab(store, tx, pos, valued, psum, acct, px)
    with t_bt:
        backtest_tab(stop_mult, rr, cost, ww)
    with t_learn:
        st.info("The lessons use made-up charts, and the same patterns show up on coin charts. The big differences: coins move "
                "more, so stops sit further away, and the market never closes.")
        learn.show(risk_dollars=risk_dollars)
    with t_guide:
        guide_tab()


# ------------------------------------------------------------------ scanner
def _coin_set_ui(key):
    pick = st.selectbox("Coins to scan", ["Majors (44 liquid coins, best data)", "Everything on Robinhood I can find"],
                        key=f"{key}_set")
    extra = st.text_input("Extra coins (tickers like WIF, or Yahoo symbols like UNI7083-USD, comma-separated)", value="",
                          key=f"{key}_extra")
    coins = list(cr.MAJORS) if pick.startswith("Majors") else list(cr.COIN_NAMES)
    for e in extra.replace(",", " ").split():
        e = e.upper()
        if e not in coins:
            coins.append(e)
    if "BTC" not in coins:
        coins.append("BTC")             # Bitcoin is the yardstick for 'strength vs the market'
    return coins


def _load_chart(coin):
    st.session_state["cx_coin_in"] = coin


def scanner_tab(acct, risk_dollars, max_pos, max_new, stop_mult, rr, weather, invested, cost, ww=False):
    st.subheader("Swing scanner for coins")
    st.caption("Looks for the same three setups as the stock scanner (pullback, breakout, bounce) on daily candles, inside "
               "uptrends, then ranks them with the Score. Sized so a stop-out costs about "
               f"{money(risk_dollars)}.")
    win = None
    if ww:
        win = cr.ww_window()
        if win["open"]:
            left = win["left"]
            st.success(f"**Weekend Warrior is on, and the window is open.** Sell everything by Sunday {win['end']:%I:%M %p} Pacific "
                       f"({left.days * 24 + left.seconds // 3600} hours left) so the cash is free when stocks open Monday 6:30 AM.")
        else:
            until = win["until"]
            st.info(f"**Weekend Warrior is on.** The next window opens Friday {win['start']:%I:%M %p} Pacific, in "
                    f"{until.days}d {until.seconds // 3600}h. Run the scan then, after Friday's candle closes. "
                    "You can scan now to preview what it would pick.")
    coins = _coin_set_ui("cxs")
    f1, f2 = st.columns(2)
    hide_stretch = f1.checkbox("Hide setups whose target is a stretch", value=True, key="cx_stretch",
                               help=f"Hides results where the target is more than {(cr.WW_STRETCH_ROOM if ww else STRETCH_ROOM):g} times the coin's usual "
                                    f"{'3' if ww else '15'}-day move.")
    gate = f2.checkbox("Be pickier when Bitcoin is weak", value=True, key="cx_gate",
                       help="Partly cloudy: only scores of 50 or more. Stormy: 65 or more.")
    if st.button("Run crypto scan", key="cx_run"):
        with st.spinner("Downloading daily candles and checking setups... this can take a minute."):
            frames, names, no_data = cached_frames(tuple(coins), "2y")
            c = cr.weekend_criteria(cost_pct=cost) if ww else cr.criteria(stop_atr_mult=stop_mult, reward_risk=rr, cost_pct=cost)
            df, stats = cr.scan(c, frames, names, acct, risk_dollars, max_pos)
            stats["no_data"] = no_data
            st.session_state["cx_scan"] = (df, stats, datetime.now(), bool(ww))
    res = st.session_state.get("cx_scan")
    if not res:
        st.info("Press Run crypto scan. Nothing is bought or sold; it only suggests.")
        return
    df, stats, when, scan_ww = res
    if scan_ww != bool(ww):
        st.warning("These results were made with the Weekend Warrior setting " + ("on" if scan_ww else "off") + ". Run the scan again to match the current setting.")
    st.caption(f"Scanned {when:%b %d %I:%M %p}  ·  {stats['loaded']} coins loaded, {stats['trend']} in an uptrend, "
               f"{stats['matches']} with a setup (latest finished candle: {stats['last_bar']}).")
    if stats.get("no_data"):
        with st.expander(f"{len(stats['no_data'])} coin(s) had no Yahoo data and were skipped"):
            st.write(", ".join(stats["no_data"]))
            st.caption("Newer coins often are not on Yahoo yet. If you know the Yahoo symbol, add it in 'Extra coins'.")
    if df.empty:
        st.info("No coin has a setup on the latest finished candle. That is normal; check again after the next daily close.")
        return
    notes = []
    if hide_stretch and "Room x" in df.columns:
        keep = ~(df["Room x"] > (cr.WW_STRETCH_ROOM if scan_ww else STRETCH_ROOM))
        if (~keep).any():
            notes.append(f"{int((~keep).sum())} hidden because the target is a stretch")
        df = df[keep]
    if gate and weather:
        need = WEATHER_MIN_SCORE.get(weather["label"], 0)
        if need:
            keep = ~(df["Score"] < need)
            if (~keep).any():
                notes.append(f"{int((~keep).sum())} hidden because Bitcoin is {weather['label'].lower()} (scores under {need})")
            df = df[keep]
    if notes:
        st.caption("Filters: " + "; ".join(notes) + ". Untick the boxes above to see everything.")
    if df.empty:
        st.info("Everything was filtered out. Untick a filter above to see the rest.")
        return
    show = [c for c in ["Coin", "Name", "Price", "Setup", "Score", "Why", "Stop", "Target", "Risk %", "R after fees", "Buy $", "Units", "Risk $",
                        "ATR %", "Room x", "vs BTC 3mo %", "Past setups", "Past hit target %", "Past avg R", "RSI", "Vol x"]
            if c in df.columns]
    table(df[show], TIPS, price_cols=("Price", "Stop", "Target", "Units"))

    st.markdown("#### Weekend Warrior plan" if ww else "#### Combined plan: what you could take together")
    if ww:
        lb = stats.get("last_date")
        if lb is not None and pd.Timestamp(lb).weekday() != cr.WW_DAY:
            st.caption(f"Heads up: the latest finished candle is {pd.Timestamp(lb):%A}, not Friday, so these are previews, not Friday-night picks.")
    s_mv, s_n = sh.stock_held(cached_prices)
    s_reserve = sh.stock_account()[1]
    cash = max(acct - invested - s_mv - s_reserve, 0.0)      # one Robinhood account: stocks held tie up the same cash
    if s_mv > 0 or s_reserve > 0:
        st.info(f"One shared account: {money(acct)} total, minus {money(invested)} in coins"
                + (f", {money(s_mv)} in stocks ({s_n} position{'s' if s_n != 1 else ''})" if s_mv > 0 else "")
                + (f" and {money(s_reserve)} kept uninvested" if s_reserve > 0 else "")
                + f" leaves {money(cash)} free cash for this plan.")
    plan, left = [], cash
    for _, r in df.iterrows():
        if len(plan) >= max_new:
            break
        if "Buy $" not in r or pd.isna(r["Buy $"]) or r["Buy $"] <= 0:
            continue
        cost = min(float(r["Buy $"]), left)
        if cost < 1.0:                       # too small to be worth an order
            continue
        scale = cost / float(r["Buy $"])
        plan.append({"Coin": r["Coin"], "Buy $": round(cost, 2), "Units": cr.nice(float(r["Units"]) * scale, 4),
                     "Stop": r["Stop"], "Target": r["Target"], "Risk $": round(float(r["Risk $"]) * scale, 2),
                     "Score": r["Score"]})
        left -= cost
    if not plan:
        st.info("Nothing fits your cash and limits right now. Common reasons: cash is already invested, or stops are wide for the risk you allow.")
    else:
        p = pd.DataFrame(plan)
        if ww:
            p["Sell by"] = f"Sun {cr.ww_window()['end']:%I:%M %p} PT" if win and win["open"] else "Sun 11:00 PM PT"
        table(p, TIPS, price_cols=("Units", "Stop", "Target"))
        st.caption(esc(f"Cash available: {money(cash)}. Total cost {money(p['Buy $'].sum())}. If every stop is hit you would lose "
                       f"about {money(p['Risk $'].sum())} ({p['Risk $'].sum() / acct * 100:.1f}% of the account) if they fill at the stop; "
                       "a fast drop can fill lower. Crypto has no market close, so a stop can trigger overnight."
                       + (" Weekend Warrior: if the target hasn't hit by Sunday night, sell at market anyway so your cash is back for Monday." if ww else "")))
    pick = st.selectbox("Open a coin in the Chart tab", df["Coin"].tolist(), key="cx_pick")
    st.button("Load chart", key="cx_loadchart", on_click=_load_chart, args=(pick,))
    if st.session_state.get("cx_coin_in") == pick:
        st.caption(f"{pick} is loaded in the Chart tab.")


# ------------------------------------------------------------------ chart
def chart_tab(stop_mult, rr, valued, ww=False):
    st.subheader("Coin chart (daily)")
    coin_default = "BTC"
    c1, c2 = st.columns([1, 2])
    coin = c1.text_input("Coin (ticker like BTC, or a Yahoo symbol)", value=coin_default, key="cx_coin_in").strip().upper()
    ranges = {"1 month": 30, "3 months": 90, "6 months": 180, "1 year": 365, "2 years": 730}
    WEEK = "This week (Mon-Sun)"
    if ww:
        ranges = {WEEK: 7, **ranges}
        pick = c2.radio("Time range (each candle is one day)", list(ranges), index=0, horizontal=True, key="cx_range_ww",
                        help="Weekend Warrior is on, so the chart starts on the week from Monday to Sunday. Pick another range to zoom out.")
    else:
        pick = c2.radio("Time range (each candle is one day)", list(ranges), index=1, horizontal=True, key="cx_range")
    week_view = ww and pick == WEEK
    show_cone = st.checkbox("Show the likely range through Sunday (shaded)" if week_view else "Show the likely range for the next 15 days (shaded)",
                            value=True, key="cx_cone")
    if not coin:
        return
    frames, names, no_data = cached_frames((coin, "BTC"), "2y")
    sym = cr.yahoo_symbol(coin)
    if sym not in frames:
        sym = next((s for s in frames if s.startswith(coin + "-") or s == coin), None)
    if sym is None:
        st.warning(f"No Yahoo data found for {coin}. Try its Yahoo symbol (for example UNI7083-USD).")
        return
    raw = frames[sym]
    if len(raw) < so.MIN_BARS:
        st.warning(f"Only {len(raw)} days of history, and the swing rules need {so.MIN_BARS}. Newer coins can't be charted this way yet.")
        return
    scale = cr.chart_scale(raw)
    raw = raw.copy()
    for col in ("Open", "High", "Low", "Close"):
        raw[col] = raw[col] * scale
    df = so.add_indicators(raw)
    crit = cr.criteria(stop_atr_mult=stop_mult, reward_risk=rr, max_atr_pct=100.0, min_avg_volume=0)
    flags = sc.swing_setup_flags(df, crit)
    cone = None
    mon = None
    n = ranges[pick]
    if week_view:
        last = pd.Timestamp(df.index[-1])
        mon = last.normalize() - pd.Timedelta(days=last.weekday())
        n = max(int((pd.DatetimeIndex(df.index) >= mon).sum()), 1)
        days_left = 6 - last.weekday()
    if show_cone and not (week_view and days_left <= 0):
        try:
            cone = fc.range_cone(df, horizon=days_left, every_day=True) if week_view else fc.range_cone(df, every_day=True)
        except Exception:
            cone = None
    fig = swc.build_swing_chart(df.tail(n), flags.tail(n), crit, f"{sym} - swing setups (daily)",
                                setups=("pullback", "breakout", "bounce"), opts={"volume": True, "sr": True, "beginner": True,
                                                                                    "always_open": True},
                                overlay=None, show_outcomes=True, cone=cone)
    fig.update_layout(uirevision=f"{sym}-crypto-{'week' if week_view else 'std'}")
    if week_view:
        fig.update_xaxes(range=[mon - pd.Timedelta(hours=12), mon + pd.Timedelta(days=6, hours=12)])
    try:
        st.plotly_chart(fig, width="stretch", key="cx_chart")
    except TypeError:
        st.plotly_chart(fig, use_container_width=True, key="cx_chart")
    if scale > 1:
        st.caption(f"This coin is very cheap, so the chart shows prices multiplied by {scale:,} to keep the labels readable. "
                   "Shapes and percentages are unaffected; divide chart prices by that number for real prices.")
    st.caption("Diamond = pullback, star = breakout, circle = bounce. Hover a marker to see why it was flagged and what price did next. "
               "Weekends are on the chart because crypto trades every day.")
    if cone:
        lo, hi = cone["end68"]
        lo2, hi2 = cone["end95"]
        st.markdown(esc(f"**Likely range by {cone['dates'][-1]:%b %d}** ({cone['horizon']} days): **${lo / scale:,.6g} to ${hi / scale:,.6g}** about 2 times "
                        f"out of 3, and **${lo2 / scale:,.6g} to ${hi2 / scale:,.6g}** almost always. It does not predict direction."))
    st.subheader("Current read")
    st.code("\n".join(swc.current_swing_read(df, flags, crit, plain=True)), language=None)


# ------------------------------------------------------------------ portfolio
def portfolio_tab(store, tx, pos, valued, psum, acct, px):
    st.subheader("What you own (crypto)")
    st.caption("Built from the trades you enter below. This app does not read your Robinhood account, so record each buy and sell here.")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Invested (market value)", money(psum["market_value"]),
              None if psum["exposure_pct"] is None else f"{psum['exposure_pct']:.0f}% of account", delta_color="off")
    m2.metric("Unrealized P&L", money(psum["unrealized"]))
    m3.metric("Realized today", money(psum["realized_today"]))
    m4.metric("Realized, all time", money(psum["realized_total"]))
    if valued.empty:
        st.info("No open crypto positions yet. Record a buy below.")
    else:
        v = valued.copy()
        v["Coin"] = v["Symbol"].str.replace("-USD", "", regex=False)
        cols = ["Coin", "Shares", "Avg cost", "Price", "Market value", "Unrealized $", "Unrealized %", "Stop", "Target",
                "To stop %", "To target %", "Risk to stop $", "Days held"]
        table(v[cols], price_cols=("Shares", "Avg cost", "Price", "Stop", "Target"))
        st.markdown("#### If your stops or targets are hit")
        pay, tot = lg.payoff_table(valued, acct)
        p1, p2, p3 = st.columns(3)
        p1.metric("If every stop is hit", money(tot["stop_total"]),
                  None if tot["stop_pct"] is None else f"{tot['stop_pct']:+.1f}% of account", delta_color="off")
        p2.metric("If every target is hit", money(tot["target_total"]),
                  None if tot["target_pct"] is None else f"{tot['target_pct']:+.1f}% of account", delta_color="off")
        p3.metric("Gap between the two", money(tot["target_total"] - tot["stop_total"]))
        pay = pay.copy()
        pay.insert(0, "Coin", pay["Symbol"].str.replace("-USD", "", regex=False))
        table(pay.drop(columns=["Symbol"]), price_cols=("Shares", "Avg cost", "Stop", "Target"))
        miss = []
        if tot["missing_stop"]:
            miss.append(f"{tot['missing_stop']} position(s) have no stop recorded and are NOT in the stop total")
        if tot["missing_target"]:
            miss.append(f"{tot['missing_target']} have no target and are left out of the target total")
        st.caption(esc("Measured against what you paid, at the exact stop and target prices. A stop can fill lower on a fast drop. "
                       + ("; ".join(miss) + "." if miss else "")))
        sugs = lg.stop_suggestions(valued, plain=True)
        if sugs:
            st.markdown("#### Raise your stops")
            for sg in sugs:
                a, b = st.columns([4, 1])
                a.success(sg["text"])
                if b.button(f"I moved it to {sg['Suggested stop']:.6g}", key=f"cxmv_{sg['Symbol']}_{sg['Suggested stop']}"):
                    try:
                        store.add_transaction(sg["Symbol"], "ADJUST", stop=sg["Suggested stop"], ts=datetime.now())
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
        with st.expander("Close or remove a position"):
            rp = st.selectbox("Position", valued["Symbol"].tolist(), key="cx_rm_pos")
            row = valued[valued["Symbol"] == rp].iloc[0]
            q1, q2, q3 = st.columns(3)
            sp = q1.number_input("Sale price", min_value=0.0, format="%.8f",
                                 value=float(row["Price"]) if pd.notna(row["Price"]) else 0.0, key="cx_rm_px")
            fee = q2.number_input("Fees ($)", min_value=0.0, step=0.01, key="cx_rm_fee")
            if q3.button("Record: sold all", key="cx_sellall"):
                try:
                    store.add_transaction(rp, "SELL", float(row["Shares"]), sp, ts=datetime.now(), fees=fee, strategy="swing")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    st.subheader("Record a trade")
    with st.form("cx_trade"):
        f1, f2, f3, f4 = st.columns(4)
        sym = f1.text_input("Coin (like BTC)", value="BTC")
        side = f2.selectbox("Action", ["BUY", "SELL", "ADJUST stop/target"])
        qty = f3.number_input("Amount of coin", min_value=0.0, step=0.0001, format="%.8f")
        price = f4.number_input("Price per coin ($)", min_value=0.0, step=0.01, format="%.8f")
        g1, g2, g3 = st.columns(3)
        fees = g1.number_input("Fees ($)", min_value=0.0, step=0.01)
        stop = g2.number_input("Stop (0 = unchanged / none)", min_value=0.0, step=0.01, format="%.8f")
        target = g3.number_input("Target (0 = unchanged / none)", min_value=0.0, step=0.01, format="%.8f")
        notes = st.text_input("Notes (why you took it)")
        go = st.form_submit_button("Save trade")
    if go:
        try:
            store.add_transaction(cr.yahoo_symbol(sym), side.split()[0], qty, price, ts=datetime.now(), fees=fees,
                                  strategy="swing", stop=stop or None, target=target or None, notes=notes)
            st.success("Saved.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    with st.expander("Trade history and corrections"):
        if tx.empty:
            st.caption("No trades recorded yet.")
        else:
            table(tx.sort_values("ts", ascending=False)[["id", "ts", "symbol", "side", "qty", "price", "fees", "stop", "target", "notes"]])
            did = st.selectbox("Delete a trade (by id)", tx["id"].tolist()[::-1], key="cx_del")
            if st.button("Delete this trade", key="cx_delbtn"):
                try:
                    store.delete_transaction(did)
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
    st.subheader("Finished trades")
    if pos["closed"].empty:
        st.caption("Nothing closed yet.")
    else:
        s = lg.closed_trade_stats(pos["closed"])
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Trades", s["trades"])
        k2.metric("Win rate", f"{s['win_rate']:.0f}%")
        k3.metric("Profit factor", "no losses" if s["profit_factor"] == float("inf") else f"{s['profit_factor']:.2f}")
        k4.metric("Average R", "-" if s["avg_r"] != s["avg_r"] else f"{s['avg_r']:+.2f}")
        table(pos["closed"].sort_values("Closed", ascending=False), price_cols=("Shares", "Avg entry", "Avg exit"))


# ------------------------------------------------------------------ backtest
def backtest_tab(stop_mult, rr, fee, ww=False):
    st.subheader("Test the swing rules on past coin data")
    st.caption("Enters at the NEXT day's open after a setup and simulates your stop and target day by day (stop first if one day touches "
               "both), minus a round-trip cost. It only includes coins that exist today, which flatters the results more in crypto than "
               "in stocks, because many coins have died. Treat it as a sanity check.")
    if ww:
        st.info("Weekend Warrior is on: only setups seen on a Friday candle are tested, bought at Saturday's open (Friday 5 PM Pacific in summer) "
                "and closed within 2 daily candles (by Sunday's close).")
    b1, b2, b3, b4 = st.columns(4)
    setups = b1.multiselect("Setups", ["Pullback", "Breakout", "Bounce"], default=["Pullback", "Breakout", "Bounce"], key="cxb_setups")
    hold = b2.number_input("Max days to hold", min_value=2, max_value=60, value=2 if ww else 15, key="cxb_hold_ww" if ww else "cxb_hold")
    cost = b3.number_input("Round-trip cost (%)", min_value=0.0, max_value=5.0, value=float(fee), step=0.1, key="cxb_cost",
                           help="Starts from your sidebar round-trip fee. Robinhood's lowest tier is 0.95% per market or stop order and 0.50% per limit order.")
    years = b4.selectbox("History", ["2y", "3y", "5y"], index=1, key="cxb_years")
    coins = _coin_set_ui("cxb")
    if st.button("Run crypto backtest", key="cxb_run"):
        with st.spinner("Downloading history and testing..."):
            frames, names, no_data = cached_frames(tuple(coins), years)
            crit = cr.weekend_criteria(cost_pct=cost) if ww else cr.criteria(stop_atr_mult=stop_mult, reward_risk=rr, cost_pct=cost)
            params = bt.BTParams(setups=tuple(s.lower() for s in setups) or ("pullback",), stop_atr_mult=stop_mult,
                                 reward_risk=rr, max_hold=int(hold), cost_pct=cost)
            trades = bt.run_backtest(frames, crit, params, weekday=cr.WW_DAY if ww else None)
            st.session_state["cxb_res"] = (trades, len(frames), len(coins), frames, params, crit, bool(ww))
            st.session_state.pop("cxb_q", None)
    res = st.session_state.get("cxb_res")
    if not res:
        return
    trades, loaded, asked, frames, params, crit, res_ww = res
    weekday = cr.WW_DAY if res_ww else None
    st.caption(f"{loaded} of {asked} coins had data.")
    if trades.empty:
        st.info("No trades were generated with these settings.")
        return
    m = bt.metrics(trades)
    summ = pd.DataFrame([{"Trades": m["trades"], "Win rate %": round(m["win_rate"], 1), "Avg R": round(m["avg_r"], 2),
                          "Avg win R": round(m["avg_win_r"], 2), "Avg loss R": round(m["avg_loss_r"], 2),
                          "Profit factor": round(m["profit_factor"], 2) if m["profit_factor"] != float("inf") else None,
                          "Avg days": round(m["avg_days"], 1), "Max drawdown R": round(m["max_drawdown_r"], 1),
                          "Gap stops": m["gap_stops"]}])
    table(summ, {"Avg R": "Average result per trade in R (1R = what you risked). Above 0 means the rules made money after costs.",
                 "Win rate %": f"With a {rr:g}-to-1 target you only need about {100 / (1 + rr):.0f}% to break even.",
                 "Max drawdown R": "The worst peak-to-trough drop in cumulative R. Expect real stretches of losing."})
    eq = trades[trades["reason"] != "Still open"].sort_values("exit_date")
    st.line_chart(pd.DataFrame({"Cumulative R": eq["r"].cumsum().to_numpy()}, index=eq["exit_date"]))
    with st.expander("Does the quality score actually help? (test on these same trades)"):
        if st.button("Test the quality score", key="cxb_qbtn"):
            bench = frames.get(cr.BENCH)
            fr = {k: v for k, v in frames.items() if k != cr.BENCH}
            qt = ql.score_trades(fr, crit, params, bench["Close"] if bench is not None else None, weekday=weekday)
            st.session_state["cxb_q"] = ql.evaluate(qt)
        q = st.session_state.get("cxb_q")
        if q:
            qtab, verdict = q
            if len(qtab):
                table(qtab)
            (st.success if "evidence the score helps" in verdict else st.warning if "WORSE" in verdict else st.info)(verdict)
    with st.expander("All simulated trades"):
        table(trades, price_cols=("entry", "stop", "target", "exit"))
        st.download_button("Download trades as CSV", trades.to_csv(index=False), "crypto_backtest_trades.csv", "text/csv")


# ------------------------------------------------------------------ guide
def guide_tab():
    st.subheader("How crypto mode differs from stocks")
    st.markdown(esc("""
**Same engine, different market.** The setups (pullback, breakout, bounce), the Score, the past-setup stats, the likely-range cone and the backtest work the same way. What changes is the market they run on.

**It never closes.** Crypto trades every hour of every day, weekends included. A daily candle runs midnight to midnight UTC (it closes at 5 PM Pacific in summer, 4 PM in winter). The scanner uses finished candles only, so the best time to scan is just after that close.

**It moves a lot more.** Daily swings of 4 to 8% are normal for coins, against 1 to 3% for big stocks. So stops sit further from your entry, and the same dollar risk buys a much smaller position. That is normal here, not a bug.

**Stop orders exist, with a catch.** Robinhood Crypto supports market, limit, stop and stop-limit orders. A stop order turns into a market order when the price hits your stop, and a sell stop can fill up to 5% BELOW the stop price (Robinhood's own limit on the buffer). So the real loss can be bigger than the plan shows, most in a fast overnight drop, which is why the app sizes positions small. A stop-limit order avoids bad fills but may not fill at all.

**Fees, in plain words.** Robinhood charges a percentage of each trade, and the percentage depends on how much crypto you traded in the last 30 days (using exchange routing). For a small account that is the top tier: 0.95% when you place a market or stop order, 0.50% when you place a limit order that waits in line. Selling costs the same percentage again, so a round trip is about 1.9% with market orders, or about 1.45% if you buy with a limit order and exit with a stop. There is also a setting called market maker routing with no listed commission, but its cost is hidden in the price you get, and Robinhood says neither choice is always cheaper. The sidebar's Round-trip fee (default 1.5%) is used everywhere: the scanner's "R after fees" column, the past-setup stats and the backtest. The 'R after fees' column is the honest version of reward-to-risk: a 2-to-1 setup with a small move can drop to under 1.5-to-1 once fees are counted. Fees hurt small, quick trades the most, so favor setups with room to run.

**Crypto never takes a day off.** It trades 24 hours a day, 7 days a week, weekends and holidays included (Robinhood only pauses it for scheduled maintenance). The only "close" is the daily candle: each daily candle ends at midnight UTC (5 PM Pacific in summer, 4 PM in winter), which is just where the chart cuts one day from the next. Weekends show up on the charts because real trading happens on them.

**Bitcoin is the tide.** When Bitcoin is in a downtrend, nearly every coin falls harder. The "crypto market weather" banner reads Bitcoin's trend, and the scanner asks for a higher Score when it is weak.

**Only coins with a long enough history work.** The swing rules need about 210 days of daily data. Brand-new coins are skipped, and some coins on Robinhood's list are not on Yahoo Finance yet; the scan tells you which.

**Where the coin list comes from.** It is built from Robinhood's coin-availability page (tradable coins only, without stablecoins and gold-backed tokens, since they barely move). Availability can differ by state. Confirm a coin is tradable in your own app before acting.

**Your data stays separate.** Crypto trades and settings are stored in their own files (signal_crypto.db and crypto_settings.json), apart from your stocks.

**Not financial advice.** Simple rules fail live, crypto can lose most of its value fast, and this app never places orders. Use money you can afford to lose and keep every trade small.
"""))

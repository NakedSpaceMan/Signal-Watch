#!/usr/bin/env python3
"""
signal_app.py - Signal Watch: scanner, charts, portfolio and backtest in one app.

Run with:
    streamlit run signal_app.py          (or double-click "Start Signal Watch.command")

Tabs:
    Scanner              swing / steady / momentum scans, sized to your account and holdings
    Chart                intraday signal chart or the swing chart with hover-to-learn markers
    Portfolio            what you own, P&L, risk to stops, trade log, watchlists, price alerts
    Backtest & history   test the swing rules on past data, and see how saved scans performed

Keep all the .py files together in one folder. Your trades are stored locally in
signal_ledger.db and your settings in signal_settings.json. Nothing here connects
to Robinhood or places orders: you type your trades in.

Not financial advice. Simple indicator rules often fail live.
"""

import json
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import streamlit as st

import backtest as bt
import coach
import guide
import ledger as lg
import scanner as sc
import signal_overlay as so
import swing_chart as swc

st.set_page_config(page_title="Signal Watch", layout="wide")


SETTINGS_FILE = Path(__file__).with_name("signal_settings.json")
PRACTICE_DB = lg.DB_PATH.with_name("signal_practice.db")


def load_settings():
    try:
        return json.loads(SETTINGS_FILE.read_text())
    except Exception:
        return {}


_saved = load_settings()


@st.cache_resource
def get_store(path):
    return lg.Store(path)


st.sidebar.header("Mode")
practice = st.sidebar.checkbox("Practice mode (fake money)", value=bool(_saved.get("practice", False)),
                               help="A separate practice ledger, kept apart from your real trades. Good for "
                                    "learning or letting someone else try the app.")
store = get_store(str(PRACTICE_DB if practice else lg.DB_PATH))

# ====================================================================== sidebar
st.session_state.setdefault("ticker_input", "AAPL")
st.sidebar.header("Search")
st.sidebar.text_input("Ticker (press Enter to load)", key="ticker_input")
ticker = st.session_state["ticker_input"].strip().upper()


def _bar_size_changed():
    # The swing chart is always daily, so picking a shorter bar size means "show me the intraday chart".
    if st.session_state.get("bar_size") != "1d":
        st.session_state["chart_mode"] = "Intraday signals"


interval = st.sidebar.selectbox("Bar size", ["1m", "5m", "15m", "30m", "1h", "1d"], index=1, key="bar_size",
                                on_change=_bar_size_changed,
                                help="Used by the Intraday signals chart. The Swing chart is always daily.")

st.sidebar.header("Live updates")
auto = st.sidebar.checkbox("Auto-refresh the chart", value=True)
refresh = st.sidebar.slider("Refresh every (seconds)", 15, 300, 60, step=15)

st.sidebar.header("Explanations")
beginner = st.sidebar.checkbox("Beginner mode (plain English, explain like I'm five)",
                               value=bool(_saved.get("beginner", False)),
                               help="Chart hovers, alerts and the Current read use everyday words instead of "
                                    "trading terms, and a small glossary appears on the Chart tab.")

st.sidebar.header("Account & risk")
acct_key = "acct_value_practice" if practice else "acct_value"
acct_value = st.sidebar.number_input(
    "Practice account value ($, fake money)" if practice else "Account value ($, total including stocks you own)",
    min_value=0.0, step=50.0, value=float(_saved.get(acct_key, 100.0 if practice else 0.0)), key=f"acct_{practice}")
cash_reserve = st.sidebar.number_input("Cash to keep uninvested ($)", min_value=0.0, step=25.0,
                                       value=float(_saved.get("cash_reserve", 0.0)))
risk_pct = st.sidebar.number_input("Max loss per trade (% of account)", min_value=0.1, max_value=10.0,
                                   step=0.25, value=float(_saved.get("risk_pct", 1.0)))
risk_budget = st.sidebar.number_input("Max total risk ($): open stop risk + today's losses stay under this",
                                      min_value=0.0, step=5.0, value=float(_saved.get("daily_risk", 0.0)))
extra_risk = st.sidebar.number_input("Risk not in the Portfolio tab ($)", min_value=0.0, step=5.0,
                                     value=float(_saved.get("extra_risk", 0.0)))
max_pos_pct = st.sidebar.number_input("Biggest single position (% of account)", min_value=5.0,
                                      max_value=100.0, step=5.0, value=float(_saved.get("max_pos_pct", 25.0)))
max_new = st.sidebar.number_input("Most new positions per scan plan", min_value=1, max_value=10,
                                  value=int(_saved.get("max_new", 3)))
max_open = st.sidebar.number_input("Most open positions at once (0 = no cap)", min_value=0, max_value=20,
                                   value=int(_saved.get("max_open", 2)))
fractional = st.sidebar.checkbox("Allow fractional shares", value=bool(_saved.get("fractional", False)))

st.sidebar.header("Trade levels")
stop_mult = st.sidebar.number_input("Stop = ATRs below price", min_value=0.5, max_value=6.0, step=0.5,
                                    value=float(_saved.get("stop_mult", 2.0)))
reward_risk = st.sidebar.number_input("Target = x times risk", min_value=0.5, max_value=6.0, step=0.5,
                                      value=float(_saved.get("reward_risk", 2.0)))

if st.sidebar.button("Save these settings"):
    try:
        SETTINGS_FILE.write_text(json.dumps({**_saved, "practice": practice,
            acct_key: acct_value, "cash_reserve": cash_reserve, "risk_pct": risk_pct,
            "daily_risk": risk_budget, "extra_risk": extra_risk, "max_pos_pct": max_pos_pct,
            "max_new": int(max_new), "max_open": int(max_open), "fractional": fractional,
            "stop_mult": stop_mult, "reward_risk": reward_risk, "beginner": beginner}))
        st.sidebar.success("Saved on this computer.")
    except Exception as e:
        st.sidebar.error(f"Couldn't save: {e}")
st.sidebar.caption("Update your account value as it changes. What you own comes from the Portfolio tab, "
                   "not Robinhood. Settings stay in signal_settings.json next to the app.")

st.sidebar.header("Scanner")
scan_auto = st.sidebar.checkbox("Auto-rescan", value=False)
scan_minutes = st.sidebar.slider("Rescan every (minutes)", 1, 15, 5)

st.sidebar.header("Chart options")
opt_volume = st.sidebar.checkbox("Volume", value=True)
opt_vwap = st.sidebar.checkbox("VWAP (intraday only)", value=False)
opt_sr = st.sidebar.checkbox("Support / resistance lines", value=False)
opt_bb = st.sidebar.checkbox("Bollinger Bands", value=True)
opt_macd = st.sidebar.checkbox("MACD panel", value=True)
bars = st.sidebar.slider("Bars shown on chart", 60, 400, 150, step=10)

st.sidebar.header("Signal settings")
threshold = st.sidebar.slider("Signal threshold (higher = fewer signals)", 2, 6, 3)
window = st.sidebar.slider("Pattern memory (bars)", 2, 10, 5)
st.sidebar.caption("Signals use finished bars only, daily bars included. Free Yahoo data can be "
                   "several minutes delayed.")


# ====================================================================== helpers
@st.cache_data(ttl=20, show_spinner=False)
def fetch(tkr, period, intv):
    return so.load_data(tkr, period, intv)


@st.cache_data(ttl=60, show_spinner=False)
def cached_prices(symbols):
    try:
        return lg.fetch_prices(list(symbols))
    except Exception:
        return {}


@st.cache_data(ttl=3600, show_spinner=False)
def cached_earnings(sym):
    """(Yahoo earnings table, days to next report from the calendar). Cached for an hour."""
    try:
        return sc.get_earnings_dates(sym), sc.get_earnings_days(sym)
    except Exception:
        return None, None


@st.cache_data(ttl=86400, show_spinner=False)
def cached_aliases(sym):
    """Names a headline about this stock would use (company name, products, ticker)."""
    try:
        return sc.company_aliases(sym, sc.fetch_company_name(sym))
    except Exception:
        return sc.company_aliases(sym, "")


@st.cache_data(ttl=1800, show_spinner=False)
def cached_implied_move(sym, report_date, spot):
    """What options traders expect around the next earnings report (cached 30 minutes)."""
    try:
        return sc.implied_earnings_move(sym, report_date, round(float(spot), 2))
    except Exception:
        return None


@st.cache_data(ttl=600, show_spinner=False)
def cached_news(sym):
    """(parsed Yahoo headlines, note about where they came from). Cached for 10 minutes."""
    try:
        return sc.fetch_news(sym)
    except Exception:
        return [], ""


def copy_button(text, label="Copy for Claude", key="copy"):
    """A real copy-to-clipboard button (Streamlit has none built in). Falls back to the code box below it."""
    import json
    import streamlit.components.v1 as components

    payload = json.dumps(text).replace("</", "<\\/")
    components.html(f"""
<button id="b{key}" style="font:500 14px -apple-system,Segoe UI,sans-serif;padding:7px 14px;border-radius:8px;
 border:1px solid #bbb;background:#f0f2f6;color:#31333F;cursor:pointer;width:100%">{label}</button>
<script>
const T = {payload};
const b = document.getElementById("b{key}");
function done(ok) {{ b.textContent = ok ? "Copied! Now paste it into Claude" : "Copy failed: use the box below"; setTimeout(() => b.textContent = "{label}", 2500); }}
function fallback() {{
  const a = document.createElement("textarea"); a.value = T; a.style.position = "fixed"; a.style.opacity = "0";
  document.body.appendChild(a); a.select(); let ok = false;
  try {{ ok = document.execCommand("copy"); }} catch (e) {{}}
  document.body.removeChild(a); done(ok);
}}
b.onclick = () => {{
  if (navigator.clipboard && window.isSecureContext) {{ navigator.clipboard.writeText(T).then(() => done(true), fallback); }}
  else {{ fallback(); }}
}};
</script>""", height=46)


def show_chart(fig, key):
    try:
        st.plotly_chart(fig, width="stretch", key=key)
    except TypeError:  # older Streamlit versions
        st.plotly_chart(fig, use_container_width=True, key=key)


def show_table(df, **kw):
    try:
        st.dataframe(df, hide_index=True, width="stretch", **kw)
    except TypeError:  # older Streamlit versions
        st.dataframe(df, hide_index=True, use_container_width=True, **kw)


def _age_text(hours):
    if hours is None or pd.isna(hours):
        return ""
    return f"{hours:.0f}h ago" if hours < 48 else f"{hours / 24:.0f}d ago"


def _open_in_chart():
    st.session_state["ticker_input"] = st.session_state["scan_pick"]
    st.toast(f"Loaded {st.session_state['scan_pick']}. Open the Chart tab.")


def build_overlay(sym, positions, tx, suggested=None):
    """Your real position for `sym` (if any), plus scanner-suggested levels, for the chart."""
    ov = dict(suggested or {})
    row = positions[positions["Symbol"] == sym] if not positions.empty else positions
    if len(row):
        r = row.iloc[0]
        ov.update(entry=float(r["Avg cost"]),
                  stop=None if pd.isna(r["Stop"]) else float(r["Stop"]),
                  target=None if pd.isna(r["Target"]) else float(r["Target"]))
    fills = tx[(tx["symbol"] == sym) & tx["side"].isin(["BUY", "SELL"])]
    ov["fills"] = [{"ts": f.ts, "side": f.side, "qty": f.qty, "price": f.price} for f in fills.itertuples()]
    return ov if (len(row) or ov["fills"] or suggested) else None


# ---- portfolio state (recomputed on every run from the local ledger)
tx_all = store.transactions()
pos = lg.build_positions(tx_all)
held_prices = cached_prices(tuple(sorted(pos["open"]["Symbol"]))) if not pos["open"].empty else {}
valued = lg.value_positions(pos["open"], held_prices, acct_value)
psum = lg.portfolio_summary(valued, pos["closed"], pos["realized"], acct_value, cash_reserve)


def make_account(**extra):
    return sc.Account(
        value=acct_value, risk_pct=risk_pct, daily_risk=risk_budget, daily_used=extra_risk,
        max_position_pct=max_pos_pct, max_positions=int(max_new), fractional=fractional,
        stop_atr_mult=stop_mult, reward_risk=reward_risk,
        cash_available=psum["cash_available"] if (acct_value > 0 and not valued.empty) else None,
        open_risk=psum["open_risk"], realized_today=psum["realized_today"],
        open_positions=psum["positions"], max_open_positions=int(max_open),
        held_symbols=tuple(valued["Symbol"]) if not valued.empty else (), **extra)


# ====================================================================== alerts banner
def show_alert_banner():
    msgs = []
    try:
        alerts = store.price_alerts(include_fired=False)
        if not alerts.empty:
            px = cached_prices(tuple(sorted(set(alerts["symbol"]))))
            for aid, text in lg.price_alert_hits(alerts, px):
                msgs.append(("warning", "Price alert: " + text))
                if f"fired_{aid}" not in st.session_state:
                    st.session_state[f"fired_{aid}"] = True
                    st.toast("Price alert: " + text)
                    store.mark_alert_fired(aid)
    except Exception:
        pass
    if not valued.empty:
        msgs += lg.position_alerts(valued, st.session_state.get("held_extras"), plain=beginner)
    if msgs:
        with st.expander(f"Alerts ({len(msgs)})", expanded=any(m[0] == "error" for m in msgs)):
            for level, text in msgs:
                getattr(st, level)(text)
            st.caption("Alerts are checked only while this app is open, using Yahoo prices that can be delayed. "
                       "They do not replace stop orders at your broker.")


@st.cache_data(ttl=900, show_spinner=False)
def cached_weather():
    try:
        return sc.get_market_weather()
    except Exception:
        return None


def show_weather_banner():
    w = cached_weather()
    if not w:
        st.caption("Market weather is unavailable right now (could not download SPY / QQQ data).")
        return
    getattr(st, w["level"])(f"**Market weather: {w['label']}** ({w['score']}/{w['max']}). "
                            + (w["plain"] if beginner else w["headline"]))
    with st.expander("Weather details"):
        for line in w["details"]:
            st.markdown("- " + line)
        st.caption("Graded from finished daily candles of the S&P 500, the Nasdaq 100 and the VIX. It describes "
                   "the market as a whole, not any one stock, and it is a rule of thumb, not a forecast.")


if practice:
    st.markdown("<div style='background:#6a1b9a;color:white;padding:10px 14px;border-radius:6px;margin-bottom:8px'>"
                "<b>PRACTICE MODE</b>: fake money. Trades you record here are kept apart from your real ones."
                "</div>", unsafe_allow_html=True)
show_weather_banner()
show_alert_banner()

(tab_today, tab_scan, tab_chart, tab_port, tab_week, tab_bt, tab_guide) = st.tabs(
    ["Today", "Scanner", "Chart", "Portfolio", "Weekly review", "Backtest & history", "Guide"])

# ====================================================================== TODAY TAB (daily checklist)
with tab_today:
    today = datetime.now().date()
    day = today.strftime("%Y-%m-%d")
    items = coach.checklist_for(today)
    state = store.checklist_state(day)
    counts = store.checklist_counts()
    st.subheader(f"Today: {today:%A, %B %d}")
    n_done = sum(bool(state.get(i[0], False)) for i in items)
    st.progress(n_done / len(items), text=f"{n_done} of {len(items)} done")
    sk = coach.streak(counts, today)
    if sk:
        st.caption(f"Streak: {sk} finished weekday(s) in a row. Keep it going.")
    elif today.weekday() < 5:
        st.caption("Finish every box today to start a streak.")
    else:
        st.caption("It's the weekend: no trading. Here is a short reset for the week ahead.")
    changed, last_section = False, None
    for iid, section, text in items:
        if section != last_section:
            st.markdown(f"**{section}**")
            last_section = section
        tick = st.checkbox(text, value=bool(state.get(iid, False)), key=f"chk_{day}_{iid}")
        if tick != bool(state.get(iid, False)):
            store.set_check(day, iid, tick)
            changed = True
    if changed:
        st.rerun()
    if n_done == len(items):
        st.success("Checklist complete. Following your routine is the habit that matters most. Great job.")
    st.markdown("**One thing I did well " + ("this week" if today.weekday() >= 5 else "today") + "**")
    note_text = st.text_area("Write it here", value=store.day_note(day), key=f"note_{day}", height=80,
                             label_visibility="collapsed")
    if st.button("Save this"):
        store.set_day_note(day, note_text)
        st.success("Saved. Small wins count.")
    wins_log = store.day_notes((today - pd.Timedelta(days=14)).strftime("%Y-%m-%d"),
                               (today + pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
    if wins_log:
        with st.expander("Your recent wins"):
            for d_, n_ in sorted(wins_log.items(), reverse=True):
                st.markdown(f"- **{d_}:** {n_}")

# ====================================================================== SCANNER TAB
SWING = "Swing setups (check once a day)"
STEADY = "Steady uptrend pullbacks (lower risk)"
MOMENTUM = "Low-float momentum (higher risk)"
PRESET_SHORT = {SWING: "Swing", STEADY: "Steady", MOMENTUM: "Momentum"}


def show_details(sym, d, sig_interval):
    cat, sig, quote = d["catalyst"], d["signal"], d.get("quote") or {}
    st.markdown(f"#### {sym}")
    st.markdown(f"**Signal on {sig_interval} bars:** {sig['label']}")
    for r in (sig.get("reasons_plain") if beginner else sig["reasons"]) or sig["reasons"]:
        st.markdown(f"- {r}")
    if quote.get("spread_pct") is not None:
        st.caption(f"Bid/ask spread: {quote['spread_pct']:.2f}% of price ({quote['bid']:.2f} / {quote['ask']:.2f}). "
                   "Only reliable while the market is open.")
    st.markdown("**Catalyst check** (Yahoo headlines; always read them yourself)")
    if cat["flags"]:
        st.warning("Red flags in the last week of headlines: " + ", ".join(cat["flags"]))
    if cat["earnings_days"] is not None:
        st.caption("Next earnings report: " + ("today" if cat["earnings_days"] == 0
                                               else f"in {cat['earnings_days']} day(s)")
                   + ". Yahoo may show an estimate, so confirm on the company's own site.")
    if not cat["headlines"]:
        st.info("No recent headlines found. That does not mean there is no catalyst. "
                "A big move with no news deserves extra caution.")
    for h in cat["headlines"]:
        title = f"[{h['title']}]({h['url']})" if h["url"] else h["title"]
        st.markdown(f"- {title}  \n  <small>{h['source']} · {_age_text(h['age_h'])}</small>",
                    unsafe_allow_html=True)


def show_plan(plan, info, acct):
    st.markdown("#### Combined plan: what you could take together")
    st.caption(
        f"Cash available to invest: ${info['cash']:.2f}. Risk budget left: ${info['daily_left']:.2f} "
        f"(your ${acct.daily_risk:.2f} limit, minus ${info['open_risk']:.2f} risk on what you own"
        + (f", minus ${info['loss_today']:.2f} lost today" if info["loss_today"] else "")
        + f"). Per trade: ${info['per_trade']:.2f}. Biggest single position: ${info['max_cost']:.2f}. "
        + ("" if info["slots"] >= 10 ** 6 else f"Open slots: {info['slots']}."))
    if plan.empty:
        st.info("Nothing fits your limits right now. Common reasons: the budget is used up by positions you own, "
                "shares cost too much for the position cap, or stops are too wide for the per-trade risk. "
                "Fractional shares or a wider budget would change that, but I would not loosen limits just to see picks.")
        return
    cols = [c for c in ["Symbol", "Price", "Shares", "Cost $", "Stop", "Target", "Risk $",
                        "Signal", "Setup", "Catalyst", "Earnings"] if c in plan.columns]
    show_table(plan[cols])
    st.caption(f"Total cost ${info['plan_cost']:.2f} ({info['plan_cost'] / acct.value * 100:.0f}% of account). "
               f"If every stop is hit you would lose about ${info['plan_risk']:.2f} "
               f"({info['plan_risk'] / acct.value * 100:.1f}% of account). A stop can fill lower if a stock "
               "gaps overnight, so the real loss can be bigger. This is a ceiling on planned stop risk, "
               "not a guarantee of the most you can lose.")


@st.fragment(run_every=scan_minutes * 60 if scan_auto else None)
def scanner_view(preset, criteria, symbols, also_market, only_buy, recent_bars, acct, hide_nofit, sort_by):
    due = scan_auto and (time.time() - st.session_state.get("scan_ts", 0) >= scan_minutes * 60 - 2)
    clicked = st.button("Run scan", key="run_scan")
    if clicked or due:
        with st.spinner("Scanning, then checking headlines and signals... this can take a minute or two."):
            try:
                if preset == SWING:
                    df, stats = sc.swing_scan(criteria, symbols or None, also_market=also_market)
                elif preset == STEADY:
                    df, stats = sc.steady_scan(criteria, symbols or None, also_market=also_market)
                else:
                    df, stats = sc.scan(criteria, symbols or None, also_market=also_market)
                sig_interval = "1d" if preset == SWING else interval
                df, details = sc.enrich(df, interval=sig_interval, threshold=threshold,
                                        window=window, recent_bars=recent_bars)
                st.session_state["scan_res"] = (df, stats, details, sig_interval, preset)
                st.session_state["scan_err"] = None
                try:  # keep a snapshot so you can measure later how these picks did
                    store.save_scan(PRESET_SHORT[preset], sig_interval, asdict(criteria),
                                    sc.stats_line(stats), df)
                except Exception:
                    pass
            except Exception as e:
                st.session_state["scan_res"] = None
                st.session_state["scan_err"] = str(e)
        st.session_state["scan_ts"] = time.time()

    if st.session_state.get("scan_err"):
        st.error(f"Scan failed: {st.session_state['scan_err']}")
    res = st.session_state.get("scan_res")
    if not res:
        return
    df, stats, details, sig_interval, ran_preset = res
    when = time.strftime("%H:%M:%S", time.localtime(st.session_state["scan_ts"]))
    st.caption(f"Scanned {when}  ·  {sc.stats_line(stats)}")
    st.caption(sc.data_line(stats))
    if ran_preset != preset:
        st.warning(f"These results are from the '{PRESET_SHORT[ran_preset]}' scan. Press Run scan to refresh "
                   f"for '{PRESET_SHORT[preset]}'.")
    if only_buy and not df.empty:
        df = df[df["Signal"].str.startswith("BUY")]
    sized, plan, info = sc.size_positions(df, acct)
    if info["enabled"]:
        df = sized
        if hide_nofit:
            df = df[df["Fit"] == "OK"]
    else:
        st.info(info["reason"])
    if df.empty:
        st.info("No matches right now" + (" with a recent BUY signal." if only_buy else "")
                + (" that fit your account limits." if info["enabled"] and hide_nofit else "."))
        return
    if sort_by != "Signal rank (default)" and sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=False, na_position="last")
    show_table(df)
    if info["enabled"]:
        st.caption("'Max shares / cost / risk' is the biggest position you could take in that ONE stock. "
                   "You cannot take them all at once. The combined plan below spends your shared budget in rank order.")
        show_plan(plan, info, acct)
    pick = st.selectbox("Details / open in chart", df["Symbol"].tolist(), key="scan_pick")
    st.button("Load chart", key="load_chart", on_click=_open_in_chart)
    if pick in details:
        show_details(pick, details[pick], sig_interval)


with tab_scan:
    preset = st.radio("Scanner", [SWING, STEADY, MOMENTUM], horizontal=True, key="scan_preset")
    if preset == SWING:
        picked = st.multiselect("Setups to look for", ["Pullback", "Breakout", "Bounce"],
                                default=["Pullback", "Breakout", "Bounce"])
        c1, c2, c3, c4, c5 = st.columns(5)
        w_price = c1.number_input("Price at least ($)", value=10.0, step=1.0)
        w_vol = c2.number_input("Avg volume at least (M shares)", value=1.0, step=0.5)
        w_dollar = c3.number_input("Avg $ volume at least (M)", value=10.0, step=5.0)
        w_atr = c4.number_input("Max daily swing (ATR %)", value=6.0, step=0.5)
        w_earn = c5.number_input("Skip earnings within (days)", min_value=0, max_value=30, value=10)
        criteria = sc.SwingCriteria(setups=tuple(x.lower() for x in picked) or ("pullback",),
                                    min_price=w_price, min_avg_volume=int(w_vol * 1_000_000),
                                    min_dollar_volume=w_dollar * 1_000_000, max_atr_pct=w_atr,
                                    skip_earnings_days=int(w_earn), stop_atr_mult=stop_mult,
                                    reward_risk=reward_risk)
        st.caption("For when you can't watch the screen. Run it after the close. It scans finished daily "
                   "candles of liquid US stocks in an uptrend for pullbacks to the 20 EMA, breakouts above "
                   "the 20-day high on strong volume, and oversold bounces. Stop and target come from recent "
                   "daily swings (set in the sidebar under Trade levels).")
    elif preset == STEADY:
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        s_price = c1.number_input("Price at least ($)", value=10.0, step=1.0)
        s_vol = c2.number_input("Avg volume at least (M shares)", value=1.0, step=0.5)
        s_dollar = c3.number_input("Avg $ volume at least (M)", value=10.0, step=5.0)
        s_dist = c4.number_input("Within % of 20 EMA", value=3.0, step=0.5)
        s_rsi_lo = c5.number_input("RSI at least", value=40.0, step=1.0)
        s_rsi_hi = c6.number_input("RSI at most", value=60.0, step=1.0)
        d1, d2 = st.columns(2)
        s_atr = d1.number_input("Max daily swing (ATR %)", value=4.0, step=0.5)
        s_earn = d2.number_input("Skip earnings within (days, 0 = don't skip)", min_value=0, max_value=30, value=5)
        criteria = sc.SteadyCriteria(min_price=s_price, min_avg_volume=int(s_vol * 1_000_000),
                                     min_dollar_volume=s_dollar * 1_000_000, max_dist_ema20_pct=s_dist,
                                     rsi_min=s_rsi_lo, rsi_max=s_rsi_hi, max_atr_pct=s_atr,
                                     skip_earnings_days=int(s_earn))
        st.caption("Finds liquid US stocks (market cap over $2B) whose daily chart is in an uptrend and that "
                   "have pulled back near the 20 EMA without being overheated or wildly volatile.")
    else:
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        min_change = c1.number_input("Change % at least", value=10.0, step=1.0)
        price_lo = c2.number_input("Price from ($)", value=1.0, step=0.5)
        price_hi = c3.number_input("Price to ($)", value=20.0, step=1.0)
        max_float_m = c4.number_input("Float at most (M)", value=20.0, step=1.0)
        min_rvol = c5.number_input("Rel. volume over", value=5.0, step=0.5)
        min_vol = c6.number_input("Min volume today", value=100_000, step=50_000)
        e1, e2 = st.columns(2)
        m_dollar = e1.number_input("Min $ traded today ($)", value=250_000, step=50_000)
        m_stop = e2.number_input("Stop = % below price (0 = no sizing for this scanner)", value=0.0, step=1.0)
        criteria = sc.Criteria(min_change, price_lo, price_hi, max_float_m * 1_000_000, min_rvol,
                               int(min_vol), min_dollar_volume=float(m_dollar))
        st.caption("Fast, volatile, high risk: wide spreads, halts and sudden reversals are common. It pulls up to "
                   "750 of the biggest movers from Yahoo. If it hits that cap the summary line says so.")

    o1, o2, o3, o4 = st.columns(4)
    only_buy = o1.checkbox("Only show stocks with a recent BUY signal", value=False)
    hide_nofit = o2.checkbox("Hide stocks that don't fit my account", value=True)
    recent_bars = o3.number_input("Count a BUY as recent for (bars)", min_value=1, max_value=30, value=6)
    sort_cols = {SWING: ["Day Vol x", "RSI", "Risk %"], STEADY: ["Avg Vol (M)", "RSI", "ATR %"],
                 MOMENTUM: ["Rel Vol", "Change %", "Volume"]}[preset]
    sort_by = o4.selectbox("Sort by", ["Signal rank (default)"] + sort_cols)

    wl = store.watchlists()
    w1, w2 = st.columns(2)
    chosen_lists = w1.multiselect("Saved watchlists to scan", list(wl))
    typed = w2.text_input("Extra tickers to scan (comma-separated)", value="")
    symbols = sorted({s for n in chosen_lists for s in wl[n]} |
                     {t.upper() for t in typed.replace(",", " ").split() if t})
    also_market = True
    if symbols:
        also_market = st.checkbox("Also scan the whole US market (otherwise only your symbols)", value=False)
    with st.expander("Manage watchlists"):
        n1, n2 = st.columns([1, 2])
        wl_name = n1.text_input("Watchlist name", key="wl_name")
        wl_syms = n2.text_input("Symbols", value=", ".join(symbols), key="wl_syms")
        b1, b2 = st.columns(2)
        if b1.button("Save watchlist"):
            try:
                store.save_watchlist(wl_name, wl_syms.replace(",", " ").split())
                st.success(f"Saved '{wl_name}'.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
        if wl:
            del_name = b2.selectbox("Delete a watchlist", list(wl), key="wl_del")
            if b2.button("Delete watchlist"):
                store.delete_watchlist(del_name)
                st.rerun()

    acct = make_account(pct_stop=(m_stop if preset == MOMENTUM else 0.0))
    st.caption(f"Results are ranked by the current signal on {'daily' if preset == SWING else interval} bars. "
               "Sizing uses your Portfolio holdings, cash and open risk.")
    scanner_view(preset, criteria, symbols, also_market, only_buy, int(recent_bars), acct, hide_nofit, sort_by)


# ====================================================================== CHART TAB

def holding_for(sym):
    row = valued[valued["Symbol"] == sym] if not valued.empty else valued
    if len(row):
        r = row.iloc[0]
        return {"avg": float(r["Avg cost"]), "stop": None if pd.isna(r["Stop"]) else float(r["Stop"])}
    return None


def _pts(n):
    return "0" if n == 0 else f"{n:+d}"


def show_news_check(sym, v, news, price):
    """News section of the verdict card: reasoning lines, tagged headlines, Claude buttons, your own call."""
    st.markdown("**News check:**")
    if news.get("note"):
        st.info(news["note"])
    for tech, plain_ in v["news_lines"]:
        st.markdown("- " + (plain_ if beginner else tech))
    hl = news["headlines"]
    if hl:
        with st.expander(f"Recent headlines with automatic tags ({news['recent']} in the last 7 days)", expanded=True):
            for r in hl:
                safe = r["title"].replace("[", "(").replace("]", ")").replace("<", "").replace(">", "")
                title = f"[{safe}]({r['url']})" if str(r["url"]).startswith("http") else safe
                tags = ", ".join(r["topics"] + [f"⚠ {f}" for f in r["flags"]])
                why = f" ({sc.SKIP_WHY[r['skip']]})" if r.get("skip") else ""
                st.markdown(f"{sc.TONE_ICON[r['tone']]}{why} · {title}")
                st.caption(f"{r['source'] or 'unknown source'} · {sc.age_text(r['age_h'])}" + (f" · {tags}" if tags else ""))
            st.caption("Good / Bad is a rough guess from certain words. It can be wrong (for example 'cuts costs' is good "
                       "but 'cuts guidance' is bad). 'Not counted' means a list, a market blurb, or a headline that does not name "
                       "this company. Yahoo's feed can also miss the biggest stories, so use the Claude buttons.")
    prompt = sc.claude_prompt(sym, v, news, price=price, beginner=beginner)
    st.markdown("**Want help understanding the news?**" if beginner else "**Ask Claude about this news:**")
    c1, c2 = st.columns(2)
    with c1:
        copy_button(prompt, "Copy for Claude", key="c" + "".join(ch if ch.isalnum() else "_" for ch in sym))
    with c2:
        try:
            st.link_button("Open Claude in a new tab", "https://claude.ai/new", width="stretch")
        except TypeError:
            st.link_button("Open Claude in a new tab", "https://claude.ai/new")
    st.caption("Click Copy, open Claude, paste, and send. Claude answers with a good / bad / neutral call you can use below.")
    with st.expander("Show the text that gets copied"):
        st.code(prompt, language=None)
    with st.expander("Know about a trading update, investor day or similar event? Add its date"):
        st.text_input("What is it? (for example: trading update)", key=f"evlabel_{sym}", placeholder="trading update")
        st.date_input("Date", value=None, key=f"evdate_{sym}", help="A BUY within 7 days of this date is held back to HOLD, "
                      "the same as an earnings report. Clear the date to remove it.")
        st.caption("Yahoo's earnings date only covers full earnings reports. Companies like Rolls-Royce also hold trading updates "
                   "that can move the price just as much. Claude can help you find the date.")
    st.radio("Your call on the news after reading it:", ["Not set", "Good news", "Neutral", "Bad news"],
             key=f"newspick_{sym}", horizontal=True,
             help="'Bad news' holds a BUY back to HOLD. 'Good news' never creates a BUY. Your pick is remembered until you "
                  "close the app.")


def show_verdict(sym, df, flags, crit):
    """Buy / Hold / Sell card built from the last 3 months of daily bars."""
    dates, fb_days = cached_earnings(sym)
    earn = sc.earnings_profile(dates, df, fallback_days=fb_days) if (dates is not None or fb_days is not None) else None
    items, news_note = cached_news(sym)
    news = sc.news_profile(items, aliases=cached_aliases(sym))
    news["note"] = news_note
    if earn and earn.get("next_date") is not None:
        earn["implied"] = cached_implied_move(sym, str(pd.Timestamp(earn["next_date"]).date()), float(df.Close.iloc[-1]))
        news["implied_move"] = earn["implied"]
    ev_date = st.session_state.get(f"evdate_{sym}")
    extra_event = None
    if ev_date:
        try:
            extra_event = {"days": (pd.Timestamp(ev_date).normalize() - pd.Timestamp.now().normalize()).days,
                           "label": st.session_state.get(f"evlabel_{sym}") or "company event"}
        except Exception:
            extra_event = None
    pick = st.session_state.get(f"newspick_{sym}", "Not set")
    news["manual"] = {"Good news": "good", "Neutral": "neutral", "Bad news": "bad"}.get(pick)
    v = swc.three_month_verdict(df, flags, crit, holding=holding_for(sym), earnings=earn, news=news, extra_event=extra_event)
    st.subheader("Buy, hold or sell? (last 3 months of daily data)")
    if v is None:
        st.caption("Not enough daily history to give a 3-month verdict.")
        return
    box = {"BUY": st.success, "HOLD": st.warning, "SELL": st.error}[v["verdict"]]
    box(f"**{v['verdict']}**: {v['sub_plain' if beginner else 'sub']}\n\n"
        f"{v['headline_plain' if beginner else 'headline']}\n\n"
        f"Signal strength: {v['strength']} (score {_pts(v['score'])} on a scale from -{v['max']} to +{v['max']})")
    st.caption(v["stats"])
    st.markdown("**Why:**")
    for fct in v["factors"]:
        st.markdown(f"- **({_pts(fct['points'])}) {fct['name']}:** {fct['plain' if beginner else 'tech']}")
    if v["earn_inside"]:
        st.warning("**Earnings land inside this trade.** " + (
            f"The company reports in {v['next_earnings_days']} days, probably while you own the stock. The price can jump past your "
            "safety exit, so buy less or plan to sell before the report." if beginner else
            f"Report in {v['next_earnings_days']} days, inside the plan's {v['hold_days']}-day max hold. Gap risk: size smaller or exit before it."))
    st.markdown("**Earnings check:**")
    for tech, plain_ in v["earnings_lines"]:
        st.markdown("- " + (plain_ if beginner else tech))
    show_news_check(sym, v, news, float(df.Close.iloc[-1]))
    if v["earnings_reports"]:
        with st.expander("Recent earnings reports and how the stock reacted"):
            show_table(pd.DataFrame([{
                "Report date": f"{x['date']:%b %d, %Y}", "EPS expected": x["est"], "EPS reported": x["actual"],
                "Beat / miss %": None if x["surprise"] is None else round(x["surprise"], 1),
                "Stock move over 2 days %": None if x["move"] is None else round(x["move"], 1)}
                for x in v["earnings_reports"]]))
            st.caption("EPS is earnings per share. 'Stock move' is the change from the close before the report day to "
                       "the close after it, so it covers reports made before the open or after the close.")
    st.caption("Read the real release: " + "  ·  ".join(f"[{n}]({u})" for n, u in sc.earnings_links(sym))
               + ". Companies file their earnings press release on SEC form 8-K (Item 2.02).")
    for tech, plain_ in v["holding"]:
        st.info(plain_ if beginner else tech)
    st.markdown("**Watch out for:**")
    for tech, plain_ in v["cautions"]:
        st.markdown("- " + (plain_ if beginner else tech))
    st.markdown("**What would change this:** " + v["change"][1 if beginner else 0])
    if v["levels"]:
        px = float(df.Close.iloc[-1])
        st.markdown(f"**If you bought around {px:.2f}:** " + (
            f"a safety exit (stop) near {v['levels']['stop']:.2f} and a profit goal (target) near {v['levels']['target']:.2f}."
            if beginner else
            f"stop near {v['levels']['stop']:.2f}, target near {v['levels']['target']:.2f} (from your Trade levels settings)."))
    st.caption("A rule-of-thumb read of recent prices, not a prediction or advice. It adds up seven simple checks, "
               "each scored -1 to +1 (the 3-month change counts up to 2). BUY needs +4 or more and SELL needs -3 or less.")


def daily_inputs(sym):
    """Daily bars, swing-setup flags and criteria for the verdict (used by the intraday chart too)."""
    raw_d = so.drop_unfinished_bar(fetch(sym, "3y", "1d"), so.interval_to_timedelta("1d"))
    if len(raw_d) < so.MIN_BARS:
        return None
    d = so.add_indicators(raw_d)
    crit_d = sc.SwingCriteria(stop_atr_mult=stop_mult, reward_risk=reward_risk, max_atr_pct=100.0,
                              min_avg_volume=0, min_dollar_volume=0, min_price=0)
    return d, sc.swing_setup_flags(d, crit_d), crit_d


GLOSSARY = [
    ("Candle", "One bar on the chart. It shows where the price started, ended, and its highest and lowest points in that time."),
    ("EMA (the colored lines)", "An average of recent prices. Blue = very recent, orange = a bit longer, purple = the long-term trend."),
    ("Uptrend", "The price is above the purple line, so over the long run the stock has been going up."),
    ("RSI", "A mood gauge from 0 to 100. Above 70 = people are buying very fast (may cool off). Below 30 = heavy selling (may bounce)."),
    ("Volume", "How many shares traded. Big volume means lots of people care, so a move is more believable."),
    ("Stop (safety exit)", "A sell order that triggers if the price falls to your chosen level, to limit how much you can lose."),
    ("Target (profit goal)", "The price where you plan to sell and take your profit."),
    ("Signal", "A clue from the tool that something may be changing. Signals are often wrong, so they are a reason to look closer, not an order."),
]


def show_glossary():
    with st.expander("What do these words mean? (beginner glossary)"):
        for term, text in GLOSSARY:
            st.markdown(f"**{term}:** {text}")

@st.fragment(run_every=refresh if auto else None)
def chart_view(mode):
    if not ticker:
        st.info("Type a ticker symbol in the sidebar to begin.")
        return
    swing_mode = mode.startswith("Swing")
    bar = "1d" if swing_mode else interval
    delta = so.interval_to_timedelta(bar)
    try:
        raw = fetch(ticker, "3y" if swing_mode else so.default_period(bar), bar)
        raw = so.drop_unfinished_bar(raw, delta)
        if len(raw) < so.MIN_BARS:
            st.error(f"Only {len(raw)} finished bars available; need about {so.MIN_BARS} "
                     "for the 200 EMA. Try a larger bar size.")
            return
    except Exception as e:
        st.error(f"Couldn't load {ticker}: {e}")
        return

    st.title(f"{ticker}  ·  {'swing (daily)' if swing_mode else bar + ' bars'}")
    st.caption(f"Source: Yahoo Finance (can be delayed)  ·  updated {pd.Timestamp.now():%H:%M:%S}  ·  "
               f"{so.market_session_label()}  ·  last finished bar: {raw.index[-1]}  ·  close {raw.Close.iloc[-1]:.2f}")

    if not swing_mode and delta is not None:
        now = pd.Timestamp.now(tz=raw.index.tz) if raw.index.tz is not None else pd.Timestamp.now()
        if now - (raw.index[-1] + delta) > 3 * delta:
            st.warning("The latest bar is old, so the market is probably closed. Nothing will change until it reopens.")

    n = bars
    if swing_mode:
        df = so.add_indicators(raw)
        crit = sc.SwingCriteria(stop_atr_mult=stop_mult, reward_risk=reward_risk, max_atr_pct=100.0,
                                min_avg_volume=0, min_dollar_volume=0, min_price=0)
        flags = sc.swing_setup_flags(df, crit)
        shown = st.multiselect("Markers to show", ["Pullback", "Breakout", "Bounce"],
                               default=["Pullback", "Breakout", "Bounce"], key="swing_markers")
        outcomes = st.checkbox("Show what happened next in the hover text (for learning)", value=True,
                               key="swing_outcomes")
        ranges = {"1 month": 21, "3 months": 63, "6 months": 126, "1 year": 252, "2 years": 504}
        rng_pick = st.radio("Time range (each candle is one trading day)", list(ranges), index=1,
                            horizontal=True, key="swing_range")
        n = ranges[rng_pick]
        last = df.iloc[-1]
        atr = float(flags["atr"].iloc[-1])
        sugg = None
        if any(bool(flags[k].iloc[-1]) for k in ("pullback", "breakout", "bounce")) and atr == atr:
            stp = float(last.Close - stop_mult * atr)
            sugg = {"suggested_stop": stp, "suggested_target": float(last.Close + reward_risk * (last.Close - stp))}
        overlay = build_overlay(ticker, valued, tx_all, sugg)
        fig = swc.build_swing_chart(df.tail(n), flags.tail(n), crit, f"{ticker} - swing setups (daily)",
                                    setups=tuple(s.lower() for s in shown), opts={"volume": opt_volume, "sr": opt_sr, "beginner": beginner},
                                    overlay=overlay, show_outcomes=outcomes)
        st.caption("The swing chart is always daily, so the Bar size setting in the sidebar doesn't apply here. "
                   "Pick a bar size or switch to Intraday signals to use it.")
        st.caption("Hover a marker to see why the scanner would have flagged that day, the levels it would have "
                   "suggested, and what price did next. Diamond = pullback, star = breakout, circle = bounce. "
                   "Your own entry, stop and target (from the Portfolio tab) are solid lines; suggested levels are dotted.")
        fig.update_layout(uirevision=f"{ticker}-swing")
        show_chart(fig, "swing_chart")
        show_verdict(ticker, df, flags, crit)
        st.subheader("Current read")
        st.code("\n".join(swc.current_swing_read(df, flags, crit, plain=beginner)), language=None)
        return

    args = SimpleNamespace(window=window, threshold=threshold)
    df, ev, active = so.analyze(raw, args)
    latest = df.iloc[-1]
    if latest.BUY or latest.SELL:
        kind = "BUY" if latest.BUY else "SELL"
        msg = f"New {kind} signal on {ticker} at {latest.Close:.2f}. See the explanation below."
        (st.success if latest.BUY else st.error)(msg)
        key = f"alerted_{ticker}_{bar}"
        if st.session_state.get(key) != df.index[-1]:
            st.session_state[key] = df.index[-1]
            st.toast(msg)
    overlay = build_overlay(ticker, valued, tx_all)
    fig = so.build_chart(df.tail(n), ev.tail(n), active.tail(n), window, f"{ticker} - signals ({bar})",
                         opts={"volume": opt_volume, "vwap": opt_vwap, "sr": opt_sr, "bb": opt_bb, "macd": opt_macd,
                               "beginner": beginner},
                         overlay=overlay)
    fig.update_layout(uirevision=f"{ticker}-{bar}")
    show_chart(fig, "main_chart")
    try:
        inp = daily_inputs(ticker)
        if inp:
            show_verdict(ticker, *inp)
        else:
            st.caption("Not enough daily history to give a 3-month verdict.")
    except Exception as e:
        st.caption(f"The 3-month verdict is unavailable right now ({e}).")
    left, right = st.columns(2)
    with left:
        st.subheader("Current read")
        st.code("\n".join(so.current_report(df, ev, active, window, threshold, plain=beginner)), language=None)
    with right:
        st.subheader("Recent signals")
        st.code("\n".join(so.history_report(df, ev, active, window, last_n=4, plain=beginner)), language=None)
    with st.expander("Quick look: what price did after past signals (not a backtest)"):
        st.code("\n".join(so.hit_rate_report(df, 10)), language=None)
        st.caption("For a fuller test with next-bar entries, stops, gaps and costs, use the Backtest & history tab.")


with tab_chart:
    chart_mode = st.radio("Chart", ["Swing setups (daily)", "Intraday signals"], horizontal=True,
                          key="chart_mode")
    if beginner:
        show_glossary()
    chart_view(chart_mode)


# ====================================================================== PORTFOLIO TAB
def rnd(df, n=2):
    """Round numeric columns only (leaves dates and text alone)."""
    out = df.copy()
    num = out.select_dtypes("number").columns
    out[num] = out[num].round(n)
    return out


def money(x):
    return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"


with tab_port:
    st.subheader("What you own")
    st.caption("Built from the trades you enter below. This app does not read your Robinhood account, so record "
               "each buy, sell and stop change here to keep it accurate.")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Invested (market value)", money(psum["market_value"]),
              None if psum["exposure_pct"] is None else f"{psum['exposure_pct']:.0f}% of account", delta_color="off")
    m2.metric("Unrealized P&L", money(psum["unrealized"]))
    m3.metric("Realized today", money(psum["realized_today"]))
    m4.metric("Realized, all time", money(psum["realized_total"]))
    m5, m6, m7, m8 = st.columns(4)
    m5.metric("Risk to stops", money(psum["open_risk"]),
              None if risk_budget <= 0 else f"of ${risk_budget:,.0f} budget", delta_color="off")
    m6.metric("Cash available", "set account value" if psum["cash_available"] is None
              else money(psum["cash_available"]))
    m7.metric("Open positions", psum["positions"], None if max_open <= 0 else f"cap {int(max_open)}", delta_color="off")
    m8.metric("Largest position", "-" if psum["largest_pct"] is None else f"{psum['largest_pct']:.0f}%")
    st.caption("'Risk to stops' is the estimated loss if every stop fills at its price. Positions with no stop "
               "recorded count as fully at risk. Gaps and poor fills can make a real loss bigger.")

    if valued.empty:
        st.info("No open positions yet. Record a buy below, or run the Scanner tab.")
    else:
        cols = ["Symbol", "Shares", "Avg cost", "Price", "Market value", "Unrealized $", "Unrealized %",
                "Stop", "Target", "To stop %", "To target %", "Risk to stop $", "Exposure %", "Days held", "Strategy"]
        show_table(rnd(valued[cols]))
        st.caption("Prices are from Yahoo and can be delayed. 'To stop %' is how far price is above your stop.")

        st.markdown("#### Raise your stops")
        sugs = lg.stop_suggestions(valued, plain=beginner)
        if not sugs:
            st.caption("Nothing to raise yet. Suggestions appear once a trade is up about 1R (the amount you risked).")
        for sg in sugs:
            sc1, sc2 = st.columns([4, 1])
            sc1.success(sg["text"])
            if sc2.button(f"I moved it to {sg['Suggested stop']:.2f}", key=f"mv_{sg['Symbol']}_{sg['Suggested stop']}"):
                try:
                    store.add_transaction(sg["Symbol"], "ADJUST", stop=sg["Suggested stop"], ts=datetime.now())
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
        if sugs:
            st.caption("At Robinhood, cancel your old stop order and place a new one at the suggested price, then "
                       "click the button to record it here. A stop only ever moves UP.")

        with st.expander("Close or remove a position", expanded=False):
            rp = st.selectbox("Position", valued["Symbol"].tolist(), key="rm_pos")
            rrow = valued[valued["Symbol"] == rp].iloc[0]
            st.markdown("**You sold it:** records a sale, so it moves to Finished trades with its profit or loss.")
            q1, q2, q3 = st.columns(3)
            sell_px = q1.number_input("Sale price", min_value=0.0, step=0.01, format="%.4f",
                                      value=float(rrow["Price"]) if pd.notna(rrow["Price"]) else 0.0, key="rm_px")
            sell_fee = q2.number_input("Fees ($)", min_value=0.0, step=0.01, key="rm_fee")
            if q3.button("Record: sold all shares"):
                try:
                    store.add_transaction(rp, "SELL", float(rrow["Shares"]), sell_px, ts=datetime.now(),
                                          fees=sell_fee, strategy=str(rrow["Strategy"] or ""))
                    st.success(f"{rp} closed.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
            st.markdown("**I entered it by mistake:** erases every record of this position as if it never happened "
                        "(no profit or loss is kept).")
            sure = st.checkbox(f"Yes, erase the {rp} position", key=f"rm_sure_{rp}")
            if st.button("Erase this position"):
                if not sure:
                    st.warning("Tick the box first to confirm.")
                else:
                    try:
                        n_gone = store.remove_open_position(rp)
                        st.success(f"Erased {n_gone} record(s) for {rp}.")
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))

    cA, cB = st.columns(2)
    if cA.button("Check news & signals for my positions") and not valued.empty:
        with st.spinner("Checking headlines, earnings dates and daily signals..."):
            extras = {}
            for s in valued["Symbol"]:
                extras[s] = {"catalyst": sc.get_catalyst(s), "signal": sc.signal_summary(s, "1d")}
            st.session_state["held_extras"] = extras
        st.rerun()
    if st.session_state.get("held_extras"):
        cB.caption("Alerts above include earnings, red-flag headlines and daily SELL signals for your positions.")

    st.subheader("Record a trade")
    with st.form("trade_form"):
        f1, f2, f3, f4 = st.columns(4)
        t_sym = f1.text_input("Symbol", value=ticker)
        t_side = f2.selectbox("Action", ["BUY", "SELL", "ADJUST stop/target"])
        t_qty = f3.number_input("Shares", min_value=0.0, step=1.0, format="%.4f")
        t_px = f4.number_input("Price", min_value=0.0, step=0.01, format="%.4f")
        g1, g2, g3, g4 = st.columns(4)
        t_date = g1.date_input("Date", value=datetime.now().date())
        t_time = g2.time_input("Time", value=datetime.now().time().replace(microsecond=0))
        t_fees = g3.number_input("Fees ($)", min_value=0.0, step=0.01)
        t_strategy = g4.selectbox("Strategy", ["swing", "steady", "momentum", "other"])
        h1, h2, h3 = st.columns([1, 1, 2])
        t_stop = h1.number_input("Stop (0 = unchanged / none)", min_value=0.0, step=0.01, format="%.4f")
        t_target = h2.number_input("Target (0 = unchanged / none)", min_value=0.0, step=0.01, format="%.4f")
        t_notes = h3.text_input("Notes (why you took it)")
        submitted = st.form_submit_button("Save trade")
    if submitted:
        try:
            store.add_transaction(t_sym, t_side.split()[0], t_qty, t_px, ts=datetime.combine(t_date, t_time),
                                  fees=t_fees, strategy=t_strategy, stop=t_stop or None,
                                  target=t_target or None, notes=t_notes)
            st.success("Saved.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))

    with st.expander("Trade history and corrections"):
        if tx_all.empty:
            st.caption("No trades recorded yet.")
        else:
            show_table(tx_all.sort_values("ts", ascending=False)[
                ["id", "ts", "symbol", "side", "qty", "price", "fees", "strategy", "stop", "target", "notes"]])
            d1, d2 = st.columns([1, 3])
            del_id = d1.selectbox("Delete a trade (by id)", tx_all["id"].tolist()[::-1], key="del_tx")
            if d1.button("Delete this trade"):
                try:
                    store.delete_transaction(del_id)
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))
            d2.download_button("Download all trades as CSV", tx_all.to_csv(index=False), "trades.csv", "text/csv")

    st.subheader("Finished trades")
    if pos["closed"].empty:
        st.caption("Nothing closed yet.")
    else:
        stt = lg.closed_trade_stats(pos["closed"])
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Trades", stt["trades"])
        k2.metric("Win rate", f"{stt['win_rate']:.0f}%")
        k3.metric("Profit factor", "no losses" if stt["profit_factor"] == float("inf") else f"{stt['profit_factor']:.2f}")
        k4.metric("Average R", "-" if stt["avg_r"] != stt["avg_r"] else f"{stt['avg_r']:+.2f}")
        show_table(rnd(pos["closed"]).sort_values("Closed", ascending=False))
        st.caption("R = profit or loss measured in units of the risk you took (entry minus your first stop). "
                   "A handful of trades says very little, so judge your process more than the totals.")

    st.subheader("Price alerts")
    p1, p2, p3, p4 = st.columns([1, 1, 1, 2])
    a_sym = p1.text_input("Symbol", value=ticker, key="al_sym")
    a_dir = p2.selectbox("Alert when price is", ["above", "below"], key="al_dir")
    a_px = p3.number_input("Price", min_value=0.0, step=0.01, key="al_px")
    a_note = p4.text_input("Note", key="al_note")
    if st.button("Add price alert"):
        try:
            store.add_price_alert(a_sym, a_dir, a_px, a_note)
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    al = store.price_alerts()
    if not al.empty:
        show_table(al[["id", "symbol", "direction", "price", "note", "created", "fired"]])
        x1, x2 = st.columns([1, 3])
        rm = x1.selectbox("Remove alert (id)", al["id"].tolist(), key="al_rm")
        if x1.button("Remove alert"):
            store.delete_price_alert(rm)
            st.rerun()
        x2.caption("Alerts are checked each time the app refreshes while it is open. Keep real stops at Robinhood.")


# ====================================================================== WEEKLY REVIEW TAB
with tab_week:
    st.subheader("Weekly review")
    st.caption("A look back at your week. It starts with what you did well, then offers one thing to work on. "
               "It judges your habits more than your profit, because good habits are what grow a small account.")
    this_monday = coach.week_bounds(datetime.now().date())[0]
    weeks = [this_monday - pd.Timedelta(days=7 * i) for i in range(12)]
    wk = st.selectbox("Week starting (Monday)", weeks, key="wk_pick",
                      format_func=lambda d: f"{d:%b %d, %Y}" + ("  (this week)" if d == this_monday else ""))
    rev = coach.weekly_review(pos["closed"], tx_all, wk, counts=store.checklist_counts(),
                              account_value=acct_value, risk_pct=risk_pct)
    s_ = rev["stats"]
    w1, w2, w3, w4 = st.columns(4)
    w1.metric("Trades closed", s_["trades"])
    w2.metric("Win rate", "-" if s_["win_rate"] is None else f"{s_['win_rate']:.0f}%")
    w3.metric("Profit / loss", money(s_["pnl"]))
    w4.metric("Habits on track", f"{rev['good']} of {rev['total']}" if rev["total"] else "-")

    if rev["praise"]:
        st.markdown("#### What went well")
        for p_ in rev["praise"]:
            st.success(p_)
    if rev["improve"]:
        st.markdown("#### What to work on")
        st.caption("In order of importance. Focus on the first one or two; the rest can wait.")
        for what, tip in rev["improve"][:3]:
            st.info(f"{what}\n\n**Try this:** {tip}")
        if len(rev["improve"]) > 3:
            with st.expander("Smaller things for later"):
                for what, tip in rev["improve"][3:]:
                    st.markdown(f"- {what} **Try this:** {tip}")
    st.markdown(f"**One focus for next week:** {rev['focus']}")

    if rev["habits"]:
        st.markdown("#### Habit scorecard")
        show_table(pd.DataFrame([{"Habit": h["title"], "This week": "On track" if h["status"] == "good" else "Work on",
                                  "Details": h["message"]} for h in rev["habits"]]))
    st.caption("R means the amount you planned to risk on a trade. +2R is twice that in profit; -1R is a loss "
               "of what you planned.")

    notes_wk = store.day_notes(wk.strftime("%Y-%m-%d"), (wk + pd.Timedelta(days=7)).strftime("%Y-%m-%d"))
    if notes_wk:
        st.markdown("#### Wins you wrote down this week")
        for d_, n_ in notes_wk.items():
            st.markdown(f"- **{d_}:** {n_}")

    trades_wk = rev["trades"]
    if len(trades_wk):
        st.markdown("#### What did you learn from each trade?")
        with st.form(f"lessons_{wk:%Y%m%d}"):
            lesson_inputs = []
            for _, t_ in trades_wk.iterrows():
                k_ = coach.lesson_key(t_["Symbol"], t_["Closed"])
                label = f"{t_['Symbol']} (closed {t_['Closed']:%b %d}, {money(t_['P&L $'])})"
                lesson_inputs.append((k_, st.text_input(label, value=store.lesson(k_), key=f"les_{k_}")))
            if st.form_submit_button("Save lessons"):
                for k_, txt in lesson_inputs:
                    store.set_lesson(k_, txt)
                st.success("Saved.")


# ====================================================================== GUIDE TAB
with tab_guide:
    guide.show(st)


# ====================================================================== BACKTEST TAB
with tab_bt:
    st.subheader("Test the swing rules on past data")
    st.caption("Enters at the NEXT day's open after a setup, simulates your stop and target day by day (a gap "
               "through the stop fills at the worse price; if one day touches both, the stop counts first), and "
               "subtracts a round-trip cost. It does not avoid earnings dates, and it only includes stocks that "
               "still exist, so results look a bit better than reality. Treat it as a sanity check.")
    b1, b2, b3, b4 = st.columns(4)
    bt_setups = b1.multiselect("Setups", ["Pullback", "Breakout", "Bounce"], default=["Pullback", "Breakout", "Bounce"])
    bt_hold = b2.number_input("Max days to hold", min_value=2, max_value=60, value=15)
    bt_cost = b3.number_input("Round-trip cost (%)", min_value=0.0, max_value=3.0, value=0.2, step=0.05)
    bt_years = b4.selectbox("History", ["3y", "5y", "10y"], index=1)
    u1, u2 = st.columns(2)
    bt_universe = u1.selectbox("Stocks to test", ["My symbols (watchlists / typed below)", "Top liquid US stocks"])
    bt_n = u2.number_input("How many top liquid stocks", min_value=20, max_value=500, value=100, step=20)
    bt_typed = st.text_input("Symbols for 'My symbols' (comma-separated)", value="")
    split_date = st.date_input("Split date: results before vs after (check the rules on newer data)",
                               value=(pd.Timestamp.now() - pd.DateOffset(years=1)).date())
    if st.button("Run backtest"):
        syms = [s.upper() for s in bt_typed.replace(",", " ").split() if s]
        if bt_universe.startswith("My") and not syms:
            syms = sorted({s for lst in store.watchlists().values() for s in lst})
        try:
            if bt_universe.startswith("Top"):
                syms = [s for s, _ in sc.steady_universe(sc.SwingCriteria(universe_size=int(bt_n)))]
            if not syms:
                st.error("Enter some symbols, or choose 'Top liquid US stocks'.")
            else:
                bar = st.progress(0.0, text="Downloading history...")
                frames = bt.load_daily(syms, period=bt_years)
                crit = sc.SwingCriteria(stop_atr_mult=stop_mult, reward_risk=reward_risk)
                params = bt.BTParams(setups=tuple(s.lower() for s in bt_setups) or ("pullback",),
                                     stop_atr_mult=stop_mult, reward_risk=reward_risk,
                                     max_hold=int(bt_hold), cost_pct=bt_cost)
                trades = bt.run_backtest(frames, crit, params,
                                         progress=lambda f, s: bar.progress(min(f, 1.0), text=f"Testing {s}..."))
                bar.empty()
                st.session_state["bt_res"] = (trades, len(frames), len(syms), str(split_date))
        except Exception as e:
            st.error(f"Backtest failed: {e}")
    res = st.session_state.get("bt_res")
    if res:
        trades, loaded, asked, split = res
        st.caption(f"{loaded} of {asked} symbols had data. Stop {stop_mult:g} ATR, target {reward_risk:g}x risk.")
        if trades.empty:
            st.info("No trades were generated with these settings.")
        else:
            allm = bt.metrics(trades)
            before, after = bt.split_metrics(trades, split)

            def row(label, m):
                if not m.get("trades"):
                    return {"Period": label, "Trades": 0}
                return {"Period": label, "Trades": m["trades"], "Win rate %": round(m["win_rate"], 1),
                        "Avg R": round(m["avg_r"], 2), "Avg win R": round(m["avg_win_r"], 2),
                        "Avg loss R": round(m["avg_loss_r"], 2),
                        "Profit factor": round(m["profit_factor"], 2) if m["profit_factor"] != float("inf") else None,
                        "Avg days": round(m["avg_days"], 1), "Max drawdown R": round(m["max_drawdown_r"], 1),
                        "Gap stops": m["gap_stops"], "Most open at once": m["max_concurrent"]}
            show_table(pd.DataFrame([row("All", allm), row(f"Before {split}", before), row(f"From {split}", after)]))
            st.caption("R = profit measured in units of the risk taken. Avg R above 0 means the average trade made money "
                       "after costs. If 'before' looks great and 'from' does not, the edge may not be real.")
            eq = trades[trades["reason"] != "Still open"].sort_values("exit_date")
            st.line_chart(pd.DataFrame({"Cumulative R": eq["r"].cumsum().to_numpy()}, index=eq["exit_date"]))
            with st.expander("All simulated trades"):
                show_table(rnd(trades))
                st.download_button("Download trades as CSV", trades.to_csv(index=False), "backtest_trades.csv", "text/csv")

    st.subheader("How saved scans performed")
    st.caption("Every scan you run is saved with its settings and picks. This looks at what each pick did afterward, "
               "so you can judge a scanner by real results instead of one chart.")
    hist = store.scan_history()
    if hist.empty:
        st.info("No saved scans yet. Run a scan in the Scanner tab and come back in a few days.")
    else:
        show_table(hist.head(15))
        if st.button("Measure how past picks did"):
            def fetch_history(sym, start):
                import yfinance as yf
                return yf.Ticker(sym).history(start=(start - pd.Timedelta(days=3)).strftime("%Y-%m-%d"), interval="1d")
            with st.spinner("Downloading prices after each scan..."):
                try:
                    ev = lg.evaluate_scan_results(store.scan_results(), fetch_history)
                    st.session_state["scan_eval"] = ev
                except Exception as e:
                    st.error(f"Couldn't evaluate: {e}")
        ev = st.session_state.get("scan_eval")
        if ev is not None and not ev.empty:
            show_table(rnd(lg.summarize_evaluation(ev)))
            with st.expander("Each pick"):
                show_table(rnd(ev))
            st.caption("'Target first' means the suggested target was reached before the stop within 10 trading days. "
                       "Picks from today have no future days yet, so they only appear once a later session has closed.")
        elif ev is not None:
            st.info("Not enough time has passed since your scans to measure them. Check again after the next session closes.")

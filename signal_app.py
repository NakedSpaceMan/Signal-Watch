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
    Learn                lessons and practice trades on made-up charts (support, breakouts, flags and more)

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
import chart_utils as cu
import coach
import forecast as fc
import guide
import learn
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
def get_store(path, code_version=0.0):
    # code_version changes when ledger.py is replaced, so an updated Store is used without restarting the app
    return lg.Store(path)


st.sidebar.header("Mode")
practice = st.sidebar.checkbox("Practice mode (fake money)", value=bool(_saved.get("practice", False)),
                               help="A separate practice ledger, kept apart from your real trades. Good for "
                                    "learning or letting someone else try the app.")
try:
    _ledger_version = Path(lg.__file__).stat().st_mtime
except OSError:
    _ledger_version = 0.0
store = get_store(str(PRACTICE_DB if practice else lg.DB_PATH), _ledger_version)

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
fractional = False   # Robinhood stop-loss orders need whole shares, so plans use whole shares only

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
            "max_new": int(max_new), "max_open": int(max_open),
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


# A small easter egg at the bottom of the sidebar: hover the bill for a note, click it for a little "ka-ching".
# The sound is generated in the browser (no audio file, nothing downloaded).
def money_egg():
    import streamlit.components.v1 as components

    components.html("""
<style>
  body { margin: 0; font-family: -apple-system, Segoe UI, sans-serif; color: #888; text-align: center; }
  #bill { font-size: 34px; cursor: pointer; display: inline-block; transition: transform .15s; user-select: none; }
  #bill:hover { transform: rotate(-8deg) scale(1.2); }
  #msg { font-size: 12px; line-height: 1.35; max-height: 0; opacity: 0; overflow: hidden; transition: all .25s; padding: 0 4px; }
  #wrap:hover #msg { max-height: 130px; opacity: 1; margin-top: 4px; }
  #sm { font-size: 10px; opacity: .8; margin-top: 3px; }
</style>
<div id="wrap">
  <div id="bill" title="Click me">💵</div>
  <div id="msg">I've got the brains, you've got the  looks<br>Let's make lots of money
    <div id="sm">♪ A nod to the Pet Shop Boys' &ldquo;Opportunities (Let's Make Lots of Money)&rdquo;</div></div>
</div>
<script>
// A bright two-note "ka-ching". Plays a small generated WAV (works in Safari too); falls back to Web Audio.
let audio = null, ctx = null;

function makeWav() {
  const sr = 22050, n = Math.floor(sr * 0.65), pcm = new Int16Array(n);
  [[1318.5, 0, 0.12], [1760, 0.11, 0.45]].forEach(([f, d, len]) => {
    const s0 = Math.floor(sr * d), s1 = Math.min(n, Math.floor(sr * (d + len + 0.05)));
    for (let i = s0; i < s1; i++) {
      const t = (i - s0) / sr, ph = (t * f) % 1;
      const env = Math.min(1, t / 0.01) * Math.exp(-t * 7);
      pcm[i] += Math.round((4 * Math.abs(ph - 0.5) - 1) * env * 0.25 * 32767);   // triangle wave
    }
  });
  const buf = new ArrayBuffer(44 + n * 2), v = new DataView(buf);
  const str = (o, t) => { for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i)); };
  str(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); str(8, "WAVE"); str(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
  v.setUint32(24, sr, true); v.setUint32(28, sr * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
  str(36, "data"); v.setUint32(40, n * 2, true);
  for (let i = 0; i < n; i++) v.setInt16(44 + i * 2, pcm[i], true);
  return new Blob([buf], {type: "audio/wav"});
}

function webAudioFallback() {
  try {
    const AC = window.AudioContext || window.webkitAudioContext;
    ctx = ctx || new AC();
    const go = () => {
      const t = ctx.currentTime;
      [[1318.5, 0, .12], [1760, .11, .45]].forEach(([f, d, len]) => {
        const o = ctx.createOscillator(), g = ctx.createGain();
        o.type = "triangle"; o.frequency.value = f;
        g.gain.setValueAtTime(0, t + d); g.gain.linearRampToValueAtTime(.25, t + d + .01);
        g.gain.exponentialRampToValueAtTime(.001, t + d + len);
        o.connect(g); g.connect(ctx.destination); o.start(t + d); o.stop(t + d + len + .05);
      });
    };
    if (ctx.state === "suspended") ctx.resume().then(go); else go();
  } catch (e) {}
}

document.getElementById("bill").addEventListener("click", () => {
  try {
    if (!audio) audio = new Audio(URL.createObjectURL(makeWav()));
    audio.currentTime = 0;
    const p = audio.play();
    if (p && p.catch) p.catch(webAudioFallback);
  } catch (e) { webAudioFallback(); }
});
</script>""", height=150)


try:
    with st.sidebar:
        st.divider()
        money_egg()
except Exception:
    pass


# ====================================================================== helpers
@st.cache_data(ttl=20, show_spinner=False)
def fetch(tkr, period, intv):
    return so.load_data(tkr, period, intv)


@st.cache_data(ttl=900, show_spinner=False)
def cached_history(symbols, start):
    """Daily closes since `start` for each symbol (used for the Portfolio growth chart). Symbols that fail are left out."""
    import yfinance as yf
    out = {}
    for s in symbols:
        try:
            h = yf.Ticker(s).history(start=start, interval="1d", auto_adjust=True)
            if len(h):
                out[s] = h["Close"]
        except Exception:
            pass
    return out


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


def esc_md(text):
    """Streamlit reads text between two $ signs as math, which garbles prices. Escape them."""
    return text.replace("$", "\\$")


def col_help(df, tips):
    """Hover help for table headers: pass {column name: plain-English tip}. Skips columns that aren't there."""
    try:
        return {c: st.column_config.Column(c, help=tips[c]) for c in df.columns if c in tips}
    except Exception:  # older Streamlit without column_config
        return {}


BT_TIPS = {
    "Period": "Which slice of history this row covers. 'All' is everything. The other two split it at your split "
              "date, so you can see whether the rules also worked on the newer data.",
    "Trades": "How many pretend trades the rules would have taken. More is better. Under about 30 trades is too "
              "few to trust any of the other numbers.",
    "Win rate %": "How often a trade reached its target before its stop. A LOW win rate is normal and fine here: "
                  "because winners are set to pay more than losers cost, you can lose most trades and still make "
                  "money. With a 2-to-1 target, you only need to win about 1 in 3.",
    "Avg R": "The average result per trade, measured in units of what you risked (R). +0.2R means that on average "
             "you made 20% of your risk per trade, after costs. Anything above 0 means the rules made money on "
             "average. Small positive numbers are good and realistic. Very big ones usually mean something is off.",
    "Avg win R": "How much a winning trade made on average, in units of risk. +2R means winners paid twice what "
                 "you risked.",
    "Avg loss R": "How much a losing trade lost on average, in units of risk. Close to -1R means the stop did its "
                  "job and you lost about what you planned. Worse than -1R means gaps or costs made losses bigger.",
    "Profit factor": "Total money won divided by total money lost. Above 1.0 means winners outweighed losers. "
                     "1.3 or more is decent. Blank means there were no losing trades.",
    "Avg days": "How long a typical trade lasted, in trading days (weekends and holidays don't count).",
    "Max drawdown R": "The worst losing stretch: how far the running total fell from its best point, in units of "
                      "risk. It tells you how bad a rough patch can feel. Plan for it, because it will happen.",
    "Gap stops": "Trades where the price jumped past your stop overnight, so you got out at a worse price than "
                 "planned. This is a real risk of holding overnight, and the test includes it.",
    "Most open at once": "The most trades the rules would have held at the same time. With a small account you "
                         "can't hold that many, so treat it as a ceiling.",
    "symbol": "The stock.", "setup": "Which pattern triggered the trade: Pullback, Breakout or Bounce.",
    "entry_date": "The day the pretend trade was opened (the morning after the signal).",
    "exit_date": "The day the pretend trade was closed.",
    "days": "Trading days the trade lasted.", "entry": "Price paid (that morning's open).",
    "stop": "The price where the trade would be given up to limit the loss.",
    "target": "The price where the trade would be closed to take profit.",
    "exit": "The price the trade actually closed at.",
    "reason": "Why it closed: Target (profit), Stop (loss), Time limit (held the max days), or a Gap (price jumped "
              "past the level overnight).",
    "pnl_pct": "Profit or loss as a percent of the money put in, after costs.",
    "r": "Result in units of risk. +2 means it made twice what was risked; -1 means it lost what was risked.",
}

SCAN_TIPS = {
    "Preset": "The scanner preset you used for that scan.",
    "Picks": "How many stocks the scans suggested.",
    "Avg 1d %": "Average price change one trading day after the scan, from the price when it was scanned.",
    "Avg 5d %": "Average price change five trading days after the scan.",
    "Avg 10d %": "Average price change ten trading days after the scan.",
    "Up after 5d %": "Share of picks that were higher five days later. Around 50% is a coin flip. What matters "
                     "more is how much winners gained versus how much losers lost.",
    "Target first": "Picks that hit the suggested target before the stop (within 10 trading days).",
    "Stop first": "Picks that hit the stop before the target. Stops are meant to be hit sometimes. That is how "
                  "losses stay small.",
    "Target-first rate %": "Of the picks that reached either level, the share that reached the target first. "
                           "Even 35-40% can be profitable when the target is twice as far as the stop.",
    "Scan": "The saved scan this pick came from.", "Scanned": "The day of the scan.",
    "Symbol": "The stock.", "Setup": "Which pattern the scanner saw.", "Signal": "The scanner's signal at the time.",
    "Price": "The price when the scan ran.",
    "1d %": "Price change one trading day later.", "5d %": "Price change five trading days later.",
    "10d %": "Price change ten trading days later.",
    "Result": "Target first, Stop first, Neither yet, Still open (not enough days have passed), or Too early.",
}


def _age_text(hours):
    if hours is None or pd.isna(hours):
        return ""
    return f"{hours:.0f}h ago" if hours < 48 else f"{hours / 24:.0f}d ago"


def _open_in_chart():
    st.session_state["ticker_input"] = st.session_state["scan_pick"]
    # The scanner lives in a fragment, so the sidebar and the chart would not notice the new ticker until
    # something reruns the whole app. This flag makes the scanner ask for that full rerun (see below).
    st.session_state["_goto_chart"] = True
    st.toast(f"Loaded {st.session_state['scan_pick']}. Click the Chart tab to see it.")


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
auto_closed = []
if not pos["open"].empty:
    _hp = cached_prices(tuple(sorted(pos["open"]["Symbol"])))
    try:
        auto_closed = store.auto_close_stopped(lg.value_positions(pos["open"], _hp, 0.0))
    except Exception:
        auto_closed = []
    if auto_closed:
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


STRETCH_ROOM = 1.6                                   # target more than 1.6x the usual 15-day move = a stretch
WEATHER_MIN_SCORE = {"Sunny": 0, "Partly cloudy": 50, "Stormy": 65}   # weaker market, pickier about setups


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
st.session_state.setdefault("stop_notices", [])
st.session_state["stop_notices"] += auto_closed
for _n, _c in enumerate(list(st.session_state["stop_notices"])):
    _loss = _c["Loss $"]
    st.error(f"Stop loss hit: {_c['Symbol']} traded at \\${_c['Price']:,.2f}, at or below your stop of "
             f"\\${_c['Stop']:,.2f}. It was taken off your open list and recorded as a sale of "
             f"{_c['Shares']:g} shares at the stop price ({'-' if _loss < 0 else '+'}\\${abs(_loss):,.2f}). "
             "If your real fill was different, fix it in Trade history and corrections.")
    if st.button("Got it", key=f"stop_ok_{_n}_{_c['Symbol']}"):
        st.session_state["stop_notices"].pop(_n)
        st.rerun()

(tab_today, tab_scan, tab_chart, tab_port, tab_week, tab_bt, tab_learn, tab_guide) = st.tabs(
    ["Today", "Scanner", "Chart", "Portfolio", "Weekly review", "Backtest & history", "Learn", "Guide"])

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


PAST_TIPS = {
    "Score": "Setup quality from 0 to 100: how this setup did on this stock before (30%), whether the target is inside "
             "the stock's usual range (25%), strength against the market (20%), trend strength (15%) and volume (10%). "
             "Higher is better. It is a starting guess, not a promise; the Backtest tab can test whether it helps.",
    "Room x": "Target distance divided by the stock's usual 15-day move. Under about 1 means the target is inside the "
              "usual range; above 1.5 it is a stretch and may just time out.",
    "vs SPY 3mo %": "How much the stock beat (+) or lagged (-) the S&P 500 over about 3 months. Leaders tend to hold "
                    "their setups better.",
    "Past setups": "How many times this same kind of setup showed up on this stock in the past (a finished trade "
                   "each time: next-day entry, your stop and target). A small number means a small sample, so "
                   "treat the next two columns with caution. Blank below 3.",
    "Past hit target %": "Of those past setups on this stock, how often price reached the target before the stop "
                         "or the time limit. With a 2-to-1 target, a bit over a third is break-even and "
                         "more than that is profit. Timeouts count as not hitting it.",
    "Past avg R": "Average result per past trade on this stock, in R (1R = what you risked). Above 0 means this "
                  "setup made money on this stock on average after costs. Negative means it lost on average here, "
                  "which is a reason to be pickier, not proof it will lose again.",
    "Why ranked": "A plain-English reason this stock is on the list: the setup, how strong the volume was, and how "
                  "the same setup has done on this stock before.",
    "Catalyst": "Recent news (last 48 hours) that could be moving the stock. 'Quiet' means there are older headlines "
                "but nothing new, which is normal for big, steady stocks. 'Headlines didn't load' means Yahoo "
                "refused the request, so run the scan again.",
    "Signal": "The chart's buy/sell signal engine on daily bars. 'No signal' just means it is not firing right now. "
              "That is common and does not mean the setup is bad, since swing setups and this signal are different checks.",
}


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
                "Plans use whole shares only, because Robinhood stop orders need them. I would not loosen limits just to see picks.")
        return
    cols = [c for c in ["Symbol", "Price", "Shares", "Cost $", "Stop", "Target", "Risk $",
                        "Setup", "Score", "Why ranked", "Past setups", "Past hit target %", "Past avg R",
                        "Signal", "Catalyst", "Earnings"] if c in plan.columns]
    show_table(plan[cols], column_config=col_help(plan[cols], PAST_TIPS))
    st.caption(esc_md(f"Total cost ${info['plan_cost']:.2f} ({info['plan_cost'] / acct.value * 100:.0f}% of account). "
               f"If every stop is hit you would lose about ${info['plan_risk']:.2f} "
               f"({info['plan_risk'] / acct.value * 100:.1f}% of account). A stop can fill lower if a stock "
               "gaps overnight, so the real loss can be bigger. This is a ceiling on planned stop risk, "
               "not a guarantee of the most you can lose."))


@st.fragment(run_every=scan_minutes * 60 if scan_auto else None)
def add_to_portfolio_ui(df, plan, preset, acct, info):
    """One click to record a scanner pick as a BUY in the Portfolio (it only records; it does not place an order)."""
    st.markdown("#### Add a pick to your Portfolio")
    st.caption("After you buy a stock in Robinhood, record it here in one click. This only adds it to your Portfolio tab "
               "(with the scan's stop and target); it does not place any order. Change the shares or price if your fill was different.")
    plan_shares = {r["Symbol"]: int(r["Shares"]) for _, r in plan.iterrows()} if plan is not None and len(plan) else {}
    syms = df["Symbol"].tolist()
    first = next((x for x in syms if x in plan_shares), syms[0])
    sym = st.selectbox("Stock you bought", syms, index=syms.index(first), key="add_sym")
    row = df[df["Symbol"] == sym].iloc[0]
    sized = plan_shares.get(sym)
    if sized is None:
        mx = row.get("Max shares")
        sized = int(mx) if mx is not None and not pd.isna(mx) else 0
    px = float(row["Price"])
    stop = None if "Stop" not in row or pd.isna(row["Stop"]) else float(row["Stop"])
    target = None if "Target" not in row or pd.isna(row["Target"]) else float(row["Target"])
    b1, b2, b3 = st.columns([1, 1, 2])
    qty = b1.number_input("Shares", min_value=0, step=1, value=int(sized), key=f"add_qty_{sym}",
                          help="Starts at the size in the combined plan (or the biggest position that fits your limits). Whole shares only, because Robinhood stop orders need them.")
    fill = b2.number_input("Price paid ($)", min_value=0.0, step=0.01, value=round(px, 2), format="%.2f", key=f"add_px_{sym}",
                           help="The scan's price. Change it to what you actually paid.")
    b3.markdown(esc_md(f"Stop **{'none' if stop is None else f'${stop:,.2f}'}**  ·  Target **{'none' if target is None else f'${target:,.2f}'}**"))
    if sym in set(acct.held_symbols):
        st.warning(f"You already hold {sym}. This will add to that position.")
    if st.button(f"Add {sym} to my Portfolio as bought", key="add_to_portfolio", disabled=qty <= 0 or fill <= 0):
        try:
            store.add_transaction(sym, "BUY", float(qty), float(fill), ts=datetime.now(),
                                  strategy={"Swing": "swing", "Steady": "steady", "Momentum": "momentum"}.get(PRESET_SHORT[preset], "other"),
                                  stop=stop, target=target, notes="Added from the scanner")
            st.session_state["_added_msg"] = f"Added {int(qty)} {sym} at ${fill:,.2f} to your Portfolio."
            st.rerun()
        except ValueError as e:
            st.error(str(e))
    if st.session_state.get("_added_msg"):
        st.success(esc_md(st.session_state.pop("_added_msg")))


def scanner_view(preset, criteria, symbols, also_market, only_buy, recent_bars, acct, hide_nofit, sort_by,
                 hide_stretch=False, weather_gate=False):
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
                                        window=window, recent_bars=recent_bars,
                                        frames=sc.LAST_DAILY if preset == SWING else None)
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
    if stats.get("spy_ok") is False:
        st.caption("Couldn't download SPY, so the Score leaves out 'strength vs the market' this time.")
    st.caption(sc.data_line(stats))
    if ran_preset != preset:
        st.warning(f"These results are from the '{PRESET_SHORT[ran_preset]}' scan. Press Run scan to refresh "
                   f"for '{PRESET_SHORT[preset]}'.")
    if only_buy and not df.empty:
        df = df[df["Signal"].str.startswith("BUY")]
    notes = []
    if ran_preset == SWING and not df.empty and "Score" in df.columns:
        if hide_stretch and "Room x" in df.columns:
            keep = ~(df["Room x"] > STRETCH_ROOM)
            if (~keep).any():
                notes.append(f"{int((~keep).sum())} hidden because the target is a stretch for the stock (Room x above {STRETCH_ROOM:g})")
            df = df[keep]
        if weather_gate:
            w = cached_weather()
            need = WEATHER_MIN_SCORE.get(w["label"], 0) if w else 0
            if need:
                keep = ~(df["Score"] < need)
                if (~keep).any():
                    notes.append(f"{int((~keep).sum())} hidden because the market is {w['label'].lower()}, so only scores of "
                                 f"{need} or more are shown")
                df = df[keep]
    if notes:
        st.caption("Filters: " + "; ".join(notes) + ". Untick the boxes under the scan settings to see everything.")
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
    if not sort_by.endswith("(default)") and sort_by in df.columns:
        df = df.sort_values(sort_by, ascending=False, na_position="last")
    bad_sig = [k for k, v in details.items() if v["signal"].get("error")]
    bad_news = [k for k, v in details.items() if v["catalyst"].get("news_error")]
    if bad_sig or bad_news:
        st.warning(f"Yahoo refused some requests (signal data for {len(bad_sig)} stock(s), headlines for {len(bad_news)}), "
                   "so those cells say they didn't load. This usually clears up if you wait a minute and run the scan again. "
                   + (f"Example error: {(details[(bad_sig or bad_news)[0]]['signal'].get('error') or details[(bad_sig or bad_news)[0]]['catalyst'].get('news_error'))}"))
    show_table(df, column_config=col_help(df, {
        "15d range +/-%": "How far this stock usually moves in 15 trading days (about 2 times out of 3), up or down, "
                          "based on how much it has been moving lately. Compare it with the distance to the Target: "
                          "a target much bigger than this range is a long shot. It says nothing about direction.",
        **PAST_TIPS}))
    if info["enabled"]:
        st.caption("'Max shares / cost / risk' is the biggest position you could take in that ONE stock. "
                   "You cannot take them all at once. The combined plan below spends your shared budget in rank order.")
        show_plan(plan, info, acct)
    add_to_portfolio_ui(df, plan, preset, acct, info)
    pick = st.selectbox("Details / open in chart", df["Symbol"].tolist(), key="scan_pick")
    st.button("Load chart", key="load_chart", on_click=_open_in_chart)
    if st.session_state.pop("_goto_chart", False):
        st.rerun(scope="app")
    if pick in details:
        show_details(pick, details[pick], sig_interval)


with tab_scan:
    preset = st.radio("Scanner", [SWING, STEADY, MOMENTUM], horizontal=True, key="scan_preset")
    if preset == SWING:
        picked = st.multiselect("Setups to look for", ["Pullback", "Breakout", "Bounce"],
                                default=["Pullback", "Breakout", "Bounce"],
                                help="Pullback: an uptrending stock dips back to its 20-day average. Breakout: it pushes above its 20-day high on strong volume. Bounce: it was oversold and is turning up. Remove any you don't want.")
        c1, c2, c3, c4, c5 = st.columns(5)
        w_price = c1.number_input("Price at least ($)", value=10.0, step=1.0,
                                  help="Skips stocks priced below this. Cheap stocks tend to gap more and fill your stop worse. Lower it to see cheaper stocks; raise it for steadier ones.")
        w_vol = c2.number_input("Avg volume at least (M shares)", value=1.0, step=0.5,
                                help="The stock must trade at least this many shares a day on average (1.00 = one million). Higher means easier to buy and sell at a fair price; lower lets thinly traded stocks in.")
        w_dollar = c3.number_input("Avg $ volume at least (M)", value=10.0, step=5.0,
                                   help="Average dollars traded per day (price times shares), in millions. 10 means about $10 million a day. It catches cheap stocks with lots of shares that still are not liquid.")
        w_atr = c4.number_input("Max daily swing (ATR %)", value=6.0, step=0.5,
                                help="How much the stock typically moves in a day, as a percent of its price (ATR). Stocks swinging more than this are skipped. Wild stocks need wide stops, so you can only afford small positions. Lower = calmer stocks only.")
        w_earn = c5.number_input("Skip earnings within (days)", min_value=0, max_value=30, value=10,
                                help="Skips stocks reporting earnings within this many days. Earnings can make a stock jump past your stop. Set 0 to turn this off.")
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
        s_price = c1.number_input("Price at least ($)", value=10.0, step=1.0,
                                  help="Skips stocks priced below this. Cheap stocks tend to gap more and fill your stop worse. Lower it to see cheaper stocks; raise it for steadier ones.")
        s_vol = c2.number_input("Avg volume at least (M shares)", value=1.0, step=0.5,
                                help="The stock must trade at least this many shares a day on average (1.00 = one million). Higher means easier to buy and sell at a fair price; lower lets thinly traded stocks in.")
        s_dollar = c3.number_input("Avg $ volume at least (M)", value=10.0, step=5.0,
                                   help="Average dollars traded per day (price times shares), in millions. 10 means about $10 million a day. It catches cheap stocks with lots of shares that still are not liquid.")
        s_dist = c4.number_input("Within % of 20 EMA", value=3.0, step=0.5,
                                help="How close the price must be to its 20-day average (the orange line). Smaller = only stocks sitting right on the line.")
        s_rsi_lo = c5.number_input("RSI at least", value=40.0, step=1.0,
                                  help="RSI is a 0-100 gauge of how stretched a stock is. Under about 30 is oversold, over 70 overheated. This is the lowest value allowed.")
        s_rsi_hi = c6.number_input("RSI at most", value=60.0, step=1.0,
                                  help="The highest RSI allowed. 60 keeps out stocks that already ran up and look overheated.")
        d1, d2 = st.columns(2)
        s_atr = d1.number_input("Max daily swing (ATR %)", value=4.0, step=0.5,
                                help="How much the stock typically moves in a day, as a percent of its price (ATR). Stocks swinging more than this are skipped. Wild stocks need wide stops, so you can only afford small positions. Lower = calmer stocks only.")
        s_earn = d2.number_input("Skip earnings within (days, 0 = don't skip)", min_value=0, max_value=30, value=5,
                                help="Skips stocks reporting earnings within this many days. Earnings can make a stock jump past your stop. Set 0 to turn this off.")
        criteria = sc.SteadyCriteria(min_price=s_price, min_avg_volume=int(s_vol * 1_000_000),
                                     min_dollar_volume=s_dollar * 1_000_000, max_dist_ema20_pct=s_dist,
                                     rsi_min=s_rsi_lo, rsi_max=s_rsi_hi, max_atr_pct=s_atr,
                                     skip_earnings_days=int(s_earn))
        st.caption("Finds liquid US stocks (market cap over $2B) whose daily chart is in an uptrend and that "
                   "have pulled back near the 20 EMA without being overheated or wildly volatile.")
    else:
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        min_change = c1.number_input("Change % at least", value=10.0, step=1.0,
                                     help="Only stocks up at least this much today.")
        price_lo = c2.number_input("Price from ($)", value=1.0, step=0.5,
                                  help="Lowest share price to include.")
        price_hi = c3.number_input("Price to ($)", value=20.0, step=1.0,
                                  help="Highest share price to include.")
        max_float_m = c4.number_input("Float at most (M)", value=20.0, step=1.0,
                                      help="Float is how many shares are available to trade, in millions. Low-float stocks can move fast, up or down.")
        min_rvol = c5.number_input("Rel. volume over", value=5.0, step=0.5,
                                   help="Today's volume compared with the stock's normal volume. 5 means five times busier than usual, a sign something is happening.")
        min_vol = c6.number_input("Min volume today", value=100_000, step=50_000,
                                  help="Shares traded so far today. Keeps out stocks too quiet to trade.")
        e1, e2 = st.columns(2)
        m_dollar = e1.number_input("Min $ traded today ($)", value=250_000, step=50_000,
                                  help="Dollars traded so far today (price times shares). Another way to skip stocks you couldn't easily sell.")
        m_stop = e2.number_input("Stop = % below price (0 = no sizing for this scanner)", value=0.0, step=1.0,
                                 help="Sets your stop this many percent under the price so the scan can size a position. Leave at 0 to skip sizing.")
        criteria = sc.Criteria(min_change, price_lo, price_hi, max_float_m * 1_000_000, min_rvol,
                               int(min_vol), min_dollar_volume=float(m_dollar))
        st.caption("Fast, volatile, high risk: wide spreads, halts and sudden reversals are common. It pulls up to "
                   "750 of the biggest movers from Yahoo. If it hits that cap the summary line says so.")

    o1, o2, o3, o4 = st.columns(4)
    only_buy = o1.checkbox("Only show stocks with a recent BUY signal", value=False,
                           help="When ticked, the list only keeps stocks whose chart showed a BUY signal within the last few bars (set in the next box). Fewer results, fresher timing.")
    hide_nofit = o2.checkbox("Hide stocks that don't fit my account", value=True,
                            help="Hides stocks you couldn't buy sensibly with your account settings: not enough cash, the position would be too big, or not even one share fits your risk limit. Untick to see everything.")
    recent_bars = o3.number_input("Count a BUY as recent for (bars)", min_value=1, max_value=30, value=6,
                                  help="How far back a BUY signal still counts as recent, in chart bars (candles). 6 means within the last 6. Raise it to include older signals.")
    sort_cols = {SWING: ["Score", "Day Vol x", "RSI", "Risk %"], STEADY: ["Avg Vol (M)", "RSI", "ATR %"],
                 MOMENTUM: ["Rel Vol", "Change %", "Volume"]}[preset]
    sort_by = o4.selectbox("Sort by", ["Quality score (default)" if preset == SWING else "Signal rank (default)"] + sort_cols,
                           help="Which column orders the results. The default puts the best-looking setups first (Quality score for swing setups, current signal for the others). Pick another column to re-rank.")

    hide_stretch = weather_gate = False
    if preset == SWING:
        g1, g2 = st.columns(2)
        hide_stretch = g1.checkbox("Hide setups whose target is a stretch", value=True,
                                   help=f"Hides results where the target is more than {STRETCH_ROOM:g} times the stock's usual "
                                        "15-day move (Room x column). Those targets are often not reached before time runs out.")
        weather_gate = g2.checkbox("Be pickier when the market is weak", value=True,
                                   help="Partly cloudy market: only scores of 50 or more. Stormy: 65 or more. Sunny: no change. "
                                        "Swing setups fail more often when the whole market is falling.")

    wl = store.watchlists()
    w1, w2 = st.columns(2)
    chosen_lists = w1.multiselect("Saved watchlists to scan", list(wl),
                                  help="Scan only the stocks on your saved lists. Create lists under Manage watchlists below.")
    typed = w2.text_input("Extra tickers to scan (comma-separated)", value="",
                          help="Type tickers like AAPL, MSFT to scan just those (plus any saved lists). Leave blank to scan the market.")
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
    scanner_view(preset, criteria, symbols, also_market, only_buy, int(recent_bars), acct, hide_nofit, sort_by,
                 hide_stretch, weather_gate)


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


RANGE_TIPS = {
    "Situation": "Which group of past days this row looks at: every ordinary day in the window, or only days when a swing "
                 "setup (Pullback, Breakout or Bounce) showed up on this stock.",
    "Trades": "How many pretend entries were tested. Under about 20, take the percentages with a big grain of salt.",
    "Target first %": "How often price reached the target before the stop. Many trades end without hitting either, "
                      "so look at Avg R (the real scoreboard) rather than this number alone.",
    "Stop first %": "How often the stop was hit before the target. Stops are meant to be hit sometimes. That is how "
                    "losses stay small.",
    "Timed out %": "How often neither was hit within the hold window, so the trade was closed at the end.",
    "Avg R": "Average result per trade in units of risk, after costs. Above 0 means the plan made money on average "
             "on this stock.",
}


@st.cache_data(ttl=3600, show_spinner=False)
def cached_plan_history(sym, last_bar, stop_mult_, rr_, _df, _flags):
    return fc.plan_history(_df, _flags, stop_mult_, rr_)


def show_range_box(sym, df, cone, flags):
    """The words under the chart that explain the shaded cone, plus the 'did this plan work before?' table."""
    if not cone:
        st.caption("Not enough price history to draw a likely range for this stock.")
        return
    p0, h = cone["price"], cone["horizon"]
    end = cone["dates"][-1]
    lo, hi = cone["end68"]
    lo2, hi2 = cone["end95"]
    st.markdown(esc_md(
        f"**Likely range by {end:%b %d}** ({h} trading days): **${lo:,.2f} to ${hi:,.2f}** about 2 times out of 3, "
        f"and **${lo2:,.2f} to ${hi2:,.2f}** almost always (about 19 times out of 20). That is roughly "
        f"{(cone['pct68_down'] + cone['pct68']) / 2:.0f}% either way for the usual range."))
    atr = float(flags["atr"].iloc[-1])
    if atr == atr and atr > 0:
        stp = p0 - stop_mult * atr
        tgt = p0 + reward_risk * (p0 - stp)
        lo_end = cone["lo68"][-1]
        notes = []
        if tgt > hi2:
            notes.append(f"a target of ${tgt:,.2f} is beyond even the wider range, so it would take an unusual move")
        elif tgt > hi:
            notes.append(f"a target of ${tgt:,.2f} is inside the wider range but outside the usual one, so it is "
                         "possible but not the typical outcome")
        else:
            notes.append(f"a target of ${tgt:,.2f} is inside the usual range, so it is within normal movement")
        if stp > lo_end:
            notes.append(f"a stop at ${stp:,.2f} is above the bottom of the usual range, so ordinary wiggles could hit it")
        else:
            notes.append(f"a stop at ${stp:,.2f} sits below the usual range, so only a bigger-than-normal drop would hit it")
        st.caption(esc_md("With your current settings: " + "; ".join(notes) + "."))
    st.caption("This shows how far the stock could wander. It does not say which way. The bands are checked against "
               f"this stock's own history ({cone['samples']} past days), but surprises like earnings or big news can "
               "break through any range. It is a map of what is normal, not a promise.")
    with st.expander("How did a plan like this work on this stock in the past?"):
        try:
            ph = cached_plan_history(sym, str(df.index[-1]), float(stop_mult), float(reward_risk), df, flags)
        except Exception as e:
            st.caption(f"Couldn't work that out: {e}")
            return
        rows = []
        for label, key in (("Any ordinary day", "all"), ("Days a setup showed up", "setup")):
            r = ph[key]
            if not r["trades"]:
                rows.append({"Situation": label, "Trades": 0})
                continue
            rows.append({"Situation": label, "Trades": r["trades"], "Target first %": round(r["target_pct"], 1),
                         "Stop first %": round(r["stop_pct"], 1), "Timed out %": round(r["timeout_pct"], 1),
                         "Avg R": round(r["avg_r"], 2)})
        tb = pd.DataFrame(rows)
        show_table(tb, column_config=col_help(tb, RANGE_TIPS))
        st.caption(f"Pretend entries at the next open over about the last 3 years of this stock, with a stop "
                   f"{stop_mult:g} ATR below, a target {reward_risk:g}x the risk above, and up to {ph['days']} trading "
                   f"days. Avg R is the number to watch: above 0 means the plan made money on average on this stock after "
                   f"costs. (If almost every trade ended at the target or the stop, you would need to win about "
                   f"{ph['breakeven_pct']:.0f}% of them to break even.) The past on one stock is a small sample. Use "
                   "the Backtest tab for a broader test.")


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


def show_growth(tx):
    """Profit/loss since your first trade, day by day: finished sells plus what you still hold at each day's close."""
    st.subheader("Growth")
    if tx.empty:
        st.caption("Record your first trade and a profit-and-loss chart will appear here.")
        return
    import plotly.graph_objects as go
    syms = tuple(sorted(set(tx["symbol"])))
    first = pd.to_datetime(tx["ts"]).min().normalize()
    hist = cached_history(syms, (first - pd.Timedelta(days=7)).strftime("%Y-%m-%d"))
    curve = lg.equity_curve(tx, hist)
    if curve.empty:
        st.caption("Nothing to chart yet.")
        return
    missing = [s for s in syms if s not in hist]
    now_tot, now_real, now_unreal = (float(curve[c].iloc[-1]) for c in ("Total", "Realized", "Unrealized"))
    g1, g2, g3 = st.columns(3)
    g1.metric("Total gain / loss", money(now_tot),
              help="Everything you have made or lost since your first trade: money from finished sells (after fees) plus the "
                   "paper gain or loss on what you still hold.")
    g2.metric("Locked in (sold)", money(now_real), help="Profit or loss from stocks you have already sold, after fees.")
    g3.metric("Still open", money(now_unreal), help="Paper gain or loss on stocks you still hold, at the latest close. It changes until you sell.")
    color = "#26a69a" if now_tot >= 0 else "#ef5350"
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=curve.index, y=curve["Total"], name="Total gain / loss", mode="lines+markers" if len(curve) < 15 else "lines",
                             line=dict(color=color, width=2.5), fill="tozeroy",
                             fillcolor="rgba(38,166,154,0.18)" if now_tot >= 0 else "rgba(239,83,80,0.18)",
                             hovertemplate="%{x|%b %d}<br>Total %{y:+,.2f}<extra></extra>"))
    fig.add_trace(go.Scatter(x=curve.index, y=curve["Realized"], name="Locked in (sold)", mode="lines",
                             line=dict(color="#9e9e9e", width=1.3, dash="dot"),
                             hovertemplate="%{x|%b %d}<br>Locked in %{y:+,.2f}<extra></extra>"))
    fig.add_hline(y=0, line=dict(color="gray", width=1))
    fig.update_layout(template="plotly_dark", height=340, margin=dict(l=10, r=10, t=30, b=10), hovermode="x unified",
                      yaxis_title="Profit / loss ($)", legend=dict(orientation="h", y=1.12), uirevision="growth")
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"])])
    show_chart(fig, "growth_chart")
    note = ("Built from the trades you recorded, valued at each day's closing price. It does not read your Robinhood balance, "
            "so deposits and withdrawals are not included. Prices come from Yahoo and can be delayed.")
    if len(curve) < 3:
        note = "Only a day or two of history so far, so the line is short. " + note
    if missing:
        note += " No price history found for " + ", ".join(missing) + ", so those are counted at what you paid until sold."
    st.caption(esc_md(note))


def mark_weekends(fig, index):
    """Dotted vertical line (labelled Weekend) wherever the chart skips over a Saturday and Sunday."""
    try:
        idx = pd.DatetimeIndex(index)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        for a, b in zip(idx[:-1], idx[1:]):
            if a.weekday() <= 4 and (b.normalize() - a.normalize()).days >= 1 and b.weekday() < a.weekday():
                at = (a.normalize() + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                fig.add_vline(x=at, row="all", col=1, line_dash="dot", line_color="rgba(255,255,255,0.55)", line_width=1.5)
                fig.add_annotation(x=at, y=1.0, yref="paper", text="Weekend", showarrow=False, yanchor="bottom",
                                   font=dict(size=11, color="rgba(255,255,255,0.8)"))
    except Exception:
        pass


def show_day_chart(sym, overlay, with_volume=True):
    """Today's session in 5-minute candles (a one-day view of daily candles would be a single bar)."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    try:
        d5 = fetch(sym, "5d", "5m")
    except Exception as e:
        st.error(f"Couldn't load today's 5-minute bars for {sym}: {e}")
        return
    days = pd.DatetimeIndex(d5.index).normalize()
    day = d5[days == days[-1]]
    if len(day) < 3:
        st.info("Not enough 5-minute bars yet for today. If the market just opened, check back in a few minutes.")
        return
    x = cu.plot_x(day.index)
    tp = (day.High + day.Low + day.Close) / 3
    vwap = (tp * day.Volume).cumsum() / day.Volume.replace(0, float("nan")).cumsum()
    rows = 2 if with_volume else 1
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                        row_heights=[0.75, 0.25] if with_volume else [1.0])
    fig.add_trace(go.Candlestick(x=x, open=day.Open, high=day.High, low=day.Low, close=day.Close, name="Price",
                                 increasing_line_color="#26a69a", decreasing_line_color="#ef5350"), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=vwap, name="VWAP (average price paid today)", line=dict(width=1.3, color="#ffee58")), row=1, col=1)
    cu.add_position_overlay(fig, overlay, x, daily=False, row=1)
    if with_volume:
        vcol = ["#26a69a" if c >= o else "#ef5350" for c, o in zip(day.Close, day.Open)]
        fig.add_trace(go.Bar(x=x, y=day.Volume, name="Volume", marker_color=vcol), row=2, col=1)
        fig.update_yaxes(title_text="Volume", row=2, col=1)
    fig.update_layout(template="plotly_dark", height=620, xaxis_rangeslider_visible=False, hovermode="x unified",
                      title=f"{sym} - today ({days[-1]:%a %b %d}, 5-minute candles)", legend=dict(orientation="h", y=1.06),
                      uirevision=f"{sym}-day")
    fig.update_xaxes(rangebreaks=cu.time_rangebreaks(day.index))
    fig.update_yaxes(title_text="Price", row=1, col=1)
    chg = (day.Close.iloc[-1] / day.Open.iloc[0] - 1) * 100
    st.caption(f"Today so far: open {day.Open.iloc[0]:,.2f}, high {day.High.max():,.2f}, low {day.Low.min():,.2f}, "
               f"last {day.Close.iloc[-1]:,.2f} ({chg:+.1f}% from the open). Yahoo data can be delayed, and the newest candle is still forming.")
    show_chart(fig, "day_chart")


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
        raw_live = raw                      # includes today's candle while it is still forming
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
        show_cone = st.checkbox("Show the likely range for the next 15 trading days (shaded, right of the last candle)",
                                value=True, key="swing_cone")
        ranges = {"1 day": 1, "1 week": 5, "1 month": 21, "3 months": 63, "6 months": 126, "1 year": 252, "2 years": 504}
        rng_pick = st.radio("Time range (each candle is one trading day)", list(ranges), index=list(ranges).index("3 months"),
                            horizontal=True, key="swing_range")
        n = ranges[rng_pick]
        if rng_pick == "1 day":
            show_day_chart(ticker, build_overlay(ticker, valued, tx_all), opt_volume)
            return
        week_view = rng_pick == "1 week"
        if week_view:
            df_live = so.add_indicators(raw_live)
            flags_live = sc.swing_setup_flags(df_live, crit)
            last_ts = pd.Timestamp(df_live.index[-1])
            week_start = last_ts.normalize() - pd.Timedelta(days=last_ts.weekday() + 7)   # Monday of last week
            n = max(int((pd.DatetimeIndex(df_live.index).tz_localize(None) >= week_start).sum()), 2) \
                if pd.DatetimeIndex(df_live.index).tz is not None else \
                max(int((pd.DatetimeIndex(df_live.index) >= week_start).sum()), 2)
        last = df.iloc[-1]
        atr = float(flags["atr"].iloc[-1])
        sugg = None
        if any(bool(flags[k].iloc[-1]) for k in ("pullback", "breakout", "bounce")) and atr == atr:
            stp = float(last.Close - stop_mult * atr)
            sugg = {"suggested_stop": stp, "suggested_target": float(last.Close + reward_risk * (last.Close - stp))}
        overlay = build_overlay(ticker, valued, tx_all, sugg)
        cone = None
        if show_cone:
            try:
                cone = fc.range_cone(df_live if week_view else df)
            except Exception:
                cone = None
        chart_df, chart_flags = (df_live, flags_live) if week_view else (df, flags)
        fig = swc.build_swing_chart(chart_df.tail(n), chart_flags.tail(n), crit, f"{ticker} - swing setups (daily)",
                                    setups=tuple(s.lower() for s in shown), opts={"volume": opt_volume, "sr": opt_sr, "beginner": beginner},
                                    overlay=overlay, show_outcomes=outcomes, cone=cone,
                                    sr=cu.support_resistance(df.tail(max(n, 63))) if opt_sr else None)
        st.caption("The swing chart is always daily, so the Bar size setting in the sidebar doesn't apply here. "
                   "Pick a bar size or switch to Intraday signals to use it.")
        st.caption("Hover a marker to see why the scanner would have flagged that day, the levels it would have "
                   "suggested, and what price did next. Diamond = pullback, star = breakout, circle = bounce. "
                   "Your own entry, stop and target (from the Portfolio tab) are solid lines; suggested levels are dotted.")
        fig.update_layout(uirevision=f"{ticker}-swing-{rng_pick}")
        if week_view:
            mark_weekends(fig, chart_df.tail(n).index)
            st.caption("This view shows last week and this week so far, including today's candle while it is still forming. "
                       "Today's candle and its markers can still change until the close. The dotted line marks the weekend.")
        show_chart(fig, "swing_chart")
        if show_cone:
            show_range_box(ticker, df, cone, flags)
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

        st.markdown("#### If your stops or targets are hit")
        pay, ptot = lg.payoff_table(valued, acct_value)
        p1, p2, p3 = st.columns(3)
        p1.metric("If every stop is hit", money(ptot["stop_total"]),
                  None if ptot["stop_pct"] is None else f"{ptot['stop_pct']:+.1f}% of account", delta_color="off")
        p2.metric("If every target is hit", money(ptot["target_total"]),
                  None if ptot["target_pct"] is None else f"{ptot['target_pct']:+.1f}% of account", delta_color="off")
        p3.metric("Gap between the two", money(ptot["target_total"] - ptot["stop_total"]),
                  help="How much the outcome swings between 'every stop hit' and 'every target hit'.")
        show_table(rnd(pay), column_config=col_help(pay, {
            "If stop hits $": "Profit or loss on this position if your stop fills at its price, compared with what you paid "
                              "(shares x (stop - average cost)). Positive means the stop is above your cost, so a stop-out "
                              "would still lock in a gain.",
            "If target hits $": "Profit on this position if your target fills at its price, compared with what you paid.",
            "Stop, % of account": "That stop result as a share of your account value (set in the sidebar).",
            "Target, % of account": "That target result as a share of your account value."}))
        _gone = []
        if ptot["missing_stop"]:
            _gone.append(f"{ptot['missing_stop']} position(s) have no stop recorded, so they are blank and NOT in the stop total "
                         "(with no stop the real loss is unlimited down to zero)")
        if ptot["missing_target"]:
            _gone.append(f"{ptot['missing_target']} position(s) have no target recorded and are left out of the target total")
        st.caption(esc_md("Measured against what you paid, using the stop and target you recorded. These are best and worst "
                          "cases at those exact prices: a stop can fill lower after an overnight gap, and not every target "
                          "will be hit. " + ("; ".join(_gone) + "." if _gone else "")))

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

        st.markdown("#### Progress toward your next stop raise")
        for pr in lg.stop_progress(valued):
            pc1, pc2 = st.columns([1, 4])
            pc1.markdown(esc_md(f"**{pr['Symbol']}**  \n" + ("price unavailable" if pr["Price"] is None else f"${pr['Price']:,.2f} now")))
            if pr["Progress"] is None:
                pc2.caption(esc_md(pr["Status"]))
            else:
                pc2.progress(min(max(pr["Progress"] / 100.0, 0.0), 1.0), text=esc_md(pr["Status"]))
        st.caption("Each bar fills as a stock moves toward the price where the rules above would raise its stop: up 1R moves it to "
                   "break-even, 2R locks in +1R, 3R locks in +2R. R is your entry price minus your first recorded stop. "
                   "A bar that goes backward just means the price pulled back.")

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
    if cA.button("Check news & signals for my positions"):
        if valued.empty:
            st.info("You have no open positions to check yet. Record a buy first.")
        else:
            with st.spinner("Checking headlines, earnings dates and daily signals..."):
                extras = {}
                for s_ in valued["Symbol"]:
                    try:
                        cat_ = sc.get_catalyst(s_)
                    except Exception as e_:
                        cat_ = {"headlines": [], "flags": [], "tags": [], "fresh": 0, "earnings_days": None,
                                "news_error": str(e_)[:80]}
                    try:
                        sig_ = sc.signal_summary(s_, "1d")
                    except Exception as e_:
                        sig_ = {"label": f"Couldn't check ({str(e_)[:60]})", "reasons": []}
                    extras[s_] = {"catalyst": cat_, "signal": sig_}
                st.session_state["held_extras"] = extras
                st.session_state["held_extras_time"] = datetime.now()
            st.rerun()
    held_x = st.session_state.get("held_extras")
    if held_x and not valued.empty:
        rows = []
        for s_ in valued["Symbol"]:
            ex = held_x.get(s_)
            if not ex:
                continue
            cat_, sig_ = ex.get("catalyst") or {}, ex.get("signal") or {}
            d_ = cat_.get("earnings_days")
            rows.append({"Symbol": s_, "Daily signal": sig_.get("label", "-"),
                         "Earnings": "not found" if d_ is None else ("today" if d_ == 0 else f"in {d_} day(s)"),
                         "New headlines (48h)": cat_.get("fresh", 0),
                         "Red flags": ", ".join(cat_.get("flags") or []) or "none",
                         "Headline check": ("couldn't load" if cat_.get("news_error") else "ok")})
        if rows:
            when_ = st.session_state.get("held_extras_time")
            st.markdown("**Latest check of your positions**" + (f" ({when_:%I:%M %p})" if when_ else ""))
            show_table(pd.DataFrame(rows))
            st.caption("Anything urgent (a SELL signal, close earnings, red-flag headlines) also shows in the alerts at the top "
                       "of the page. A signal of 'No signal' or 'Building buy' means nothing needs doing. Headlines are matched by "
                       "keywords, so always read them yourself.")
            for s_ in valued["Symbol"]:
                heads_ = ((held_x.get(s_) or {}).get("catalyst") or {}).get("headlines") or []
                if heads_:
                    with st.expander(f"{s_} headlines"):
                        for h_ in heads_[:6]:
                            st.markdown(esc_md(f"- {h_.get('title', '')}" + (f" ({h_['source']})" if h_.get("source") else "")))

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

            st.markdown("**Fix a stop or target**")
            st.caption("Typed a wrong number? Pick the trade, change its stop and/or target, and save. Leave a box at 0 to clear it. "
                       "Shares, price and date stay as they are. On a buy, the stop is also what your R is measured against.")
            ids_desc = tx_all.sort_values("ts", ascending=False)
            fx_id = st.selectbox("Trade to fix", ids_desc["id"].tolist(), key="fix_tx",
                                 format_func=lambda i: "#{} {} {} {:g} @ {:,.2f}".format(
                                     i, *[ids_desc.loc[ids_desc["id"] == i, c].iloc[0] for c in ("side", "symbol", "qty", "price")]))
            cur = tx_all[tx_all["id"] == fx_id].iloc[0]
            f1, f2, f3 = st.columns([1, 1, 1])
            fx_stop = f1.number_input("Stop", min_value=0.0, step=0.01, format="%.4f", key=f"fix_stop_{fx_id}",
                                      value=0.0 if pd.isna(cur["stop"]) else float(cur["stop"]),
                                      help="The corrected stop price. 0 clears it.")
            fx_target = f2.number_input("Target", min_value=0.0, step=0.01, format="%.4f", key=f"fix_target_{fx_id}",
                                        value=0.0 if pd.isna(cur["target"]) else float(cur["target"]),
                                        help="The corrected target price. 0 clears it.")
            if cur["side"] == "BUY" and fx_stop and fx_stop >= float(cur["price"]):
                st.warning("That stop is at or above your buy price, so it would trigger immediately. Double-check it.")
            if cur["side"] == "BUY" and fx_target and fx_target <= float(cur["price"]):
                st.warning("That target is at or below your buy price. Double-check it.")
            if f3.button("Save stop / target", key="fix_save"):
                try:
                    store.update_levels(fx_id, stop=fx_stop or None, target=fx_target or None)
                    st.toast("Saved.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))

    show_growth(tx_all)

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


# ====================================================================== LEARN TAB
with tab_learn:
    learn.show(risk_dollars=round(acct_value * risk_pct / 100, 2))


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
                _spy = bt.load_daily(["SPY"], period=bt_years).get("SPY")
                st.session_state["bt_frames"] = (frames, _spy["Close"] if _spy is not None else None)
                st.session_state.pop("bt_quality", None)
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
            summ = pd.DataFrame([row("All", allm), row(f"Before {split}", before), row(f"From {split}", after)])
            show_table(summ, column_config=col_help(summ, BT_TIPS))
            st.caption("Hover over a column title for a plain-English explanation. If 'before' looks great and "
                       "'from' does not, the edge may not be real.")
            be = 100 / (1 + reward_risk)
            with st.expander("Why a low win rate can still be a good thing", expanded=False):
                st.markdown(esc_md(
                    f"Most beginners think a good system has to win most of the time. It doesn't. What matters is how "
                    f"much you make when you win compared with how much you lose when you lose.\n\n"
                    f"**Example with a {reward_risk:g}-to-1 target.** Say you risk $10 on each trade. A winner makes "
                    f"${10 * reward_risk:g}; a loser costs $10. Take 10 trades with only 4 winners: "
                    f"4 x ${10 * reward_risk:g} = **+${4 * 10 * reward_risk:g}**, and 6 x $10 = **-$60**. "
                    f"Net: **{'+' if 4 * 10 * reward_risk - 60 >= 0 else '-'}${abs(4 * 10 * reward_risk - 60):g}**, "
                    f"even though you lost more often than you won.\n\n"
                    f"**With your current settings you only need to win about {be:.0f}% of trades to break even** "
                    f"(1 divided by {1 + reward_risk:g}). Anything above that, after costs, is profit.\n\n"
                    f"**Avg R is the number to watch.** It folds win rate, win size and loss size into one figure: "
                    f"the average result per trade, in units of what you risked. Above 0 means the rules made "
                    f"money. A small positive number, repeated many times with small, controlled losses, is how "
                    f"swing trading builds up. Stops are not failures. They are the cost of doing business "
                    f"that keeps each loss small."))
            eq = trades[trades["reason"] != "Still open"].sort_values("exit_date")
            st.line_chart(pd.DataFrame({"Cumulative R": eq["r"].cumsum().to_numpy()}, index=eq["exit_date"]))
            with st.expander("Does the quality score actually help? (test on these same trades)"):
                st.caption("The scanner ranks setups with a 0-100 score. This checks, using only information that existed "
                           "on each signal day, whether higher scores really did better, compared with the old "
                           "sort by volume. If the gap is within the noise, it says so.")
                if st.button("Test the quality score", key="bt_quality_btn"):
                    fr = st.session_state.get("bt_frames")
                    if not fr:
                        st.info("Run the backtest first.")
                    else:
                        import quality as ql
                        with st.spinner("Scoring every past setup..."):
                            qt = ql.score_trades(fr[0], sc.SwingCriteria(stop_atr_mult=stop_mult, reward_risk=reward_risk),
                                                 bt.BTParams(setups=tuple(s.lower() for s in bt_setups) or ("pullback",),
                                                             stop_atr_mult=stop_mult, reward_risk=reward_risk,
                                                             max_hold=int(bt_hold), cost_pct=bt_cost), fr[1])
                        st.session_state["bt_quality"] = ql.evaluate(qt)
                        if fr[1] is None:
                            st.warning("Couldn't download SPY, so 'strength vs the market' was left out of the score here.")
                qres = st.session_state.get("bt_quality")
                if qres:
                    qtab, qverdict = qres
                    if len(qtab):
                        show_table(qtab)
                    (st.success if "evidence the score helps" in qverdict else st.warning if "WORSE" in qverdict else st.info)(qverdict)
                    st.caption("Thirds are by score among all setups. More stocks and years make this more reliable. Even a "
                               "real edge in the past can fade, so keep the stop on every trade.")
            with st.expander("All simulated trades"):
                _tr = rnd(trades)
                show_table(_tr, column_config=col_help(_tr, BT_TIPS))
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
            _sm = rnd(lg.summarize_evaluation(ev))
            show_table(_sm, column_config=col_help(_sm, SCAN_TIPS))
            with st.expander("Each pick"):
                _ev = rnd(ev)
                show_table(_ev, column_config=col_help(_ev, SCAN_TIPS))
            st.caption("'Target first' means the suggested target was reached before the stop within 10 trading days. "
                       "Picks from today have no future days yet, so they only appear once a later session has closed.")
        elif ev is not None:
            st.info("Not enough time has passed since your scans to measure them. Check again after the next session closes.")

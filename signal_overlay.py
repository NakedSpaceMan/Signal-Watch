#!/usr/bin/env python3
"""
signal_overlay.py - Buy/sell signal chart with plain-English explanations.

Usage examples:
    python signal_overlay.py AAPL
    python signal_overlay.py TSLA --period 2y --interval 1d
    python signal_overlay.py NVDA --period 60d --interval 1h
    python signal_overlay.py AAPL --threshold 4 --window 5
    python signal_overlay.py AAPL --watch      # live mode, 5-minute bars, refreshes every 60s
    python signal_overlay.py AAPL --watch --interval 15m --refresh 120
    python signal_overlay.py --demo            # fake data, works offline

Works the same on Linux (incl. Bazzite) and macOS. Opens an interactive chart
in your browser and prints an explanation of the latest signals to the terminal.

This is a learning/analysis tool, NOT financial advice. Signals from simple
indicator rules are frequently wrong; see the hit-rate summary it prints.
"""

import argparse
import sys

import numpy as np
import pandas as pd


MIN_BARS = 210  # the 200 EMA needs 200 bars before it exists
ET = "America/New_York"

_CAL = None


def _calendar():
    """NYSE trading calendar if the optional exchange_calendars package is installed."""
    global _CAL
    if _CAL is None:
        try:
            import exchange_calendars as xcals
            _CAL = xcals.get_calendar("XNYS")
        except Exception:
            _CAL = False
    return _CAL or None


def session_close_et(day):
    """
    Closing time (tz-aware, Eastern) of the NYSE session on `day`, or None when the
    market is closed that day. Uses the real exchange calendar (holidays and early
    closes) when exchange_calendars is installed; otherwise assumes Mon-Fri, 4:00 PM.
    """
    day = pd.Timestamp(day).normalize()
    cal = _calendar()
    if cal is not None:
        try:
            ds = day.strftime("%Y-%m-%d")
            if not cal.is_session(ds):
                return None
            return pd.Timestamp(cal.session_close(ds)).tz_convert(ET)
        except Exception:
            pass
    if day.weekday() >= 5:
        return None
    return day.tz_localize(ET) + pd.Timedelta(hours=16)


def daily_bar_in_progress(last_ts, now=None):
    """
    True if the daily bar at `last_ts` is today's and the session hasn't finished
    (plus a 10-minute buffer for Yahoo to finalize it). Holidays and weekends
    never produce a bar, so the last bar is then a finished one.
    """
    now = now if now is not None else pd.Timestamp.now(tz=ET)
    ts = pd.Timestamp(last_ts)
    if ts.tzinfo is not None:
        ts = ts.tz_convert(ET).tz_localize(None)
    if ts.normalize() != pd.Timestamp(now.date()):
        return False
    close = session_close_et(ts)
    if close is None:
        return False
    return now < close + pd.Timedelta(minutes=10)


def market_session_label(now=None):
    """Plain-English market state, shown next to scan results."""
    now = now if now is not None else pd.Timestamp.now(tz=ET)
    day = pd.Timestamp(now.date())
    close = session_close_et(day)
    if close is None:
        return "Closed (weekend or holiday)"
    opening = day.tz_localize(ET) + pd.Timedelta(hours=9, minutes=30)
    if now < opening:
        return "Pre-market (regular session not open yet)"
    if now < close:
        return "Regular session (open)"
    return "After hours (regular session closed)"


def default_period(interval):
    """History length that gives enough bars for the 200 EMA."""
    unit = interval[-1]
    if interval in ("1m", "5m"):
        return "5d"
    if unit == "m":
        return "30d"
    if unit == "h":
        return "60d"
    return "2y"


# --------------------------------------------------------------------------
# 1. Data
# --------------------------------------------------------------------------
def load_data(ticker, period, interval):
    import yfinance as yf

    df = yf.download(
        ticker, period=period, interval=interval,
        auto_adjust=True, progress=False,
    )
    if df is None or df.empty:
        raise RuntimeError(f"No data returned for '{ticker}'. Check the ticker/period/interval.")
    # Newer yfinance versions return MultiIndex columns even for one ticker.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def make_demo_data(n=500, seed=7):
    """Random-walk price data so you can test the tool without internet."""
    rng = np.random.default_rng(seed)
    drift = np.where(np.sin(np.linspace(0, 8 * np.pi, n)) > 0, 0.0008, -0.0007)
    rets = drift + rng.normal(0, 0.014, n)
    close = 100 * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
    vol = rng.integers(800_000, 2_000_000, n) * (1 + 1.5 * (rng.random(n) > 0.93))
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=idx,
    )


# --------------------------------------------------------------------------
# 2. Indicators
# --------------------------------------------------------------------------
def add_indicators(df):
    df = df.copy()
    c = df["Close"]

    # EMAs (the same three used on the Legend chart)
    df["EMA9"] = c.ewm(span=9, adjust=False, min_periods=9).mean()
    df["EMA20"] = c.ewm(span=20, adjust=False, min_periods=20).mean()
    df["EMA200"] = c.ewm(span=200, adjust=False, min_periods=200).mean()
    df["SMA20"] = c.rolling(20).mean()  # midline for the Bollinger Bands

    # RSI (Wilder smoothing)
    delta = c.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["RSI"] = 100 - 100 / (1 + gain / loss)

    # MACD
    ema12 = c.ewm(span=12, adjust=False).mean()
    ema26 = c.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_SIG"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_HIST"] = df["MACD"] - df["MACD_SIG"]

    # Bollinger Bands (20, 2)
    std = c.rolling(20).std()
    df["BB_UP"] = df["SMA20"] + 2 * std
    df["BB_LO"] = df["SMA20"] - 2 * std

    df["VOL_AVG"] = df["Volume"].rolling(20).mean()
    return df


# --------------------------------------------------------------------------
# 3. Pattern events and the reasons attached to them
# --------------------------------------------------------------------------
# Each event: (column name, side, weight, plain-English explanation)
EVENT_INFO = {
    "ma_up": ("buy", 2,
              "9 EMA crossed ABOVE the 20 EMA: short-term momentum is "
              "overtaking the slightly longer trend."),
    "ma_down": ("sell", 2,
                "9 EMA crossed BELOW the 20 EMA: short-term momentum is "
                "fading under the slightly longer trend."),
    "rsi_up": ("buy", 2,
               "RSI climbed back above 30: the stock was oversold (heavily sold) "
               "and selling pressure is easing."),
    "rsi_down": ("sell", 2,
                 "RSI dropped back below 70: the stock was overbought (heavily "
                 "bought) and buying pressure is easing."),
    "macd_up": ("buy", 2,
                "MACD crossed ABOVE its signal line: momentum turned upward."),
    "macd_down": ("sell", 2,
                  "MACD crossed BELOW its signal line: momentum turned downward."),
    "bb_up": ("buy", 1,
              "Price dipped below the lower Bollinger Band and closed back "
              "inside it: a possible snap-back from an extreme low."),
    "bb_down": ("sell", 1,
                "Price poked above the upper Bollinger Band and closed back "
                "inside it: a possible pullback from an extreme high."),
}

# Shorter wording for chart hovers, and "explain like I'm five" wording for beginners.
EVENT_SHORT = {
    "ma_up": "9 EMA crossed above the 20 EMA (short-term momentum turning up)",
    "ma_down": "9 EMA crossed below the 20 EMA (short-term momentum fading)",
    "rsi_up": "RSI back above 30 (was oversold, selling is easing)",
    "rsi_down": "RSI back below 70 (was overbought, buying is easing)",
    "macd_up": "MACD crossed above its signal line (momentum turning up)",
    "macd_down": "MACD crossed below its signal line (momentum turning down)",
    "bb_up": "Price dipped under the lower Bollinger Band, then recovered",
    "bb_down": "Price poked above the upper Bollinger Band, then fell back",
}
EVENT_PLAIN = {
    "ma_up": "The stock's quick-moving average price just climbed above its slower one. That usually means it is speeding up.",
    "ma_down": "The stock's quick-moving average price just dropped below its slower one. That usually means it is slowing down.",
    "rsi_up": "People had been selling this stock hard, and the selling is now slowing down.",
    "rsi_down": "People had been buying this stock very fast, and that rush is now calming down.",
    "macd_up": "The stock's momentum gauge just flipped to pointing up.",
    "macd_down": "The stock's momentum gauge just flipped to pointing down.",
    "bb_up": "The price got pushed unusually low, then snapped back, like a stretched rubber band.",
    "bb_down": "The price got pushed unusually high, then dropped back, like a ball that bounced too high.",
}
VOLUME_TEXT = {
    "full": "Volume was well above its 20-bar average, which adds confirmation that real money is behind the move.",
    "short": "Heavy trading volume backs the move",
    "plain": "Many more people than usual were trading it, so the move is more believable.",
}
CAUTION_TEXT = {
    ("buy", "full"): "CAUTION: price is still below the 200 EMA, so this may be a bounce inside a downtrend.",
    ("sell", "full"): "CAUTION: price is still above the 200 EMA, so the larger uptrend may still be intact.",
    ("buy", "short"): "Caution: still below the 200 EMA (long-term downtrend)",
    ("sell", "short"): "Caution: still above the 200 EMA (long-term uptrend intact)",
    ("buy", "plain"): "Careful: over the long run this stock is still heading down, so this may only be a small bounce.",
    ("sell", "plain"): "Careful: over the long run this stock is still heading up, so this dip may be just a wiggle.",
}


def detect_events(df):
    p = df.shift(1)  # previous bar
    ev = pd.DataFrame(index=df.index)
    ev["ma_up"] = (p.EMA9 <= p.EMA20) & (df.EMA9 > df.EMA20)
    ev["ma_down"] = (p.EMA9 >= p.EMA20) & (df.EMA9 < df.EMA20)
    ev["rsi_up"] = (p.RSI < 30) & (df.RSI >= 30)
    ev["rsi_down"] = (p.RSI > 70) & (df.RSI <= 70)
    ev["macd_up"] = (p.MACD <= p.MACD_SIG) & (df.MACD > df.MACD_SIG)
    ev["macd_down"] = (p.MACD >= p.MACD_SIG) & (df.MACD < df.MACD_SIG)
    ev["bb_up"] = (p.Close < p.BB_LO) & (df.Close >= df.BB_LO)
    ev["bb_down"] = (p.Close > p.BB_UP) & (df.Close <= df.BB_UP)
    return ev.fillna(False).astype(bool)


def score_signals(df, ev, window, threshold):
    """
    Events stay 'active' for `window` bars so near-simultaneous patterns can
    stack up. A signal fires on the bar where a side's score first reaches the
    threshold (and beats the other side).
    """
    active = ev.rolling(window, min_periods=1).max().astype(bool)
    vol_spike = (df["Volume"] > 1.5 * df["VOL_AVG"]).rolling(window, min_periods=1).max().astype(bool)

    buy_score = pd.Series(0, index=df.index, dtype=float)
    sell_score = pd.Series(0, index=df.index, dtype=float)
    for name, (side, weight, _) in EVENT_INFO.items():
        if side == "buy":
            buy_score += active[name] * weight
        else:
            sell_score += active[name] * weight

    # A volume spike only adds confirmation to a side that already has a pattern.
    buy_score += ((buy_score > 0) & vol_spike) * 1
    sell_score += ((sell_score > 0) & vol_spike) * 1

    df = df.copy()
    df["BUY_SCORE"] = buy_score
    df["SELL_SCORE"] = sell_score
    df["VOL_SPIKE_ACTIVE"] = vol_spike

    buy_now = (buy_score >= threshold) & (buy_score > sell_score)
    sell_now = (sell_score >= threshold) & (sell_score > buy_score)
    df["BUY"] = buy_now & ~buy_now.shift(1, fill_value=False)
    df["SELL"] = sell_now & ~sell_now.shift(1, fill_value=False)
    return df, active


def explain_bar(df, ev, active, i, window, side, mode="full"):
    """
    Reason strings for the bar at integer position i.
    mode: "full" (detailed, for reports), "short" (chart hovers) or "plain" (beginner wording).
    """
    reasons = []
    lo = max(0, i - window + 1)
    for name, (s, weight, text) in EVENT_INFO.items():
        if s != side or not active[name].iloc[i]:
            continue
        seg = ev[name].iloc[lo:i + 1].to_numpy()
        if not seg.any():  # the triggering event happened before the visible slice began
            continue
        ago = (len(seg) - 1) - int(np.where(seg)[0][-1])
        if mode == "plain":
            when = "just now" if ago == 0 else f"{ago} candle(s) ago"
            reasons.append(f"{EVENT_PLAIN[name]} ({when})")
        elif mode == "short":
            when = "this bar" if ago == 0 else f"{ago} bar(s) ago"
            reasons.append(f"{EVENT_SHORT[name]} ({when})")
        else:
            when = "this bar" if ago == 0 else f"{ago} bar(s) ago"
            reasons.append(f"{text} [{when}]")
    if df["VOL_SPIKE_ACTIVE"].iloc[i] and reasons:
        reasons.append(VOLUME_TEXT[mode])

    row = df.iloc[i]
    if side == "buy" and row.Close < row.EMA200:
        reasons.append(CAUTION_TEXT[("buy", mode)])
    if side == "sell" and row.Close > row.EMA200:
        reasons.append(CAUTION_TEXT[("sell", mode)])
    return reasons


# --------------------------------------------------------------------------
# 4. Text reports
# --------------------------------------------------------------------------
def describe_state_plain(df):
    r = df.iloc[-1]
    lines = []
    if r.Close > r.EMA200:
        lines.append("Big picture: over the long run this stock has been going UP (price is above the purple line).")
    else:
        lines.append("Big picture: over the long run this stock has been going DOWN (price is below the purple line).")
    lines.append("Short term: it is picking up speed." if r.EMA9 > r.EMA20
                 else "Short term: it is losing speed.")
    if r.RSI >= 70:
        lines.append("Crowd mood: very excited. People have been buying fast, which often cools off.")
    elif r.RSI <= 30:
        lines.append("Crowd mood: gloomy. People have been selling hard, which sometimes bounces back.")
    else:
        lines.append("Crowd mood: calm, not too excited and not too scared.")
    if r.Close > r.BB_UP:
        lines.append("Price: stretched unusually high compared with recent days.")
    elif r.Close < r.BB_LO:
        lines.append("Price: stretched unusually low compared with recent days.")
    else:
        lines.append("Price: in a normal range for recent days.")
    return lines


def describe_state(df):
    r = df.iloc[-1]
    lines = []
    trend = "above" if r.Close > r.EMA200 else "below"
    ma = "above" if r.EMA9 > r.EMA20 else "below"
    lines.append(f"Trend: price is {trend} the 200 EMA; the 9 EMA is {ma} the 20 EMA.")
    if r.RSI >= 70:
        z = "overbought territory (70+)"
    elif r.RSI <= 30:
        z = "oversold territory (30 or below)"
    else:
        z = "the neutral zone (30-70)"
    lines.append(f"RSI is {r.RSI:.1f}, in {z}.")
    mom = "positive (momentum up)" if r.MACD_HIST > 0 else "negative (momentum down)"
    lines.append(f"MACD histogram is {mom}.")
    if r.Close > r.BB_UP:
        b = "above the upper Bollinger Band (stretched high)"
    elif r.Close < r.BB_LO:
        b = "below the lower Bollinger Band (stretched low)"
    else:
        b = "inside the Bollinger Bands (not stretched)"
    lines.append(f"Price is {b}.")
    return lines


def current_report(df, ev, active, window, threshold, plain=False):
    r = df.iloc[-1]
    i = len(df) - 1
    mode = "plain" if plain else "full"
    out = ["", "=" * 70, f"CURRENT READ  (as of {df.index[-1]}, close {r.Close:.2f})", "=" * 70]
    out += ["  " + l for l in (describe_state_plain(df) if plain else describe_state(df))]
    out.append("")
    if plain:
        out.append(f"  Buy points {r.BUY_SCORE:.0f} | Sell points {r.SELL_SCORE:.0f} | a signal needs {threshold}")
    else:
        out.append(f"  Buy score {r.BUY_SCORE:.0f} | Sell score {r.SELL_SCORE:.0f} | threshold {threshold}")

    if r.BUY:
        out.append("  >>> NEW BUY SIGNAL on the latest bar. Why:" if not plain
                   else "  >>> NEW BUY SIGNAL. The tool thinks this could be a good moment to buy. Why:")
        out += [f"      - {x}" for x in explain_bar(df, ev, active, i, window, "buy", mode)]
    elif r.SELL:
        out.append("  >>> NEW SELL SIGNAL on the latest bar. Why:" if not plain
                   else "  >>> NEW SELL SIGNAL. The tool thinks the stock may be losing steam. Why:")
        out += [f"      - {x}" for x in explain_bar(df, ev, active, i, window, "sell", mode)]
    else:
        out.append("  No new signal on the latest bar." if not plain else "  No new signal right now.")
        for side, score in (("buy", r.BUY_SCORE), ("sell", r.SELL_SCORE)):
            if score >= threshold:
                out.append(f"  {side.capitalize()} conditions are still active ({score:.0f}/{threshold}), "
                           "but the signal already fired earlier, so nothing new:")
            elif score > 0:
                out.append(f"  Partial {side} evidence building ({score:.0f}/{threshold}):")
            if score > 0:
                out += [f"      - {x}" for x in explain_bar(df, ev, active, i, window, side, mode)
                        if not x.startswith(("CAUTION", "Careful"))]
        if r.BUY_SCORE == 0 and r.SELL_SCORE == 0:
            out.append("  None of the tracked patterns fired in the last "
                       f"{window} bars, so the rules have nothing to say right now.")
    return out


def history_report(df, ev, active, window, last_n=5, plain=False):
    out = ["", "=" * 70, f"LAST {last_n} SIGNALS", "=" * 70]
    sig = df[df.BUY | df.SELL].tail(last_n)
    if sig.empty:
        out.append("  No signals in this date range.")
        return out
    for ts, row in sig.iterrows():
        i = df.index.get_loc(ts)
        side = "buy" if row.BUY else "sell"
        out.append(f"\n  {ts}  {side.upper()} at {row.Close:.2f}")
        out += [f"      - {x}" for x in explain_bar(df, ev, active, i, window, side, "plain" if plain else "full")]
    return out


def hit_rate_report(df, horizon, cost_pct=0.2):
    """
    A quick look at what price did after past signals. NOT a trading backtest:
    it enters at the signal bar's close, ignores stops/targets and gaps, and
    only subtracts a rough round-trip cost. Use the Backtest tab for a fuller test.
    """
    out = ["", "=" * 70, f"QUICK LOOK: price change {horizon} bars after each signal", "=" * 70]
    fwd = df["Close"].shift(-horizon) / df["Close"] - 1
    r = fwd[df.BUY].dropna() - cost_pct / 100
    if r.empty:
        out.append("  BUY: no completed signals to measure.")
    else:
        out.append(f"  BUY: {len(r)} signals | up after costs {100 * (r > 0).mean():.0f}% of the time | "
                   f"avg {100 * r.mean():+.2f}% | worst {100 * r.min():+.2f}%")
    r = fwd[df.SELL].dropna()
    if r.empty:
        out.append("  SELL: no completed signals to measure.")
    else:
        out.append(f"  SELL: {len(r)} signals | the price then moved {100 * r.mean():+.2f}% on average "
                   f"(below zero means selling early helped if you held the stock)")
    out.append(f"  Assumes entry at the signal bar's close and a {cost_pct:g}% round-trip cost. "
               "Past results do not predict future ones.")
    return out


# --------------------------------------------------------------------------
# 5. Chart
# --------------------------------------------------------------------------
def build_chart(df, ev, active, window, title, opts=None, overlay=None, sr=None):
    """
    Interactive chart. Nights, weekends and holidays are squeezed out so trading
    hours fill the screen.
      opts    - which extras to show: volume, vwap, bb (Bollinger), macd, sr (support/resistance)
      overlay - your real position from the ledger (see chart_utils.add_position_overlay)
      sr      - precomputed support/resistance levels (computed here if omitted)
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    import chart_utils as cu

    o = {"volume": True, "vwap": False, "bb": True, "macd": True, "sr": False, "beginner": False}
    o.update(opts or {})
    x = cu.plot_x(df.index)
    intraday = len(x) > 2 and pd.Series(x).diff().median() < pd.Timedelta(days=1)

    panels = ["price"] + (["volume"] if o["volume"] else []) + ["rsi"] + (["macd"] if o["macd"] else [])
    weights = {"price": 5.0, "volume": 1.2, "rsi": 1.4, "macd": 1.4}
    heights = [weights[p] for p in panels]
    heights = [h / sum(heights) for h in heights]
    row = {p: i + 1 for i, p in enumerate(panels)}

    fig = make_subplots(rows=len(panels), cols=1, shared_xaxes=True,
                        vertical_spacing=0.03, row_heights=heights)
    fig.add_trace(go.Candlestick(
        x=x, open=df.Open, high=df.High, low=df.Low, close=df.Close,
        name="Price", increasing_line_color="#26a69a", decreasing_line_color="#ef5350"), row=1, col=1)
    for col, color in (("EMA9", "#2962ff"), ("EMA20", "#ff9800"), ("EMA200", "#e040fb")):
        fig.add_trace(go.Scatter(x=x, y=df[col], name=col, line=dict(width=1.3, color=color)), row=1, col=1)
    if o["bb"]:
        for col in ("BB_UP", "BB_LO"):
            fig.add_trace(go.Scatter(x=x, y=df[col], name=col, showlegend=False,
                                     line=dict(width=0.8, color="rgba(150,150,150,0.6)", dash="dot")), row=1, col=1)
    if o["vwap"] and intraday:
        fig.add_trace(go.Scatter(x=x, y=cu.session_vwap(df), name="VWAP",
                                 line=dict(width=1.4, color="#ffee58", dash="dash")), row=1, col=1)
    if o["sr"]:
        cu.add_sr_lines(fig, sr or cu.support_resistance(df), x)

    for flag, side, symbol, color, ypos in (
        ("BUY", "buy", "triangle-up", "#00c853", "Low"),
        ("SELL", "sell", "triangle-down", "#d50000", "High"),
    ):
        mask = df[flag].to_numpy()
        if not mask.any():
            continue
        hover = []
        for i in np.flatnonzero(mask):
            if o["beginner"]:
                reasons = explain_bar(df, ev, active, int(i), window, side, "plain")
                head = (f"<b>{flag} signal</b> at {df.Close.iloc[i]:.2f}<br>"
                        + ("The tool thinks this might be a good moment to buy." if side == "buy"
                           else "The tool thinks the stock may be losing steam.") + "<br>Why:")
                tail = "<br><i>Signals are only clues. They are wrong a lot, so treat them as a prompt to look closer.</i>"
            else:
                reasons = explain_bar(df, ev, active, int(i), window, side, "short")
                head = f"<b>{flag}</b> at {df.Close.iloc[i]:.2f}"
                tail = ""
            wrapped = "<br>".join("• " + _wrap(t, 52) for t in reasons[:4])
            hover.append(f"{head}<br>{wrapped}{tail}")
        offset = 0.985 if side == "buy" else 1.015
        fig.add_trace(go.Scatter(
            x=x[mask], y=df[ypos][mask] * offset, mode="markers", name=flag,
            marker=dict(symbol=symbol, size=14, color=color, line=dict(width=1, color="white")),
            hovertext=hover, hoverinfo="text"), row=1, col=1)

    cu.add_position_overlay(fig, overlay, x, daily=not intraday, row=1)

    if o["volume"]:
        vcol = np.where(df.Close >= df.Open, "#26a69a", "#ef5350")
        fig.add_trace(go.Bar(x=x, y=df.Volume, name="Volume", marker_color=vcol), row=row["volume"], col=1)
        fig.add_trace(go.Scatter(x=x, y=df.Volume.rolling(20).mean(), name="Avg volume",
                                 line=dict(width=1.2, color="#ffee58")), row=row["volume"], col=1)

    fig.add_trace(go.Scatter(x=x, y=df.RSI, name="RSI", line=dict(color="#7e57c2", width=1.3)), row=row["rsi"], col=1)
    for y in (30, 70):
        fig.add_hline(y=y, line=dict(color="gray", dash="dash", width=0.8), row=row["rsi"], col=1)

    if o["macd"]:
        colors = np.where(df.MACD_HIST >= 0, "#26a69a", "#ef5350")
        fig.add_trace(go.Bar(x=x, y=df.MACD_HIST, name="MACD hist", marker_color=colors), row=row["macd"], col=1)
        fig.add_trace(go.Scatter(x=x, y=df.MACD, name="MACD", line=dict(color="#2962ff", width=1.2)), row=row["macd"], col=1)
        fig.add_trace(go.Scatter(x=x, y=df.MACD_SIG, name="Signal", line=dict(color="#ff9800", width=1.2)), row=row["macd"], col=1)

    fig.update_layout(
        title=title, template="plotly_dark", height=420 + 160 * len(panels),
        xaxis_rangeslider_visible=False, hovermode="closest",
        hoverlabel=dict(align="left"), legend=dict(orientation="h", y=1.04),
    )
    fig.update_xaxes(rangebreaks=cu.time_rangebreaks(df.index))
    fig.update_yaxes(title_text="Price", row=1, col=1)
    if o["volume"]:
        fig.update_yaxes(title_text="Volume", row=row["volume"], col=1)
    fig.update_yaxes(title_text="RSI", row=row["rsi"], col=1)
    if o["macd"]:
        fig.update_yaxes(title_text="MACD", row=row["macd"], col=1)
    return fig


def _wrap(text, width=60):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    return "<br>&nbsp;&nbsp;".join(lines)


# --------------------------------------------------------------------------
# 6. Live watch mode
# --------------------------------------------------------------------------
def interval_to_timedelta(interval):
    unit, num = interval[-1], interval[:-1]
    if unit == "m" and num.isdigit():
        return pd.Timedelta(minutes=int(num))
    if unit == "h" and num.isdigit():
        return pd.Timedelta(hours=int(num))
    return None  # daily or longer: no partial-bar handling


def is_intraday(interval):
    return interval_to_timedelta(interval) is not None


def drop_unfinished_bar(raw, delta):
    """
    Signals should only use CLOSED bars; drop the bar still forming. Intraday bars
    are checked against the clock. Daily bars (delta is None) are checked against
    the exchange session, so a half-finished daily candle never feeds a signal.
    """
    if raw.empty:
        return raw
    if delta is None:
        return raw.iloc[:-1] if daily_bar_in_progress(raw.index[-1]) else raw
    now = pd.Timestamp.now(tz=raw.index.tz) if raw.index.tz is not None else pd.Timestamp.now()
    if raw.index[-1] + delta > now:
        return raw.iloc[:-1]
    return raw


def add_auto_refresh(path, seconds):
    """Make the saved chart page reload itself every `seconds`."""
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    tag = f'<meta http-equiv="refresh" content="{seconds}" />'
    if "<head>" in html:
        html = html.replace("<head>", "<head>" + tag, 1)
    else:
        html = tag + html
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)


def analyze(raw, args):
    df = add_indicators(raw)
    ev = detect_events(df)
    df, active = score_signals(df, ev, args.window, args.threshold)
    return df, ev, active


def watch(args, ticker):
    import time
    import webbrowser
    from pathlib import Path

    delta = interval_to_timedelta(args.interval)
    path = args.save or f"{ticker}_live.html"
    last_alerted = None
    opened = False

    try:
        while True:
            now_str = pd.Timestamp.now().strftime("%H:%M:%S")
            try:
                raw = load_data(ticker, args.period, args.interval)
                raw = drop_unfinished_bar(raw, delta)
                if len(raw) < MIN_BARS:
                    raise RuntimeError(f"Not enough closed bars yet (need ~{MIN_BARS} for the 200 EMA).")
                df, ev, active = analyze(raw, args)
            except Exception as e:  # network hiccup, rate limit, etc. Keep going.
                print(f"[{now_str}] Data problem: {e}. Retrying in {args.refresh}s...")
                time.sleep(args.refresh)
                continue

            print("\033[2J\033[H", end="")  # clear terminal
            print(f"WATCHING {ticker} ({args.interval}) | updated {now_str} | "
                  f"next check in {args.refresh}s | Ctrl+C to stop")
            if delta is not None:
                last_end = df.index[-1] + delta
                now = pd.Timestamp.now(tz=df.index.tz) if df.index.tz is not None else pd.Timestamp.now()
                if now - last_end > 3 * delta:
                    print(f"NOTE: latest closed bar is from {df.index[-1]}; the market may be "
                          "closed, so nothing will change until it reopens.")
            print("\n".join(current_report(df, ev, active, args.window, args.threshold)))
            print("\n".join(history_report(df, ev, active, args.window, last_n=3)))

            # Alert once per fresh signal on the newest closed bar.
            latest = df.iloc[-1]
            if (latest.BUY or latest.SELL) and df.index[-1] != last_alerted:
                last_alerted = df.index[-1]
                kind = "BUY" if latest.BUY else "SELL"
                print(f"\a\n*** NEW {kind} SIGNAL on {ticker} at {latest.Close:.2f} "
                      f"({df.index[-1]}) - see explanation above ***")

            # Chart: show the most recent bars so it stays readable.
            n = args.bars
            fig = build_chart(df.tail(n), ev.tail(n), active.tail(n), args.window,
                              f"{ticker} - live signals ({args.interval})")
            fig.write_html(path)
            add_auto_refresh(path, args.refresh)
            if not opened:
                webbrowser.open(Path(path).resolve().as_uri())
                opened = True
            time.sleep(args.refresh)
    except KeyboardInterrupt:
        print("\nStopped watching.")


# --------------------------------------------------------------------------
# 7. Main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Buy/sell signals with explanations.")
    ap.add_argument("ticker", nargs="?", default="AAPL")
    ap.add_argument("--period", default=None, help="e.g. 5d, 60d, 1y (auto-picked from the interval if omitted)")
    ap.add_argument("--interval", default=None, help="e.g. 5m, 15m, 1h, 1d (default: 5m with --watch, else 1d)")
    ap.add_argument("--threshold", type=int, default=3, help="score needed to fire a signal (default 3)")
    ap.add_argument("--window", type=int, default=5, help="bars during which a pattern still counts (default 5)")
    ap.add_argument("--horizon", type=int, default=10, help="bars ahead for the reality check (default 10)")
    ap.add_argument("--watch", action="store_true", help="live mode: refetch, redraw and alert on new signals")
    ap.add_argument("--refresh", type=int, default=60, help="seconds between checks in --watch mode (default 60)")
    ap.add_argument("--bars", type=int, default=150, help="bars shown on the live chart (default 150)")
    ap.add_argument("--demo", action="store_true", help="use fake data (no internet needed)")
    ap.add_argument("--no-chart", action="store_true", help="text report only")
    ap.add_argument("--save", metavar="FILE.html", help="save the chart to this HTML file")
    args = ap.parse_args()

    if args.interval is None:
        args.interval = "5m" if args.watch else "1d"
    if args.period is None:
        args.period = default_period(args.interval)

    ticker = "DEMO" if args.demo else args.ticker.upper()

    if args.watch:
        watch(args, ticker)
        return

    try:
        raw = make_demo_data() if args.demo else load_data(ticker, args.period, args.interval)
    except RuntimeError as e:
        sys.exit(str(e))
    if not args.demo:
        raw = drop_unfinished_bar(raw, interval_to_timedelta(args.interval))
    if len(raw) < MIN_BARS:
        sys.exit(f"Not enough data (need at least ~{MIN_BARS} bars for the 200 EMA). Try a longer --period.")

    df, ev, active = analyze(raw, args)

    print("\n".join(current_report(df, ev, active, args.window, args.threshold)))
    print("\n".join(history_report(df, ev, active, args.window)))
    print("\n".join(hit_rate_report(df, args.horizon)))
    print("\nNot financial advice. Simple indicator rules often fail live.\n")

    if not args.no_chart:
        fig = build_chart(df, ev, active, args.window, f"{ticker} - signals ({args.interval})")
        if args.save:
            fig.write_html(args.save)
            print(f"Chart saved to {args.save}")
        fig.show()


if __name__ == "__main__":
    main()

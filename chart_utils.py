"""
chart_utils.py - helpers shared by the intraday chart and the swing chart.

* plot_x / time_rangebreaks: hide nights, weekends and holidays so trading
  hours fill the chart instead of 80% blank gaps.
* session_vwap, support_resistance: optional chart extras.
* add_position_overlay: draws YOUR actual entry/stop/target lines and fills
  (from the trade ledger), separate from the scanner's suggested levels.

Plotly is imported only inside the functions that draw, so the calculations
here can be used and tested without it.
"""

from datetime import datetime

import numpy as np
import pandas as pd

ET = "America/New_York"


def plot_x(index):
    """
    Timezone-naive wall-clock timestamps for plotting. Plotly has no real time
    zone support, so we plot the exchange's local clock time (US stocks: Eastern),
    which is also what makes the hour-based gap hiding below line up.
    """
    idx = pd.DatetimeIndex(index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx


def time_rangebreaks(index):
    """
    Plotly rangebreaks that remove weekends, market holidays (days with no
    bars) and, for intraday data, the hours outside the trading session.
    """
    tz = getattr(pd.DatetimeIndex(index), "tz", None)
    idx = plot_x(index)
    breaks = [dict(bounds=["sat", "mon"])]
    if len(idx) < 3:
        return breaks

    # Holidays / closures: business days inside the range that have no bars at all.
    present = set(idx.normalize())
    missing = [d for d in pd.bdate_range(idx[0].normalize(), idx[-1].normalize()) if d not in present]
    if missing:
        breaks.append(dict(values=[d.strftime("%Y-%m-%d") for d in missing], dvalue=86_400_000))

    step = pd.Series(idx).diff().median()
    if pd.notna(step) and step < pd.Timedelta(days=1):  # intraday: hide the overnight hours
        tod = np.asarray(idx.hour + idx.minute / 60.0, dtype=float)
        open_h = float(tod.min())
        close_h = float(tod.max()) + step.total_seconds() / 3600.0
        if tz is not None and str(tz) == ET and 15.9 < close_h <= 17.0:
            close_h = 16.0  # hourly bars end at 16:00 even though the last one starts at 15:30
        if 0 < open_h < close_h < 24:
            breaks.append(dict(bounds=[close_h, open_h], pattern="hour"))
    return breaks


def session_vwap(df):
    """Volume-weighted average price, restarting each trading day (intraday charts)."""
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    day = plot_x(df.index).normalize()
    pv = (tp * df["Volume"]).groupby(day).cumsum()
    vol = df["Volume"].groupby(day).cumsum()
    return pv / vol.replace(0, np.nan)


def support_resistance(df, left=5, right=5, n=3, tol_pct=0.6, min_touches=2):
    """
    Nearby support (below price) and resistance (above price) levels, found from
    swing highs/lows that price has respected at least `min_touches` times.
    Returns {"support": [(price, touches)], "resistance": [(price, touches)]}.
    """
    h = df["High"].to_numpy(float)
    l = df["Low"].to_numpy(float)
    pts = []
    for i in range(left, len(df) - right):
        wh, wl = h[i - left:i + right + 1], l[i - left:i + right + 1]
        if np.argmax(wh) == left:
            pts.append(h[i])
        if np.argmin(wl) == left:
            pts.append(l[i])
    if not pts:
        return {"support": [], "resistance": []}

    price = float(df["Close"].iloc[-1])
    tol = tol_pct / 100 * price
    levels = []  # [sum of prices, count]
    for p in sorted(pts):
        if levels and abs(p - levels[-1][0] / levels[-1][1]) <= tol:
            levels[-1][0] += p
            levels[-1][1] += 1
        else:
            levels.append([p, 1])
    lv = [(s / c, c) for s, c in levels if c >= min_touches]
    return {
        "support": sorted([x for x in lv if x[0] < price], key=lambda t: -t[0])[:n],
        "resistance": sorted([x for x in lv if x[0] > price], key=lambda t: t[0])[:n],
    }


def _to_chart_clock(ts, daily):
    """Convert a ledger timestamp (your computer's clock) to the chart's wall clock."""
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize(datetime.now().astimezone().tzinfo)
    t = t.tz_convert(ET).tz_localize(None)
    return t.normalize() if daily else t


def snap_position(x, ts, daily=False):
    """Index of the bar a fill belongs to, or None if it is outside the chart."""
    t = _to_chart_clock(ts, daily)
    if t < x[0].normalize() - pd.Timedelta(days=1) or t > x[-1] + pd.Timedelta(days=5):
        return None
    pos = int(x.searchsorted(t))
    return min(max(pos, 0), len(x) - 1)


def add_sr_lines(fig, levels, x, row=1):
    import plotly.graph_objects as go

    for kind, color in (("support", "rgba(0,200,83,0.55)"), ("resistance", "rgba(255,82,82,0.55)")):
        for price, touches in levels.get(kind, []):
            fig.add_trace(go.Scatter(
                x=[x[0], x[-1]], y=[price, price], mode="lines",
                name=f"{kind.capitalize()} {price:.2f} ({touches} touches)", showlegend=False,
                line=dict(color=color, width=1, dash="dashdot"),
                hovertext=f"{kind.capitalize()} near {price:.2f} (price turned here {touches} times)",
                hoverinfo="text"), row=row, col=1)


def add_position_overlay(fig, overlay, x, daily=False, row=1):
    """
    Draw your real position: average cost, current stop, target, and every fill.
    Scanner-suggested levels (if given) are drawn dotted so they are never
    confused with your actual orders.
    """
    import plotly.graph_objects as go

    if not overlay:
        return

    def line(y, label, color, dash):
        if y is None or pd.isna(y):
            return
        fig.add_trace(go.Scatter(
            x=[x[0], x[-1]], y=[y, y], mode="lines", name=f"{label} {y:.2f}",
            line=dict(color=color, width=1.5, dash=dash), hoverinfo="skip"), row=row, col=1)

    line(overlay.get("entry"), "Your avg cost", "#4fc3f7", "dash")
    line(overlay.get("stop"), "Your stop", "#ff5252", "solid")
    line(overlay.get("target"), "Your target", "#69f0ae", "solid")
    line(overlay.get("suggested_stop"), "Suggested stop", "#ff8a80", "dot")
    line(overlay.get("suggested_target"), "Suggested target", "#b9f6ca", "dot")

    for side, symbol, color in (("BUY", "triangle-up", "#00e5ff"), ("SELL", "triangle-down", "#ffd740")):
        xs, ys, tips = [], [], []
        for f in overlay.get("fills", []):
            if f["side"] != side:
                continue
            pos = snap_position(x, f["ts"], daily)
            if pos is None:
                continue
            xs.append(x[pos])
            ys.append(f["price"])
            verb = "bought" if side == "BUY" else "sold"
            tips.append(f"You {verb} {f['qty']:g} @ {f['price']:.2f}<br>{pd.Timestamp(f['ts']):%b %d %H:%M}")
        if xs:
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="markers", name=f"Your {side.lower()}s",
                marker=dict(symbol=symbol, size=13, color=color, line=dict(width=1.5, color="black")),
                hovertext=tips, hoverinfo="text"), row=row, col=1)

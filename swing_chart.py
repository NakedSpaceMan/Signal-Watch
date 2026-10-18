"""
swing_chart.py - daily chart built for swing trading, with a teaching marker on
every setup. Hover a marker to see WHY the scanner would have flagged it, the
suggested stop and target for that day, and what price actually did next.

Uses the exact same rules as the Swing scanner (scanner.swing_setup_flags), so
the chart and the scan can never disagree. Plotly is imported only when drawing.
"""

import numpy as np
import pandas as pd

import backtest as bt
import chart_utils as cu
import signal_overlay as so

STYLE = {
    "pullback": dict(label="Pullback", symbol="diamond", color="#29b6f6"),
    "breakout": dict(label="Breakout", symbol="star", color="#ffd600"),
    "bounce": dict(label="Bounce", symbol="circle", color="#66bb6a"),
}

IDEAS = {
    "pullback": "Idea: buying a short dip inside a healthy uptrend, near the 20 EMA where buyers often step in.",
    "breakout": "Idea: price pushed above recent resistance on heavy volume, which can mean new buyers are in control.",
    "bounce": "Idea: the stock was heavily sold, then turned up, which can mean selling pressure is fading.",
}


TAGLINE = {
    "pullback": "Buying a small dip inside an uptrend",
    "breakout": "Price pushing above recent highs on heavy volume",
    "bounce": "Oversold stock starting to turn up",
}
TAGLINE_PLAIN = {
    "pullback": "A possible 'buy the dip' moment.",
    "breakout": "The stock just broke out upward.",
    "bounce": "The stock was beaten down and may be bouncing back.",
}


def explain_setup(df, flags, i, key, c, mode="full"):
    """
    Reasons (a list of strings) why bar i is a `key` setup.
    mode: "full" (detailed, for the text panel), "short" (chart hover) or "plain" (beginner wording).
    """
    r, f = df.iloc[i], flags.iloc[i]
    if mode == "plain":
        up = "The stock has been climbing for months (price is above its long-term average)."
        if key == "pullback":
            off = (df["Close"].iloc[max(0, i - 9):i + 1].max() / r.Close - 1) * 100
            return [up,
                    f"It just stepped back {off:.1f}% from its recent high, like a ball bouncing down one stair.",
                    "It is resting near its short-term average (the orange line), where buyers often return.",
                    f"It is not too hot or too cold right now (RSI {r.RSI:.0f})."]
        if key == "breakout":
            ph = df["High"].iloc[max(0, i - c.breakout_days):i].max()
            return [up,
                    f"It closed at {r.Close:.2f}, above the highest price of the last {c.breakout_days} days "
                    f"({ph:.2f}), like clearing a hurdle it could not clear before.",
                    f"{f['rvol']:.1f}x more people than usual traded it, so the jump looks real.",
                    f"It is not overheated yet (RSI {r.RSI:.0f})."]
        low = df["RSI"].iloc[max(0, i - 4):i + 1].min()
        return [up,
                f"It was sold off hard in the last few days (RSI dipped to {low:.0f}).",
                "Sellers now look tired: the price ticked back up."]
    if mode == "short":
        trend = "Uptrend: above the 200 EMA, 20 EMA above 200 EMA"
        if key == "pullback":
            off = (df["Close"].iloc[max(0, i - 9):i + 1].max() / r.Close - 1) * 100
            return [trend, f"Dipped {off:.1f}% from its 10-day high",
                    f"{abs(f['dist20']):.1f}% {'below' if f['dist20'] < 0 else 'above'} the 20 EMA (support area)",
                    f"RSI {r.RSI:.0f}: not overheated"]
        if key == "breakout":
            ph = df["High"].iloc[max(0, i - c.breakout_days):i].max()
            return [trend, f"Closed {r.Close:.2f}, above the {c.breakout_days}-day high ({ph:.2f})",
                    f"Volume {f['rvol']:.1f}x normal", f"RSI {r.RSI:.0f}: not overheated"]
        low = df["RSI"].iloc[max(0, i - 4):i + 1].min()
        return [trend, f"RSI fell to {low:.0f} in the last 5 days (oversold)",
                f"RSI now {r.RSI:.0f} and price closed up (turning)"]
    trend = (f"Uptrend: price {r.Close:.2f} is above the 200 EMA ({r.EMA200:.2f}) and the 20 EMA "
             f"({r.EMA20:.2f}) is above the 200 EMA.")
    if key == "pullback":
        off = (df["Close"].iloc[max(0, i - 9):i + 1].max() / r.Close - 1) * 100
        why = [trend,
               f"Dip: price is {off:.1f}% below its 10-day high (the rule needs at least 2%).",
               f"Location: {abs(f['dist20']):.1f}% {'below' if f['dist20'] < 0 else 'above'} the 20 EMA "
               "(the rule needs within 3%).",
               f"Calm momentum: RSI is {r.RSI:.0f} (the rule wants 40 to 60, not overheated or oversold)."]
    elif key == "breakout":
        ph = df["High"].iloc[max(0, i - c.breakout_days):i].max()
        why = [trend,
               f"Breakout: it closed at {r.Close:.2f}, above the highest high of the prior {c.breakout_days} days ({ph:.2f}).",
               f"Volume: {f['rvol']:.1f}x its 30-day average (the rule needs {c.breakout_rvol:g}x).",
               f"Not overheated: RSI is {r.RSI:.0f} (the rule caps it at 75)."]
    else:
        low = df["RSI"].iloc[max(0, i - 4):i + 1].min()
        why = [trend,
               f"Oversold: RSI dropped to {low:.0f} within the last 5 days (35 or less counts).",
               f"Turning up: RSI is now {r.RSI:.0f}, higher than yesterday, and price closed above the prior close."]
    return why + [IDEAS[key]]


def _wrap(text, width=56):
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    lines.append(cur)
    return "<br>&nbsp;&nbsp;".join(lines)


def _outcome_line(trade, atr, p, mode="short"):
    if trade is None:
        return "What happened next: too recent to know."
    if mode == "plain":
        pre = (f"What happened next: if you had bought the next morning at ${trade['entry']:.2f}, with a safety exit at "
               f"${trade['stop']:.2f} and a profit goal of ${trade['target']:.2f}, ")
        if trade["reason"] == "Still open":
            return pre + "the trade would still be going."
        word = {"Target": "the price reached the profit goal", "Target (gap)": "the price jumped past the profit goal",
                "Stop": "the price fell to the safety exit", "Stop (gap)": "the price fell below the safety exit overnight",
                "Time limit": f"neither was reached, so it would have been sold at the {p.max_hold}-day limit"}[trade["reason"]]
        res = "making" if trade["pnl_pct"] >= 0 else "losing"
        when = "" if trade["reason"] == "Time limit" else f" after {trade['days']} day(s)"
        return pre + f"{word}{when}, {res} about {abs(trade['pnl_pct']):.0f}%."
    pre = f"Next open {trade['entry']:.2f}, stop {trade['stop']:.2f}, target {trade['target']:.2f}: "
    if trade["reason"] == "Still open":
        return pre + "still open."
    word = {"Target": "target hit", "Target (gap)": "gapped past the target",
            "Stop": "stop hit", "Stop (gap)": "gapped below the stop (worse fill)",
            "Time limit": f"closed at the {p.max_hold}-day limit"}[trade["reason"]]
    return pre + f"{word} after {trade['days']}d, {trade['r']:+.1f}R ({trade['pnl_pct']:+.1f}%)."


def build_swing_chart(df, flags, criteria, title, setups=("pullback", "breakout", "bounce"),
                      opts=None, overlay=None, params=None, show_outcomes=True, sr=None):
    """
    df     - daily OHLCV with indicators (signal_overlay.add_indicators)
    flags  - scanner.swing_setup_flags(df, criteria), same index as df
    Returns a Plotly figure. `setups` picks which markers to draw.
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    p = params or bt.BTParams(stop_atr_mult=criteria.stop_atr_mult, reward_risk=criteria.reward_risk)
    o = {"volume": True, "sr": True, "beginner": False}
    o.update(opts or {})
    x = cu.plot_x(df.index)

    panels = ["price"] + (["volume"] if o["volume"] else []) + ["rsi"]
    weights = {"price": 5.5, "volume": 1.1, "rsi": 1.5}
    h = [weights[k] for k in panels]
    h = [v / sum(h) for v in h]
    row = {k: n + 1 for n, k in enumerate(panels)}
    fig = make_subplots(rows=len(panels), cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=h)

    fig.add_trace(go.Candlestick(x=x, open=df.Open, high=df.High, low=df.Low, close=df.Close, name="Price",
                                 increasing_line_color="#26a69a", decreasing_line_color="#ef5350"), row=1, col=1)
    for col, color in (("EMA9", "#2962ff"), ("EMA20", "#ff9800"), ("EMA200", "#e040fb")):
        fig.add_trace(go.Scatter(x=x, y=df[col], name=col, line=dict(width=1.3, color=color)), row=1, col=1)
    if o["sr"]:
        cu.add_sr_lines(fig, sr or cu.support_resistance(df), x)

    atr = flags["atr"].to_numpy(float)
    for key in setups:
        mask = (flags[key] & flags["filters_ok"]).to_numpy(bool)
        if not mask.any():
            continue
        st = STYLE[key]
        tips = []
        for i in np.flatnonzero(mask):
            when = f"{df.index[i]:%b %d, %Y}"
            if o["beginner"]:
                lines = [f"<b>{st['label']} setup</b> · {when}", TAGLINE_PLAIN[key], "Why the tool flagged it:"]
                reasons = explain_setup(df, flags, int(i), key, criteria, "plain")
            else:
                lines = [f"<b>{st['label']} setup</b> · {when} · close {df.Close.iloc[i]:.2f}", TAGLINE[key]]
                reasons = explain_setup(df, flags, int(i), key, criteria, "short")
            lines += ["• " + _wrap(t) for t in reasons]
            if show_outcomes:
                trade = bt.simulate_trade(df, int(i), atr[i], p)
                lines.append("<i>" + _wrap(_outcome_line(trade, atr[i], p, "plain" if o["beginner"] else "short")) + "</i>")
            tips.append("<br>".join(lines))
        fig.add_trace(go.Scatter(
            x=x[mask], y=df["Low"][mask] * 0.985, mode="markers", name=st["label"],
            marker=dict(symbol=st["symbol"], size=15, color=st["color"], line=dict(width=1, color="white")),
            hovertext=tips, hoverinfo="text"), row=1, col=1)

    cu.add_position_overlay(fig, overlay, x, daily=True, row=1)

    if o["volume"]:
        vcol = np.where(df.Close >= df.Open, "#26a69a", "#ef5350")
        fig.add_trace(go.Bar(x=x, y=df.Volume, name="Volume", marker_color=vcol), row=row["volume"], col=1)
        fig.add_trace(go.Scatter(x=x, y=df.Volume.rolling(30).mean(), name="30d avg volume",
                                 line=dict(width=1.2, color="#ffee58")), row=row["volume"], col=1)
        fig.update_yaxes(title_text="Volume", row=row["volume"], col=1)

    fig.add_trace(go.Scatter(x=x, y=df.RSI, name="RSI", line=dict(color="#7e57c2", width=1.3)), row=row["rsi"], col=1)
    for y in (30, 70):
        fig.add_hline(y=y, line=dict(color="gray", dash="dash", width=0.8), row=row["rsi"], col=1)
    fig.update_yaxes(title_text="RSI", row=row["rsi"], col=1)

    fig.update_layout(title=title, template="plotly_dark", height=420 + 160 * len(panels),
                      xaxis_rangeslider_visible=False, hovermode="closest",
                      hoverlabel=dict(align="left"), legend=dict(orientation="h", y=1.04))
    fig.update_xaxes(rangebreaks=cu.time_rangebreaks(df.index))
    fig.update_yaxes(title_text="Price", row=1, col=1)
    return fig


def current_swing_read(df, flags, criteria, p=None, plain=False):
    """Summary of where the latest daily bar stands, for the text panel. plain=True uses beginner wording."""
    p = p or bt.BTParams(stop_atr_mult=criteria.stop_atr_mult, reward_risk=criteria.reward_risk)
    i = len(df) - 1
    r, f = df.iloc[i], flags.iloc[i]
    mode = "plain" if plain else "full"
    lines = [f"Latest finished daily bar: {df.index[i]:%b %d, %Y}, close {r.Close:.2f}"]
    if not bool(f["uptrend"]):
        lines.append("Trend: this stock is NOT in a steady climb right now, so the swing scanner skips it."
                     if plain else
                     "Trend: NOT an uptrend (price must be above the 200 EMA with the 20 EMA above it). "
                     "The swing scanner skips stocks like this.")
    else:
        lines.append("Trend: the stock has been climbing steadily (a healthy uptrend)." if plain else
                     "Trend: uptrend (price above the 200 EMA, 20 EMA above the 200 EMA).")
    if not bool(f["filters_ok"]):
        lines.append("Screening filters: this stock does not pass your price/volume/ATR limits right now.")
    found = [STYLE[k]["label"] for k in ("pullback", "breakout", "bounce") if bool(f[k])]
    if found and bool(f["filters_ok"]):
        lines.append("Setup today: " + ", ".join(found) + ".")
        atr = float(f["atr"])
        stop = r.Close - p.stop_atr_mult * atr
        target = r.Close + p.reward_risk * (r.Close - stop)
        if plain:
            lines.append(f"Suggested safety exit (stop): {stop:.2f}. Suggested profit goal (target): {target:.2f}. "
                         "These come from how much the stock normally moves in a day.")
        else:
            lines.append(f"Suggested levels from today's close: stop {stop:.2f}, target {target:.2f}.")
        for k in ("pullback", "breakout", "bounce"):
            if bool(f[k]):
                lines += ["  - " + t for t in explain_setup(df, flags, i, k, criteria, mode)]
    else:
        lines.append("Setup today: none of the three setups is present on the latest bar.")
        if plain:
            lines.append("In plain terms: nothing here looks like a good entry today.")
        else:
            lines.append(f"RSI {r.RSI:.0f}, {f['dist20']:+.1f}% from the 20 EMA, volume {f['rvol']:.1f}x average.")
    return lines


# ---------------------------------------------------------------------------
# Buy / Hold / Sell verdict from the last ~3 months of daily data
# ---------------------------------------------------------------------------
VERDICT_LOOKBACK = 63  # trading days, about 3 months


def three_month_verdict(df, flags, criteria, p=None, holding=None, lookback=VERDICT_LOOKBACK, earnings=None, news=None, extra_event=None):
    """
    Read the last ~3 months of DAILY bars and return a plain Buy / Hold / Sell verdict with the reasons.
    df: daily bars with indicators (signal_overlay.add_indicators), at least `lookback` + 1 rows.
    flags: scanner.swing_setup_flags(df, criteria).
    holding: optional {"avg": entry, "stop": stop or None, "price": last} if the user owns the stock.

    Seven factors, each scored from -1 to +1 (the 3-month change counts up to +/-2), so the total runs
    from -8 to +8:  3-month change, long-term trend, short-term trend, RSI momentum, highs and lows,
    volume on up days vs down days, and distance from the 3-month high.
      score >= 4  -> BUY      score <= -3 -> SELL      otherwise HOLD
    earnings: optional scanner.earnings_profile(...) result. A BUY is downgraded to HOLD if the company reports
    within 7 days (a report can gap the price right past a stop), and the report history is shown.
    extra_event: optional {"days": int, "label": str} for a company event the user typed in (trading update, investor day).
    Treated like an earnings date: a BUY within 7 days is held back to HOLD.
    news: optional dict = scanner.news_profile(...) plus an optional "manual" key ("good"/"neutral"/"bad") holding the
    user's own call. News can only hold a BUY back (a red-flag headline, a clearly negative mood across at least
    3 recent headlines, or the user marking it bad). Good news never creates a BUY.
    A BUY is downgraded to HOLD if the stock is stretched (RSI over 75 or more than 10% above its 20 EMA),
    because chasing a stretched stock is how swing trades get started at bad prices.
    Returns None if there is not enough data.
    """
    p = p or bt.BTParams(stop_atr_mult=criteria.stop_atr_mult, reward_risk=criteria.reward_risk)
    if len(df) < lookback + 1:
        return None
    w = df.tail(lookback)
    r = df.iloc[-1]
    close = float(r.Close)
    third = lookback // 3
    f = []  # factors: (name, points, tech text, plain text)

    chg = (close / float(df.Close.iloc[-lookback]) - 1) * 100
    pts = 2 if chg >= 8 else 1 if chg >= 2 else -2 if chg <= -8 else -1 if chg <= -2 else 0
    f.append(("3-month change", pts, f"Price is {chg:+.1f}% over the last 3 months.",
              f"Over the last 3 months the price has {'gone up' if chg >= 2 else 'dropped' if chg <= -2 else 'barely moved'}"
              f"{'' if -2 < chg < 2 else f' by about {abs(chg):.0f}%'}."))

    up200, up20_200 = close > r.EMA200, r.EMA20 > r.EMA200
    pts = 1 if (up200 and up20_200) else -1 if (not up200 and not up20_200) else 0
    f.append(("Long-term trend", pts,
              "Above the 200 EMA with the 20 EMA above it (long-term uptrend)." if pts == 1 else
              "Below the 200 EMA with the 20 EMA under it (long-term downtrend)." if pts == -1 else
              "Mixed against the 200 EMA (the long-term trend is unclear).",
              "Over the long run the stock has been climbing." if pts == 1 else
              "Over the long run the stock has been sinking." if pts == -1 else
              "Over the long run the stock is not clearly going up or down."))

    above20, e9_20 = close > r.EMA20, r.EMA9 > r.EMA20
    pts = 1 if (above20 and e9_20) else -1 if (not above20 and not e9_20) else 0
    f.append(("Short-term trend", pts,
              "Price is above the 20 EMA and the 9 EMA is above the 20 EMA (short-term strength)." if pts == 1 else
              "Price is below the 20 EMA and the 9 EMA is under it (short-term weakness)." if pts == -1 else
              "Short-term signals disagree (price and the 9 and 20 EMAs are mixed).",
              "In the last couple of weeks it has been gaining speed." if pts == 1 else
              "In the last couple of weeks it has been losing speed." if pts == -1 else
              "In the last couple of weeks it has been going sideways."))

    rsi = float(r.RSI)
    pts = 1 if 50 <= rsi <= 70 else -1 if (rsi < 40 or rsi > 75) else 0
    f.append(("Momentum (RSI)", pts,
              f"RSI is {rsi:.0f}: " + ("healthy momentum (50 to 70)." if pts == 1 else
                                      "overheated (above 75), so chasing is risky." if rsi > 75 else
                                      "weak (below 40)." if rsi < 40 else "neutral."),
              "The crowd's mood is healthy: buying interest without being too excited." if pts == 1 else
              "The crowd is too excited, which often cools off." if rsi > 75 else
              "The crowd's mood is gloomy." if rsi < 40 else "The crowd's mood is neutral."))

    last, mid = w.iloc[-third:], w.iloc[-2 * third:-third]
    hh, hl = last.High.max() > mid.High.max(), last.Low.min() > mid.Low.min()
    lh, ll = last.High.max() < mid.High.max(), last.Low.min() < mid.Low.min()
    pts = 1 if (hh and hl) else -1 if (lh and ll) else 0
    f.append(("Highs and lows", pts,
              "The last month made higher highs and higher lows (a staircase up)." if pts == 1 else
              "The last month made lower highs and lower lows (a staircase down)." if pts == -1 else
              "The last month's highs and lows are not clearly rising or falling.",
              "Each recent peak and dip has been higher than the one before, like climbing stairs." if pts == 1 else
              "Each recent peak and dip has been lower than the one before, like walking down stairs." if pts == -1 else
              "The recent peaks and dips are not clearly climbing or falling."))

    d = w.Close.diff()
    up_v, dn_v = float(w.Volume[d > 0].sum()), float(w.Volume[d < 0].sum())
    ratio = up_v / dn_v if dn_v > 0 else float("inf")
    pts = 1 if ratio > 1.15 else -1 if ratio < 0.87 else 0
    f.append(("Volume", pts,
              f"Volume on up days was {ratio:.1f}x volume on down days ("
              + ("buyers are more active)." if pts == 1 else "sellers are more active)." if pts == -1
                 else "about balanced).") if ratio != float("inf") else "Volume was all on up days.",
              "More people have been trading on the days it rose than on the days it fell." if pts == 1 else
              "More people have been trading on the days it fell than on the days it rose." if pts == -1 else
              "Buying and selling activity have been about even."))

    hi = float(w.High.max())
    off = (hi - close) / hi * 100
    pts = 1 if off <= 5 else -1 if off >= 15 else 0
    f.append(("Distance from the 3-month high", pts,
              f"Price is {off:.1f}% below its 3-month high ({hi:.2f}).",
              "It is near the highest price of the last 3 months." if pts == 1 else
              "It is well below the highest price of the last 3 months." if pts == -1 else
              f"It is {off:.0f}% below the highest price of the last 3 months."))

    score = sum(x[1] for x in f)
    verdict = "BUY" if score >= 4 else "SELL" if score <= -3 else "HOLD"

    dist20 = (close / float(r.EMA20) - 1) * 100
    cautions = []
    extended = rsi > 75 or dist20 > 10
    if verdict == "BUY" and extended:
        verdict = "HOLD"
        cautions.append((f"Stretched: RSI {rsi:.0f}, {dist20:+.1f}% from the 20 EMA. The 3 months look strong, but "
                         "buying a stretched stock often means buying right before a pullback. Waiting for a dip is safer.",
                         "It has risen so fast that buying now means paying a high price. Waiting for a small dip is safer."))
    # ---- earnings cross-check
    e_lines, earn_wait, nd = [], False, None
    hold_days = int(round(p.max_hold * 7 / 5))   # trading days -> calendar days: how long the plan may hold a trade
    earn_inside = False
    if earnings:
        nd = earnings.get("next_days")
        avg = earnings.get("avg_abs_move")
        nd_date = earnings.get("next_date")
        if nd is not None:
            when = "today" if nd == 0 else "tomorrow" if nd == 1 else f"in {nd} days"
            ds = f" ({nd_date:%b %d})" if nd_date is not None else ""
            mv_t = f" Past reports moved this stock about {avg:.1f}% on average over two days." if avg else ""
            mv_p = f" After past reports it has moved about {avg:.0f}% in two days." if avg else ""
            if nd <= 7:
                e_lines.append((f"Next earnings report {when}{ds}. A report can gap the price straight past a stop.{mv_t}",
                                f"The company reports its earnings {when}{ds}. News like this can make the price jump over your "
                                f"safety exit (stop) overnight.{mv_p}"))
                if verdict == "BUY":
                    verdict, earn_wait = "HOLD", True
            elif nd <= hold_days:
                earn_inside = True
                e_lines.append((f"Next earnings report {when}{ds}. The plan holds a trade up to about {hold_days} days, so this trade "
                                f"would probably include the report. Plan to sell before it, or size smaller.{mv_t}",
                                f"The company reports earnings {when}{ds}. A swing trade can last up to about {hold_days} days, so the "
                                f"report would probably land while you own it. Sell before it, or buy less.{mv_p}"))
            else:
                e_lines.append((f"Next earnings report {when}{ds}, so it is not an immediate concern.{mv_t}",
                                f"The next earnings report is {when}{ds}, so it should not interfere with a short trade.{mv_p}"))
        else:
            e_lines.append(("Next earnings date unknown. Check it before buying (links below).",
                            "I could not find the next earnings date. Look it up before buying (links below)."))
        im = earnings.get("implied")
        if im and nd is not None and nd <= max(hold_days, 30):
            e_lines.append((f"Options traders are pricing in a move of roughly +/-{im['pct']:.0f}% around the report "
                            f"(from options expiring {im['expiry']:%b %d}; a rough guide that runs a little high).",
                            f"People who bet on options expect the price to move roughly {im['pct']:.0f}% up or down around the report. "
                            "That is a big swing for a small account."))
        reps = earnings.get("reports") or []
        if reps:
            x = reps[0]
            sur = x["surprise"]
            if x["est"] is not None:
                res_t = f"EPS {x['actual']:.2f} vs {x['est']:.2f} expected" + (f" ({sur:+.0f}%)" if sur is not None else "")
                verb = "beat" if (sur or 0) > 0 else "missed" if (sur or 0) < 0 else "matched"
                res_p = f"earned ${x['actual']:.2f} per share, which {verb} the ${x['est']:.2f} analysts expected"
            else:
                res_t, res_p = f"EPS {x['actual']:.2f}", f"earned ${x['actual']:.2f} per share"
            mv = x["move"]
            mt = f", and the stock moved {mv:+.1f}% over the two days around it" if mv is not None else ""
            mp = (f", and the stock {'rose' if mv > 0 else 'fell'} about {abs(mv):.0f}% in the two days around it"
                  if mv is not None else "")
            e_lines.append((f"Last report ({x['date']:%b %d}): {res_t}{mt}.",
                            f"On its last report ({x['date']:%b %d}) the company {res_p}{mp}."))
            if sur is not None and mv is not None and sur > 0 and mv < -2:
                e_lines.append(("It beat estimates but the stock still fell: the market was hoping for more, often better guidance.",
                                "The company did better than expected, yet the price still dropped. Investors wanted even more."))
            if earnings.get("of"):
                e_lines.append((f"It beat EPS estimates in {earnings['beats']} of its last {earnings['of']} reports.",
                                f"It beat what analysts expected in {earnings['beats']} of its last {earnings['of']} reports."))
    else:
        e_lines.append(("Earnings data was not available for this stock. Check the next report date yourself (links below).",
                        "I could not get earnings information for this stock. Look up the next report date yourself (links below)."))
        earnings = {}

    # ---- extra company event the user entered (trading update, investor day, ...)
    if extra_event and extra_event.get("days") is not None and extra_event["days"] >= 0:
        xd, xl = extra_event["days"], extra_event.get("label") or "company event"
        when = "today" if xd == 0 else "tomorrow" if xd == 1 else f"in {xd} days"
        if xd <= 7:
            e_lines.append((f"Your noted {xl} is {when}. Like earnings, it can gap the price past a stop.",
                            f"You noted a {xl} {when}. News like this can make the price jump over your safety exit (stop)."))
            if verdict == "BUY":
                verdict, earn_wait = "HOLD", True
        elif xd <= 14:
            e_lines.append((f"Your noted {xl} is {when}. Plan to be out or smaller before then.",
                            f"You noted a {xl} {when}. A swing trade lasts days, so it could land inside it."))
        else:
            e_lines.append((f"Your noted {xl} is {when}, not an immediate concern.",
                            f"You noted a {xl} {when}, so it should not interfere with a short trade."))
        nd = xd if (nd is None or xd < nd) else nd

    # ---- news check (can hold a BUY back, never creates one)
    n_lines, news_hold, n_flags = [], False, []
    manual = (news or {}).get("manual")
    news_bad = False
    if news is not None:
        n_flags = list(news.get("red_flags") or [])
        for fl in n_flags:
            n_lines.append((f"Red flag in the news ({fl['flag']}): \"{fl['title']}\". Why it matters: {fl['why']}",
                            f"Warning sign in the news ({fl['flag']}): \"{fl['title']}\". This matters because {fl['why']}"))
        rec, lean = news.get("recent", 0), news.get("lean", "unclear")
        g, b = news.get("good", 0), news.get("bad", 0)
        if news.get("feed_empty"):
            n_lines.append(("Yahoo returned no headlines at all for this symbol, so the app can't judge the news. This is common for foreign "
                            "or OTC stocks. Use the Claude buttons below to have Claude search for it.",
                            "The app could not find any news for this stock. That is common for foreign companies. Use the Claude buttons "
                            "below and ask Claude to look for news."))
        elif rec == 0 and news.get("recent_all", 0) > 0:
            n_lines.append((f"{news['recent_all']} headline(s) this week, but none were real news about this company (lists, market "
                            "blurbs or other companies), so they are ignored. The news is unknown, not quiet. Use the Claude buttons.",
                            f"There were {news['recent_all']} news item(s) this week, but none were really about this company (they were "
                            "lists, market summaries or other companies). So I do not know the news. Use the Claude buttons below."))
        elif rec == 0:
            n_lines.append(("No headlines in the last 7 days, so the news adds nothing either way.",
                            "There has been no news this past week, so it adds nothing either way."))
        elif not news.get("enough"):
            n_lines.append((f"Only {rec} headline(s) in the last 7 days. That is too few to judge the mood, so the news "
                            "tone does not affect the verdict (red flags still do).",
                            f"There are only {rec} news story(ies) from this week. That is too few to tell whether the news "
                            "is good or bad, so I am not counting it."))
        elif lean == "positive":
            n_lines.append((f"Recent news leans positive ({g} good, {b} bad out of {rec} headlines this week). Good news can "
                            "support a BUY but never creates one on its own.",
                            f"Most of this week's news is good ({g} good, {b} bad out of {rec}). That helps, but it is not a "
                            "reason to buy by itself."))
        elif lean == "negative":
            n_lines.append((f"Recent news leans negative ({b} bad, {g} good out of {rec} headlines this week).",
                            f"Most of this week's news is bad ({b} bad, {g} good out of {rec}), which is a reason to be careful."))
        else:
            n_lines.append((f"Recent news is mixed or neutral ({g} good, {b} bad out of {rec} headlines this week).",
                            f"This week's news is a mix, or not very important ({g} good, {b} bad out of {rec})."))
        for t in (news.get("event_hints") or [])[:2]:
            n_lines.append((f"A headline hints at a scheduled company event: \"{t}\". Find the date. It can move the price like earnings.",
                            f"A news story mentions an upcoming company event: \"{t}\". Find out the date, because it can make the price jump."))
        ign = news.get("skipped_list", 0) + news.get("skipped_other", 0)
        if ign and rec:
            n_lines.append((f"{ign} other headline(s) this week were lists, market blurbs or about other companies, and were not counted.",
                            f"{ign} other news item(s) were lists, summaries or about other companies, so I did not count them."))
        if lean == "negative" and news.get("enough"):
            news_bad = True
        n_lines.append(("Tags come from keywords, so they can misread a headline. Read the stories, or use the Claude buttons "
                        "below, and set your own call.",
                        "The good/bad labels are only rough guesses from certain words. Read the stories, or ask Claude with the "
                        "buttons below, and make your own call."))
    if manual in ("good", "neutral", "bad"):
        n_lines.append({"good": ("You marked the news as GOOD. It supports the chart but does not turn a HOLD into a BUY.",
                                 "You marked the news as good. That helps, but it does not make this a buy by itself."),
                        "neutral": ("You marked the news as NEUTRAL.", "You marked the news as neutral."),
                        "bad": ("You marked the news as BAD, so a BUY is held back to HOLD.",
                                "You marked the news as bad, so I am holding back the buy signal.")}[manual])
    if manual == "bad":
        news_bad = True
    if verdict == "BUY" and (n_flags or news_bad):
        verdict, news_hold = "HOLD", True
        cautions.append(("News is holding this BUY back. Find out what the story is before you put money in.",
                         "The news has a warning in it, so I am holding back the buy signal until you know what the story is."))

    if earn_inside and verdict == "BUY":
        cautions.append((f"This trade would likely be open during the earnings report ({nd} days away). A gap can jump straight over "
                         "your stop, so consider half size or plan to sell before the report.",
                         f"The company reports earnings in {nd} days, probably while you own the stock. The price can jump past your "
                         "safety exit, so buy less or plan to sell before the report."))
    setups = [STYLE[k]["label"] for k in ("pullback", "breakout", "bounce")
              if bool(flags[k].iloc[-1]) and bool(flags["filters_ok"].iloc[-1])]
    if verdict == "BUY" and setups:
        cautions.append((f"A swing setup is flagged today ({', '.join(setups)}), which gives a specific entry idea.",
                         "The scanner also sees a specific entry pattern today, which supports the idea."))
    elif verdict == "BUY":
        cautions.append(("No swing setup is flagged today. The trend is strong, but a pullback to the 20 EMA "
                         f"({float(r.EMA20):.2f}) often gives a better price.",
                         "The trend is strong, but there is no clean entry pattern today. A small dip first often gives a better price."))
    if verdict != "BUY" and setups:
        cautions.append((f"A {', '.join(setups)} setup is flagged today, but the 3-month picture does not back it up, "
                         "so setups like this fail more often.",
                         "The scanner sees an entry pattern, but the bigger picture is not strong, so be extra careful."))
    atr = float(flags["atr"].iloc[-1]) if "atr" in flags else float("nan")
    if atr == atr and atr / close * 100 > 6:
        cautions.append((f"Big daily swings (about {atr / close * 100:.1f}% a day). Use smaller position sizes.",
                         "This stock jumps around a lot each day, so risk less money on it."))
    if news is None:
        cautions.append(("The score uses price, volume and trend. Earnings dates come from Yahoo and can be estimates, "
                         "and news is not included, so confirm the date on the company's site and use the Scanner's catalyst check.",
                         "The score only looks at the price chart. Earnings dates come from Yahoo and can be estimates, and it does "
                         "not read company news, so double-check both."))
    else:
        cautions.append(("The score itself uses price, volume and trend only. Earnings dates come from Yahoo and can be estimates. "
                         "News can hold a BUY back but never adds to the score; confirm dates and stories on the company's site.",
                         "The score itself only looks at the price chart. News can only hold a buy back, it never adds points. "
                         "Earnings dates can be estimates, so double-check them."))

    ema20, ema200 = float(r.EMA20), float(r.EMA200)
    if news_hold and not earn_wait:
        change = ("Reconsider once you know what the news is about and it looks resolved or harmless (or you change your news call).",
                  "Look again once you understand the news story and it no longer looks like a problem.")
    elif earn_wait:
        change = ("Reconsider after the earnings report, once you can see how the price reacts and whether the trend holds.",
                  "Look again after the earnings report, when you can see how the price reacted.")
    elif verdict == "BUY":
        change = (f"Would weaken if it closes below the 20 EMA ({ema20:.2f}), and more so below the 200 EMA ({ema200:.2f}).",
                  f"It would look weaker if the price drops under {ema20:.2f}, and much weaker under {ema200:.2f}.")
    elif verdict == "SELL":
        change = (f"Would improve if it closes back above the 20 EMA ({ema20:.2f}), then the 200 EMA ({ema200:.2f}).",
                  f"It would look better if the price climbs back above {ema20:.2f}, and better still above {ema200:.2f}.")
    elif extended:
        change = (f"Would turn into a BUY on a pullback toward the 20 EMA ({ema20:.2f}) with RSI cooling below 70.",
                  f"It could become a buy after a small dip toward {ema20:.2f}.")
    else:
        change = (f"Would turn into a BUY if momentum builds: price above the 20 EMA ({ema20:.2f}), higher highs, and more volume on up days.",
                  "It could become a buy if the stock starts climbing steadily again with more people buying.")

    levels = None
    if atr == atr and atr > 0 and verdict != "SELL":
        stop = close - p.stop_atr_mult * atr
        levels = {"stop": stop, "target": close + p.reward_risk * (close - stop)}

    held = []
    if holding and holding.get("avg"):
        pl = (close / holding["avg"] - 1) * 100
        stp = holding.get("stop")
        base = f"You own it: entry {holding['avg']:.2f}, now {close:.2f} ({pl:+.1f}%)" + (f", stop {stp:.2f}." if stp else ", no stop recorded.")
        base_plain = (f"You own this stock. You paid {holding['avg']:.2f} and it is {close:.2f} now "
                      f"({'up' if pl >= 0 else 'down'} {abs(pl):.1f}%).")
        if nd is not None and nd <= 7:
            held.append((f"You hold it into earnings (report {'today' if nd == 0 else f'in {nd} day(s)'}). Decide ahead of time: "
                         "sell before, trim to a smaller size, or accept that a stop may not protect you from a gap.",
                         "The company reports earnings very soon while you own the stock. Decide now: sell before, hold less, "
                         "or accept that the price could jump past your safety exit."))
        if n_flags or news_bad:
            held.append(("You own it and the news has a warning in it. Read the story, check that your stop order is in place, "
                         "and decide whether to sell or tighten the stop.",
                         "You own this stock and the news has a warning sign. Read the story, make sure your safety exit (stop) is set, "
                         "and decide whether to sell or move the stop up."))
        if verdict == "SELL":
            held.append((base + " The 3-month picture has turned weak. Check that your stop order is in place and whether the reason you bought still holds.",
                         base_plain + " The bigger picture has turned weak, so make sure your safety exit (stop) is set and ask whether your reason for buying still holds."))
        else:
            held.append((base + " Nothing here says to sell. Keep your stop in place.",
                         base_plain + " Nothing here says to sell. Keep your safety exit (stop) in place."))

    strength = "Strong" if abs(score) >= 6 else "Moderate" if abs(score) >= 4 else "Mixed"
    heads = {
        "BUY": ("The last 3 months show a healthy uptrend with momentum and volume behind it.",
                "Looks like a decent time to buy. Over the last 3 months it has been climbing steadily, and real buying is behind it."),
        "HOLD": (("Strong 3 months, but there is a warning in the news. Find out what it is before buying." if (news_hold and not earn_wait) else
                  "Strong 3 months, but earnings are very close. A report can gap the price past any stop, so waiting until "
                  "after it is safer." if earn_wait else
                  "Strong 3 months, but it is stretched right now. Better to wait for a dip than to chase it." if extended else
                  "The 3-month picture is mixed, so there is no clear edge right now."),
                 ("It has done well, but the news has a warning sign. Understand the story first." if (news_hold and not earn_wait) else
                  "It has done well, but the company reports earnings very soon, and the price can jump either way. "
                  "Waiting until after the report is safer." if earn_wait else
                  "It has done well, but it has run up fast. Waiting for a small dip is safer than buying now." if extended else
                  "The signals are mixed, so there is no clear reason to act right now.")),
        "SELL": ("The 3-month trend has weakened: falling price, weak momentum and sellers in control.",
                 "The stock has been getting weaker for 3 months. It is not a good time to buy, and owners should be careful."),
    }
    sub = {
        "BUY": ("Looks like a good entry.", "Good moment to look at buying."),
        "HOLD": ("Not a clear entry: wait. If you own it, keep holding.", "Not a clear buy yet, so wait. If you already own it, keep holding."),
        "SELL": ("Weak: avoid buying. If you own it, consider selling.", "Weak: do not buy. If you own it, think about selling."),
    }
    stats = (f"Last 3 months: {chg:+.1f}%, high {hi:.2f} ({w.High.idxmax():%b %d}), low {float(w.Low.min()):.2f} "
             f"({w.Low.idxmin():%b %d}), now {close:.2f}.")
    return {"verdict": verdict, "score": int(score), "max": 8, "strength": strength,
            "headline": heads[verdict][0], "headline_plain": heads[verdict][1],
            "sub": sub[verdict][0], "sub_plain": sub[verdict][1], "stats": stats,
            "factors": [{"name": n, "points": int(pt), "tech": t, "plain": pl} for n, pt, t, pl in f],
            "cautions": cautions, "change": change, "levels": levels, "holding": held, "extended": extended,
            "earnings_lines": e_lines, "news_lines": n_lines, "news_hold": news_hold, "earn_wait": earn_wait, "earn_inside": earn_inside, "hold_days": hold_days, "next_earnings_days": nd,
            "earnings_reports": earnings.get("reports", []) if earnings else []}

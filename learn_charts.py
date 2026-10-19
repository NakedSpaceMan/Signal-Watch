"""
learn_charts.py - practice charts for the Learn tab.

Every chart here is MADE UP by the app, never a real stock. That is on purpose: it lets us
guarantee a clean, textbook example of each pattern, with every level marked, and lets you
practice as often as you like without risking money.

What makes the practice honest:
  * The chart is built in two halves. The first half (what you see when you decide) has the
    pattern. The second half (what happens next) is generated separately.
  * The second half is chosen to WIN or LOSE at random (a bit under or over half the time, about
    like real setups) and the result is then checked by actually simulating the trade with the
    stop and target. So when the screen says "stopped out", the simulation really did stop you out.
  * Patterns can fail. A flag can be a fake-out. A breakout can fall back into its base. That is part
    of what you are learning.

Plotly is only imported when a figure is drawn.
"""

from functools import lru_cache

import numpy as np
import pandas as pd

HIST_MIN = 70
FUT_BARS = 20
MAX_HOLD = 15
KINDS = ["range", "bounce", "breakout", "pullback", "flag", "triangle", "none"]
SUCCESS_P = {"range": 0.55, "bounce": 0.45, "breakout": 0.5, "pullback": 0.55, "flag": 0.55,
             "triangle": 0.5}
PRACTICE_WEIGHTS = {"range": 0.12, "bounce": 0.15, "breakout": 0.17, "pullback": 0.17, "flag": 0.12,
                    "triangle": 0.12, "none": 0.15}
NAMES = {"range": "Support and resistance (range)", "bounce": "Bounce off support", "breakout": "Breakout",
         "pullback": "Pullback in an uptrend", "flag": "Bull flag", "triangle": "Ascending triangle",
         "none": "No setup"}

GREEN, RED = "#26a69a", "#ef5350"
SUPPORT_C, RESIST_C, STOP_C, TARGET_C, ENTRY_C, TREND_C = (
    "#66bb6a", "#ef5350", "#ff5252", "#69f0ae", "#4fc3f7", "#ffd54f")


# ------------------------------------------------------------------ building blocks
def _ar_noise(rng, n, sigma, phi=0.4):
    z = rng.normal(0, 1, n)
    if n < 4:                      # too short to normalise; just scale it
        return z * sigma
    e = np.zeros(n)
    for i in range(n):
        e[i] = (phi * e[i - 1] if i else 0.0) + z[i]
    sd = e.std()
    return e * (sigma / sd) if sd > 0 else e


def _path(start, legs, rng, sigma):
    """Piecewise-straight route through (bars, end_price) legs, with wobble so it looks like trading."""
    parts, cur = [], start
    for bars, end in legs:
        parts.append(np.linspace(cur, end, int(bars) + 1)[1:])
        cur = end
    base = np.concatenate(parts)
    return base * (1 + _ar_noise(rng, len(base), sigma))


def _candles(close, rng, sigma, first_open):
    n = len(close)
    o = np.empty(n)
    o[0] = first_open
    o[1:] = close[:-1] * (1 + rng.normal(0, sigma * 0.35, n - 1))
    hi = np.maximum(o, close) * (1 + np.abs(rng.normal(0, sigma * 0.6, n)))
    lo = np.minimum(o, close) * (1 - np.abs(rng.normal(0, sigma * 0.6, n)))
    return o, hi, lo


def _vol(rng, n, mult=1.0, base=1_000_000.0):
    return base * np.exp(rng.normal(0, 0.25, n)) * np.asarray(mult, dtype=float)


def _fix(o, h, l, c):
    h = np.maximum(h, np.maximum(o, c))
    l = np.minimum(l, np.minimum(o, c))
    return o, h, l, c


def _seg(rng, start, legs, s, vmult=1.0):
    close = _path(start, legs, rng, s)
    o, h, l = _candles(close, rng, s, start)
    return {"o": o, "h": h, "l": l, "c": close, "v": _vol(rng, len(close), vmult)}


def _cat(*segs):
    return {k: np.concatenate([g[k] for g in segs]) for k in ("o", "h", "l", "c", "v")}


def _atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return float(tr[-n:].mean())


def _money(x):
    return f"${x:,.2f}"


def _line(x0, y0, x1, y1, label, color=TREND_C, dash="solid"):
    return {"x0": x0, "y0": float(y0), "x1": x1, "y1": float(y1), "label": label, "color": color, "dash": dash}


# ------------------------------------------------------------------ pattern generators
# Each returns the visible half (arrays o,h,l,c,v) plus the markup and the plan levels.
def _gen_range(rng, s):
    S = rng.uniform(25, 120)
    R = S * (1 + rng.uniform(0.11, 0.16))
    leg = int(rng.integers(8, 12))
    legs = [(6, R), (leg, S), (leg, R), (leg, S), (leg, R), (leg, S), (2, S * 1.02)]
    ends = np.cumsum([b for b, _ in legs]) - 1
    mid = (S + R) / 2
    lead = _path(mid, [(20, mid * (1 + rng.uniform(-0.01, 0.01)))], rng, s)   # a quiet stretch before the range
    legs[0] = (6, R)
    close = np.concatenate([lead, np.clip(_path(lead[-1], legs, rng, s), S * 1.003, R * 0.997)])
    ends = ends + 20
    o, h, l = _candles(close, rng, s, mid)
    h = np.minimum(h, R * 1.003)
    l = np.maximum(l, S * 0.997)
    for i in (ends[0], ends[2], ends[4]):
        h[i] = R * (1 + rng.uniform(-0.002, 0.002))
    for i in (ends[1], ends[3], ends[5]):
        l[i] = S * (1 + rng.uniform(-0.002, 0.002))
    if close[-1] <= o[-1]:
        o[-1] = close[-1] * 0.993
    o, h, l, c = _fix(o, h, l, close)
    v = _vol(rng, len(c), 1.0)
    atr = _atr(h, l, c)
    pts = [(int(ends[i]), R, f"{n}") for n, i in ((1, 0), (3, 2), (5, 4))]
    pts += [(int(ends[i]), S, f"{n}") for n, i in ((2, 1), (4, 3), (6, 5))]
    return {
        "arr": {"o": o, "h": h, "l": l, "c": c, "v": v},
        "levels": [dict(y=R, label=f"Resistance {_money(R)}", color=RESIST_C, dash="dash"),
                   dict(y=S, label=f"Support {_money(S)}", color=SUPPORT_C, dash="dash")],
        "zones": [(R * 0.996, R * 1.004, RESIST_C), (S * 0.996, S * 1.004, SUPPORT_C)],
        "points": [dict(x=i, y=y, text=t, color="#ffffff") for i, y, t in sorted(pts)],
        "lines": [],
        "stop": S - 0.6 * atr, "target": R * 0.985,
        "notes": [
            f"Support {_money(S)} (green): price fell to this level and turned back up 3 times (points 2, 4, 6). "
            "Buyers keep stepping in here.",
            f"Resistance {_money(R)} (red): price rose to this level and turned back down 3 times (points 1, 3, 5). "
            "Sellers keep stepping in here.",
            "The more times a level holds, the more traders watch it, and the more it tends to hold again, until it doesn't.",
            f"The last candle just bounced off support. The plan buys the next open, with the stop a little BELOW "
            f"support ({_money(S - 0.6 * atr)}): if price breaks support, the idea was wrong and you want out.",
            f"The target sits just under resistance ({_money(R * 0.985)}), where sellers have appeared before.",
        ]}


def _gen_bounce(rng, s):
    S = rng.uniform(25, 120)
    H = S * rng.uniform(1.16, 1.24)
    legs_a = [(5, S * 0.998), (4, S * 1.04), (3, S * 1.0)]                      # the base that makes support
    legs_b = [(18, H), (8, H * 0.985), (24, S * 1.006)]                           # rally, top, then the sell-off
    pre = _seg(rng, S * 1.03, [(14, S * 1.03)], s, 1.0)
    a = _seg(rng, pre["c"][-1], legs_a, s, 1.0)
    b = _seg(rng, a["c"][-1], legs_b, s, [1.0] * 18 + [0.9] * 8 + list(np.linspace(1.1, 1.7, 24)))
    last2 = _seg(rng, b["c"][-1], [(1, S * 1.0)], s, 1.8)
    ham = _seg(rng, last2["c"][-1], [(1, S * 1.016)], s, 2.3)
    arr = _cat(pre, a, b, last2, ham)
    n = len(arr["c"])
    # shape the last two candles: a probe of support, then a hammer (long lower wick, closes near the high)
    arr["l"][-2] = min(arr["l"][-2], S * 0.994)
    arr["o"][-1], arr["c"][-1] = S * 1.003, S * 1.016
    arr["l"][-1] = S * 0.985
    arr["h"][-1] = S * 1.019
    o, h, l, c = _fix(arr["o"], arr["h"], arr["l"], arr["c"])
    arr.update(o=o, h=h, l=l, c=c)
    atr = _atr(h, l, c)
    base_i = [len(pre["c"]) + 4, len(pre["c"]) + 11]
    stop = float(l[-1]) - 0.5 * atr
    return {
        "arr": arr,
        "levels": [dict(y=S, label=f"Support {_money(S)}", color=SUPPORT_C, dash="dash")],
        "zones": [(S * 0.993, S * 1.007, SUPPORT_C)],
        "points": [dict(x=base_i[0], y=S, text="1", color="#ffffff"), dict(x=base_i[1], y=S, text="2", color="#ffffff"),
                   dict(x=n - 1, y=float(l[-1]), text="3", color="#ffffff")],
        "lines": [_line(len(pre["c"]) + 12, H, n - 3, S * 1.006, "Sell-off", RESIST_C, "dot")],
        "stop": stop, "target": None,
        "notes": [
            f"Support {_money(S)}: early on, price based here and turned up (points 1 and 2). That makes it a level traders remember.",
            "Then the stock rallied, topped out, and sold off hard back to the same level. Fast sell-offs push a stock into oversold "
            "territory, where sellers run out of steam.",
            f"Point 3 is a 'hammer' candle: it dipped below support (long lower wick), then buyers pushed it back up to close near "
            f"the high. That says sellers tried and failed.",
            f"The plan buys the next open. The stop goes under the hammer's low ({_money(stop)}): if price makes a new low below the "
            "hammer, the bounce failed and you leave.",
        ]}


def _gen_breakout(rng, s):
    R = rng.uniform(25, 120)
    ctx = _seg(rng, R * 0.72, [(40, R * 0.95)], s, 1.0)
    legs = [(4, R * 0.935), (5, R), (6, R * 0.94), (5, R), (5, R * 0.945), (5, R), (4, R * 0.96)]
    base = _seg(rng, ctx["c"][-1], legs, s * 0.9, 0.7)
    ends = np.cumsum([b for b, _ in legs]) - 1
    off = len(ctx["c"])
    n0 = off + len(base["c"])
    for i in (ends[1], ends[3], ends[5]):
        base["c"][i] = min(base["c"][i], R * 0.998)
        base["h"][i] = R * (1 + rng.uniform(-0.002, 0.002))
    base["c"] = np.minimum(base["c"], R * 0.998)
    base["h"] = np.minimum(base["h"], R * 1.003)
    bo = _seg(rng, base["c"][-1], [(1, R * 1.03)], s, 3.0)
    bo["o"][0], bo["c"][0] = R * 1.0, R * 1.03
    bo["l"][0], bo["h"][0] = R * 0.998, R * 1.034
    arr = _cat(ctx, base, bo)
    o, h, l, c = _fix(arr["o"], arr["h"], arr["l"], arr["c"])
    arr.update(o=o, h=h, l=l, c=c)
    atr = _atr(h, l, c)
    stop = R - 0.5 * atr
    n = len(c)
    return {
        "arr": arr,
        "levels": [dict(y=R, label=f"Resistance {_money(R)}", color=RESIST_C, dash="dash")],
        "zones": [(R * 0.996, R * 1.004, RESIST_C)],
        "points": [dict(x=off + int(ends[i]), y=R, text=t, color="#ffffff") for i, t in ((1, "1"), (3, "2"), (5, "3"))]
        + [dict(x=n - 1, y=float(h[-1]), text="4", color="#ffffff")],
        "lines": [],
        "stop": stop, "target": None,
        "notes": [
            f"Resistance {_money(R)}: price pushed up to this level and got turned back 3 times (points 1 to 3), "
            "while the dips got shallower. Sellers are running out.",
            "During the base, volume was quiet (bars at the bottom). Calm before the move.",
            f"Point 4 is the breakout: a strong candle CLOSING above resistance, with volume about 3 times normal. "
            "Heavy volume says real buyers showed up, not just a blip.",
            f"The plan buys the next open. The stop goes just under the old resistance ({_money(stop)}): once price is above a "
            "level, that level should act as support. If it falls back below, the breakout failed.",
        ]}


def _gen_pullback(rng, s):
    for _ in range(80):
        P = rng.uniform(25, 120)
        legs = [(18, P * 1.10), (4, P * 1.075), (16, P * 1.20), (5, P * 1.17), (16, P * 1.30), (5, P * 1.275),
                (12, P * 1.40)]
        d = rng.uniform(0.045, 0.085)
        peak = P * 1.40
        up = _seg(rng, P, legs, s, 1.0)
        dip = _seg(rng, up["c"][-1], [(int(rng.integers(5, 8)), peak * (1 - d))], s, 0.75)
        back = _seg(rng, dip["c"][-1], [(1, dip["c"][-1] * 1.014)], s, 1.5)
        arr = _cat(up, dip, back)
        o, h, l, c = _fix(arr["o"], arr["h"], arr["l"], arr["c"])
        if c[-1] <= o[-1]:
            o[-1] = c[-1] * 0.994
            o, h, l, c = _fix(o, h, l, c)
        ema = pd.Series(c).ewm(span=20, adjust=False).mean().to_numpy()
        dip_low = float(l[-6:-1].min())
        if (dip_low <= ema[-1] * 1.015 and dip_low >= ema[-1] * 0.96 and c[-1] >= ema[-1] * 0.99
                and ema[-1] > ema[-6] and c[-1] > h[-2] * 0.995):
            break
    arr.update(o=o, h=h, l=l, c=c)
    atr = _atr(h, l, c)
    stop = dip_low - 0.5 * atr
    n = len(c)
    lo_i = n - 6 + int(np.argmin(l[-6:-1]))
    return {
        "arr": arr, "levels": [], "zones": [],
        "points": [dict(x=int(np.argmax(h[: n - 4])), y=float(h[: n - 4].max()), text="1", color="#ffffff"),
                   dict(x=lo_i, y=dip_low, text="2", color="#ffffff"),
                   dict(x=n - 1, y=float(c[-1]), text="3", color="#ffffff")],
        "lines": [], "stop": stop, "target": None,
        "notes": [
            "The stock is in an uptrend: higher highs and higher lows, with the orange 20-day line (EMA 20) rising underneath.",
            "Point 1 is the latest high. Then price pulled back (dipped) for several days on lighter volume. Quiet dips in an "
            "uptrend are usually profit-taking, not panic.",
            f"Point 2: the dip stopped right at the 20-day line, a spot where buyers often step in. The low was {_money(dip_low)}.",
            "Point 3: a green candle that closes above the previous day's high. That is the sign buyers are back, and your trigger to buy.",
            f"The stop goes just under the dip's low ({_money(stop)}): if price goes below the dip the trend may be over.",
        ]}


def _gen_flag(rng, s):
    F = rng.uniform(25, 120)
    pre = _seg(rng, F * 0.92, [(46, F * 1.02)], s, 1.0)
    pole = _seg(rng, pre["c"][-1], [(7, F * 1.02 * 1.26)], s * 0.55, 2.0)
    T = float(pole["c"][-1])
    nf = int(rng.integers(10, 13))
    t = np.arange(1, nf + 1)
    centre = T * (1 - 0.012) - T * 0.065 * t / nf
    upper_f, lower_f = centre + 0.016 * T, centre - 0.016 * T
    close = np.clip(centre + _ar_noise(rng, nf, 0.006 * T), centre - 0.011 * T, centre + 0.011 * T)
    o, h, l = _candles(close, rng, s * 0.8, T)
    h = np.minimum(h, upper_f + 0.002 * T)
    l = np.maximum(l, lower_f - 0.002 * T)
    o, h, l, c = _fix(o, h, l, close)
    flag = {"o": o, "h": h, "l": l, "c": c, "v": _vol(rng, nf, np.linspace(0.8, 0.45, nf))}
    ub = float(upper_f[-1] - (upper_f[0] - upper_f[-1]) / (nf - 1))
    bo = _seg(rng, c[-1], [(1, ub * 1.025)], s, 2.6)
    bo["o"][0], bo["c"][0] = ub * 0.998, ub * 1.025
    bo["h"][0], bo["l"][0] = bo["c"][0] * 1.006, ub * 0.995
    arr = _cat(pre, pole, flag, bo)
    o, h, l, c = _fix(arr["o"], arr["h"], arr["l"], arr["c"])
    arr.update(o=o, h=h, l=l, c=c)
    atr = _atr(h, l, c)
    f0 = len(pre["c"]) + len(pole["c"])
    n = len(c)
    flag_low = float(l[f0:n - 1].min())
    stop = flag_low - 0.5 * atr
    pole_pct = (T / float(pre["c"][-1]) - 1) * 100
    return {
        "arr": arr, "levels": [], "zones": [],
        "points": [dict(x=f0 - 4, y=float(h[f0 - 4]), text="1", color="#ffffff"),
                   dict(x=f0 + nf // 2, y=float(upper_f[nf // 2]), text="2", color="#ffffff"),
                   dict(x=n - 1, y=float(h[-1]), text="3", color="#ffffff")],
        "lines": [_line(f0 - 0.5, upper_f[0] + (upper_f[0] - upper_f[-1]) / nf, n - 1,
                        upper_f[-1] - (upper_f[0] - upper_f[-1]) / (nf - 1), "Flag top", TREND_C),
                  _line(f0 - 0.5, lower_f[0] + (lower_f[0] - lower_f[-1]) / nf, n - 2, lower_f[-1], "Flag bottom", TREND_C)],
        "stop": stop, "target": None,
        "notes": [
            f"Point 1: the 'pole'. A fast, strong run up of about {pole_pct:.0f}% in a week, on heavy volume. That shows big buying interest.",
            "Point 2: the 'flag'. Price drifts down in a tight, sloping channel (the yellow lines) on shrinking volume. This is a "
            "pause where early buyers take a little profit, not a reversal.",
            "Point 3: price breaks above the top of the flag on rising volume. That says the pause is over and buyers are back in charge.",
            f"The stop goes under the flag's low ({_money(stop)}). If price falls back through the whole flag, the pattern failed.",
            "Textbook note: some traders aim for the pole's height added to the breakout. This lesson uses a simpler 2-to-1 target.",
        ]}


def _gen_triangle(rng, s):
    R = rng.uniform(25, 120)
    ctx = _seg(rng, R * 0.70, [(42, R * 0.93)], s, 1.0)
    nt = 40
    L = lambda t: R * (0.915 + 0.053 * t / (nt - 1))  # rising floor of the triangle
    lens = [5, 6, 6, 6, 5, 5, 5, 2]
    ends_t = np.cumsum(lens) - 1
    legs = [(5, R), (6, L(ends_t[1])), (6, R), (6, L(ends_t[3])), (5, R), (5, L(ends_t[5])), (5, R), (2, R * 0.992)]
    tri = _seg(rng, ctx["c"][-1], legs, s * 0.85, np.linspace(1.0, 0.55, nt))
    off = len(ctx["c"])
    tt = np.arange(nt)
    tri["c"] = np.clip(tri["c"], L(tt) * 1.003, R * 0.997)
    tri["h"] = np.minimum(tri["h"], R * 1.003)
    tri["l"] = np.maximum(tri["l"], L(tt) * 0.997)
    for i in (ends_t[0], ends_t[2], ends_t[4], ends_t[6]):
        tri["h"][i] = R * (1 + rng.uniform(-0.002, 0.002))
    for i in (ends_t[1], ends_t[3], ends_t[5]):
        tri["l"][i] = L(i) * (1 + rng.uniform(-0.002, 0.002))
    bo = _seg(rng, tri["c"][-1], [(1, R * 1.03)], s, 2.8)
    bo["o"][0], bo["c"][0] = R * 0.998, R * 1.03
    bo["l"][0], bo["h"][0] = R * 0.995, R * 1.034
    arr = _cat(ctx, tri, bo)
    o, h, l, c = _fix(arr["o"], arr["h"], arr["l"], arr["c"])
    arr.update(o=o, h=h, l=l, c=c)
    n = len(c)
    stop = R * 0.975
    lows = [(off + int(ends_t[i]), float(L(ends_t[i]))) for i in (1, 3, 5)]
    return {
        "arr": arr,
        "levels": [dict(y=R, label=f"Flat top {_money(R)}", color=RESIST_C, dash="dash")],
        "zones": [(R * 0.996, R * 1.004, RESIST_C)],
        "points": [dict(x=off + int(ends_t[i]), y=R, text=t, color="#ffffff") for i, t in ((0, "1"), (2, "2"), (4, "3"), (6, "4"))]
        + [dict(x=n - 1, y=float(h[-1]), text="5", color="#ffffff")],
        "lines": [_line(lows[0][0], lows[0][1], n - 1, float(L(nt - 1 + 2)), "Rising floor", TREND_C)],
        "stop": stop, "target": None,
        "notes": [
            f"The top is flat: price hits {_money(R)} again and again (points 1 to 4) and gets turned back. Sellers are defending it.",
            "But the lows keep getting HIGHER (yellow line). Each dip, buyers step in earlier. Buyers are pushing, sellers are holding the line.",
            "The squeeze: the space between the two lines narrows and volume dries up. Pressure builds like a spring.",
            f"Point 5: price closes above the flat top on heavy volume, the release of the spring. Ascending triangles break up "
            "more often than down, but not always.",
            f"The stop goes back inside the pattern, below the old top ({_money(stop)}). If price falls back in, it was a false breakout.",
        ]}


def _gen_none(rng, s):
    P = rng.uniform(25, 120)
    legs, cur = [], P
    left = 84
    while left > 0:
        b = int(min(left, rng.integers(5, 12)))
        cur = P * (1 + rng.uniform(-0.06, 0.06))
        legs.append((b, cur))
        left -= b
    seg = _seg(rng, P, legs, s * 1.15, 1.0)
    o, h, l, c = _fix(seg["o"], seg["h"], seg["l"], seg["c"])
    seg.update(o=o, h=h, l=l, c=c)
    atr = _atr(h, l, c)
    return {
        "arr": seg, "levels": [], "zones": [], "points": [], "lines": [],
        "stop": float(c[-1]) - 2 * atr, "target": None,
        "notes": [
            "No level has been tested over and over. No clean trend. No tight squeeze. No burst of volume.",
            "Price is drifting in the middle of nowhere, which is the worst place to buy: no nearby level to put a stop behind, "
            "so your stop is a guess.",
            "Not every chart is a trade. Waiting is a position too, and it protects your small account from small cuts.",
        ]}


GEN = {"range": _gen_range, "bounce": _gen_bounce, "breakout": _gen_breakout, "pullback": _gen_pullback,
       "flag": _gen_flag, "triangle": _gen_triangle, "none": _gen_none}

# how a winning / losing second half behaves, as a fraction of the risk distance
FUT = {"range": dict(dip=0.25, up=0.0, k2=(8, 13)), "bounce": dict(dip=0.25, up=0.0, k2=(6, 11)),
       "breakout": dict(dip=0.40, up=0.35, k2=(6, 11)), "pullback": dict(dip=0.30, up=0.0, k2=(6, 11)),
       "flag": dict(dip=0.30, up=0.30, k2=(6, 11)), "triangle": dict(dip=0.30, up=0.30, k2=(6, 11))}


def _future(rng, entry, stop, target, success, s, kind, vol_base):
    risk = entry - stop
    pr = FUT.get(kind)
    if kind == "none" or pr is None:
        legs = [(5, entry * (1 + rng.normal(0, 0.03))) for _ in range(FUT_BARS // 5)]
    elif success:
        k1, k2 = int(rng.integers(2, 5)), int(rng.integers(*pr["k2"]))
        legs = [(k1, entry - pr["dip"] * risk), (k2, target + 0.35 * risk),
                (max(FUT_BARS - k1 - k2, 1), target + 0.35 * risk)]
    else:
        f1, f2 = int(rng.integers(1, 3)), int(rng.integers(3, 6))
        legs = [(f1, entry + pr["up"] * risk), (f2, stop - 0.9 * risk), (max(FUT_BARS - f1 - f2, 1), stop - 1.2 * risk)]
    close = _path(entry, legs, rng, s)
    o, h, l = _candles(close, rng, s, entry)
    o, h, l, c = _fix(o, h, l, close)
    return {"o": o, "h": h, "l": l, "c": c, "v": _vol(rng, len(c), 1.0, base=vol_base)}


def simulate_plan(fut, entry, stop, target, max_hold=MAX_HOLD):
    """Walk forward bar by bar. If one bar touches both stop and target, the stop counts first (the cautious way)."""
    o, h, l, c = (np.asarray(fut[k], float) for k in ("Open", "High", "Low", "Close"))
    risk = entry - stop
    if risk <= 0 or len(c) == 0:
        return {"reason": "No trade", "bar": 0, "exit": entry, "r": 0.0, "win": False}
    n = min(len(c), max_hold)
    for k in range(n):
        if k > 0 and o[k] <= stop:
            return {"reason": "Stop (gap)", "bar": k, "exit": float(o[k]), "r": (o[k] - entry) / risk, "win": False}
        if l[k] <= stop:
            return {"reason": "Stop", "bar": k, "exit": float(stop), "r": -1.0, "win": False}
        if k > 0 and o[k] >= target:
            return {"reason": "Target (gap)", "bar": k, "exit": float(o[k]), "r": (o[k] - entry) / risk, "win": True}
        if h[k] >= target:
            return {"reason": "Target", "bar": k, "exit": float(target), "r": (target - entry) / risk, "win": True}
    px = float(c[n - 1])
    return {"reason": "Time limit", "bar": n - 1, "exit": px, "r": (px - entry) / risk, "win": px > entry}


@lru_cache(maxsize=96)
def make_chart(kind, seed):
    """One practice chart: {'hist','fut','plan','outcome','markup',...}. Deterministic for a (kind, seed)."""
    best = None
    for attempt in range(150):
        rng = np.random.default_rng(int(seed) * 997 + attempt)
        want = (rng.random() < SUCCESS_P[kind]) if kind in SUCCESS_P else None
        s = float(rng.uniform(0.009, 0.013))
        g = GEN[kind](rng, s)
        a = g["arr"]
        hist = pd.DataFrame({"Open": a["o"], "High": a["h"], "Low": a["l"], "Close": a["c"], "Volume": a["v"]})
        entry = float(hist.Close.iloc[-1] * (1 + rng.normal(0, 0.002)))
        stop = float(g["stop"])
        if stop >= entry * 0.995:
            continue
        risk = entry - stop
        target = float(g["target"]) if g.get("target") else entry + 2 * risk
        if target < entry + 1.4 * risk:
            continue
        f = _future(rng, entry, stop, target, bool(want), s, kind, float(hist.Volume.median()))
        fut = pd.DataFrame({"Open": f["o"], "High": f["h"], "Low": f["l"], "Close": f["c"], "Volume": f["v"]})
        out = simulate_plan(fut, entry, stop, target)
        best = (hist, fut, g, entry, stop, target, out)
        if kind == "none":
            break
        if (want and out["reason"].startswith("Target")) or (not want and out["reason"].startswith("Stop")):
            break
        if attempt >= 60:           # good enough: a valid chart whose outcome we simply report truthfully
            break
    hist, fut, g, entry, stop, target, out = best
    return {"kind": kind, "seed": int(seed), "hist": hist, "fut": fut, "g": g,
            "plan": {"entry": entry, "stop": stop, "target": target, "rr": (target - entry) / (entry - stop)},
            "outcome": out}


def basics_notes(chart):
    """Notes and points that explain how to read the candles, volume and EMA on any chart."""
    h = chart["hist"]
    body = (h.Close - h.Open) / h.Open
    gi, ri = int(body.iloc[-40:].idxmax()), int(body.iloc[-40:].idxmin())
    vi = int(h.Volume.iloc[-40:].idxmax())
    wick = (h.High - np.maximum(h.Open, h.Close)) / h.Close
    wi = int(wick.iloc[-40:].idxmax())
    pts = [dict(x=gi, y=float(h.High[gi]), text="1", color="#ffffff"), dict(x=ri, y=float(h.High[ri]), text="2", color="#ffffff"),
           dict(x=wi, y=float(h.High[wi]), text="3", color="#ffffff"), dict(x=vi, y=float(h.High[vi]), text="4", color="#ffffff")]
    notes = [
        f"Point 1, a green candle: price opened at {_money(h.Open[gi])} and closed higher, at {_money(h.Close[gi])}. The thick part "
        "(the body) runs from open to close. Green = buyers won that day.",
        f"Point 2, a red candle: it opened at {_money(h.Open[ri])} and closed lower, at {_money(h.Close[ri])}. Red = sellers won that day.",
        f"Point 3, a long upper wick: the thin line shows price reached {_money(h.High[wi])} during the day but got pushed back "
        "down. A long wick shows a rejection: one side tried and failed.",
        "Point 4, the busiest day: volume (bars at the bottom) shows how many shares traded. Big moves on big volume matter "
        "more than big moves on thin volume.",
        "The orange line is the 20-day average price (EMA 20). When price is above it and it is rising, the short-term trend is up.",
        "The purple RSI panel at the bottom measures how stretched a move is. Under 30 means heavily sold, over 70 means "
        "heavily bought. It is a gauge, not a signal on its own.",
    ]
    return pts, notes


# ------------------------------------------------------------------ drawing
def _rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn.replace(0, np.nan))


def build_figure(chart, markup=True, reveal=False, user_plan=None, quiz_lines=None, basics=False, show_plan=None,
                 height=640):
    """
    markup      draw levels, trend lines, numbered points (from the pattern) and the plan lines
    reveal      show the second half (what happened next) and the exit
    user_plan   {'entry','stop','target'} to draw instead of the textbook plan (practice mode)
    quiz_lines  [(label, price)] candidate stop lines to draw as A / B / C
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    hist, fut, g = chart["hist"], chart["fut"], chart["g"]
    h = len(hist)
    full = pd.concat([hist, fut]) if reveal else hist
    full = full.reset_index(drop=True)
    x = np.arange(len(full))
    xmax = h + FUT_BARS
    ema = full.Close.ewm(span=20, adjust=False).mean()
    rsi = _rsi(full.Close)

    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.66, 0.16, 0.18])
    fig.add_trace(go.Candlestick(x=x, open=full.Open, high=full.High, low=full.Low, close=full.Close, name="Price",
                                 increasing_line_color=GREEN, decreasing_line_color=RED), row=1, col=1)
    fig.add_trace(go.Scatter(x=x, y=ema, name="20-day average (EMA 20)", line=dict(width=1.3, color="#ff9800")), row=1, col=1)
    vcol = np.where(full.Close >= full.Open, GREEN, RED)
    fig.add_trace(go.Bar(x=x, y=full.Volume, name="Volume", marker_color=vcol, showlegend=False), row=2, col=1)
    fig.add_trace(go.Scatter(x=x, y=rsi, name="RSI", line=dict(color="#7e57c2", width=1.3), showlegend=False), row=3, col=1)
    for yv in (30, 70):
        fig.add_trace(go.Scatter(x=[0, xmax], y=[yv, yv], mode="lines", line=dict(color="gray", dash="dash", width=0.8),
                                 hoverinfo="skip", showlegend=False), row=3, col=1)

    x_end = xmax if reveal else h + 2

    def hline(y, label, color, dash, x0=0, x1=None):
        fig.add_trace(go.Scatter(x=[x0, x1 if x1 is not None else x_end], y=[y, y], mode="lines", name=label,
                                 line=dict(color=color, dash=dash, width=1.6), hoverinfo="skip"), row=1, col=1)

    if markup:
        for z0, z1, col in g.get("zones", []):
            fig.add_trace(go.Scatter(x=[0, x_end, x_end, 0], y=[z0, z0, z1, z1], fill="toself", mode="none",
                                     fillcolor=_rgba(col, 0.13), hoverinfo="skip", showlegend=False), row=1, col=1)
        for lv in g.get("levels", []):
            hline(lv["y"], lv["label"], lv["color"], lv["dash"])
        for ln in g.get("lines", []):
            fig.add_trace(go.Scatter(x=[ln["x0"], ln["x1"]], y=[ln["y0"], ln["y1"]], mode="lines", name=ln["label"],
                                     line=dict(color=ln["color"], dash=ln["dash"], width=1.6), hoverinfo="skip"), row=1, col=1)
        pts = g.get("points", [])
        if basics:
            pts, _ = basics_notes(chart)
        if pts:
            fig.add_trace(go.Scatter(
                x=[p["x"] for p in pts], y=[p["y"] for p in pts], mode="markers+text", text=[p["text"] for p in pts],
                textposition="top center", textfont=dict(size=13, color="#ffffff"), name="Numbered points",
                marker=dict(size=19, color="rgba(30,136,229,0.85)", line=dict(width=1, color="white")),
                hoverinfo="skip"), row=1, col=1)
    plan = user_plan or (chart["plan"] if (markup and show_plan is not False) or show_plan else None)
    if plan:
        e, st_, tg = plan["entry"], plan["stop"], plan["target"]
        hline(st_, f"Stop {_money(st_)}", STOP_C, "solid", h - 1)
        hline(tg, f"Target {_money(tg)}", TARGET_C, "solid", h - 1)
        hline(e, f"Entry {_money(e)}", ENTRY_C, "dot", h - 1)
        fig.add_trace(go.Scatter(x=[h], y=[e], mode="markers", name="Buy (next open)",
                                 marker=dict(symbol="triangle-up", size=15, color=ENTRY_C, line=dict(width=1, color="white")),
                                 hoverinfo="skip"), row=1, col=1)
    if reveal and plan:
        out = simulate_plan(fut, plan["entry"], plan["stop"], plan["target"])
        if out["reason"] != "No trade":
            fig.add_trace(go.Scatter(
                x=[h + out["bar"]], y=[out["exit"]], mode="markers+text", text=[out["reason"]], textposition="bottom center",
                textfont=dict(size=12, color="#ffffff"), name="Exit",
                marker=dict(symbol="x", size=15, color="#ffffff", line=dict(width=2, color="#ffffff")),
                hoverinfo="skip"), row=1, col=1)
    for lab, y in (quiz_lines or []):
        hline(y, f"{lab}", "#ce93d8", "dash", h - 8, h + 8)
        fig.add_annotation(x=h + 8.4, y=y, text=f"<b>{lab}</b>", showarrow=False, xanchor="left",
                           font=dict(size=15, color="#ce93d8"), row=1, col=1)

    fig.add_trace(go.Scatter(x=[h - 0.5, h - 0.5], y=[float(hist.Low.min()), float(hist.High.max())], mode="lines",
                             line=dict(color="rgba(255,255,255,0.35)", dash="dot", width=1), hoverinfo="skip",
                             showlegend=False), row=1, col=1)
    fig.add_annotation(x=h - 0.5, y=float(hist.High.max()), text="Decision point  →", showarrow=False,
                       xanchor="right", yanchor="bottom", font=dict(size=11, color="#bbbbbb"), row=1, col=1)
    fig.update_layout(template="plotly_dark", height=height, xaxis_rangeslider_visible=False, hovermode="closest",
                      legend=dict(orientation="h", y=1.05), margin=dict(l=10, r=10, t=30, b=10),
                      xaxis3=dict(title=dict(text="Trading days (each candle is one day)")))
    fig.update_xaxes(range=[-1, xmax + 2])
    fig.update_yaxes(title_text="Price", row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    fig.update_yaxes(title_text="RSI", row=3, col=1)
    return fig


def _rgba(hexcolor, a):
    hc = hexcolor.lstrip("#")
    r, g_, b = (int(hc[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g_},{b},{a})"


def quiz_stop_options(chart, rng_seed):
    """Three candidate stop prices (shuffled A/B/C) and which letter is the sensible one."""
    p = chart["plan"]
    risk = p["entry"] - p["stop"]
    cands = [("good", p["stop"]), ("tight", p["entry"] - 0.3 * risk), ("far", p["entry"] - 3.2 * risk)]
    order = list(np.random.default_rng(rng_seed).permutation(3))
    letters = ["A", "B", "C"]
    lines = [(letters[i], cands[j][1]) for i, j in enumerate(order)]
    answer = letters[[cands[j][0] for j in order].index("good")]
    why = {letters[i]: cands[j][0] for i, j in enumerate(order)}
    return lines, answer, why

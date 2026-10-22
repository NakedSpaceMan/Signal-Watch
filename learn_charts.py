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
import design  # registers the chart theme

import numpy as np
import pandas as pd

HIST_MIN = 70
FUT_BARS = 20
MAX_HOLD = 15
KINDS = ["range", "bounce", "breakout", "pullback", "flag", "triangle", "double", "cup", "none"]
SUCCESS_P = {"range": 0.55, "bounce": 0.45, "breakout": 0.5, "pullback": 0.55, "flag": 0.55, "triangle": 0.5,
             "double": 0.5, "cup": 0.5}
PRACTICE_WEIGHTS = {"range": 0.10, "bounce": 0.12, "breakout": 0.14, "pullback": 0.14, "flag": 0.10, "triangle": 0.09,
                    "double": 0.09, "cup": 0.08, "none": 0.14}
NAMES = {"range": "Support and resistance (range)", "bounce": "Bounce off support", "breakout": "Breakout",
         "pullback": "Pullback in an uptrend", "flag": "Bull flag", "triangle": "Ascending triangle",
         "double": "Double bottom", "cup": "Cup and handle", "none": "No setup"}

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
# Each generator draws its OWN random structure (how long the run-up was, how many times a level was touched, how deep
# the dips are, which candle shape ends the pattern, how big the breakout is), so two charts of the same pattern
# do not look alike. Each returns the visible half (arrays o,h,l,c,v) plus the markup and the plan levels.
class _Retry(Exception):
    """This random draw didn't produce a clean example; draw again."""


def _ri(rng, lo, hi):
    return int(rng.integers(lo, hi + 1))


def _rr(rng, lo, hi):
    return float(rng.uniform(lo, hi))


def _bar(rng, o, h, l, c, vmult):
    return {"o": np.array([o], float), "h": np.array([h], float), "l": np.array([l], float),
            "c": np.array([c], float), "v": _vol(rng, 1, vmult)}


def _context(rng, start, end, bars, s, waves=None, vmult=1.0):
    """A believable move from start to end: a few waves with counter-moves, not one straight line."""
    bars = int(bars)
    waves = waves or _ri(rng, 2, 4)
    if bars < 14 or waves < 2:
        return _seg(rng, start, [(bars, end)], s, vmult)
    cuts = np.sort(rng.choice(np.arange(5, bars - 4), size=waves - 1, replace=False))
    edges = np.r_[0, cuts, bars]
    span, floor_px = end - start, min(start, end) * 0.75
    legs = []
    for i in range(1, len(edges)):
        price = start + span * edges[i] / bars
        if i < len(edges) - 1:
            price += span * rng.uniform(-0.2, 0.2)
        legs.append((int(edges[i] - edges[i - 1]), max(price, floor_px)))
    legs[-1] = (legs[-1][0], end)
    return _seg(rng, start, legs, s, vmult)


def _gen_range(rng, s, mid_end=False):
    S = rng.uniform(25, 120)
    R = S * (1 + _rr(rng, 0.09, 0.18))
    mid = (S + R) / 2
    n_s = _ri(rng, 2, 4)
    lead_n = _ri(rng, 10, 32)
    legs, kinds = [(_ri(rng, 4, 9), R)], ["R"]
    for j in range(n_s):
        legs.append((_ri(rng, 6, 13), S)); kinds.append("S")
        if j < n_s - 1:
            legs.append((_ri(rng, 6, 13), R)); kinds.append("R")
    if mid_end:
        legs.append((_ri(rng, 5, 8), mid * _rr(rng, 0.99, 1.01)))
    else:
        legs.append((2, S * _rr(rng, 1.012, 1.03)))
    kinds.append("end")
    lead = _path(mid, [(lead_n, mid * (1 + _rr(rng, -0.02, 0.02)))], rng, s)
    body = np.clip(_path(lead[-1], legs, rng, s), S * 1.003, R * 0.997)
    close = np.concatenate([lead, body])
    ends = np.cumsum([b for b, _ in legs]) - 1 + lead_n
    o, h, l = _candles(close, rng, s, mid)
    h, l = np.minimum(h, R * 1.003), np.maximum(l, S * 0.997)
    pts, nR, nS = [], 0, 0
    for i, k in zip(ends, kinds):
        if k == "R":
            h[i] = R * (1 + _rr(rng, -0.002, 0.002)); nR += 1
            pts.append(dict(x=int(i), y=R, text=str(len(pts) + 1), color="#ffffff"))
        elif k == "S":
            l[i] = S * (1 + _rr(rng, -0.002, 0.002)); nS += 1
            pts.append(dict(x=int(i), y=S, text=str(len(pts) + 1), color="#ffffff"))
    if not mid_end and close[-1] <= o[-1]:
        o[-1] = close[-1] * 0.993
    o, h, l, c = _fix(o, h, l, close)
    arr = {"o": o, "h": h, "l": l, "c": c, "v": _vol(rng, len(c), 1.0)}
    atr = _atr(h, l, c)
    g = {
        "arr": arr, "variant": "range",
        "levels": [dict(y=R, label=f"Resistance {_money(R)}", color=RESIST_C, dash="dash"),
                   dict(y=S, label=f"Support {_money(S)}", color=SUPPORT_C, dash="dash")],
        "zones": [(R * 0.996, R * 1.004, RESIST_C), (S * 0.996, S * 1.004, SUPPORT_C)],
        "points": pts, "lines": [],
        "stop": S - 0.6 * atr, "target": R * 0.985,
        "hint": "Price has been bouncing between a floor and a ceiling. Notice where the last candle sits compared with them.",
        "notes": [
            f"Support {_money(S)} (green): price fell to this level and turned back up {nS} times. Buyers keep stepping in here.",
            f"Resistance {_money(R)} (red): price rose to this level and turned back down {nR} times. Sellers keep stepping in here.",
            "The more times a level holds, the more traders watch it, and the more it tends to hold again, until it doesn't.",
            f"The last candle just bounced off support. The plan buys the next open, with the stop a little BELOW support "
            f"({_money(S - 0.6 * atr)}): if price breaks support, the idea was wrong and you want out.",
            f"The target sits just under resistance ({_money(R * 0.985)}), where sellers have appeared before.",
        ]}
    if mid_end:
        g.update(stop=float(c[-1]) - 2 * atr, target=None)
    return g


def _gen_bounce(rng, s):
    S = rng.uniform(25, 120)
    H = S * _rr(rng, 1.12, 1.28)
    pre_n = _ri(rng, 6, 28)
    pre = _seg(rng, S * _rr(rng, 1.0, 1.05), [(pre_n, S * _rr(rng, 1.015, 1.05))], s, 1.0)
    n_base = _ri(rng, 2, 3)
    legs_a = []
    for j in range(n_base):
        legs_a.append((_ri(rng, 3, 6), S * _rr(rng, 0.996, 1.002)))
        if j < n_base - 1:
            legs_a.append((_ri(rng, 3, 6), S * _rr(rng, 1.025, 1.05)))
    a = _seg(rng, pre["c"][-1], legs_a, s, 1.0)
    base_idx = [pre_n + int(e) for e in (np.cumsum([b for b, _ in legs_a]) - 1)[::2]]
    rally_n, top_n, sell_n = _ri(rng, 14, 24), _ri(rng, 4, 10), _ri(rng, 16, 32)
    legs_b = [(rally_n, H), (top_n, H * _rr(rng, 0.975, 0.99)), (sell_n, S * _rr(rng, 1.004, 1.012))]
    b = _seg(rng, a["c"][-1], legs_b, s, [1.0] * rally_n + [0.9] * top_n + list(np.linspace(1.1, 1.7, sell_n)))
    variant = "hammer" if rng.random() < 0.55 else "engulf"
    if variant == "hammer":
        two = {"o": [S * 1.004, S * 1.003], "h": [S * 1.009, S * 1.019], "l": [S * 0.994, S * 0.985],
               "c": [S * 1.002, S * 1.016]}
    else:
        two = {"o": [S * 1.012, S * 0.998], "h": [S * 1.014, S * 1.023], "l": [S * 0.996, S * 0.993],
               "c": [S * 1.001, S * 1.021]}
    last2 = {k: np.array(v, float) for k, v in two.items()}
    last2["v"] = _vol(rng, 2, [1.8, 2.3])
    arr = _cat(pre, a, b, last2)
    o, h, l, c = _fix(arr["o"], arr["h"], arr["l"], arr["c"])
    arr.update(o=o, h=h, l=l, c=c)
    n = len(c)
    atr = _atr(h, l, c)
    stop = float(l[-2:].min()) - 0.5 * atr
    peak_i = pre_n + len(a["c"]) + rally_n + top_n - 1
    pts = [dict(x=i, y=S, text=str(k + 1), color="#ffffff") for k, i in enumerate(base_idx)]
    pts.append(dict(x=n - 1, y=float(l[-1]), text=str(len(pts) + 1), color="#ffffff"))
    cand = ("a 'hammer' candle: it dipped below support (long lower wick), then buyers pushed it back up to close near the high. "
            "That says sellers tried and failed." if variant == "hammer" else
            "a 'bullish engulfing' pair: a red candle followed by a green candle whose body swallows the red one. That says "
            "buyers overwhelmed the sellers in a single day.")
    return {
        "arr": arr, "variant": variant,
        "levels": [dict(y=S, label=f"Support {_money(S)}", color=SUPPORT_C, dash="dash")],
        "zones": [(S * 0.993, S * 1.007, SUPPORT_C)], "points": pts,
        "lines": [_line(peak_i, float(b["c"][rally_n + top_n - 1]), n - 3, float(b["c"][-1]), "Sell-off", RESIST_C, "dot")],
        "stop": stop, "target": None,
        "hint": ("A sharp sell-off has run into a price where the stock stopped before, and the last candle has a long lower wick."
                 if variant == "hammer" else
                 "A sharp sell-off has run into a price where the stock stopped before, and a green candle just swallowed the red one before it."),
        "notes": [
            f"Support {_money(S)}: earlier, price based here and turned up ({n_base} touches before the rally). That makes it a level traders remember.",
            "Then the stock rallied, topped out, and sold off hard back to the same level. Fast sell-offs push a stock into "
            "oversold territory, where sellers run out of steam.",
            f"Point {len(pts)} is {cand}",
            f"The plan buys the next open. The stop goes under the low of the last two candles ({_money(stop)}): if price makes "
            "a new low below that, the bounce failed and you leave.",
        ]}


def _gen_breakout(rng, s):
    R = rng.uniform(25, 120)
    ctx_n = _ri(rng, 25, 60)
    ctx = _context(rng, R * _rr(rng, 0.6, 0.85), R * _rr(rng, 0.93, 0.97), ctx_n, s)
    n_t = _ri(rng, 2, 4)
    legs, touch = [], []
    dip = _rr(rng, 0.05, 0.09)
    for _ in range(n_t):
        legs.append((_ri(rng, 3, 7), R * (1 - dip))); touch.append(False)
        legs.append((_ri(rng, 3, 6), R)); touch.append(True)
        dip = max(dip * _rr(rng, 0.6, 0.9), 0.02)
    legs.append((_ri(rng, 3, 5), R * _rr(rng, 0.955, 0.975))); touch.append(False)
    base = _seg(rng, ctx["c"][-1], legs, s * 0.9, _rr(rng, 0.6, 0.85))
    ends = np.cumsum([b for b, _ in legs]) - 1
    base["c"] = np.minimum(base["c"], R * 0.998)
    for i, t in zip(ends, touch):
        if t:
            base["h"][i] = R * (1 + _rr(rng, -0.002, 0.002))
    base["h"] = np.minimum(base["h"], R * 1.003)
    gap = rng.random() < 0.3
    o_ = R * (1 + _rr(rng, 0.006, 0.014)) if gap else R * _rr(rng, 0.997, 1.003)
    c_ = R * (1 + _rr(rng, 0.022, 0.042))
    bo = _bar(rng, o_, c_ * (1 + _rr(rng, 0.002, 0.008)), R * (1.001 if gap else _rr(rng, 0.996, 1.0)), c_, _rr(rng, 2.2, 3.8))
    arr = _cat(ctx, base, bo)
    o, h, l, c = _fix(arr["o"], arr["h"], arr["l"], arr["c"])
    arr.update(o=o, h=h, l=l, c=c)
    atr = _atr(h, l, c)
    stop = R - 0.5 * atr
    n = len(c)
    pts = [dict(x=ctx_n + int(i), y=R, text="", color="#ffffff") for i, t in zip(ends, touch) if t]
    for k, p in enumerate(pts):
        p["text"] = str(k + 1)
    pts.append(dict(x=n - 1, y=float(h[-1]), text=str(len(pts) + 1), color="#ffffff"))
    return {
        "arr": arr, "variant": "gap" if gap else "close",
        "levels": [dict(y=R, label=f"Resistance {_money(R)}", color=RESIST_C, dash="dash")],
        "zones": [(R * 0.996, R * 1.004, RESIST_C)], "points": pts, "lines": [],
        "stop": stop, "target": None,
        "hint": "Price kept getting turned back at the same ceiling, and the last candle just closed above it on heavy volume.",
        "notes": [
            f"Resistance {_money(R)}: price pushed up to this level and got turned back {n_t} times (points 1 to {n_t}), while "
            "the dips got shallower. Sellers are running out.",
            "During the base, volume was quiet (bars at the bottom). Calm before the move.",
            f"Point {n_t + 1} is the breakout: a strong candle CLOSING above resistance"
            + (", after opening with a gap above it," if gap else ",") + " with volume well above normal. Heavy volume says real "
            "buyers showed up, not just a blip.",
            f"The plan buys the next open. The stop goes just under the old resistance ({_money(stop)}): once price is above a "
            "level, that level should act as support. If it falls back below, the breakout failed.",
        ]}


def _gen_pullback(rng, s):
    for _ in range(150):
        P = rng.uniform(25, 120)
        pre = _seg(rng, P * _rr(rng, 0.88, 0.97), [(_ri(rng, 12, 40), P)], s, 1.0)
        k, lv, legs = _ri(rng, 3, 5), 1.0, []
        for i in range(k):
            lv *= 1 + _rr(rng, 0.05, 0.12)
            legs.append((_ri(rng, 8, 15), P * lv))
            if i < k - 1:
                legs.append((_ri(rng, 3, 6), P * lv * (1 - _rr(rng, 0.02, 0.045))))
        peak, d, dn = P * lv, _rr(rng, 0.04, 0.09), _ri(rng, 4, 8)
        up = _seg(rng, pre["c"][-1], legs, s, 1.0)
        dip = _seg(rng, up["c"][-1], [(dn, peak * (1 - d))], s, 0.75)
        back = _seg(rng, dip["c"][-1], [(1, dip["c"][-1] * 1.014)], s, 1.5)
        arr = _cat(pre, up, dip, back)
        o, h, l, c = _fix(arr["o"], arr["h"], arr["l"], arr["c"])
        if c[-1] <= o[-1]:
            o[-1] = c[-1] * 0.994
            o, h, l, c = _fix(o, h, l, c)
        ema = pd.Series(c).ewm(span=20, adjust=False).mean().to_numpy()
        dip_low = float(l[-(dn + 1):-1].min())
        if (len(c) >= 58 and dip_low <= ema[-1] * 1.015 and dip_low >= ema[-1] * 0.96 and c[-1] >= ema[-1] * 0.99
                and ema[-1] > ema[-6] and c[-1] > h[-2] * 0.995):
            break
    else:
        raise _Retry()
    arr.update(o=o, h=h, l=l, c=c)
    atr = _atr(h, l, c)
    stop = dip_low - 0.5 * atr
    n = len(c)
    lo_i = n - (dn + 1) + int(np.argmin(l[-(dn + 1):-1]))
    return {
        "arr": arr, "variant": "pullback", "levels": [], "zones": [], "lines": [],
        "points": [dict(x=int(np.argmax(h[: n - 4])), y=float(h[: n - 4].max()), text="1", color="#ffffff"),
                   dict(x=lo_i, y=dip_low, text="2", color="#ffffff"),
                   dict(x=n - 1, y=float(c[-1]), text="3", color="#ffffff")],
        "stop": stop, "target": None,
        "hint": "The stock is in an uptrend and has just dipped to its rising orange line. The last candle is green.",
        "notes": [
            "The stock is in an uptrend: higher highs and higher lows, with the orange 20-day line (EMA 20) rising underneath.",
            f"Point 1 is the latest high. Then price pulled back (dipped) for about {dn} days on lighter volume. Quiet dips in an "
            "uptrend are usually profit-taking, not panic.",
            f"Point 2: the dip stopped right at the 20-day line, a spot where buyers often step in. The low was {_money(dip_low)}.",
            "Point 3: a green candle that closes above the previous day's high. That is the sign buyers are back, and your trigger to buy.",
            f"The stop goes just under the dip's low ({_money(stop)}): if price goes below the dip the trend may be over.",
        ]}


def _gen_flag(rng, s):
    F = rng.uniform(25, 120)
    pre = _context(rng, F * _rr(rng, 0.85, 0.95), F * _rr(rng, 1.0, 1.03), _ri(rng, 20, 55), s)
    pole_n, pole_g = _ri(rng, 5, 9), _rr(rng, 0.16, 0.32)
    p0 = float(pre["c"][-1])
    pole = _seg(rng, p0, [(pole_n, p0 * (1 + pole_g))], s * 0.55, 2.0)
    T = float(pole["c"][-1])
    nf, drift, hw = _ri(rng, 7, 14), _rr(rng, 0.035, 0.09), _rr(rng, 0.012, 0.022)
    t = np.arange(1, nf + 1)
    centre = T * (1 - 0.012) - T * drift * t / nf
    upper_f, lower_f = centre + hw * T, centre - hw * T
    close = np.clip(centre + _ar_noise(rng, nf, 0.006 * T), centre - 0.7 * hw * T, centre + 0.7 * hw * T)
    o, h, l = _candles(close, rng, s * 0.8, T)
    h, l = np.minimum(h, upper_f + 0.002 * T), np.maximum(l, lower_f - 0.002 * T)
    o, h, l, c = _fix(o, h, l, close)
    flag = {"o": o, "h": h, "l": l, "c": c, "v": _vol(rng, nf, np.linspace(0.8, 0.45, nf))}
    slope = (upper_f[0] - upper_f[-1]) / (nf - 1)
    ub = float(upper_f[-1] - slope)
    bc = ub * (1 + _rr(rng, 0.012, 0.035))
    bo = _bar(rng, ub * _rr(rng, 0.996, 1.0), bc * 1.006, ub * 0.995, bc, _rr(rng, 2.2, 3.2))
    arr = _cat(pre, pole, flag, bo)
    o, h, l, c = _fix(arr["o"], arr["h"], arr["l"], arr["c"])
    arr.update(o=o, h=h, l=l, c=c)
    atr = _atr(h, l, c)
    f0 = len(pre["c"]) + len(pole["c"])
    n = len(c)
    stop = float(l[f0:n - 1].min()) - 0.5 * atr
    return {
        "arr": arr, "variant": "flag", "levels": [], "zones": [],
        "points": [dict(x=f0 - max(pole_n // 2, 1), y=float(h[f0 - max(pole_n // 2, 1)]), text="1", color="#ffffff"),
                   dict(x=f0 + nf // 2, y=float(upper_f[nf // 2]), text="2", color="#ffffff"),
                   dict(x=n - 1, y=float(h[-1]), text="3", color="#ffffff")],
        "lines": [_line(f0 - 0.5, upper_f[0] + slope, n - 1, ub, "Flag top", TREND_C),
                  _line(f0 - 0.5, lower_f[0] + slope, n - 2, lower_f[-1], "Flag bottom", TREND_C)],
        "stop": stop, "target": None,
        "hint": "A fast run-up was followed by a short, tight drift down on quiet volume, and the last candle breaks out of it.",
        "notes": [
            f"Point 1: the 'pole'. A fast, strong run up of about {pole_g * 100:.0f}% in {pole_n} days, on heavy volume. That shows big buying interest.",
            f"Point 2: the 'flag'. Price drifts down in a tight, sloping channel (the yellow lines) for about {nf} days on shrinking "
            "volume. This is a pause where early buyers take a little profit, not a reversal.",
            "Point 3: price breaks above the top of the flag on rising volume. That says the pause is over and buyers are back in charge.",
            f"The stop goes under the flag's low ({_money(stop)}). If price falls back through the whole flag, the pattern failed.",
            "Textbook note: some traders aim for the pole's height added to the breakout. This lesson uses a simpler 2-to-1 target.",
        ]}


def _gen_triangle(rng, s):
    R = rng.uniform(25, 120)
    ctx_n = _ri(rng, 28, 55)
    ctx = _context(rng, R * _rr(rng, 0.62, 0.8), R * _rr(rng, 0.9, 0.94), ctx_n, s)
    n_low = _ri(rng, 2, 4)
    f0, f1 = _rr(rng, 0.89, 0.93), _rr(rng, 0.955, 0.975)
    legs, kinds, low_px = [(_ri(rng, 4, 7), R)], ["R"], []
    for j in range(n_low):
        px = R * (f0 + (f1 - f0) * j / (n_low - 1))
        low_px.append(px)
        legs.append((_ri(rng, 4, 7), px)); kinds.append("L")
        legs.append((_ri(rng, 4, 7), R)); kinds.append("R")
    legs.append((_ri(rng, 2, 3), R * 0.992)); kinds.append("hold")
    nt = sum(b for b, _ in legs)
    tri = _seg(rng, ctx["c"][-1], legs, s * 0.85, np.linspace(1.0, 0.55, nt))
    ends = np.cumsum([b for b, _ in legs]) - 1
    low_idx = [int(e) for e, k in zip(ends, kinds) if k == "L"]
    tri["c"] = np.minimum(tri["c"], R * 0.997)
    tri["h"] = np.minimum(tri["h"], R * 1.003)
    t = np.arange(nt)
    floor = np.interp(t, low_idx, low_px)
    inside = (t >= low_idx[0]) & (t <= low_idx[-1])
    tri["c"] = np.where(inside, np.maximum(tri["c"], floor * 1.003), tri["c"])
    tri["l"] = np.where(inside, np.maximum(tri["l"], floor * 0.997), tri["l"])
    for i, k in zip(ends, kinds):
        if k == "R":
            tri["h"][i] = R * (1 + _rr(rng, -0.002, 0.002))
        elif k == "L":
            tri["l"][i] = low_px[low_idx.index(int(i))] * (1 + _rr(rng, -0.002, 0.002))
    c_ = R * (1 + _rr(rng, 0.022, 0.04))
    bo = _bar(rng, R * _rr(rng, 0.996, 1.0), c_ * 1.005, R * 0.995, c_, _rr(rng, 2.4, 3.4))
    arr = _cat(ctx, tri, bo)
    o, h, l, c = _fix(arr["o"], arr["h"], arr["l"], arr["c"])
    arr.update(o=o, h=h, l=l, c=c)
    n = len(c)
    stop = R * 0.975
    pts = [dict(x=ctx_n + int(i), y=R, text="", color="#ffffff") for i, k in zip(ends, kinds) if k == "R"]
    for q, p in enumerate(pts):
        p["text"] = str(q + 1)
    pts.append(dict(x=n - 1, y=float(h[-1]), text=str(len(pts) + 1), color="#ffffff"))
    slope = (low_px[-1] - low_px[0]) / (low_idx[-1] - low_idx[0])
    x0 = ctx_n + low_idx[0]
    return {
        "arr": arr, "variant": "triangle",
        "levels": [dict(y=R, label=f"Flat top {_money(R)}", color=RESIST_C, dash="dash")],
        "zones": [(R * 0.996, R * 1.004, RESIST_C)], "points": pts,
        "lines": [_line(x0, low_px[0], n - 1, low_px[0] + slope * (n - 1 - x0), "Rising floor", TREND_C)],
        "stop": stop, "target": None,
        "hint": "The highs are flat while the lows keep rising, squeezing price tighter, and the last candle closes above the flat top.",
        "notes": [
            f"The top is flat: price hits {_money(R)} again and again (points 1 to {len(pts) - 1}) and gets turned back. Sellers are defending it.",
            "But the lows keep getting HIGHER (yellow line). Each dip, buyers step in earlier. Buyers are pushing, sellers are holding the line.",
            "The squeeze: the space between the two lines narrows and volume dries up. Pressure builds like a spring.",
            f"Point {len(pts)}: price closes above the flat top on heavy volume, the release of the spring. Ascending triangles "
            "break up more often than down, but not always.",
            f"The stop goes back inside the pattern, below the old top ({_money(stop)}). If price falls back in, it was a false breakout.",
        ]}


def _gen_double(rng, s):
    N = rng.uniform(25, 120)
    H = N * _rr(rng, 1.07, 1.15)
    B1 = N * _rr(rng, 0.86, 0.92)
    B2 = B1 * (1 + _rr(rng, -0.015, 0.015))
    lead = _seg(rng, H * _rr(rng, 0.97, 1.0), [(_ri(rng, 12, 34), H * (1 + _rr(rng, -0.02, 0.02)))], s, 1.0)
    d1_n, r1_n, d2_n, r2_n = _ri(rng, 14, 24), _ri(rng, 8, 13), _ri(rng, 8, 13), _ri(rng, 9, 14)
    d1 = _seg(rng, lead["c"][-1], [(d1_n, B1)], s, np.linspace(1.0, 1.7, d1_n))
    r1 = _seg(rng, d1["c"][-1], [(r1_n, N * 0.997)], s, 0.9)
    d2 = _seg(rng, r1["c"][-1], [(d2_n, B2)], s, np.linspace(0.9, 0.6, d2_n))
    r2 = _seg(rng, d2["c"][-1], [(r2_n, N * 0.99)], s, np.linspace(0.9, 1.3, r2_n))
    d1["l"][-1] = B1 * (1 + _rr(rng, -0.003, 0.003))
    d2["l"][-1] = B2 * (1 + _rr(rng, -0.003, 0.003))
    for sg in (r1, d2, r2):
        sg["c"] = np.minimum(sg["c"], N * 0.999)
        sg["h"] = np.minimum(sg["h"], N * 1.003)
    r1["h"][-1] = N * (1 + _rr(rng, -0.002, 0.002))
    bc = N * (1 + _rr(rng, 0.022, 0.04))
    bo = _bar(rng, N * _rr(rng, 0.996, 1.0), bc * 1.005, N * 0.995, bc, _rr(rng, 2.4, 3.6))
    arr = _cat(lead, d1, r1, d2, r2, bo)
    o, h, l, c = _fix(arr["o"], arr["h"], arr["l"], arr["c"])
    arr.update(o=o, h=h, l=l, c=c)
    atr = _atr(h, l, c)
    stop = N - 0.5 * atr
    n = len(c)
    i1 = len(lead["c"]) + d1_n - 1
    i2 = i1 + r1_n
    i3 = i2 + d2_n
    mid_b = (B1 + B2) / 2
    return {
        "arr": arr, "variant": "double",
        "levels": [dict(y=N, label=f"Neckline {_money(N)}", color=RESIST_C, dash="dash"),
                   dict(y=mid_b, label=f"Bottoms about {_money(mid_b)}", color=SUPPORT_C, dash="dash")],
        "zones": [(N * 0.996, N * 1.004, RESIST_C), (mid_b * 0.992, mid_b * 1.008, SUPPORT_C)],
        "points": [dict(x=i1, y=float(l[i1]), text="1", color="#ffffff"), dict(x=i2, y=float(h[i2]), text="2", color="#ffffff"),
                   dict(x=i3, y=float(l[i3]), text="3", color="#ffffff"), dict(x=n - 1, y=float(h[-1]), text="4", color="#ffffff")],
        "lines": [], "stop": stop, "target": None,
        "hint": "After a long fall, price made a low, bounced, fell back to about the same low, and the last candle just closed above the bounce's high.",
        "notes": [
            f"Point 1: after a long fall, price makes a low near {_money(B1)} and bounces. Selling slowed down.",
            f"Point 2: the bounce stalls at the 'neckline' ({_money(N)}), the high of the bounce. Sellers show up there.",
            f"Point 3: price falls back to about the SAME low (within a couple of percent) but on lighter volume. The sellers who "
            "dumped the first time are already gone, so the second test fails to push lower. That is the second bottom: the 'W'.",
            "Point 4: price closes above the neckline on a burst of volume. That says the buyers have won the tug of war.",
            f"The stop goes just under the neckline ({_money(stop)}): once price is above it, it should hold. Some traders put "
            "the stop under the second bottom instead, which is safer against a retest but means a bigger loss if you're wrong.",
        ]}


def _gen_cup(rng, s):
    R = rng.uniform(25, 120)
    ctx_n = _ri(rng, 20, 40)
    ctx = _context(rng, R * _rr(rng, 0.7, 0.85), R * _rr(rng, 0.99, 1.0), ctx_n, s)
    n_c, d = _ri(rng, 24, 40), _rr(rng, 0.12, 0.22)
    x = np.linspace(0, 1, n_c + 1)[1:]
    close = np.minimum(R * (1 - d * np.sin(np.pi * x) ** 0.85) * (1 + _ar_noise(rng, n_c, s * 0.7)), R * 0.999)
    o, h, l = _candles(close, rng, s * 0.9, float(ctx["c"][-1]))
    h = np.minimum(h, R * 1.002)
    o, h, l, c = _fix(o, h, l, close)
    cup = {"o": o, "h": h, "l": l, "c": c, "v": _vol(rng, n_c, 1.0 - 0.35 * np.sin(np.pi * x))}
    hn, hd = _ri(rng, 5, 9), _rr(rng, 0.025, 0.045)
    handle = _seg(rng, float(c[-1]), [(hn - 1, R * (1 - hd)), (1, R * (1 - hd * 0.5))], s * 0.7, np.linspace(0.7, 0.5, hn))
    handle["c"] = np.minimum(handle["c"], R * 0.997)
    handle["h"] = np.minimum(handle["h"], R * 1.0)
    bc = R * (1 + _rr(rng, 0.018, 0.038))
    bo = _bar(rng, R * _rr(rng, 0.996, 1.0), bc * 1.005, R * 0.995, bc, _rr(rng, 2.4, 3.6))
    arr = _cat(ctx, cup, handle, bo)
    o, h, l, c = _fix(arr["o"], arr["h"], arr["l"], arr["c"])
    arr.update(o=o, h=h, l=l, c=c)
    atr = _atr(h, l, c)
    hs = ctx_n + n_c
    handle_low = float(l[hs:hs + hn].min())
    stop = handle_low - 0.4 * atr
    n = len(c)
    bot_i = ctx_n + int(np.argmin(c[ctx_n:ctx_n + n_c]))
    return {
        "arr": arr, "variant": "cup",
        "levels": [dict(y=R, label=f"Rim {_money(R)}", color=RESIST_C, dash="dash")],
        "zones": [(R * 0.996, R * 1.004, RESIST_C)],
        "points": [dict(x=ctx_n - 1, y=float(h[ctx_n - 1]), text="1", color="#ffffff"),
                   dict(x=bot_i, y=float(l[bot_i]), text="2", color="#ffffff"),
                   dict(x=hs + int(np.argmin(l[hs:hs + hn])), y=handle_low, text="3", color="#ffffff"),
                   dict(x=n - 1, y=float(h[-1]), text="4", color="#ffffff")],
        "lines": [], "stop": stop, "target": None,
        "hint": "Price fell in a smooth rounded dip, climbed back to where it started, paused with a small dip, and the last candle breaks above that level.",
        "notes": [
            f"Point 1: the left rim. Price runs up to {_money(R)}, where sellers appear and push it back down.",
            f"Point 2: the bottom of the 'cup'. The decline is rounded, not a crash: selling slowly fades and buyers slowly return. "
            f"The cup is about {d * 100:.0f}% deep.",
            "Then price climbs back up to the old rim. Rounded bottoms mean the stock got a genuine second look from buyers.",
            f"Point 3: the 'handle'. A short, shallow dip (about {hd * 100:.0f}%) on light volume shakes out the last impatient sellers.",
            f"Point 4: price closes above the rim on a burst of volume. The stop goes under the handle's low ({_money(stop)}): "
            "if that breaks, the pattern failed.",
        ]}


def _gen_none(rng, s):
    v = rng.choice(["chop", "knife", "extended", "mid"], p=[0.3, 0.25, 0.25, 0.2])
    P = rng.uniform(25, 120)
    if v == "mid":
        g = _gen_range(rng, s, mid_end=True)
        g["variant"] = "mid"
        g["hint"] = "There is a clear floor and ceiling. Where is price relative to them?"
        g["none_why"] = ("Price is in the middle of the range, far from both support and resistance. There is no nearby level "
                         "to anchor a stop to, so any stop is a guess, and the room to the ceiling is modest.")
        g["notes"] = ["There IS a range here (the green floor and red ceiling), but price is sitting in the middle of it.",
                      "Buying in the middle means your stop has to be far below support, or inside the range where it gets hit by noise.",
                      "Wait for price to come back to a level, or to break out of the range with volume."]
        return g
    if v == "chop":
        legs, left = [], _ri(rng, 70, 100)
        amp = _rr(rng, 0.03, 0.08)
        while left > 0:
            b = int(min(left, rng.integers(5, 12)))
            legs.append((b, P * (1 + rng.uniform(-amp, amp))))
            left -= b
        seg = _seg(rng, P, legs, s * 1.15, 1.0)
        why = ("There was no level tested over and over, no clean trend, no squeeze and no volume burst. Price was drifting "
               "in the middle of nowhere, so there was no spot where a stop clearly belongs.")
        hint = ("Nothing stands out: no level that keeps repeating, no clean trend, no squeeze. Ask yourself if you could name "
                "a clear place for a stop.")
        notes = ["No level has been tested over and over. No clean trend. No tight squeeze. No burst of volume.",
                 "Price is drifting in the middle of nowhere, which is the worst place to buy: no nearby level to put a stop "
                 "behind, so your stop is a guess.",
                 "Not every chart is a trade. Waiting is a position too, and it protects your small account from small cuts."]
        lines, drift = [], 0.0
    elif v == "knife":
        ctx = _context(rng, P * _rr(rng, 1.3, 1.6), P, _ri(rng, 55, 85), s, waves=3)
        up = _seg(rng, float(ctx["c"][-1]), [(_ri(rng, 2, 4), float(ctx["c"][-1]) * _rr(rng, 1.02, 1.045))], s, 1.2)
        seg = _cat(ctx, up)
        c0 = seg["c"]
        ema = pd.Series(c0).ewm(span=20, adjust=False).mean().to_numpy()
        if not (ema[-1] < ema[-10] and c0[-1] <= ema[-1] * 1.03):
            raise _Retry()
        why = ("The stock was in a downtrend: lower highs and lower lows with the 20-day line sloping down above price. A small "
               "bounce inside a downtrend is 'catching a falling knife'. No level had held, and the trend was against you.")
        hint = "The stock has been falling for weeks. Look at the direction of the orange line and whether the highs are getting lower."
        notes = ["Look at the trend: each rally tops out lower than the last (lower highs) and each dip goes lower (lower lows). "
                 "The orange 20-day line is sloping down and sits above price.",
                 "The last few green candles look tempting, but they are a small bounce inside a bigger fall.",
                 "No support level has held, so there is nowhere sensible to put a stop. Trading against the trend is the hard way.",
                 "Wait for the trend to change: price stops making lower lows, builds a base, and turns up."]
        lines, drift = [], -0.012
    else:
        ctx = _context(rng, P * 0.65, P * _rr(rng, 0.95, 1.0), _ri(rng, 35, 60), s)
        run = _seg(rng, float(ctx["c"][-1]), [(_ri(rng, 7, 11), float(ctx["c"][-1]) * _rr(rng, 1.14, 1.22))], s * 0.7, 1.8)
        seg = _cat(ctx, run)
        ema = pd.Series(seg["c"]).ewm(span=20, adjust=False).mean().to_numpy()
        if seg["c"][-1] / ema[-1] - 1 < 0.09:
            raise _Retry()
        why = ("Price had sprinted far above its 20-day line with no pause or base. Buying now is chasing: your stop would "
               "have to be far away, and there is no recent level to anchor it to.")
        hint = "The stock has run up fast with almost no pause. How far is price from the orange line?"
        notes = ["The stock has run up fast, and price is far above the orange 20-day line with no pause or base.",
                 "Buying now is chasing. The nearest sensible level for a stop is far below, so you'd risk a lot to make a little.",
                 "Wait for a pause (a flag or base) or a pullback toward the 20-day line, then look for a setup."]
        lines, drift = [], 0.0
    o, h, l, c = _fix(seg["o"], seg["h"], seg["l"], seg["c"])
    seg.update(o=o, h=h, l=l, c=c)
    atr = _atr(h, l, c)
    out = {"arr": seg, "variant": v, "levels": [], "zones": [], "points": [], "lines": lines,
           "stop": float(c[-1]) - 2 * atr, "target": None, "hint": hint, "none_why": why, "notes": notes, "drift": drift}
    if v == "knife":
        k = min(45, len(h))
        xs = np.arange(len(h) - k, len(h))
        m, b = np.polyfit(xs, h[-k:], 1)
        out["lines"] = [_line(xs[0], m * xs[0] + b, xs[-1], m * xs[-1] + b, "Lower highs", RESIST_C, "dot")]
    return out


GEN = {"range": _gen_range, "bounce": _gen_bounce, "breakout": _gen_breakout, "pullback": _gen_pullback,
       "flag": _gen_flag, "triangle": _gen_triangle, "double": _gen_double, "cup": _gen_cup, "none": _gen_none}

# how a winning / losing second half behaves, as a fraction of the risk distance
FUT = {"range": dict(dip=0.25, up=0.0, k2=(8, 13)), "bounce": dict(dip=0.25, up=0.0, k2=(6, 11)),
       "breakout": dict(dip=0.40, up=0.35, k2=(6, 11)), "pullback": dict(dip=0.30, up=0.0, k2=(6, 11)),
       "flag": dict(dip=0.30, up=0.30, k2=(6, 11)), "triangle": dict(dip=0.30, up=0.30, k2=(6, 11)),
       "double": dict(dip=0.35, up=0.30, k2=(6, 11)), "cup": dict(dip=0.30, up=0.30, k2=(6, 11))}


def _future(rng, entry, stop, target, success, s, kind, vol_base, drift=0.0):
    risk = entry - stop
    pr = FUT.get(kind)
    if kind == "none" or pr is None:
        legs = [(5, entry * (1 + drift * 5 * (i + 1) + rng.normal(0, 0.03))) for i in range(FUT_BARS // 5)]
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
        s = float(rng.uniform(0.0075, 0.015))
        try:
            g = GEN[kind](rng, s)
        except _Retry:
            continue
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
        f = _future(rng, entry, stop, target, bool(want), s, kind, float(hist.Volume.median()), g.get("drift", 0.0))
        fut = pd.DataFrame({"Open": f["o"], "High": f["h"], "Low": f["l"], "Close": f["c"], "Volume": f["v"]})
        out = simulate_plan(fut, entry, stop, target)
        best = (hist, fut, g, entry, stop, target, out)
        if kind == "none":
            break
        if (want and out["reason"].startswith("Target")) or (not want and out["reason"].startswith("Stop")):
            break
        if attempt >= 60:           # good enough: a valid chart whose outcome we simply report truthfully
            break
    if best is None:                 # extremely unlikely; fall back to a fixed, known-good draw
        return make_chart(kind, int(seed) + 1)
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


def chart_cone(chart):
    """The likely-range cone for the next MAX_HOLD days, from the visible half only (no peeking at the future)."""
    import forecast as fc
    return fc.range_cone(chart["hist"], horizon=MAX_HOLD, min_history=40, dates=False)


def _add_cone(fig, cone, h):
    import plotly.graph_objects as go

    xs = [h - 1] + list(range(h, h + len(cone["lo68"])))
    p0 = cone["price"]
    tips = [""] + [f"<b>Day {t + 1} from the decision point</b><br>Usually (about 2 in 3): {cone['lo68'][t]:,.2f} to {cone['hi68'][t]:,.2f}"
                   f"<br>Almost always (about 19 in 20): {cone['lo95'][t]:,.2f} to {cone['hi95'][t]:,.2f}"
                   "<br><i>A range of what is normal, not a prediction.</i>" for t in range(len(cone["lo68"]))]
    line_c = "rgba(41,182,246,0.55)"
    for name, hi, lo, fc_, w in (("Wider range (about 19 in 20)", cone["hi95"], cone["lo95"], "rgba(41,182,246,0.10)", 0.6),
                                 ("Likely range (about 2 in 3)", cone["hi68"], cone["lo68"], "rgba(41,182,246,0.22)", 1.0)):
        fig.add_trace(go.Scatter(x=xs, y=[p0] + [float(v) for v in hi], mode="lines", name=name, legendgroup=name,
                                 line=dict(width=w, color=line_c), hovertext=tips, hoverinfo="text"), row=1, col=1)
        fig.add_trace(go.Scatter(x=xs, y=[p0] + [float(v) for v in lo], mode="lines", legendgroup=name, showlegend=False,
                                 line=dict(width=w, color=line_c), fill="tonexty", fillcolor=fc_,
                                 hovertext=tips, hoverinfo="text"), row=1, col=1)
    for val, anchor in ((cone["hi68"][-1], "bottom"), (cone["lo68"][-1], "top")):
        fig.add_annotation(x=xs[-1], y=float(val), text=f"{val:,.2f}", showarrow=False, xanchor="left", yanchor=anchor,
                           font=dict(size=11, color="#81d4fa"), row=1, col=1)


def build_figure(chart, markup=True, reveal=False, user_plan=None, quiz_lines=None, basics=False, show_plan=None,
                 height=640, cone=None):
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
    if cone:
        _add_cone(fig, cone, h)
    for lab, y in (quiz_lines or []):
        hline(y, f"{lab}", "#ce93d8", "dash", h - 8, h + 8)
        fig.add_annotation(x=h + 8.4, y=y, text=f"<b>{lab}</b>", showarrow=False, xanchor="left",
                           font=dict(size=15, color="#ce93d8"), row=1, col=1)

    fig.add_trace(go.Scatter(x=[h - 0.5, h - 0.5], y=[float(hist.Low.min()), float(hist.High.max())], mode="lines",
                             line=dict(color="rgba(255,255,255,0.35)", dash="dot", width=1), hoverinfo="skip",
                             showlegend=False), row=1, col=1)
    fig.add_annotation(x=h - 0.5, y=float(hist.High.max()), text="Decision point  →", showarrow=False,
                       xanchor="right", yanchor="bottom", font=dict(size=11, color="#bbbbbb"), row=1, col=1)
    fig.update_layout(template=design.CHART, height=height, xaxis_rangeslider_visible=False, hovermode="closest",
                      legend=dict(orientation="h", y=1.05), margin=dict(l=10, r=10, t=30, b=10),
                      xaxis3=dict(title=dict(text="Trading days (each candle is one day)")))
    fig.update_xaxes(range=[-1, xmax + 2])
    # Fix the price range so nothing gets cut off at the top or bottom: include the candles, the cone, the plan lines
    # and any quiz lines, with a little padding.
    lows, highs = [float(full.Low.min())], [float(full.High.max())]
    if cone:
        lows.append(float(cone["lo95"].min())); highs.append(float(cone["hi95"].max()))
    if plan:
        lows.append(float(min(plan["stop"], plan["entry"]))); highs.append(float(max(plan["target"], plan["entry"])))
    for _, y in (quiz_lines or []):
        lows.append(float(y)); highs.append(float(y))
    lo_y, hi_y = min(lows), max(highs)
    pad = (hi_y - lo_y) * 0.05
    fig.update_yaxes(title_text="Price", range=[lo_y - pad, hi_y + pad], row=1, col=1)
    fig.update_yaxes(title_text="Volume", row=2, col=1)
    fig.update_yaxes(title_text="RSI", row=3, col=1)
    return fig


def _rgba(hexcolor, a):
    hc = hexcolor.lstrip("#")
    r, g_, b = (int(hc[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g_},{b},{a})"


def quiz_stop_options(chart, rng_seed):
    """Three candidate stop prices (shuffled A/B/C) and which letter is the sensible one.

    The two wrong lines vary: each is either too tight (0.3-0.7 of the real risk) or too far (1.8-3.6 times), so the
    right one is not always 'the middle one' and has to be judged from the chart.
    """
    p = chart["plan"]
    r = np.random.default_rng(int(rng_seed) + 12345)
    risk = p["entry"] - p["stop"]
    decoys = []
    for _ in range(2):
        if r.random() < 0.5:
            decoys.append(("tight", p["entry"] - float(r.uniform(0.3, 0.7)) * risk))
        else:
            decoys.append(("far", max(p["entry"] - float(r.uniform(1.8, 3.6)) * risk, p["entry"] * 0.3)))
    if abs(decoys[0][1] - decoys[1][1]) < 0.12 * risk:          # two near-identical decoys would be confusing
        decoys[1] = (decoys[1][0], decoys[1][1] + (0.2 if decoys[1][0] == "tight" else -0.5) * risk)
    cands = [("good", p["stop"])] + decoys
    order = list(r.permutation(3))
    letters = ["A", "B", "C"]
    lines = [(letters[i], cands[j][1]) for i, j in enumerate(order)]
    answer = letters[[cands[j][0] for j in order].index("good")]
    why = {letters[i]: cands[j][0] for i, j in enumerate(order)}
    return lines, answer, why

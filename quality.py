"""
quality.py - one 0-100 "setup quality" score for swing-scan results, plus an honest test of whether it helps.

The score blends five things, each turned into 0-1 and weighted:
  * Past results     (30%)  how this same setup did on THIS stock before (avg R). Skipped if fewer than 3 past trades.
  * Room to target   (25%)  is the target inside the stock's usual 15-day range? Far-away targets usually time out.
  * Strength vs market (20%) did the stock beat the S&P 500 (SPY) over the last ~3 months? Leaders hold up better.
  * Trend strength   (15%)  how far the 20 EMA sits above the 200 EMA.
  * Volume           (10%)  signal-day volume compared with normal.
A part that can't be measured (for example no SPY data) is left out and the rest are re-weighted.

The weights are a reasonable starting guess, NOT something fitted to data. evaluate() checks, on past trades and using only
information that existed on each signal day, whether higher scores really did better. Believe the score only if that test
says so; it is expected to be noisy with few trades.
"""

import numpy as np
import pandas as pd

import backtest as bt
import signal_overlay as so

WEIGHTS = {"past": 0.30, "room": 0.25, "rs": 0.20, "trend": 0.15, "vol": 0.10}
HORIZON = 15
RS_DAYS = 63
MIN_PAST = 3


def _clip01(x):
    return float(min(1.0, max(0.0, x)))


def parts(past_avg_r=None, room=None, rs=None, trend=None, rvol=None):
    """Each ingredient as 0-1 (None when it can't be measured)."""
    def ok(x):
        return x is not None and x == x

    return {
        "past": _clip01((past_avg_r + 0.3) / 0.8) if ok(past_avg_r) else None,
        "room": _clip01((2.0 - room) / 1.2) if ok(room) else None,           # <=0.8 of usual range -> 1, >=2.0 -> 0
        "rs": _clip01((rs + 0.05) / 0.20) if ok(rs) else None,               # -5% -> 0, +15% -> 1 (vs SPY, ~3 months)
        "trend": _clip01(trend / 0.12) if ok(trend) else None,
        "vol": _clip01((rvol - 0.8) / 1.7) if ok(rvol) else None,
    }


def score_from_parts(p):
    have = {k: v for k, v in p.items() if v is not None}
    if not have:
        return None
    w = sum(WEIGHTS[k] for k in have)
    return round(100 * sum(WEIGHTS[k] * v for k, v in have.items()) / w, 0)


def explain(p, raw, bench="SPY"):
    """Plain-English reasons, best first, mentioning the weak spot if there is one."""
    good, weak = [], []
    if p["past"] is not None:
        (good if p["past"] >= 0.6 else weak if p["past"] <= 0.3 else []).append(
            ("strong history here" if p["past"] >= 0.6 else "poor history here") + f" ({raw['past_avg_r']:+.2f}R avg)")
    if p["room"] is not None:
        (good if p["room"] >= 0.8 else weak if p["room"] <= 0.25 else []).append(
            "target inside the usual range" if p["room"] >= 0.8 else "target is a stretch for this stock")
    if p["rs"] is not None:
        (good if p["rs"] >= 0.6 else weak if p["rs"] <= 0.25 else []).append(
            f"beating the market ({raw['rs'] * 100:+.0f}% vs {bench} over 3 months)" if p["rs"] >= 0.6
            else f"lagging the market ({raw['rs'] * 100:+.0f}% vs {bench} over 3 months)")
    if p["trend"] is not None and p["trend"] >= 0.7:
        good.append("strong uptrend")
    if p["vol"] is not None:
        (good if p["vol"] >= 0.6 else weak if p["vol"] <= 0.1 else []).append(
            "heavy volume" if p["vol"] >= 0.6 else "light volume")
    out = good[:3]
    if weak:
        out.append("but " + weak[0])
    return ", ".join(out) if out else "middle of the pack on every measure"


def feature_series(df, flags, spy_close, stop_mult, reward_risk, horizon=HORIZON):
    """Per-day inputs for every bar of one stock (uses only data up to each bar)."""
    close = df["Close"].astype(float)
    r = np.log(close).diff()
    var = r.pow(2).ewm(alpha=0.06, adjust=False).mean()
    slow = r.pow(2).rolling(60).mean()
    sig = np.sqrt(0.6 * var + 0.4 * slow)
    atr = flags["atr"].astype(float)
    target_pct = reward_risk * stop_mult * atr / close
    room = target_pct / (sig * np.sqrt(horizon))
    trend = df["EMA20"] / df["EMA200"] - 1
    if spy_close is not None and len(spy_close):
        sp = spy_close.copy()
        sp.index = pd.DatetimeIndex(sp.index).tz_localize(None) if getattr(sp.index, "tz", None) is not None else sp.index
        idx = pd.DatetimeIndex(close.index).tz_localize(None) if getattr(close.index, "tz", None) is not None else close.index
        sp = sp.reindex(idx, method="ffill").astype(float)
        rs = (close.to_numpy() / close.shift(RS_DAYS).to_numpy() - 1) - (sp.to_numpy() / sp.shift(RS_DAYS).to_numpy() - 1)
        rs = pd.Series(rs, index=close.index)
    else:
        rs = pd.Series(np.nan, index=close.index)
    return pd.DataFrame({"room": room, "trend": trend, "rs": rs, "rvol": flags["rvol"].astype(float)}, index=df.index)


def score_row(feat_row, past_avg_r=None, past_n=0):
    raw = {"past_avg_r": past_avg_r if (past_n or 0) >= MIN_PAST else None, "room": feat_row["room"], "rs": feat_row["rs"],
           "trend": feat_row["trend"], "rvol": feat_row["rvol"]}
    p = parts(raw["past_avg_r"], raw["room"], raw["rs"], raw["trend"], raw["rvol"])
    return score_from_parts(p), p, raw


# ----------------------------------------------------------------------------- testing the score on history
def score_trades(frames, criteria, params, spy_close=None, progress=None, weekday=None):
    """Backtest trades (as bt.run_backtest) with the score each one had on its signal day, using only earlier information."""
    import scanner as sc

    rows = []
    for n, (sym, d) in enumerate(frames.items()):
        if progress:
            progress(n / max(len(frames), 1), sym)
        if len(d) < so.MIN_BARS + 20:
            continue
        df = so.add_indicators(d)
        flags = sc.swing_setup_flags(df, criteria)
        trades = [t for t in bt.backtest_symbol(df, flags, params, weekday=weekday) if t["reason"] != "Still open"]
        if not trades:
            continue
        feat = feature_series(df, flags, spy_close, params.stop_atr_mult, params.reward_risk,
                              getattr(criteria, "horizon", HORIZON))
        done = []
        for t in trades:                                    # trades come in time order, one at a time per stock
            i = t["signal_idx"]
            pr = [x for x in done]
            avg = float(np.mean(pr)) if pr else None
            sc_, _, _ = score_row(feat.iloc[i], avg, len(pr))
            if sc_ is not None:
                rows.append({"symbol": sym, "entry_date": t["entry_date"], "r": t["r"], "score": sc_,
                             "rvol": feat["rvol"].iloc[i], "days": t["days"]})
            done.append(t["r"])
    return pd.DataFrame(rows)


def _line(label, g):
    if g is None or len(g) == 0:
        return {"Group": label, "Trades": 0}
    return {"Group": label, "Trades": int(len(g)), "Win rate %": round(float((g["r"] > 0).mean() * 100), 1),
            "Avg R": round(float(g["r"].mean()), 3), "Avg days": round(float(g["days"].mean()), 1)}


def evaluate(t):
    """
    Did higher scores do better? Compares thirds by score, the old ranking (volume), and the best-of-the-day pick.
    Returns (table, verdict_text).
    """
    if t is None or len(t) < 60:
        return pd.DataFrame(), "Too few trades to judge (need at least about 60). Test more stocks or a longer history."
    t = t.sort_values("score", kind="stable").reset_index(drop=True)
    k = len(t) // 3
    bot, mid, top = t.iloc[:k], t.iloc[k:len(t) - k], t.iloc[len(t) - k:]
    vol_top = t.sort_values("rvol", kind="stable").iloc[len(t) - k:]
    lines = [_line("All setups", t), _line("Top third by score", top), _line("Middle third", mid),
             _line("Bottom third by score", bot), _line("Top third by volume (old sort)", vol_top)]
    # one pick per day: the highest-scoring (or highest-volume) candidate on days with 2+ candidates
    day = t.groupby(t["entry_date"].dt.normalize())
    multi = [g for _, g in day if len(g) >= 2]
    if len(multi) >= 20:
        by_score = pd.concat([g.sort_values("score", kind="stable").iloc[-1:] for g in multi])
        by_vol = pd.concat([g.sort_values("rvol", kind="stable").iloc[-1:] for g in multi])
        avg_all = pd.concat(multi)
        lines += [_line(f"Days with 2+ setups ({len(multi)} days): average pick", avg_all),
                  _line("...pick with the best score", by_score), _line("...pick with the most volume", by_vol)]
    tab = pd.DataFrame(lines)
    diff = float(top["r"].mean() - bot["r"].mean())
    se = float(np.sqrt(top["r"].var() / max(len(top), 1) + bot["r"].var() / max(len(bot), 1)))
    if diff > 2 * se:
        v = (f"Top-third setups beat bottom-third ones by {diff:.2f}R per trade, which is larger than the noise "
             f"(about {se:.2f}R). That is evidence the score helps on this data.")
    elif diff < -2 * se:
        v = (f"Top-third setups did WORSE than bottom-third ones by {-diff:.2f}R per trade, more than the noise "
             f"(about {se:.2f}R). On this data the score points the wrong way, so don't rely on it.")
    else:
        v = (f"The top-third minus bottom-third gap is {diff:+.2f}R per trade, within the noise (about {se:.2f}R). "
             "There is no proof the score helps on this data; treat it as a tie-breaker at most.")
    return tab, v

"""
forecast.py - a "likely range" for where a stock could be over the next few weeks.

This is NOT a prediction of direction. It answers: "given how much this stock has
actually been moving lately, how far could it wander?"

How it works (plain English):
  1. Measure the stock's recent daily wiggle (volatility), weighting recent days more.
  2. The range widens with the square root of time (a stock wanders further the
     longer you wait, but not in a straight line).
  3. Check the stock's own history: how often did price really stay inside bands of
     that size? If it stayed inside less often than it should (surprise moves are
     common), the bands are widened to match. So the bands are calibrated to the
     stock, not just copied from a textbook formula.
  4. The band is centered on today's price. Direction is left open on purpose.

Also here: how often a stop/target plan like yours worked on this same stock in the
past (entering on ordinary days, and on days when a swing setup appeared).

Known limits: volatility changes (a calm stock can suddenly get wild, especially
around earnings), history does not repeat exactly, and big news can blow through
any band. Treat it as a map of what is normal, not a promise.
"""

import numpy as np
import pandas as pd

import backtest as bt

HORIZON = 15           # trading days, same as the default max hold
EWMA_LAMBDA = 0.94     # standard "RiskMetrics" decay for daily volatility
MIN_HISTORY = 120      # bars needed before a range is trusted
INNER_Q, OUTER_Q = 0.68, 0.95   # what share of the time price should land inside each band


def daily_sigma(close):
    """Today's estimated daily volatility (a fraction, 0.02 = 2% a day), recent days weighted most."""
    r = np.log(pd.Series(close, dtype=float)).diff().dropna()
    if len(r) < 30:
        return None
    var = r.pow(2).ewm(alpha=1 - EWMA_LAMBDA, adjust=False).mean()
    slow = r.tail(60).pow(2).mean()
    # blend fast and slow so one wild day doesn't dominate and a calm spell doesn't fool us
    blended = 0.6 * float(var.iloc[-1]) + 0.4 * float(slow)
    s = float(np.sqrt(blended))
    return s if np.isfinite(s) and s > 0 else None


def _calibrate(close, horizon):
    """
    Find how many 'sigmas' the inner and outer bands need to be so that, on this stock's own
    history, price really landed inside them about 68% and 95% of the time.
    Returns (k_inner, k_outer, samples).
    """
    c = pd.Series(close, dtype=float).reset_index(drop=True)
    r = np.log(c).diff()
    var = r.pow(2).ewm(alpha=1 - EWMA_LAMBDA, adjust=False).mean()
    slow = r.pow(2).rolling(60).mean()
    sig = np.sqrt(0.6 * var + 0.4 * slow)
    fwd = np.log(c.shift(-horizon) / c)
    z = (fwd / (sig * np.sqrt(horizon))).replace([np.inf, -np.inf], np.nan)
    z = z.iloc[70:].dropna()          # skip the warm-up bars
    if len(z) < 100:
        return 1.0, 2.0, len(z)
    # Subtract the stock's own average drift so a stock that happened to climb for years doesn't
    # make the bands lopsided; the cone is centered on today's price on purpose.
    zc = (z - z.median()).abs()
    k_in = float(np.clip(zc.quantile(INNER_Q), 0.7, 1.6))
    k_out = float(np.clip(zc.quantile(OUTER_Q), 1.5, 3.5))
    return k_in, max(k_out, k_in + 0.4), len(z)


def future_days(last_ts, n):
    """The next n trading days (weekdays; skips real holidays when exchange_calendars is installed)."""
    import signal_overlay as so
    start = pd.Timestamp(last_ts).tz_localize(None).normalize() if pd.Timestamp(last_ts).tzinfo else pd.Timestamp(last_ts).normalize()
    cal = so._calendar()
    days = []
    d = start
    while len(days) < n:
        d = d + pd.Timedelta(days=1)
        if d.weekday() >= 5:
            continue
        if cal is not None:
            try:
                if not cal.is_session(d.strftime("%Y-%m-%d")):
                    continue
            except Exception:
                pass
        days.append(d)
    return pd.DatetimeIndex(days)


def range_cone(df, horizon=HORIZON):
    """
    The likely-range cone for the next `horizon` trading days.
    Returns a dict, or None when there isn't enough history:
      dates, mid (flat at today's price), lo68/hi68, lo95/hi95 (arrays), price, sigma, k_in, k_out,
      samples, end68/end95 as (low, high) at the end of the window, pct68/pct95 as +/- % at the end.
    """
    close = df["Close"].astype(float)
    if len(close) < MIN_HISTORY:
        return None
    s = daily_sigma(close)
    if s is None:
        return None
    k_in, k_out, n = _calibrate(close.to_numpy(), horizon)
    price = float(close.iloc[-1])
    t = np.arange(1, horizon + 1)
    spread = s * np.sqrt(t)
    out = {
        "dates": future_days(df.index[-1], horizon), "price": price, "sigma": s, "horizon": horizon,
        "k_in": k_in, "k_out": k_out, "samples": n,
        "mid": np.full(horizon, price),
        "lo68": price * np.exp(-k_in * spread), "hi68": price * np.exp(k_in * spread),
        "lo95": price * np.exp(-k_out * spread), "hi95": price * np.exp(k_out * spread),
    }
    out["end68"] = (float(out["lo68"][-1]), float(out["hi68"][-1]))
    out["end95"] = (float(out["lo95"][-1]), float(out["hi95"][-1]))
    out["pct68"] = float((out["hi68"][-1] / price - 1) * 100)
    out["pct95"] = float((out["hi95"][-1] / price - 1) * 100)
    out["pct68_down"] = float((1 - out["lo68"][-1] / price) * 100)
    out["pct95_down"] = float((1 - out["lo95"][-1] / price) * 100)
    return out


def typical_range_pct(close, horizon=HORIZON):
    """Quick number for tables: the 68% band's half-width in percent after `horizon` days (None if unknown)."""
    close = pd.Series(close, dtype=float)
    if len(close) < 60:
        return None
    s = daily_sigma(close)
    if s is None:
        return None
    return float((np.exp(s * np.sqrt(horizon)) - 1) * 100)


def plan_history(df, flags, stop_atr_mult, reward_risk, max_hold=HORIZON, cost_pct=0.2, last_n=750):
    """
    How a stop/target plan like yours did on this same stock: enter at the next open, stop `stop_atr_mult` ATR
    below, target `reward_risk` times the risk above, give up after `max_hold` days.
    Returns {"all": {...}, "setup": {...}} where each has trades, target, stop, timeout (counts) and avg_r.
    'all' uses every ordinary day in the window; 'setup' only days a swing setup appeared.
    """
    p = bt.BTParams(stop_atr_mult=stop_atr_mult, reward_risk=reward_risk, max_hold=max_hold, cost_pct=cost_pct)
    atr = flags["atr"].to_numpy(float)
    setup = (flags["pullback"] | flags["breakout"] | flags["bounce"]).to_numpy(bool)
    n = len(df)
    start = max(0, n - last_n)
    rows = []
    for i in range(start, n - 1):
        # a trade that is still running at the end of the data tells us nothing yet
        if i + max_hold >= n:
            break
        t = bt.simulate_trade(df, i, atr[i], p)
        if t is None:
            continue
        rows.append((bool(setup[i]), t["reason"], t["r"]))

    def summarize(sel):
        if not sel:
            return {"trades": 0}
        reasons = [r for _, r, _ in sel]
        tgt = sum(1 for r in reasons if r.startswith("Target"))
        stp = sum(1 for r in reasons if r.startswith("Stop"))
        tmo = len(sel) - tgt - stp
        return {"trades": len(sel), "target": tgt, "stop": stp, "timeout": tmo,
                "target_pct": tgt / len(sel) * 100, "stop_pct": stp / len(sel) * 100,
                "timeout_pct": tmo / len(sel) * 100, "avg_r": float(np.mean([x for _, _, x in sel]))}

    return {"all": summarize(rows), "setup": summarize([x for x in rows if x[0]]),
            "breakeven_pct": 100 / (1 + reward_risk), "days": max_hold}

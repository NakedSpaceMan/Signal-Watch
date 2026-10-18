#!/usr/bin/env python3
"""
scanner.py - Low-float momentum scanner (Yahoo Finance data).

Default criteria (matches your scanner):
    Change % (1 day, vs prior close)  >= 10
    Price                             $1 - $20
    Float                             <= 20M shares
    Relative volume (30 day)          >  5

Extra safety filter (not in your original): today's volume >= 100,000 shares,
because a 5x relative volume on a stock that normally trades a few thousand
shares a day means very little. Set --min-volume 0 to turn it off.

Usage:
    python scanner.py                          # scan the whole US market
    python scanner.py --tickers ABCD EFGH IJKL # scan only your own list
    python scanner.py --min-rvol 3 --max-float 30000000

Notes on the data:
  * Price is the last traded price (Yahoo has no reliable live ask).
  * Relative volume is time-of-day adjusted: volume so far today versus the
    average volume over the same stretch of the previous 30 sessions.
  * Float comes from Yahoo and is sometimes missing or stale. Stocks with no
    float figure are excluded and counted in the stats.
  * Free Yahoo data can be delayed, which matters a lot for fast small caps.

Two scanners:
    * Low-float momentum (above): fast, volatile, high risk.
    * Steady uptrend pullbacks (--steady): liquid US stocks in a daily uptrend
      (price above the 200 EMA, 20 EMA above the 200 EMA) that have pulled back
      near the 20 EMA with a calm RSI and modest daily swings. Slower, lower risk.

    * Swing setups (--swing): once-a-day scan of daily charts for pullbacks,
      breakouts and oversold bounces inside uptrends, with a suggested stop,
      target and position size. Run it after the close or before the open.

All can be enriched (--enrich) with a catalyst check (recent Yahoo headlines,
upcoming earnings, red-flag keywords) and a current-signal check using the same
EMA/RSI/MACD/Bollinger rules as the chart.

Not financial advice.
"""

import argparse
import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
import pandas as pd

import signal_overlay as so

OTC_CODES = {"PNK", "OQB", "OQX", "OTC", "OTCBB", "OTCQB", "OTCQX"}


@dataclass
class Criteria:
    min_change: float = 10.0          # percent
    min_price: float = 1.0
    max_price: float = 20.0
    max_float: float = 20_000_000     # shares
    min_rvol: float = 5.0
    min_volume: int = 100_000         # shares traded today (extra filter)
    rvol_days: int = 30
    min_dollar_volume: float = 250_000  # price x shares traded today (liquidity filter)
    max_candidates: int = 750         # most movers to pull from Yahoo's screener


def _stamp(stats):
    """Record when/how the data was gathered so the UI can show its quality."""
    stats["asof"] = pd.Timestamp.now().strftime("%H:%M:%S")
    stats["session"] = so.market_session_label()
    return stats


# ---------------------------------------------------------------- candidates
def _normalize_quote(q):
    """Turn a Yahoo screener quote dict into our simple dict (or None)."""
    sym = q.get("symbol")
    price = q.get("regularMarketPrice")
    chg = q.get("regularMarketChangePercent")
    vol = q.get("regularMarketVolume")
    if not sym or price is None or chg is None:
        return None
    if q.get("quoteType") not in (None, "EQUITY"):
        return None
    exch = str(q.get("exchange", "")).upper()
    full = str(q.get("fullExchangeName", "")).upper()
    if exch in OTC_CODES or "OTC" in full or "PINK" in full:
        return None
    return {
        "symbol": sym,
        "name": q.get("shortName") or q.get("longName") or "",
        "price": float(price),
        "change_pct": float(chg),
        "volume": int(vol or 0),
    }


def market_candidates(c, page=250):
    """
    Ask Yahoo's screener for US stocks matching the price/change/volume filters,
    paging through results up to c.max_candidates. Returns (quotes, meta) where
    meta says how many came back and whether the cap cut the list short.
    """
    import yfinance as yf

    try:
        EquityQuery = yf.EquityQuery
        screen = yf.screen
    except AttributeError as e:
        raise RuntimeError(
            "This version of yfinance has no market screener. Run "
            "'pip install -U yfinance', or scan your own list with --tickers."
        ) from e

    query = EquityQuery("and", [
        EquityQuery("eq", ["region", "us"]),
        EquityQuery("gte", ["percentchange", c.min_change]),
        EquityQuery("btwn", ["intradayprice", c.min_price, c.max_price]),
        EquityQuery("gte", ["dayvolume", c.min_volume]),
    ])
    out, seen, fetched, capped = [], set(), 0, False
    for offset in range(0, c.max_candidates, page):
        size = min(page, c.max_candidates - offset)
        try:
            res = screen(query, offset=offset, size=size, sortField="percentchange", sortAsc=False)
        except Exception:
            if offset == 0:
                raise
            break
        quotes = res.get("quotes", []) if isinstance(res, dict) else []
        fetched += len(quotes)
        for q in quotes:
            nq = _normalize_quote(q)
            if nq and nq["symbol"] not in seen:
                seen.add(nq["symbol"])
                out.append(nq)
        if len(quotes) < size:
            break
        if offset + size >= c.max_candidates:
            capped = True
    return out, {"fetched": fetched, "capped": capped}


def _quote_from_history(sym):
    """Price, 1-day change and volume for one ticker (used for your own list)."""
    import yfinance as yf

    try:
        h = yf.Ticker(sym).history(period="5d", interval="1d")
        if len(h) < 2:
            return None
        last, prev = h.iloc[-1], h.iloc[-2]
        return {
            "symbol": sym.upper(),
            "name": "",
            "price": float(last.Close),
            "change_pct": float((last.Close / prev.Close - 1) * 100),
            "volume": int(last.Volume),
        }
    except Exception:
        return None


# ---------------------------------------------------------------- enrichment
def get_float(sym):
    import yfinance as yf

    try:
        f = yf.Ticker(sym).info.get("floatShares")
        return int(f) if f else None
    except Exception:
        return None


def relative_volume(sym, days=30):
    """
    Volume so far today / average volume over the same time window in the
    previous `days` sessions. Needs 5-minute data (Yahoo keeps ~60 days).
    """
    import yfinance as yf

    try:
        h = yf.Ticker(sym).history(period="60d", interval="5m")
    except Exception:
        return None
    if h is None or h.empty:
        return None

    idx = h.index
    dates = np.array(idx.date)
    times = np.array(idx.time)
    vols = h["Volume"].to_numpy(dtype=float)
    cutoff = idx[-1].time()
    today = dates[-1]

    cum = {}
    for d in np.unique(dates):
        mask = (dates == d) & (times <= cutoff)
        cum[d] = vols[mask].sum()

    prev = [v for d, v in sorted(cum.items()) if d != today][-days:]
    prev = [v for v in prev if v > 0]
    if len(prev) < 5:
        return None
    avg = float(np.mean(prev))
    return float(cum[today] / avg) if avg > 0 else None


# ---------------------------------------------------------------- the scan
def scan(c, tickers=None, workers=4, also_market=False):
    """
    Returns (DataFrame of matches, stats dict). With `tickers`, only those are
    scanned unless also_market=True, which adds them to the whole-market scan.
    Raises RuntimeError if the market-wide screener is unavailable.
    """
    stats = {"candidates": 0, "passed_basic": 0, "unknown_float": 0,
             "too_much_float": 0, "no_rvol": 0, "matches": 0, "fetched": 0, "capped": False}

    cands = []
    if tickers:
        syms = sorted({t.strip().upper() for t in tickers if t.strip()})
        with ThreadPoolExecutor(workers) as ex:
            cands = [q for q in ex.map(_quote_from_history, syms) if q]
    if not tickers or also_market:
        market, meta = market_candidates(c)
        known = {q["symbol"] for q in cands}
        cands += [q for q in market if q["symbol"] not in known]
        stats["fetched"], stats["capped"] = meta["fetched"], meta["capped"]
    stats["candidates"] = len(cands)
    _stamp(stats)

    cands = [q for q in cands
             if q["change_pct"] >= c.min_change
             and c.min_price <= q["price"] <= c.max_price
             and q["volume"] >= c.min_volume
             and q["price"] * q["volume"] >= c.min_dollar_volume]
    stats["passed_basic"] = len(cands)

    def enrich(q):
        q = dict(q)
        q["float"] = get_float(q["symbol"])
        q["rvol"] = None
        if q["float"] is not None and q["float"] <= c.max_float:
            q["rvol"] = relative_volume(q["symbol"], c.rvol_days)
        return q

    with ThreadPoolExecutor(workers) as ex:
        rows = list(ex.map(enrich, cands))

    stats["unknown_float"] = sum(1 for q in rows if q["float"] is None)
    stats["too_much_float"] = sum(1 for q in rows if q["float"] is not None and q["float"] > c.max_float)
    small = [q for q in rows if q["float"] is not None and q["float"] <= c.max_float]
    stats["no_rvol"] = sum(1 for q in small if q["rvol"] is None)
    hits = [q for q in small if q["rvol"] is not None and q["rvol"] > c.min_rvol]
    stats["matches"] = len(hits)

    df = pd.DataFrame(
        [{
            "Symbol": q["symbol"],
            "Name": q["name"],
            "Price": round(q["price"], 2),
            "Change %": round(q["change_pct"], 1),
            "Float (M)": round(q["float"] / 1e6, 1),
            "Rel Vol": round(q["rvol"], 1),
            "Volume": q["volume"],
        } for q in hits],
        columns=["Symbol", "Name", "Price", "Change %", "Float (M)", "Rel Vol", "Volume"],
    )
    if not df.empty:
        df = df.sort_values("Rel Vol", ascending=False).reset_index(drop=True)
    return df, stats


def stats_line(stats):
    if stats.get("kind") == "swing":
        return (f"{stats['universe']} liquid stocks checked, {stats['loaded']} had enough history, "
                f"{stats['trend']} in an uptrend, {stats['setup']} showed a swing setup, "
                f"{stats['earnings_skipped']} skipped for earnings soon, {stats['matches']} match.")
    if "universe" in stats:
        return (f"{stats['universe']} liquid stocks checked, {stats['loaded']} had enough history, "
                f"{stats['trend']} in an uptrend, {stats['setup']} also pulled back calmly near the 20 EMA, "
                f"{stats['earnings_skipped']} skipped for earnings soon, {stats['matches']} match.")
    cap = (f" (hit the {stats['fetched']}-stock cap, so more movers may exist)" if stats.get("capped") else "")
    return (f"{stats['candidates']} movers found{cap}, {stats['passed_basic']} passed price/change/volume, "
            f"{stats['too_much_float']} dropped for float too large, "
            f"{stats['unknown_float']} dropped for missing float, "
            f"{stats['no_rvol']} had no relative-volume data, "
            f"{stats['matches']} match.")


# ---------------------------------------------------------------- steady scanner
@dataclass
class SteadyCriteria:
    min_price: float = 10.0
    min_market_cap: float = 2_000_000_000
    min_avg_volume: int = 1_000_000      # 30-day average shares per day
    max_dist_ema20_pct: float = 3.0      # how close to the 20 EMA counts as a pullback
    rsi_min: float = 40.0
    rsi_max: float = 60.0
    max_atr_pct: float = 4.0             # average daily swing as % of price
    skip_earnings_days: int = 5          # drop stocks reporting within this many days (0 = keep)
    universe_size: int = 500
    min_dollar_volume: float = 10_000_000  # 30-day average dollars traded per day


def steady_universe(c):
    """Liquid US stocks from Yahoo's screener, most actively traded first."""
    import yfinance as yf

    try:
        EquityQuery = yf.EquityQuery
        screen = yf.screen
    except AttributeError as e:
        raise RuntimeError(
            "This version of yfinance has no market screener. Run "
            "'pip install -U yfinance', or scan your own list with a ticker list."
        ) from e

    query = EquityQuery("and", [
        EquityQuery("eq", ["region", "us"]),
        EquityQuery("gte", ["intradaymarketcap", c.min_market_cap]),
        EquityQuery("gte", ["intradayprice", c.min_price]),
        EquityQuery("gte", ["dayvolume", 300_000]),
    ])
    out, seen = [], set()
    for offset in range(0, c.universe_size, 250):
        size = min(250, c.universe_size - offset)
        try:
            res = screen(query, offset=offset, size=size, sortField="dayvolume", sortAsc=False)
        except Exception:
            if offset == 0:
                raise
            break
        quotes = res.get("quotes", []) if isinstance(res, dict) else []
        for q in quotes:
            nq = _normalize_quote(q)
            if nq and nq["symbol"] not in seen:
                seen.add(nq["symbol"])
                out.append((nq["symbol"], nq["name"]))
        if len(quotes) < size:
            break
    return out


def _daily_frames(symbols, chunk=80):
    """Yield (symbol, daily OHLCV DataFrame) for symbols with enough history."""
    import yfinance as yf

    for i in range(0, len(symbols), chunk):
        part = symbols[i:i + chunk]
        try:
            raw = yf.download(part, period="1y", interval="1d", group_by="ticker",
                              auto_adjust=True, progress=False, threads=True)
        except Exception:
            continue
        if raw is None or raw.empty:
            continue
        for sym in part:
            try:
                d = raw[sym] if isinstance(raw.columns, pd.MultiIndex) else raw
                d = d[["Open", "High", "Low", "Close", "Volume"]].dropna()
            except KeyError:
                continue
            if len(d) and so.daily_bar_in_progress(d.index[-1]):
                d = d.iloc[:-1]  # use finished sessions only
            if len(d) >= so.MIN_BARS:
                yield sym, d


def get_earnings_dates(sym, limit=12):
    """Yahoo's table of past and upcoming earnings dates with EPS estimate / actual / surprise, or None."""
    import yfinance as yf

    try:
        t = yf.Ticker(sym)
        try:
            d = t.get_earnings_dates(limit=limit)
        except AttributeError:
            d = t.earnings_dates
        return d if d is not None and len(d) else None
    except Exception:
        return None


def earnings_profile(dates, daily, fallback_days=None, today=None, max_reports=8):
    """
    Turn Yahoo's earnings table plus daily prices into something readable.
    dates: DataFrame indexed by report date with 'EPS Estimate', 'Reported EPS', 'Surprise(%)' (or None).
    daily: daily OHLCV bars (used to measure how the stock moved around each report).
    fallback_days: days to the next report from the calendar, if the table is unavailable.
    The 'move' is the change from the close before the report day to the close after it, which covers
    reports made before the open and after the close.
    """
    today = pd.Timestamp(today or pd.Timestamp.now()).normalize()

    def naive(ts):
        ts = pd.Timestamp(ts)
        return ts.tz_localize(None).normalize() if ts.tzinfo is not None else ts.normalize()

    out = {"available": False, "next_date": None, "next_days": fallback_days, "reports": [],
           "avg_abs_move": None, "beats": 0, "of": 0}
    if dates is None or len(dates) == 0:
        return out
    out["available"] = True
    idx = pd.DatetimeIndex(daily.index)
    idx = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
    close = daily["Close"].to_numpy(float)

    rows = sorted(((naive(d), r) for d, r in dates.iterrows()), key=lambda x: x[0])
    future = [d for d, _ in rows if d >= today]
    if future:
        out["next_date"] = future[0]
        out["next_days"] = int((future[0] - today).days)
    past = [(d, r) for d, r in rows if d < today][-max_reports:]
    reports = []
    for d, r in reversed(past):
        est, act = r.get("EPS Estimate"), r.get("Reported EPS")
        if pd.isna(act):
            continue
        sur = r.get("Surprise(%)")
        if (sur is None or pd.isna(sur)) and est is not None and pd.notna(est) and est != 0:
            sur = (act - est) / abs(est) * 100
        pos = int(idx.searchsorted(d))
        move = None
        if 1 <= pos and pos + 1 < len(close):
            move = (close[pos + 1] / close[pos - 1] - 1) * 100
        reports.append({"date": d, "est": None if pd.isna(est) else float(est), "actual": float(act),
                        "surprise": None if sur is None or pd.isna(sur) else float(sur), "move": move})
    out["reports"] = reports
    moves = [abs(x["move"]) for x in reports if x["move"] is not None]
    out["avg_abs_move"] = float(sum(moves) / len(moves)) if moves else None
    graded = [x for x in reports if x["surprise"] is not None]
    out["of"], out["beats"] = len(graded), sum(1 for x in graded if x["surprise"] > 0)
    return out


def earnings_links(sym):
    """Where to read the real release: SEC filings (earnings releases are filed on form 8-K) and Nasdaq's page."""
    s = sym.upper()
    return [("SEC filings (8-K: earnings releases)",
             f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={s}&type=8-K&dateb=&owner=include&count=10"),
            ("Nasdaq earnings page", f"https://www.nasdaq.com/market-activity/stocks/{s.lower()}/earnings")]


def get_earnings_days(sym):
    """Days until the next earnings report, or None if unknown."""
    import yfinance as yf

    try:
        cal = yf.Ticker(sym).calendar
        dates = None
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date")
        elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
            dates = list(cal.loc["Earnings Date"].dropna())
        if not dates:
            return None
        today = pd.Timestamp.now().normalize()
        days = [(pd.Timestamp(d).normalize() - today).days for d in dates]
        days = [d for d in days if d >= 0]
        return min(days) if days else None
    except Exception:
        return None


def build_universe(c, tickers, also_market):
    """Your typed/watchlist symbols, the whole liquid market, or both."""
    typed = [(t.strip().upper(), "") for t in (tickers or []) if t.strip()]
    if typed and not also_market:
        return typed
    universe = steady_universe(c)
    known = {sym for sym, _ in universe}
    return universe + [t for t in typed if t[0] not in known]


def steady_scan(c, tickers=None, workers=4, also_market=False):
    """Lower-risk scanner: liquid stocks in an uptrend that have pulled back calmly."""
    stats = {"universe": 0, "loaded": 0, "trend": 0, "setup": 0,
             "earnings_skipped": 0, "matches": 0, "no_data": 0}
    _stamp(stats)

    universe = build_universe(c, tickers, also_market)
    names = dict(universe)
    stats["universe"] = len(universe)
    last_bar = None

    rows = []
    for sym, d in _daily_frames([u[0] for u in universe]):
        stats["loaded"] += 1
        last_bar = max(last_bar, d.index[-1]) if last_bar is not None else d.index[-1]
        df = so.add_indicators(d)
        r = df.iloc[-1]
        if pd.isna(r.EMA20) or pd.isna(r.EMA200) or pd.isna(r.RSI):
            continue
        if not (r.Close > r.EMA200 and r.EMA20 > r.EMA200):
            continue
        if r.Close < c.min_price:
            continue
        stats["trend"] += 1

        tr = pd.concat([d.High - d.Low,
                        (d.High - d.Close.shift()).abs(),
                        (d.Low - d.Close.shift()).abs()], axis=1).max(axis=1)
        atr_pct = float(tr.rolling(14).mean().iloc[-1] / r.Close * 100)
        avg_vol = float(d.Volume.iloc[:-1].tail(30).mean())
        dist = float((r.Close / r.EMA20 - 1) * 100)

        if (abs(dist) <= c.max_dist_ema20_pct
                and c.rsi_min <= r.RSI <= c.rsi_max
                and atr_pct <= c.max_atr_pct
                and avg_vol >= c.min_avg_volume
                and avg_vol * r.Close >= c.min_dollar_volume):
            stats["setup"] += 1
            rows.append({"Symbol": sym, "Name": names.get(sym, ""), "Price": round(float(r.Close), 2),
                         "vs 20 EMA %": round(dist, 1), "RSI": round(float(r.RSI), 0),
                         "ATR %": round(atr_pct, 1), "Avg Vol (M)": round(avg_vol / 1e6, 1)})

    if c.skip_earnings_days > 0 and rows:
        with ThreadPoolExecutor(workers) as ex:
            days = list(ex.map(get_earnings_days, [r["Symbol"] for r in rows]))
        keep = []
        for r, dd in zip(rows, days):
            if dd is not None and dd <= c.skip_earnings_days:
                stats["earnings_skipped"] += 1
            else:
                keep.append(r)
        rows = keep

    stats["matches"] = len(rows)
    stats["no_data"] = stats["universe"] - stats["loaded"]
    stats["last_bar"] = pd.Timestamp(last_bar).strftime("%b %d") if last_bar is not None else ""
    cols = ["Symbol", "Name", "Price", "vs 20 EMA %", "RSI", "ATR %", "Avg Vol (M)"]
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df = df.reindex(df["vs 20 EMA %"].abs().sort_values().index).reset_index(drop=True)
    return df, stats


# ---------------------------------------------------------------- catalyst check
CATALYST_PATTERNS = {
    "Earnings": r"earnings|\beps\b|quarterly results|beats? estimates|raises? (?:full-year )?(?:guidance|outlook)|revenue (?:beat|growth)",
    "FDA/Clinical": r"\bfda\b|phase [123]|clinical|trial|approval|breakthrough designation",
    "M&A": r"acqui(?:re|sition|red)|merger|buyout|takeover|strategic alternatives|to be bought",
    "Contract/Partner": r"contract|partnership|agreement|collaboration|awarded|purchase order|supply deal",
    "Analyst": r"upgrad|downgrad|price target|initiates coverage",
    "Legal/Regulatory": r"settlement|appeals? court|\bban\b|regulat\w+|antitrust|\bftc\b|\bdoj\b|kids act|court ruling",
}
RED_FLAG_PATTERNS = {
    "Offering/Dilution": r"public offering|registered direct|private placement|at-the-market|\batm\b|priced offering|dilut|shelf registration",
    "Reverse split": r"reverse (?:stock )?split",
    "Going concern/Delisting": r"going concern|delist|minimum bid|bankruptcy|chapter 11|nasdaq deficiency",
    "Legal/Fraud": r"investigation|subpoena|class action|lawsuit|short report|fraud",
}


def _parse_news_item(it):
    """Handle both the old and new Yahoo news formats."""
    c = it.get("content") if isinstance(it.get("content"), dict) else None
    if c:
        title = c.get("title")
        ts = pd.to_datetime(c.get("pubDate"), utc=True, errors="coerce")
        source = (c.get("provider") or {}).get("displayName", "")
        link = (c.get("canonicalUrl") or c.get("clickThroughUrl") or {}).get("url", "")
    else:
        title = it.get("title")
        ts = pd.to_datetime(it.get("providerPublishTime"), unit="s", utc=True, errors="coerce")
        source = it.get("publisher", "")
        link = it.get("link", "")
    if not title:
        return None
    return {"title": title, "source": source, "url": link, "time": ts}


def get_catalyst(sym, lookback_hours=48):
    """
    Recent headlines, rough catalyst type, red flags and next earnings date.
    The keyword tagging is crude: always read the headlines yourself.
    """
    import yfinance as yf

    out = {"headlines": [], "tags": [], "flags": [], "fresh": 0, "earnings_days": None}
    try:
        items = yf.Ticker(sym).news or []
    except Exception:
        items = []
    now = pd.Timestamp.now(tz="UTC")
    parsed = [p for p in (_parse_news_item(i) for i in items) if p]
    for p in parsed:
        age = (now - p["time"]).total_seconds() / 3600 if pd.notna(p["time"]) else None
        p["age_h"] = age
    parsed.sort(key=lambda p: (p["age_h"] is None, p["age_h"] if p["age_h"] is not None else 0))

    fresh_titles = [p["title"] for p in parsed if p["age_h"] is not None and p["age_h"] <= lookback_hours]
    week_titles = [p["title"] for p in parsed if p["age_h"] is not None and p["age_h"] <= 168]
    out["fresh"] = len(fresh_titles)
    out["tags"] = [k for k, pat in CATALYST_PATTERNS.items()
                   if any(re.search(pat, t, re.I) for t in fresh_titles)]
    out["flags"] = [k for k, pat in RED_FLAG_PATTERNS.items()
                    if any(re.search(pat, t, re.I) for t in week_titles)]
    out["headlines"] = parsed[:8]
    out["earnings_days"] = get_earnings_days(sym)
    return out


def catalyst_label(cat):
    if cat["tags"]:
        return f"{', '.join(cat['tags'])} ({cat['fresh']} new)"
    if cat["fresh"]:
        return f"{cat['fresh']} new headlines, type unclear"
    return "None found"


# ---------------------------------------------------------------- news check
# Word lists for a rough good/bad read of a headline. This is keyword matching, not understanding:
# it misses context ("cuts costs" is good, "cuts guidance" is bad) and sarcasm, so the app also
# offers a "Copy for Claude" prompt, and the user makes the final good/bad call.
POSITIVE_WORDS = (r"\b(?:beats?|tops|exceeds?|surg\w*|soar\w*|jump\w*|rall(?:y|ies|ied)|record (?:highs?|revenue|profit|earnings|quarter|sales)|raises?|raised|upgrad\w*|"
                  r"sells? out|sold out|sellout|backorder\w*|"
                  r"outperform\w*|strong\w*|growth|wins?|won|awarded|approv\w*|partner\w*|expands?|expansion|"
                  r"breakthrough|profit\w*|boost\w*|bullish|climb\w*|gains?|buyback|dividend hike|grows?|grew|rises?|rose)\b")
NEGATIVE_WORDS = (r"\b(?:miss(?:es|ed)?|plunge\w*|tumbl\w*|slump\w*|fall\w*|falls|drops?|dropped|cuts?|slash\w*|lowers?|lowered|"
                  r"downgrad\w*|underperform\w*|weak\w*|loss(?:es)?|layoffs?|recall\w*|probe|investigat\w*|lawsuit|sues?|"
                  r"halts?|halted|warns?|warning|concerns?|bearish|sinks?|slides?|crash\w*|declin\w*|resign\w*|delays?|"
                  r"delayed|reject\w*|denied|fraud|default\w*|bankrupt\w*|settle\w*|bans?|fined?|antitrust)\b")

RED_FLAG_WHY = {
    "Offering/Dilution": "the company may be selling new shares, which usually pushes the price down.",
    "Reverse split": "a reverse split is often a sign a stock price has collapsed and is a common trap for buyers.",
    "Going concern/Delisting": "the company may be in financial trouble or at risk of being removed from the exchange.",
    "Legal/Fraud": "a lawsuit, investigation or short-seller report can hit the price hard and fast.",
}

MIN_HEADLINES = 3          # need at least this many headlines in the window before tone counts
NEWS_WINDOW_DAYS = 7


# Foreign companies traded in the US as ADRs often have no Yahoo news under the US symbol.
# Map a few big ones to their home-market symbol; anything else falls back to a search by company name.
ADR_HOME = {"RYCEY": "RR.L", "RYCEF": "RR.L", "TTDKY": "6762.T", "NSRGY": "NESN.SW", "SNYNF": "SAN.PA",
            "BAESY": "BA.L", "HSBC": "HSBA.L", "SMNEY": "SIE.DE", "SAPGF": "SAP.DE", "TOYOF": "7203.T",
            "TM": "7203.T", "SONY": "6758.T", "NVO": "NOVO-B.CO", "ASML": "ASML.AS", "SHEL": "SHEL.L",
            "AZN": "AZN.L", "UL": "ULVR.L", "DEO": "DGE.L", "RIO": "RIO.L", "BHP": "BHP.AX"}


# Headlines that are lists, daily auto-generated market blurbs, fund explainers or roundups. They are not news about a
# company, so they are shown but not counted toward the mood.
LIST_PATTERN_CI = (r"stocks? to (?:watch|buy|own|consider)|best .{0,35}stocks|\btop (?:\d+|three|five|ten)\b|\b\d+ (?:best|top|stocks?|reasons|ways)\b|"
                r"reasons we love|better (?:stock|buy|investment)|which (?:is|one)|market chatter|what to expect in markets|"
                r"(?:shares|stocks?) (?:are )?(?:falling|rising|moving|jumping|sinking)|more significant (?:dip|gain|rise|drop)|"
                r"(?:fell|rose|gained|dropped|lagged|outpaced) (?:more|less) than (?:the )?(?:broader )?market|than broader market|"
                r"outperforming other|underperforming other|stocks? get new|\betfs?\b|\bvgt\b|\bqqq\b|\bspy\b|here.s how much|"
                r"is the stock (?:still )?(?:cheap|a buy)|should you (?:buy|sell)|worth buying|\bvs\.?\b|"
                r"\band \d+ (?:other|more|top|great)\b|pick of the best|"
                r"\b(?:british|uk|us|u\.s\.|american|chinese|japanese|european|canadian|indian|australian|german|nuclear|defen[cs]e|"
                r"ai|tech|dividend|growth|penny|value|cheap|small[- ]cap|blue[- ]chip)\b.{0,25}\bstocks\b")
LIST_PATTERN_TICKERS = r"(?:\b[A-Z]{2,5}\b,\s*){2,}"   # "META, TTD, SNAP, GOOGL ..." (case matters)
GENERIC_FIRST_WORDS = {"united", "first", "american", "general", "national", "global", "international", "western", "northern",
                       "southern", "eastern", "great", "new", "bank", "banco", "grupo", "china", "royal"}
NAME_SUFFIX = (r"(?:,?\s+(?:inc\.?|incorporated|corp\.?|corporation|co\.?|company|holdings?|group|plc|ltd\.?|limited|ag|sa|se|nv|n\.v\.|"
               r"llc|lp|adr|class [a-c]|common stock|ordinary shares|the))+\s*$")


# Product and brand names that headlines use instead of the company name.
PRODUCT_ALIASES = {
    "AAPL": ["iPhone", "iPad", "MacBook", "Siri", "Vision Pro", "Apple Watch", "iOS", "Tim Cook", "Ternus"],
    "SNAP": ["Snapchat", "SPECS", "Spiegel"], "SNAPCHAT": ["Snapchat"],
    "GOOGL": ["Google", "YouTube", "Android", "Waymo", "Gemini", "Alphabet"], "GOOG": ["Google", "YouTube", "Android", "Waymo", "Gemini"],
    "META": ["Facebook", "Instagram", "WhatsApp", "Zuckerberg", "Meta Platforms"], "MSFT": ["Windows", "Azure", "Xbox", "Copilot", "OpenAI"],
    "AMZN": ["AWS", "Alexa", "Prime Video", "Whole Foods"], "TSLA": ["Tesla", "Musk", "Cybertruck", "Robotaxi", "Optimus"],
    "NVDA": ["Nvidia", "Blackwell", "CUDA", "Jensen Huang"], "AMD": ["Ryzen", "Radeon", "EPYC"], "NFLX": ["Netflix"],
    "DIS": ["Disney", "Pixar", "ESPN", "Marvel"], "PYPL": ["PayPal", "Venmo"], "UBER": ["Uber Eats"], "PINS": ["Pinterest"],
    "RDDT": ["Reddit"], "SHOP": ["Shopify"], "COIN": ["Coinbase"], "RBLX": ["Roblox"], "SPOT": ["Spotify"], "ABNB": ["Airbnb"],
    "RYCEY": ["Rolls Royce", "Trent"], "BAC": ["Bank of America"], "JPM": ["JPMorgan", "Chase"], "KO": ["Coca-Cola", "Coke"],
}


def company_aliases(sym, long_name=""):
    """Names a headline about this company would use: stripped company name, first two words, ticker."""
    out = []
    name = re.sub(r"\s+", " ", str(long_name or "")).strip()
    for _ in range(3):
        name = re.sub(NAME_SUFFIX, "", name, flags=re.I).strip(" ,.")
    if name:
        out.append(name)
        words = name.split()
        if len(words) >= 3:
            out.append(" ".join(words[:2]))
        if len(words) >= 2 and len(words[0]) >= 5 and words[0].lower() not in GENERIC_FIRST_WORDS:
            out.append(words[0])
    base = re.sub(r"[.\-=^].*$", "", str(sym or "").upper())
    out += PRODUCT_ALIASES.get(base, [])
    return {"names": list(dict.fromkeys(out)), "ticker": base if len(base) >= 3 else ""}


def _alias_pattern(name):
    parts = [p for p in re.split(r"[\s\-]+", name.strip()) if p]
    return r"(?<![A-Za-z])" + r"[\s\-]?".join(re.escape(p) for p in parts) + r"(?![A-Za-z])"


def mentions_company(title, aliases):
    """True if the headline names the company or its ticker. With no alias info, everything counts as relevant."""
    if not aliases or not (aliases.get("names") or aliases.get("ticker")):
        return True
    for n in aliases.get("names", []):
        if re.search(_alias_pattern(n), title, re.I):
            return True
    t = aliases.get("ticker")
    return bool(t and re.search(r"(?<![A-Za-z])" + re.escape(t) + r"(?![A-Za-z])", title))


def fetch_company_name(sym):
    """Company name from Yahoo ('' on any problem)."""
    import yfinance as yf

    for s_ in (sym, ADR_HOME.get(str(sym).upper())):
        if not s_:
            continue
        try:
            info = yf.Ticker(s_).info or {}
            nm = info.get("longName") or info.get("shortName")
            if nm:
                return str(nm)
        except Exception:
            pass
    return ""


def implied_earnings_move(sym, report_date, spot):
    """
    Rough move the options market expects around the report: the price of an at-the-money straddle on the first
    expiry after the report, as a percent of the stock price. It also covers the days between the report and that
    expiry, so it runs a bit high. Returns {'pct', 'expiry'} or None.
    """
    import yfinance as yf

    try:
        t = yf.Ticker(sym)
        exps = [pd.Timestamp(e) for e in (t.options or [])]
        after = [e for e in exps if e >= pd.Timestamp(report_date).normalize()]
        if not after or not spot:
            return None
        exp = after[0]
        ch = t.option_chain(exp.strftime("%Y-%m-%d"))

        def mid(df):
            k = (df["strike"] - spot).abs().idxmin()
            r = df.loc[k]
            b, a = float(r.get("bid") or 0), float(r.get("ask") or 0)
            return (b + a) / 2 if b > 0 and a > 0 else float(r.get("lastPrice") or 0)

        total = mid(ch.calls) + mid(ch.puts)
        if total <= 0:
            return None
        return {"pct": total / spot * 100, "expiry": exp}
    except Exception:
        return None


def fetch_news(sym):
    """
    Recent Yahoo headlines for one stock. Returns (items, note).
    items: [{title, source, url, time}], newest not guaranteed. note: plain text if a fallback was used or none was found.
    If the US symbol has no news, tries the home-market symbol (for ADRs), then a search by company name.
    """
    import yfinance as yf

    def grab(getter):
        try:
            return [p for p in (_parse_news_item(i) for i in (getter() or [])) if p]
        except Exception:
            return []

    items = grab(lambda: yf.Ticker(sym).news)
    if items:
        return items, ""
    home = ADR_HOME.get(sym.upper())
    if home:
        items = grab(lambda: yf.Ticker(home).news)
        if items:
            return items, f"Yahoo had no news under {sym}, so these headlines come from the home-market listing ({home})."
    name = ""
    try:
        info = yf.Ticker(sym).info or {}
        name = info.get("longName") or info.get("shortName") or ""
    except Exception:
        pass
    if name:
        items = grab(lambda: yf.Search(name, news_count=10).news)
        if items:
            return items, f"Yahoo had no news under {sym}, so these headlines come from a search for \"{name}\". Some may be loosely related."
    return [], (f"Yahoo returned no headlines for {sym}. Foreign companies traded in the US (ADRs and OTC stocks) often have none. "
                "Use the Claude buttons: Claude can search the web for the news.")


# Headlines that hint at a scheduled company event which can move the price like earnings does.
EVENT_HINT = r"trading update|capital markets day|investor day|investor presentation|guidance update|to report (?:results|earnings)|results (?:on|due)|shareholder meeting|\bagm\b|interim results|full[- ]year results|half[- ]year results"


def age_text(age_h):
    if age_h is None:
        return "date unknown"
    if age_h < 1:
        return "under 1h ago"
    if age_h < 48:
        return f"{age_h:.0f}h ago"
    return f"{age_h / 24:.0f}d ago"


def tag_headline(title):
    """(topics, red flags, tone) for one headline. tone is 'good', 'bad', 'mixed' or 'neutral'."""
    topics = [k for k, pat in CATALYST_PATTERNS.items() if re.search(pat, title, re.I)]
    flags = [k for k, pat in RED_FLAG_PATTERNS.items() if re.search(pat, title, re.I)]
    pos = len(re.findall(POSITIVE_WORDS, title, re.I))
    neg = len(re.findall(NEGATIVE_WORDS, title, re.I))
    if flags:
        neg += 2
    if pos and neg:
        tone = "mixed" if pos == neg else ("good" if pos > neg else "bad")
        if flags:
            tone = "bad"
    elif pos:
        tone = "good"
    elif neg:
        tone = "bad"
    else:
        tone = "neutral"
    return topics, flags, tone


def news_profile(items, now=None, window_days=NEWS_WINDOW_DAYS, min_headlines=MIN_HEADLINES, max_show=10, aliases=None):
    """
    Turn parsed headlines into a news read. items: list from fetch_news (or _parse_news_item).
    Evidence rule: the mood only counts when there are at least `min_headlines` different headlines
    in the last `window_days` days. A red-flag headline (offering, going concern, lawsuit, ...) counts
    on its own, since one is enough.
    aliases: company_aliases(...) result. Headlines that are lists/roundups or do not name the company are shown
    but not counted ("skipped"). With no aliases every headline counts.
    Returns {headlines, recent, enough, good, bad, mixed, neutral, lean, red_flags, sources, skipped_list, skipped_other}.
    lean: 'positive' / 'negative' / 'mixed' / 'unclear' (not enough evidence).
    """
    now = now or pd.Timestamp.now(tz="UTC")
    seen, rows = set(), []
    for p in items or []:
        key = re.sub(r"[^a-z0-9]+", " ", str(p["title"]).lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        t = p.get("time")
        age = (now - t).total_seconds() / 3600 if (t is not None and pd.notna(t)) else None
        topics, flags, tone = tag_headline(p["title"])
        is_list = bool(re.search(LIST_PATTERN_CI, p["title"], re.I) or re.search(LIST_PATTERN_TICKERS, p["title"]))
        about = mentions_company(p["title"], aliases)
        skip = "list" if is_list else ("other" if not about else "")
        if skip:
            flags, tone = [], "skip"
        rows.append({"title": p["title"], "source": p.get("source", ""), "url": p.get("url", ""),
                     "age_h": age, "topics": topics, "flags": flags, "tone": tone, "skip": skip})
    rows.sort(key=lambda r: (r["age_h"] is None, r["age_h"] if r["age_h"] is not None else 0))
    recent_all = [r for r in rows if r["age_h"] is not None and r["age_h"] <= window_days * 24]
    recent = [r for r in recent_all if not r["skip"]]
    counts = {k: sum(1 for r in recent if r["tone"] == k) for k in ("good", "bad", "mixed", "neutral")}
    enough = len(recent) >= min_headlines
    toned = counts["good"] + counts["bad"]
    lean = "unclear"
    if enough:
        if toned >= 2 and counts["good"] / toned >= 2 / 3:
            lean = "positive"
        elif toned >= 2 and counts["bad"] / toned >= 2 / 3:
            lean = "negative"
        else:
            lean = "mixed"
    red_flags, seen_f = [], set()
    for r in recent:
        for f in r["flags"]:
            if f not in seen_f:
                seen_f.add(f)
                red_flags.append({"flag": f, "why": RED_FLAG_WHY.get(f, ""), "title": r["title"]})
    hints = [r["title"] for r in recent if re.search(EVENT_HINT, r["title"], re.I)]
    return {"headlines": rows[:max_show], "recent": len(recent), "enough": enough, "lean": lean,
            "feed_empty": not items, "event_hints": hints[:3],
            "skipped_list": sum(1 for r in recent_all if r["skip"] == "list"),
            "skipped_other": sum(1 for r in recent_all if r["skip"] == "other"), "recent_all": len(recent_all), "red_flags": red_flags, "sources": len({r["source"] for r in recent if r["source"]}), **counts}


TONE_ICON = {"good": "🟢 Good", "bad": "🔴 Bad", "mixed": "🟡 Mixed", "neutral": "⚪ Neutral", "skip": "➖ Not counted"}
SKIP_WHY = {"list": "list, roundup or market blurb", "other": "does not name this company"}


def claude_prompt(sym, verdict, news, price=None, beginner=False):
    """A ready-to-paste question for Claude: the headlines, the app's verdict and what to answer."""
    L = [f"I'm thinking about a swing trade (holding days to weeks) in {sym}"
         + (f", currently around ${price:.2f}." if price else ".")
         + " Please help me understand the recent news. "
         + ("I'm new to investing, so please explain in plain English.\n" if beginner else "\n")]
    if verdict:
        L.append(f"My app's price-based verdict (last 3 months of daily data): {verdict['verdict']} "
                 f"(score {verdict['score']:+d} on a scale of -{verdict['max']} to +{verdict['max']}).")
        L.append(verdict["stats"])
        for line in verdict.get("earnings_lines", [])[:3]:
            L.append("- " + line[0].replace(" (links below)", "").replace("Check it before buying", "Check it"))
        L.append("")
    L.append(f"Headlines pulled from Yahoo Finance (newest first). My app's automatic tags are keyword-based and may be wrong:")
    hl = (news or {}).get("headlines") or []
    if not hl:
        L.append("(No headlines were found. If you can search the web, please look for recent news.)")
    for i, r in enumerate(hl, 1):
        tags = ", ".join(r["topics"] + r["flags"]) or "no topic tag"
        guess = (f"not counted by the app ({SKIP_WHY[r['skip']]})" if r.get("skip") else f"tone guess: {r['tone']}")
        L.append(f"{i}. [{age_text(r['age_h'])}] {r['title']} ({r['source'] or 'unknown source'}) "
                 f"- app tags: {tags}; {guess}" + (f"\n   {r['url']}" if r["url"] else ""))
    em = (news or {}).get("implied_move")
    if em:
        L.append(f"Options traders are pricing in roughly a {em['pct']:.0f}% move around the next earnings report.")
    L.append("Note: Yahoo's feed often misses the biggest stories, so please search the web for the main developments "
             "(product launches, activist investors, analyst changes, legal or regulatory items) that these headlines don't show.")
    L.append("")
    L.append("Please:\n"
             "1. Tell me in a few sentences what is actually going on with this company right now.\n"
             "2. Label each headline GOOD, BAD or NEUTRAL for a stock I'd hold for days to weeks, and say where "
             "my app's tag got it wrong.\n"
             "3. Say whether the news looks already priced in, and whether anything could move the price suddenly "
             "(earnings, offerings, legal, FDA, etc.).\n"
             "4. If you can search the web, check for anything newer or more important than these headlines.\n"
             "5. End with one line: overall news is GOOD, NEUTRAL or BAD for a new swing trade, and why.\n"
             "This is for my own learning, not financial advice, so also tell me what you're unsure about.")
    return "\n".join(L)


# ---------------------------------------------------------------- signal check
def signal_summary(sym, interval="5m", threshold=3, window=5, recent_bars=6):
    """Run the chart's signal engine on one stock and summarise where it stands."""
    import yfinance as yf

    blank = {"label": "No data", "rank": -999, "recent_buy": False, "side": None,
             "reasons": [], "reasons_short": [], "reasons_plain": []}
    try:
        raw = yf.Ticker(sym).history(period=so.default_period(interval), interval=interval)
        raw = raw[["Open", "High", "Low", "Close", "Volume"]].dropna()
        raw = so.drop_unfinished_bar(raw, so.interval_to_timedelta(interval))
    except Exception:
        return blank
    if len(raw) < so.MIN_BARS:
        return {**blank, "label": "Not enough history"}

    df = so.add_indicators(raw)
    ev = so.detect_events(df)
    df, active = so.score_signals(df, ev, window, threshold)
    n = len(df)
    buys = np.flatnonzero(df["BUY"].to_numpy())
    sells = np.flatnonzero(df["SELL"].to_numpy())
    since_buy = n - 1 - buys[-1] if len(buys) else None
    since_sell = n - 1 - sells[-1] if len(sells) else None
    last = df.iloc[-1]

    # Facts about where price sits now (used to judge how serious a SELL signal is).
    ctx = {"close": float(last.Close),
           "above200": bool(last.Close > last.EMA200) if last.EMA200 == last.EMA200 else None,
           "above20": bool(last.Close > last.EMA20) if last.EMA20 == last.EMA20 else None,
           "threshold": threshold}

    def ago(k):
        return "now" if k == 0 else f"{k} bars ago"

    def reasons_for(i, side, drop_caution=False):
        out = {}
        for m, key in (("full", "reasons"), ("short", "reasons_short"), ("plain", "reasons_plain")):
            r = so.explain_bar(df, ev, active, i, window, side, m)
            out[key] = [x for x in r if not x.startswith(("CAUTION", "Caution", "Careful"))] if drop_caution else r
        return out

    buy_recent = since_buy is not None and since_buy <= recent_bars
    sell_recent = since_sell is not None and since_sell <= recent_bars
    if buy_recent and not (sell_recent and since_sell < since_buy):
        i = n - 1 - since_buy
        return {"label": f"BUY {ago(since_buy)}", "rank": 100 - 5 * since_buy + float(last.BUY_SCORE),
                "recent_buy": True, "side": "buy", "bars_ago": since_buy,
                "score": float(df["BUY_SCORE"].iloc[i]), **ctx, **reasons_for(i, "buy")}
    if sell_recent:
        i = n - 1 - since_sell
        return {"label": f"SELL {ago(since_sell)}", "rank": -50 - float(last.SELL_SCORE),
                "recent_buy": False, "side": "sell", "bars_ago": since_sell,
                "score": float(df["SELL_SCORE"].iloc[i]), **ctx, **reasons_for(i, "sell")}
    if last.BUY_SCORE > 0:
        return {"label": f"Building buy {last.BUY_SCORE:.0f}/{threshold}", "rank": float(last.BUY_SCORE),
                "recent_buy": False, "side": "building", **ctx, **reasons_for(n - 1, "buy", drop_caution=True)}
    return {"label": "No signal", "rank": 0, "recent_buy": False, "side": None,
            "reasons": [], "reasons_short": [], "reasons_plain": []}


# ---------------------------------------------------------------- market weather
def _index_read(df, name):
    """Where one index sits against its own averages (daily, finished candles only)."""
    d = so.add_indicators(df)
    r = d.iloc[-1]
    chg5 = (r.Close / d.Close.iloc[-6] - 1) * 100 if len(d) > 6 else float("nan")
    return {"name": name, "close": float(r.Close), "above200": bool(r.Close > r.EMA200),
            "ema20_above_200": bool(r.EMA20 > r.EMA200), "above20": bool(r.Close > r.EMA20),
            "chg5": float(chg5), "asof": d.index[-1]}


def market_weather(spy, qqq, vix=None):
    """
    Grade the overall market as Sunny / Partly cloudy / Stormy from daily data.
    spy, qqq: daily OHLCV DataFrames (200+ bars). vix: latest VIX close, or None.
    Points: SPY above its 200 EMA (2), SPY 20 EMA above 200 EMA (1), SPY above its 20 EMA (1),
    QQQ above its 200 EMA (1), QQQ above its 20 EMA (1), VIX at or below 22 (1); VIX above 30 takes 2 away.
    """
    s, q = _index_read(spy, "S&P 500 (SPY)"), _index_read(qqq, "Nasdaq 100 (QQQ)")
    score = 2 * s["above200"] + s["ema20_above_200"] + s["above20"] + q["above200"] + q["above20"]
    top = 6
    if vix is not None:
        top = 7
        score += 1 if vix <= 22 else 0
        score -= 2 if vix > 30 else 0
    score = max(0, score)
    frac = score / top
    if frac >= 0.8:
        label, level = "Sunny", "success"
        head = "The overall market is in a healthy uptrend, so swing setups have the wind at their back."
        plain = "Most stocks tend to rise when the whole market is rising, so buying good setups is easier right now."
    elif frac >= 0.5:
        label, level = "Partly cloudy", "warning"
        head = "Mixed signals in the overall market. Be pickier, and consider smaller positions."
        plain = "The market is not clearly going up or down. Only take the very best setups, and risk less on each."
    else:
        label, level = "Stormy", "error"
        head = ("The overall market is weak. Swing setups fail more often in this kind of market, "
                "so consider waiting for better weather before buying.")
        plain = ("When the whole market is falling, even good-looking stocks tend to get dragged down. "
                 "Waiting on the sidelines is a perfectly good choice.")

    def line(x):
        trend = "above" if x["above200"] else "below"
        short = "above" if x["above20"] else "below"
        return (f"{x['name']}: {x['close']:.2f}, {trend} its 200 EMA (long-term trend), {short} its 20 EMA "
                f"(short-term), {x['chg5']:+.1f}% over 5 days.")
    details = [line(s), line(q)]
    if vix is not None:
        mood = "calm" if vix <= 16 else "normal" if vix <= 22 else "nervous" if vix <= 30 else "scared"
        details.append(f"Fear gauge (VIX): {vix:.1f}, the market is {mood}. Above 22 is jumpy; above 30 is fearful.")
    return {"label": label, "level": level, "score": int(score), "max": top, "headline": head, "plain": plain,
            "details": details, "asof": s["asof"]}


def get_market_weather():
    """Download SPY, QQQ and the VIX from Yahoo and grade the market. Returns None if data is unavailable."""
    import yfinance as yf

    frames = {}
    for sym in ("SPY", "QQQ"):
        try:
            d = yf.Ticker(sym).history(period="2y", interval="1d")[["Open", "High", "Low", "Close", "Volume"]].dropna()
        except Exception:
            return None
        if len(d) and so.daily_bar_in_progress(d.index[-1]):
            d = d.iloc[:-1]
        if len(d) < so.MIN_BARS:
            return None
        frames[sym] = d
    vix = None
    try:
        v = yf.Ticker("^VIX").history(period="10d", interval="1d")["Close"].dropna()
        vix = float(v.iloc[-1]) if len(v) else None
    except Exception:
        pass
    return market_weather(frames["SPY"], frames["QQQ"], vix)


def get_quote_extras(sym):
    """Bid/ask spread as a percent of price. Only meaningful while the market is open."""
    import yfinance as yf

    try:
        info = yf.Ticker(sym).info
        bid, ask = info.get("bid"), info.get("ask")
        if bid and ask and bid > 0 and ask > 0:
            mid = (bid + ask) / 2
            return {"bid": float(bid), "ask": float(ask), "spread_pct": round((ask - bid) / mid * 100, 2)}
    except Exception:
        pass
    return {"bid": None, "ask": None, "spread_pct": None}


def _why_ranked(sig):
    """Short plain-English reason for a row's signal rank."""
    reasons = [r for r in sig.get("reasons", []) if not r.startswith("CAUTION")]
    if not reasons:
        return sig["label"]
    first = re.sub(r"\s*\[[^\]]*\]\s*$", "", reasons[0])  # drop the "[3 bar(s) ago]" suffix
    first = first.split(":")[0]
    return f"{sig['label']}: {first}"


def enrich(df, interval="5m", threshold=3, window=5, recent_bars=6, lookback_hours=48, workers=4):
    """
    Add catalyst, signal and spread columns to scan results and sort stocks with
    the best current signals to the top. Returns (DataFrame, details-by-symbol).
    """
    details = {}
    if df.empty:
        return df, details

    def job(sym):
        return (sym, get_catalyst(sym, lookback_hours),
                signal_summary(sym, interval, threshold, window, recent_bars),
                get_quote_extras(sym))

    with ThreadPoolExecutor(workers) as ex:
        for sym, cat, sig, quote in ex.map(job, list(df["Symbol"])):
            details[sym] = {"catalyst": cat, "signal": sig, "quote": quote}

    out = df.copy()
    out["Signal"] = [details[s]["signal"]["label"] for s in out["Symbol"]]
    out["Why ranked"] = [_why_ranked(details[s]["signal"]) for s in out["Symbol"]]
    out["Catalyst"] = [catalyst_label(details[s]["catalyst"]) for s in out["Symbol"]]
    out["Red flags"] = [", ".join(details[s]["catalyst"]["flags"]) or "-" for s in out["Symbol"]]
    out["Earnings"] = [("-" if details[s]["catalyst"]["earnings_days"] is None
                        else ("today" if details[s]["catalyst"]["earnings_days"] == 0
                              else f"in {details[s]['catalyst']['earnings_days']}d")) for s in out["Symbol"]]
    out["Spread %"] = [details[s]["quote"]["spread_pct"] for s in out["Symbol"]]
    out["_rank"] = [details[s]["signal"]["rank"] for s in out["Symbol"]]
    out = out.sort_values("_rank", ascending=False, kind="stable").drop(columns="_rank").reset_index(drop=True)
    return out, details


# ---------------------------------------------------------------- swing scanner
@dataclass
class SwingCriteria:
    setups: tuple = ("pullback", "breakout", "bounce")
    min_price: float = 10.0
    min_market_cap: float = 2_000_000_000
    min_avg_volume: int = 1_000_000
    max_atr_pct: float = 6.0             # swing trades tolerate slightly bigger daily swings
    skip_earnings_days: int = 10         # holding for days means earnings risk matters more
    breakout_days: int = 20              # breakout = close above the prior N-day high
    breakout_rvol: float = 1.5           # ...on at least this multiple of average daily volume
    stop_atr_mult: float = 2.0           # suggested stop = price - this many ATRs
    reward_risk: float = 2.0             # suggested target = this many times the risk
    risk_dollars: float = 0.0            # if > 0, show shares so a stop-out loses about this much
    universe_size: int = 500
    min_dollar_volume: float = 10_000_000  # 30-day average dollars traded per day


SETUP_LABELS = {"pullback": "Pullback", "breakout": "Breakout", "bounce": "Bounce"}


def _atr(d, n=14):
    tr = pd.concat([d.High - d.Low,
                    (d.High - d.Close.shift()).abs(),
                    (d.Low - d.Close.shift()).abs()], axis=1).max(axis=1)
    return float(tr.rolling(n).mean().iloc[-1])


SWING_KEYS = ("pullback", "breakout", "bounce")


def swing_setup_flags(df, c):
    """
    Evaluate the swing rules on EVERY bar of a daily DataFrame that already has
    indicators (from signal_overlay.add_indicators). Used by the scanner (last bar)
    and by the swing chart (all bars), so the two always agree.

    Returns a DataFrame with bool columns pullback / breakout / bounce / uptrend /
    filters_ok and numeric helpers atr, atr_pct, avg_vol, rvol, dist20.
    The three setup columns do NOT include the liquidity filters (filters_ok):
    those are screening choices, not part of the setup definition.
    """
    close = df["Close"]
    tr = pd.concat([df["High"] - df["Low"],
                    (df["High"] - close.shift()).abs(),
                    (df["Low"] - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    atr_pct = atr / close * 100
    avg_vol = df["Volume"].shift(1).rolling(30).mean()      # the 30 days BEFORE each bar
    rvol = df["Volume"] / avg_vol
    dist20 = (close / df["EMA20"] - 1) * 100
    uptrend = (close > df["EMA200"]) & (df["EMA20"] > df["EMA200"])
    filters_ok = ((close >= c.min_price) & (avg_vol >= c.min_avg_volume) & (atr_pct <= c.max_atr_pct)
                  & (avg_vol * close >= getattr(c, "min_dollar_volume", 0)))

    off_high = (close.rolling(10).max() / close - 1) * 100
    pullback = uptrend & (off_high >= 2.0) & (dist20.abs() <= 3.0) & df["RSI"].between(40, 60)
    prior_high = df["High"].shift(1).rolling(c.breakout_days).max()
    breakout = uptrend & (close > prior_high) & (rvol >= c.breakout_rvol) & (df["RSI"] <= 75)
    bounce = (uptrend & (df["RSI"].rolling(5).min() <= 35)
              & (df["RSI"] > df["RSI"].shift(1)) & (close > close.shift(1)))

    return pd.DataFrame({
        "pullback": pullback, "breakout": breakout, "bounce": bounce,
        "uptrend": uptrend, "filters_ok": filters_ok,
        "atr": atr, "atr_pct": atr_pct, "avg_vol": avg_vol, "rvol": rvol, "dist20": dist20,
    })


def swing_scan(c, tickers=None, workers=4, also_market=False):
    """
    Daily-chart swing setups inside uptrends (price above the 200 EMA, 20 EMA above 200 EMA):
      pullback - dipped 2%+ from its 10-day high, now within 3% of the 20 EMA, RSI 40-60
      breakout - closed above the prior N-day high on strong volume, RSI not overheated
      bounce   - RSI got oversold (35 or less) in the last 5 days and is now turning up
    Run after the close, so the day's volume is complete.
    """
    stats = {"kind": "swing", "universe": 0, "loaded": 0, "trend": 0, "setup": 0,
             "earnings_skipped": 0, "matches": 0, "no_data": 0}
    _stamp(stats)

    universe = build_universe(c, tickers, also_market)
    names = dict(universe)
    stats["universe"] = len(universe)
    last_bar = None

    rows = []
    for sym, d in _daily_frames([u[0] for u in universe]):
        stats["loaded"] += 1
        last_bar = max(last_bar, d.index[-1]) if last_bar is not None else d.index[-1]
        df = so.add_indicators(d)
        r = df.iloc[-1]
        if pd.isna(r.EMA20) or pd.isna(r.EMA200) or pd.isna(r.RSI):
            continue
        f = swing_setup_flags(df, c).iloc[-1]
        if not (bool(f["uptrend"]) and r.Close >= c.min_price):
            continue
        stats["trend"] += 1
        if not bool(f["filters_ok"]):
            continue

        found = [k for k in SWING_KEYS if k in c.setups and bool(f[k])]
        if not found:
            continue
        stats["setup"] += 1

        atr = float(f["atr"])
        stop = float(r.Close - c.stop_atr_mult * atr)
        risk = float(r.Close - stop)
        row = {"Symbol": sym, "Name": names.get(sym, ""), "Price": round(float(r.Close), 2),
               "Setup": ", ".join(SETUP_LABELS[x] for x in found),
               "RSI": round(float(r.RSI), 0), "ATR %": round(float(f["atr_pct"]), 1),
               "Day Vol x": round(float(f["rvol"]), 1),
               "Stop": round(stop, 2), "Risk %": round(risk / r.Close * 100, 1),
               "Target": round(float(r.Close + c.reward_risk * risk), 2)}
        if c.risk_dollars > 0 and risk > 0:
            row["Shares"] = int(c.risk_dollars // risk)
        rows.append(row)

    if c.skip_earnings_days > 0 and rows:
        with ThreadPoolExecutor(workers) as ex:
            days = list(ex.map(get_earnings_days, [r["Symbol"] for r in rows]))
        keep = []
        for r, dd in zip(rows, days):
            if dd is not None and dd <= c.skip_earnings_days:
                stats["earnings_skipped"] += 1
            else:
                keep.append(r)
        rows = keep

    stats["matches"] = len(rows)
    stats["no_data"] = stats["universe"] - stats["loaded"]
    stats["last_bar"] = pd.Timestamp(last_bar).strftime("%b %d") if last_bar is not None else ""
    cols = ["Symbol", "Name", "Price", "Setup", "RSI", "ATR %", "Day Vol x", "Stop", "Risk %", "Target"]
    if c.risk_dollars > 0:
        cols.append("Shares")
    df = pd.DataFrame(rows, columns=cols)
    if not df.empty:
        df = df.sort_values("Day Vol x", ascending=False).reset_index(drop=True)
    return df, stats


# ---------------------------------------------------------------- account-aware sizing
@dataclass
class Account:
    value: float = 0.0              # total account value (cash + holdings)
    risk_pct: float = 1.0           # max loss on any one trade, % of account
    daily_risk: float = 0.0         # total risk budget: open-position risk + realized losses must stay under it
    daily_used: float = 0.0         # extra risk you carry that is NOT in the ledger
    max_position_pct: float = 25.0  # biggest single position, % of account
    max_positions: int = 3          # most NEW positions in today's plan
    fractional: bool = False        # allow fractional shares
    stop_atr_mult: float = 2.0      # stop distance when results carry ATR % but no stop
    reward_risk: float = 2.0
    pct_stop: float = 0.0           # momentum scanner: stop this % below price (0 = not set, no sizing)
    # portfolio state, filled in from the trade ledger by the app:
    cash_available: float = None    # None = assume the whole account value is cash
    open_risk: float = 0.0          # estimated loss if every open position hits its stop
    realized_today: float = 0.0     # profit/loss already realized today
    open_positions: int = 0
    max_open_positions: int = 0     # 0 = no cap
    held_symbols: tuple = ()


def _shares(price, risk_per_share, risk_budget, max_cost, fractional):
    """Shares that respect both the risk budget and the cost cap, plus the reason if zero."""
    if risk_per_share <= 0:
        return 0, "No valid stop"
    if risk_budget <= 0:
        return 0, "Daily risk used up"
    by_cost = max_cost / price
    by_risk = risk_budget / risk_per_share
    raw = min(by_cost, by_risk)
    if fractional:
        shares = math.floor(raw * 100) / 100
        if shares * price < 1:   # most brokers need at least ~$1 per order
            return 0, "Position under $1"
        return shares, "OK"
    shares = math.floor(raw)
    if shares >= 1:
        return shares, "OK"
    if by_cost < 1:
        return 0, "Too expensive for your limits"
    return 0, "Stop too wide for your risk limit"


def size_positions(df, acct):
    """
    Size each candidate to the account AND to what you already own, and build
    today's combined plan.

    Columns "Max shares / Max cost $ / Max risk $" are the biggest position
    you could take in that ONE stock. They cannot all be taken together; the
    plan (second return value) spends the shared cash, risk and slot budgets
    down the ranked list. Returns (sized_df, plan_df, info).
    """
    empty = pd.DataFrame()
    if df.empty:
        return df, empty, {"enabled": False, "reason": "No results to size."}
    if acct.value <= 0:
        return df, empty, {"enabled": False, "reason": "Enter your account value in the sidebar to size positions."}
    if acct.daily_risk <= 0:
        return df, empty, {"enabled": False,
                           "reason": "Set 'Max total risk' in the sidebar to size positions."}

    d = df.copy()
    for old in ("Shares", "Max shares", "Max cost $", "Max risk $", "Fit"):
        if old in d.columns:
            d = d.drop(columns=old)
    if "Stop" not in d.columns:
        if "ATR %" in d.columns:
            d["Stop"] = (d["Price"] * (1 - acct.stop_atr_mult * d["ATR %"] / 100)).round(2)
        elif acct.pct_stop > 0:
            d["Stop"] = (d["Price"] * (1 - acct.pct_stop / 100)).round(2)
        else:
            return df, empty, {"enabled": False,
                               "reason": "Sizing needs a stop distance. For this scanner, set 'Stop = % below price' in the scanner panel."}
        d["Target"] = (d["Price"] + acct.reward_risk * (d["Price"] - d["Stop"])).round(2)

    cash = acct.value if acct.cash_available is None else max(acct.cash_available, 0.0)
    loss_today = max(-acct.realized_today, 0.0)
    daily_left = max(acct.daily_risk - acct.daily_used - acct.open_risk - loss_today, 0.0)
    slots = max(acct.max_open_positions - acct.open_positions, 0) if acct.max_open_positions > 0 else 10 ** 6
    per_trade = min(acct.value * acct.risk_pct / 100, daily_left)
    max_cost = min(acct.value * acct.max_position_pct / 100, cash)
    held = {h.upper() for h in acct.held_symbols}

    shares, cost, risk, fit = [], [], [], []
    for _, r in d.iterrows():
        rps = r["Price"] - r["Stop"]
        n, why = _shares(r["Price"], rps, per_trade, max_cost, acct.fractional)
        if why == "OK" and str(r["Symbol"]).upper() in held:
            why = "Already own"
        elif why == "OK" and slots <= 0:
            why = "No open position slots"
        shares.append(n)
        cost.append(round(n * r["Price"], 2))
        risk.append(round(n * rps, 2))
        fit.append(why)
    d["Max shares"], d["Max cost $"], d["Max risk $"], d["Fit"] = shares, cost, risk, fit

    # Today's plan: walk down the (already ranked) list, spending the shared budgets.
    plan, risk_left, cash_left = [], daily_left, cash
    limit = min(acct.max_positions, slots)
    for _, r in d[d["Fit"] == "OK"].iterrows():
        if len(plan) >= limit:
            break
        rps = r["Price"] - r["Stop"]
        n, why = _shares(r["Price"], rps, min(per_trade, risk_left), min(max_cost, cash_left), acct.fractional)
        if n <= 0:
            continue
        row = {k: v for k, v in r.to_dict().items() if k not in ("Max shares", "Max cost $", "Max risk $", "Fit")}
        row["Shares"], row["Cost $"], row["Risk $"] = n, round(n * r["Price"], 2), round(n * rps, 2)
        plan.append(row)
        risk_left -= n * rps
        cash_left -= n * r["Price"]
    plan_df = pd.DataFrame(plan)
    info = {"enabled": True, "per_trade": per_trade, "daily_left": daily_left, "max_cost": max_cost,
            "cash": cash, "slots": slots, "open_risk": acct.open_risk, "loss_today": loss_today,
            "plan_cost": float(plan_df["Cost $"].sum()) if not plan_df.empty else 0.0,
            "plan_risk": float(plan_df["Risk $"].sum()) if not plan_df.empty else 0.0}
    return d, plan_df, info


def data_line(stats):
    """One line about where the data came from and how fresh it is."""
    bits = ["Data: Yahoo Finance (can be delayed)"]
    if stats.get("asof"):
        bits.append(f"scanned {stats['asof']}")
    if stats.get("session"):
        bits.append(stats["session"])
    if stats.get("last_bar"):
        bits.append(f"latest finished daily bar: {stats['last_bar']}")
    if stats.get("no_data"):
        bits.append(f"{stats['no_data']} symbols had no or too little data (that is not the same as failing a filter)")
    if "candidates" in stats:
        bits.append("float figures come from Yahoo and may be stale")
    return "  |  ".join(bits)


def main():
    ap = argparse.ArgumentParser(description="Low-float momentum scanner.")
    ap.add_argument("--tickers", nargs="*", help="scan only these symbols instead of the whole market")
    ap.add_argument("--min-change", type=float, default=10.0, help="min 1-day change percent (default 10)")
    ap.add_argument("--min-price", type=float, default=1.0)
    ap.add_argument("--max-price", type=float, default=20.0)
    ap.add_argument("--max-float", type=float, default=20_000_000, help="max float in shares (default 20000000)")
    ap.add_argument("--min-rvol", type=float, default=5.0, help="relative volume must exceed this (default 5)")
    ap.add_argument("--min-volume", type=int, default=100_000, help="min shares traded today (default 100000)")
    ap.add_argument("--steady", action="store_true", help="run the lower-risk steady-uptrend scanner instead")
    ap.add_argument("--swing", action="store_true", help="run the swing-setup scanner (daily charts)")
    ap.add_argument("--risk-dollars", type=float, default=0.0, help="swing: show shares so a stop-out loses ~this much")
    ap.add_argument("--csv", metavar="FILE.csv", help="also save the results to a CSV file")
    ap.add_argument("--enrich", action="store_true", help="add catalyst check and current-signal columns")
    ap.add_argument("--interval", default="5m", help="bar size for the signal check (default 5m)")
    args = ap.parse_args()

    try:
        if args.swing:
            df, stats = swing_scan(SwingCriteria(risk_dollars=args.risk_dollars), args.tickers)
        elif args.steady:
            df, stats = steady_scan(SteadyCriteria(), args.tickers)
        else:
            c = Criteria(args.min_change, args.min_price, args.max_price,
                         args.max_float, args.min_rvol, args.min_volume)
            df, stats = scan(c, args.tickers)
    except RuntimeError as e:
        raise SystemExit(str(e))
    if args.enrich and not df.empty:
        df, _ = enrich(df, interval="1d" if args.swing else args.interval)
    if args.csv:
        df.to_csv(args.csv, index=False)
        print(f"Saved {len(df)} rows to {args.csv}")
    print(stats_line(stats))
    print(df.to_string(index=False) if not df.empty else "\nNo matches right now.")
    print("\nNot financial advice. Scanner results are starting points, not recommendations.")


if __name__ == "__main__":
    main()

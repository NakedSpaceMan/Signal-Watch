"""
crypto.py - the data and scanning side of Signal Watch's Crypto mode.

Crypto differs from stocks in ways that matter here:
  * It trades 24/7, so there are no weekends, holidays or "market closed" days. A daily candle runs midnight to midnight
    UTC (4 PM Pacific in winter, 5 PM in summer); the scanner only uses FINISHED candles.
  * It moves much more: daily swings of 4-8% are normal, so the filters and stops are wider and positions are smaller.
  * Stock-only checks (earnings, float, market hours) do not apply. Bitcoin's trend stands in for "market weather".
  * Yahoo's "volume" for coins is already in dollars.

The setup rules (pullback, breakout, bounce), Score, past-setup stats and backtest are the same engine as the stock side.
"""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import backtest as bt
import quality as ql
import scanner as sc
import signal_overlay as so

# Robinhood Crypto's tradable coins (from Robinhood's coin-availability page), minus stablecoins and gold-backed tokens,
# which barely move and make no sense for swing trading. Some brand-new coins may not exist on Yahoo Finance; those are
# reported as "no data" instead of crashing.
COIN_NAMES = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "XRP": "XRP", "SOL": "Solana", "DOGE": "Dogecoin", "ADA": "Cardano",
    "BNB": "BNB", "LTC": "Litecoin", "BCH": "Bitcoin Cash", "LINK": "Chainlink", "XLM": "Stellar", "AVAX": "Avalanche",
    "DOT": "Polkadot", "ETC": "Ethereum Classic", "ATOM": "Cosmos", "NEAR": "NEAR Protocol", "ALGO": "Algorand",
    "HBAR": "Hedera", "XTZ": "Tezos", "SHIB": "Shiba Inu", "AAVE": "Aave", "COMP": "Compound", "CRV": "Curve DAO",
    "GRT": "The Graph", "SNX": "Synthetix", "BAT": "Basic Attention Token", "FET": "Artificial Superintelligence Alliance",
    "INJ": "Injective", "IMX": "Immutable", "PEPE": "Pepecoin", "UNI": "Uniswap", "SUI": "SUI", "ARB": "Arbitrum",
    "OP": "Optimism", "RENDER": "Render", "WLD": "Worldcoin", "ONDO": "Ondo", "TRUMP": "OFFICIAL TRUMP",
    "HYPE": "Hyperliquid", "WIF": "Dogwifhat", "BONK": "BONK", "FLOKI": "Floki", "LDO": "Lido DAO", "SEI": "SEI",
    "STRK": "Starknet", "ENA": "Ethena", "JTO": "Jito", "PYTH": "Pyth Network", "QNT": "Quant", "ZEC": "Zcash",
    "AERO": "Aerodrome Finance", "AXS": "Axie Infinity", "ZRX": "0x Protocol", "MNT": "Mantle", "EIGEN": "EigenCloud",
    "ZRO": "LayerZero", "PENGU": "Pudgy Penguins", "VIRTUAL": "Virtuals Protocol", "WLFI": "World Liberty Financial",
    "PNUT": "Peanut the Squirrel", "POPCAT": "Popcat", "MEW": "cat in a dogs world", "MOODENG": "Moo Deng",
    "RAY": "Raydium", "SYRUP": "Maple Finance", "MORPHO": "Morpho", "XCN": "Onyxcoin", "FLR": "Flare",
    "ASTER": "Aster", "AVNT": "Avantis", "BIO": "Bio Protocol", "XPL": "Plasma", "MON": "Monad", "MEGA": "MegaETH",
    "SKY": "Sky", "ZORA": "Zora", "XDC": "XDC Network", "VVV": "Venice Token", "ORCA": "Orca", "SENT": "Sentient",
}
# The liquid, longer-lived coins that have reliable Yahoo history. Used by default so scans are fast and the data is good.
MAJORS = ["BTC", "ETH", "XRP", "SOL", "DOGE", "ADA", "BNB", "LTC", "BCH", "LINK", "XLM", "AVAX", "DOT", "ETC", "ATOM",
          "NEAR", "ALGO", "HBAR", "XTZ", "SHIB", "AAVE", "COMP", "CRV", "GRT", "SNX", "BAT", "FET", "INJ", "IMX", "PEPE",
          "UNI", "SUI", "ARB", "OP", "RENDER", "WLD", "ONDO", "TRUMP", "HYPE", "WIF", "BONK", "FLOKI", "LDO", "SEI"]
# Yahoo gives some coins an extra id in the symbol (to tell them apart from others with the same ticker). Best known ones;
# anything else falls back to a Yahoo search the first time (saved in crypto_symbols.json).
ALIASES = {"UNI": "UNI7083-USD", "SUI": "SUI20947-USD", "ARB": "ARB11841-USD", "TRUMP": "TRUMP35336-USD",
           "HYPE": "HYPE32196-USD", "STRK": "STRK22691-USD", "WLD": "WLD-USD", "OP": "OP-USD"}
SYMBOL_CACHE = Path(__file__).with_name("crypto_symbols.json")
BENCH = "BTC-USD"


def _load_cache():
    try:
        return json.loads(SYMBOL_CACHE.read_text())
    except Exception:
        return {}


def yahoo_symbol(coin, cache=None):
    coin = coin.upper().strip()
    if coin.endswith("-USD"):
        return coin
    cache = _load_cache() if cache is None else cache
    return cache.get(coin) or ALIASES.get(coin) or f"{coin}-USD"


def resolve_missing(coins, missing):
    """For coins Yahoo returned nothing for under the first-guess symbol, ask Yahoo's search once and remember the answer."""
    try:
        import yfinance as yf
    except Exception:
        return {}
    found = {}
    cache = _load_cache()
    for coin in missing:
        try:
            q = yf.Search(f"{COIN_NAMES.get(coin, coin)} USD", max_results=8).quotes
        except Exception:
            continue
        for item in q or []:
            sym = str(item.get("symbol", ""))
            if item.get("quoteType") == "CRYPTOCURRENCY" and sym.endswith("-USD") and sym != yahoo_symbol(coin, cache):
                found[coin] = sym
                break
    if found:
        cache.update(found)
        try:
            SYMBOL_CACHE.write_text(json.dumps(cache, indent=1))
        except Exception:
            pass
    return found


def criteria(**kw):
    """Swing rules tuned for coins: no price floor, no earnings, wide daily-swing limit, volume floor in dollars."""
    base = dict(min_price=0.0, min_market_cap=0, min_avg_volume=2_000_000, max_atr_pct=15.0, skip_earnings_days=0,
                breakout_days=20, breakout_rvol=1.5, stop_atr_mult=2.0, reward_risk=2.0, min_dollar_volume=0)
    base.update(kw)
    return sc.SwingCriteria(**base)


def _finished(d):
    """Drop today's (UTC) still-forming daily candle."""
    if d is None or d.empty:
        return d
    today = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()
    last = pd.Timestamp(d.index[-1]).tz_localize(None).normalize() if getattr(d.index, "tz", None) is not None \
        else pd.Timestamp(d.index[-1]).normalize()
    return d.iloc[:-1] if last >= today else d


def load_daily(symbols, period="2y", chunk=40):
    """{yahoo_symbol: finished daily bars}. Symbols Yahoo has nothing for are simply left out."""
    import yfinance as yf

    out = {}
    symbols = list(dict.fromkeys(symbols))
    for i in range(0, len(symbols), chunk):
        part = symbols[i:i + chunk]
        try:
            raw = yf.download(part, period=period, interval="1d", group_by="ticker", auto_adjust=True,
                              progress=False, threads=True)
        except Exception:
            continue
        if raw is None or raw.empty:
            continue
        for s in part:
            try:
                d = raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw
                d = d[["Open", "High", "Low", "Close", "Volume"]].dropna()
            except KeyError:
                continue
            d = _finished(d)
            if len(d):
                out[s] = d
    return out


def load_with_resolution(coins, period="2y"):
    """Load coins; for ones with no data try Yahoo search for the right symbol. Returns (frames_by_symbol, names_by_symbol, no_data)."""
    cache = _load_cache()
    syms = {c: yahoo_symbol(c, cache) for c in coins}
    frames = load_daily(list(syms.values()), period)
    missing = [c for c, s in syms.items() if s not in frames]
    if missing:
        fixed = resolve_missing(coins, missing)
        if fixed:
            for c, s in fixed.items():
                syms[c] = s
            frames.update(load_daily(list(fixed.values()), period))
    names = {s: COIN_NAMES.get(c, c) for c, s in syms.items()}
    no_data = [c for c, s in syms.items() if s not in frames]
    return frames, names, no_data


def nice(x, sig=5):
    """Round a price to a sensible number of significant digits (coins can cost $90,000 or $0.00001)."""
    if x is None or x != x or x == 0:
        return x
    return round(float(x), sig - 1 - int(math.floor(math.log10(abs(x)))))


def chart_scale(df):
    """Power of ten that lifts tiny prices (SHIB, PEPE...) to at least 1, so chart labels aren't all 0.00."""
    med = float(df["Close"].tail(60).median())
    if not med or med >= 1:
        return 1
    return 10 ** int(math.ceil(-math.log10(med)))


def weather(btc):
    """Bitcoin's trend as a 'crypto market weather' read: Sunny / Partly cloudy / Stormy."""
    d = so.add_indicators(btc)
    r = d.iloc[-1]
    pts = 2 * bool(r.Close > r.EMA200) + bool(r.EMA20 > r.EMA200) + bool(r.Close > r.EMA20)
    chg7 = (r.Close / d.Close.iloc[-8] - 1) * 100 if len(d) > 8 else float("nan")
    pts += 1 if chg7 == chg7 and chg7 > 0 else 0
    frac = pts / 5
    if frac >= 0.8:
        label, level = "Sunny", "success"
        txt = "Bitcoin is in a healthy uptrend, which usually lifts most coins with it."
    elif frac >= 0.5:
        label, level = "Partly cloudy", "warning"
        txt = "Bitcoin's trend is mixed. Be pickier and size smaller."
    else:
        label, level = "Stormy", "error"
        txt = "Bitcoin is weak. When it falls, nearly every coin falls harder, so waiting is a fine choice."
    return {"label": label, "level": level, "score": pts, "max": 5, "text": txt, "close": float(r.Close),
            "above200": bool(r.Close > r.EMA200), "above20": bool(r.Close > r.EMA20), "chg7": float(chg7)}


def scan(c, frames, names, account=None, risk_dollars=0.0, max_pos_pct=100.0):
    """
    Run the swing rules on already-loaded daily bars. Same columns as the stock scanner (Score, past-setup stats...),
    plus 'Buy $' and 'Units' sized so a stop-out loses about risk_dollars.
    Returns (DataFrame ranked by Score, stats dict).
    """
    stats = {"loaded": len(frames), "trend": 0, "setup": 0, "matches": 0}
    btc = frames.get(BENCH)
    bench_close = btc["Close"] if btc is not None else None
    last_bar = None
    rows = []
    for sym, d in frames.items():
        if len(d) < so.MIN_BARS + 5:
            continue
        df = so.add_indicators(d)
        flags = sc.swing_setup_flags(df, c)
        f = flags.iloc[-1]
        r = df.iloc[-1]
        if pd.isna(r.EMA20) or pd.isna(r.EMA200) or pd.isna(r.RSI):
            continue
        last_bar = df.index[-1] if last_bar is None else max(last_bar, df.index[-1])
        if not bool(f["uptrend"]):
            continue
        stats["trend"] += 1
        if not bool(f["filters_ok"]):
            continue
        found = [k for k in sc.SWING_KEYS if k in c.setups and bool(f[k])]
        if not found:
            continue
        stats["setup"] += 1
        atr = float(f["atr"])
        stop = float(r.Close - c.stop_atr_mult * atr)
        risk = float(r.Close - stop)
        if stop <= 0 or risk <= 0:
            continue
        past = sc.setup_history(df, flags, found, c)
        feat = ql.feature_series(df, flags, bench_close, c.stop_atr_mult, c.reward_risk).iloc[-1]
        qscore, qparts, qraw = ql.score_row(feat, past["avg_r"], past["trades"])
        target = float(r.Close + c.reward_risk * risk)
        row = {"Coin": sym.replace("-USD", ""), "Name": names.get(sym, ""), "Symbol": sym,
               "Price": nice(float(r.Close)), "Setup": ", ".join(sc.SETUP_LABELS[x] for x in found),
               "Score": qscore, "RSI": round(float(r.RSI), 0), "ATR %": round(float(f["atr_pct"]), 1),
               "Vol x": round(float(f["rvol"]), 1), "Stop": nice(stop), "Risk %": round(risk / r.Close * 100, 1),
               "Target": nice(target),
               "Room x": round(float(feat["room"]), 2) if feat["room"] == feat["room"] else None,
               "vs BTC 3mo %": round(float(feat["rs"]) * 100, 1) if feat["rs"] == feat["rs"] and sym != BENCH else None,
               "Past setups": past["trades"], "Past hit target %": past["target_pct"], "Past avg R": past["avg_r"],
               "Why": f"{', '.join(sc.SETUP_LABELS[x] for x in found)}, score {(qscore or 0):.0f}: "
                      f"{ql.explain(qparts, qraw, bench='BTC')}"}
        if risk_dollars > 0:
            units = risk_dollars / risk
            cost = units * float(r.Close)
            cap = (account or 0) * max_pos_pct / 100 if account else None
            if cap and cost > cap:
                units, cost = cap / float(r.Close), cap
            row["Buy $"] = round(cost, 2)
            row["Units"] = nice(units, 4)
            row["Risk $"] = round(units * risk, 2)
        rows.append(row)
    stats["matches"] = len(rows)
    stats["last_bar"] = pd.Timestamp(last_bar).strftime("%b %d") if last_bar is not None else ""
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Score", "Vol x"], ascending=False, na_position="last").reset_index(drop=True)
    return df, stats

"""
Cash that stocks and crypto share. Both live in the same Robinhood account, so money tied up in one is not available to
the other. This reads each side's saved trades (read-only) and values what is held, so either side can subtract the other's holdings.
"""
import json
from pathlib import Path

import ledger as lg

HERE = Path(__file__).parent
STOCK_SETTINGS = HERE / "signal_settings.json"
CRYPTO_DB = HERE / "signal_crypto.db"


def _held_value(db_path, prices_fn=None):
    """(market value, number of positions) of what is open in a trades file; (0, 0) when the file doesn't exist or can't be read."""
    try:
        db_path = Path(db_path)
        if not db_path.exists():
            return 0.0, 0
        open_df = lg.build_positions(lg.Store(str(db_path)).transactions())["open"]
        if open_df.empty:
            return 0.0, 0
        fetch = prices_fn or lg.fetch_prices
        try:
            px = fetch(list(open_df["Symbol"])) or {}
        except Exception:
            px = {}
        val = lg.value_positions(open_df, px, 0.0)      # falls back to cost when a price is missing
        return float(val["Market value"].sum()), int(len(val))
    except Exception:
        return 0.0, 0


def crypto_held(prices_fn=None, db_path=None):
    return _held_value(db_path or CRYPTO_DB, prices_fn)


def stock_held(prices_fn=None, db_path=None):
    return _held_value(db_path or lg.DB_PATH, prices_fn)


def stock_account():
    """(account value, cash reserve) the stock side saved; (0, 0) if none."""
    try:
        d = json.loads(STOCK_SETTINGS.read_text())
        if d.get("practice"):
            return float(d.get("acct_value_practice", 0.0)), 0.0
        return float(d.get("acct_value", 0.0)), float(d.get("cash_reserve", 0.0))
    except Exception:
        return 0.0, 0.0

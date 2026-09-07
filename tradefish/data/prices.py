"""Price feed via yfinance ('.NS' symbols).

Plan §3 names openchart as primary, but its upstream NSE charting API broke
(search ignores the query as of Aug 2026). Same interface either way — swapping
the source back later only touches this file.
"""

import logging

import pandas as pd
import yfinance as yf

from tradefish import db

logger = logging.getLogger(__name__)


def _yf(symbol: str) -> str:
    return f"{symbol}.NS"


def history(symbols: list[str], weeks: int = 30) -> dict[str, pd.DataFrame]:
    """Daily OHLCV per symbol (adjusted), oldest first. Missing names are skipped."""
    data = yf.download([_yf(s) for s in symbols], period=f"{weeks * 7}d", interval="1d",
                       group_by="ticker", progress=False, auto_adjust=True, threads=True)
    out = {}
    for s in symbols:
        try:
            df = data[_yf(s)].dropna()
        except KeyError:
            logger.warning("no price data for %s", s)
            continue
        df.columns = [c.lower() for c in df.columns]
        if len(df):
            out[s] = df
    return out


def index_history(symbol: str = "^NSEI", weeks: int = 60) -> pd.DataFrame:
    """Daily OHLCV for an index — no '.NS' suffix, columns lowercased."""
    df = yf.download(symbol, period=f"{weeks * 7}d", interval="1d",
                     progress=False, auto_adjust=True)
    if df.empty:
        raise RuntimeError(f"no data for index {symbol}")
    df.columns = [c[0].lower() if isinstance(c, tuple) else c.lower() for c in df.columns]
    return df.dropna()


def latest(symbol: str) -> float | None:
    """Near-live quote (delayed ~15 min on yfinance — fine for paper trading)."""
    try:
        price = float(yf.Ticker(_yf(symbol)).fast_info["last_price"])
    except Exception as e:
        logger.warning("quote failed for %s: %r", symbol, e)
        return None
    with db.connect() as conn:  # cached so the dashboard can mark to market
        conn.execute(
            "INSERT INTO quotes (ticker, price, ts) VALUES (?, ?, ?)"
            " ON CONFLICT(ticker) DO UPDATE SET price = excluded.price, ts = excluded.ts",
            (symbol, price, db.now()),
        )
    return price

"""Historical prices for the backtest: bulk fetch once, cache to disk, slice by date."""

import hashlib
import logging

import pandas as pd
import yfinance as yf

from tradefish.db import ROOT

logger = logging.getLogger(__name__)

CACHE_DIR = ROOT / "data" / "backtest_cache"


def _yf(symbol: str) -> str:
    return f"{symbol}.NS"


def fetch_all(symbols: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    """Daily OHLCV per symbol for [start, end), cached to disk after the first fetch."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # symbol list is part of the cache key — a different universe must not reuse another's cache
    universe_hash = hashlib.sha1(",".join(sorted(symbols)).encode()).hexdigest()[:10]
    cache_file = CACHE_DIR / f"prices_{start}_{end}_{universe_hash}.pkl"
    if cache_file.exists():
        logger.info("using cached prices: %s", cache_file.name)
        return pd.read_pickle(cache_file)

    logger.info("fetching %d symbols %s to %s", len(symbols), start, end)
    data = yf.download([_yf(s) for s in symbols], start=start, end=end, interval="1d",
                       group_by="ticker", progress=False, auto_adjust=True, threads=True)
    out = {}
    for s in symbols:
        try:
            df = data[_yf(s)].dropna()
        except KeyError:
            continue
        df.columns = [c.lower() for c in df.columns]
        if len(df):
            out[s] = df
    pd.to_pickle(out, cache_file)
    return out


def fetch_benchmark(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Daily OHLCV for an index symbol (e.g. '^NSEI'), no '.NS' suffix, no cache."""
    df = yf.download(symbol, start=start, end=end, interval="1d",
                     progress=False, auto_adjust=True)
    df.columns = [c[0].lower() for c in df.columns]  # yfinance returns a MultiIndex here
    return df


def as_of(history: dict[str, pd.DataFrame], cutoff: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """Slice every symbol's history to bars strictly before cutoff (point-in-time)."""
    return {s: df[df.index < cutoff] for s, df in history.items()}


def week_bars(history: dict[str, pd.DataFrame], monday: pd.Timestamp,
             friday: pd.Timestamp) -> dict[str, pd.DataFrame]:
    """One week's daily bars per symbol, inclusive of both ends, dropping empty weeks."""
    out = {}
    for s, df in history.items():
        week = df[(df.index >= monday) & (df.index <= friday)]
        if not week.empty:
            out[s] = week
    return out

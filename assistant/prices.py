"""Daily prices from Upstox, saved under data/assistant/bars.csv.

The access token is read from .env by the engine. This file never prints it.
"""

import csv
import time
from datetime import date

from assistant.clock import today
from assistant.config import BARS_PATH, INDEX_BARS, PHARMA_BARS
from assistant.engine import engine
from assistant.log import get_logger

log = get_logger()
HEADER = ["symbol", "date", "open", "high", "low", "close", "volume"]


def _last_dates(path) -> dict[str, str]:
    last = {}
    if not path.exists():
        return last
    with path.open() as handle:
        for row in csv.DictReader(handle):
            symbol = row["symbol"]
            if row["date"] > last.get(symbol, ""):
                last[symbol] = row["date"]
    return last


def ensure_prices(symbols: list[str]) -> None:
    """Download any missing days for these symbols. Older rows are left as they are."""
    known = _last_dates(PHARMA_BARS)
    known.update(_last_dates(BARS_PATH))
    index_last = _last_dates(INDEX_BARS).get(engine.INDEX_SYMBOL, "")
    end = today()
    end_text = end.isoformat()
    token = None

    def get_token() -> str:
        nonlocal token
        if token is None:
            token = engine.load_token()
            log.info("Upstox token loaded for the price refresh")
        return token

    if index_last and index_last < end_text:
        try:
            got = engine.download_daily(
                get_token(), engine.INDEX_KEY, engine.INDEX_SYMBOL, date.fromisoformat(index_last), end
            )
        except RuntimeError as exc:
            log.warning("%s", exc)
            got = []
        fresh = [row for row in got if row[1] > index_last]
        if fresh:
            with INDEX_BARS.open("a", newline="") as handle:
                csv.writer(handle).writerows(fresh)
            index_last = max(row[1] for row in fresh)
            log.info("index updated through %s", index_last)
    horizon = min(index_last, end_text) if index_last else end_text
    missing = [symbol for symbol in symbols if known.get(symbol, "") < horizon]
    log.info("Upstox price refresh: %d symbols, %d need a download", len(symbols), len(missing))
    BARS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not BARS_PATH.exists():
        with BARS_PATH.open("w", newline="") as handle:
            csv.writer(handle).writerow(HEADER)
    for symbol in missing:
        prev = known.get(symbol, "")
        start = date.fromisoformat(prev) if prev else engine.FETCH_START
        try:
            key = engine.resolve_equity(get_token(), symbol)
            got = engine.download_daily(get_token(), key, symbol, start, end)
        except RuntimeError as exc:
            log.warning("%s", exc)
            time.sleep(0.25)
            continue
        fresh = [row for row in got if row[1] > prev]
        if fresh:
            with BARS_PATH.open("a", newline="") as handle:
                csv.writer(handle).writerows(fresh)
            log.info("%s +%d through %s", symbol, len(fresh), fresh[0][1])
        else:
            log.debug("%s already current", symbol)
        time.sleep(0.25)


def load_series(symbols: list[str]) -> dict:
    """Pharma bars first, then any newer rows saved for the holdings."""
    have = {}
    if PHARMA_BARS.exists():
        have.update(engine.load_csv(PHARMA_BARS))
    if BARS_PATH.exists():
        extra = engine.load_csv(BARS_PATH)
        for symbol, series in extra.items():
            if symbol not in have:
                have[symbol] = series
                continue
            have[symbol] = _merge(have[symbol], series)
    return {symbol: have[symbol] for symbol in symbols if symbol in have}


def _merge(left, right):
    rows = {}
    for series in (left, right):
        for i, day in enumerate(series.dates):
            rows[day] = (float(series.open[i]), float(series.high[i]), float(series.low[i]), float(series.close[i]))
    days = sorted(rows)
    return engine.Series(
        dates=days,
        open=engine.np.array([rows[day][0] for day in days]),
        high=engine.np.array([rows[day][1] for day in days]),
        low=engine.np.array([rows[day][2] for day in days]),
        close=engine.np.array([rows[day][3] for day in days]),
    )

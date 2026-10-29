"""Company names for NSE equity symbols.

The public instrument file is the source. short_name is the readable
company name. The truncated exchange name is the fallback.
A copy is kept in data/assistant/names.json so the page does not
download the file on every request.
"""

import gzip
import json
import time
import urllib.request

from assistant.config import DATA, NSE_INSTRUMENTS
from assistant.log import get_logger

log = get_logger()
CACHE = DATA / "names.json"
MAX_AGE = 24 * 60 * 60
_memory = None


def equity_names() -> dict:
    global _memory
    if _memory is not None:
        return _memory
    cached = _read(allow_stale=False)
    if cached is not None:
        _memory = cached
        return _memory
    try:
        _memory = _fetch()
        _write(_memory)
        log.info("stored %d NSE company names", len(_memory))
    except Exception:
        log.exception("NSE company names unavailable")
        _memory = _read(allow_stale=True) or {}
    return _memory


def names_for(symbols) -> dict:
    table = equity_names()
    return {symbol: table[symbol] for symbol in symbols if symbol and symbol in table}


def _fetch() -> dict:
    log.info("reading NSE company names")
    with urllib.request.urlopen(NSE_INSTRUMENTS, timeout=60) as response:
        payload = gzip.decompress(response.read())
    names = {}
    kinds = {}
    for item in json.loads(payload):
        if item.get("segment") != "NSE_EQ":
            continue
        kind = item.get("instrument_type")
        if kind not in ("EQ", "BE", "SM", "ST"):
            continue
        symbol = item.get("trading_symbol")
        if not symbol:
            continue
        short = (item.get("short_name") or "").strip()
        official = (item.get("name") or "").strip()
        # short_name is the readable company. If it is only the ticker, use the official name.
        if short and short.upper() != symbol.upper():
            label = short
        else:
            label = official or short
        if not label:
            continue
        # EQ beats BE, and both beat an SME line for the same symbol.
        rank = {"EQ": 3, "BE": 2, "SM": 1, "ST": 1}
        if symbol in names and rank.get(kinds.get(symbol), 0) > rank.get(kind, 0):
            continue
        names[symbol] = label
        kinds[symbol] = kind
    return names


def _read(allow_stale: bool):
    if not CACHE.exists():
        return None
    if not allow_stale and time.time() - CACHE.stat().st_mtime > MAX_AGE:
        return None
    try:
        payload = json.loads(CACHE.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    names = payload.get("names")
    if not isinstance(names, dict):
        return None
    return names


def _write(names: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"names": names}))

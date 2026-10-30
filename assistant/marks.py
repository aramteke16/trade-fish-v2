"""Portfolio figures from the price files. No Upstox call on a page refresh."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import numpy as np

from assistant.config import BARS_PATH, PHARMA_BARS
from assistant.engine import engine
from assistant.log import get_logger

log = get_logger()
IST = ZoneInfo("Asia/Kolkata")
_cache = {"stamp": None, "series": {}}


def enrich(book: dict, top: set, sell_bar, min_hold: int) -> dict:
    as_of = datetime.now(IST).date()
    series = _series()
    rows = []
    cost_total = 0.0
    market_total = 0.0
    for lot in book["lots"]:
        rows.append(_row(lot, series.get(lot.get("symbol")), as_of, top, sell_bar, min_hold))
    for row in rows:
        if row["cost"] is not None:
            cost_total += row["cost"]
        if row["market"] is not None:
            market_total += row["market"]
    rows.sort(key=lambda item: (item.get("symbol") or "zzz", item.get("id") or 0))
    pnl = market_total - cost_total if rows else 0.0
    return {
        "cash": book["cash"],
        "sale_proceeds": book.get("sale_proceeds") or 0,
        "last_add_month": book.get("last_add_month"),
        "as_of": book.get("as_of"),
        "cost": round(cost_total, 2),
        "market": round(market_total, 2),
        "pnl": round(pnl, 2),
        "sell_bar": sell_bar,
        "rows": rows,
    }


def _row(lot: dict, one, as_of: date, top: set, sell_bar, min_hold: int) -> dict:
    symbol = lot.get("symbol")
    close = low = high = None
    if one is not None and len(one.dates):
        close = float(one.close[-1])
        low = float(one.low[-1])
        high = float(one.high[-1])
    cost = None
    if lot.get("avg_price") is not None:
        cost = round(lot["shares"] * float(lot["avg_price"]), 2)
    market = round(lot["shares"] * close, 2) if close is not None else None
    pnl = None if cost is None or market is None else round(market - cost, 2)
    pnl_pct = None
    if pnl is not None and cost:
        pnl_pct = round(pnl / cost, 4)
    held = None
    term = None
    anniversary = None
    if lot.get("purchased"):
        bought = date.fromisoformat(lot["purchased"])
        held = max(0, (as_of - bought).days)
        anniversary = engine.add_year(bought).isoformat()
        term = "short-term" if as_of <= engine.add_year(bought) else "long-term"
    life_share = None
    hold_share = None
    if one is not None and len(one.close):
        life_share = _up_share(one.open, one.close)
        if lot.get("purchased"):
            bought = date.fromisoformat(lot["purchased"])
            mask = [stamp >= bought for stamp in one.dates]
            if any(mask):
                hold_share = _up_share(one.open[mask], one.close[mask])
    if not symbol:
        listed = "unscored"
    elif symbol in engine.PHARMA_ALL or symbol in engine.PHARMA_FAMOUS:
        listed = "pharma"
    elif symbol in engine.POWER or symbol in engine.POWER_FAMOUS:
        listed = "electricity"
    else:
        listed = "personal"
    days_to_sell = None
    if lot.get("from_book"):
        sell_note = "no 60-day wait"
    elif held is None:
        sell_note = "no date"
    elif held >= min_hold:
        sell_note = "eligible"
    else:
        days_to_sell = min_hold - held
        sell_note = str(days_to_sell) + " days left"
    return {
        "id": lot["id"],
        "symbol": symbol,
        "name": lot.get("name"),
        "isin": lot.get("isin"),
        "shares": lot["shares"],
        "avg_price": lot.get("avg_price"),
        "purchased": lot.get("purchased"),
        "from_book": bool(lot.get("from_book")),
        "source": lot.get("source") or ("algo" if lot.get("from_book") else "manual"),
        "list": listed,
        "close": None if close is None else round(close, 2),
        "low": None if low is None else round(low, 2),
        "high": None if high is None else round(high, 2),
        "cost": cost,
        "market": market,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "held_days": held,
        "term": term,
        "anniversary": anniversary,
        "hold_share": None if hold_share is None else round(hold_share, 4),
        "life_share": None if life_share is None else round(life_share, 4),
        "in_top3": bool(symbol and symbol in top),
        "sell_note": sell_note,
        "days_to_sell": days_to_sell,
        "sell_bar": sell_bar,
    }


def _up_share(opens, closes) -> float:
    factor = closes / opens * (1.0 - engine.LIM_DELTA) ** 2
    return float(np.mean(factor >= 1.0))


def _series() -> dict:
    stamp = (
        PHARMA_BARS.stat().st_mtime if PHARMA_BARS.exists() else 0,
        BARS_PATH.stat().st_mtime if BARS_PATH.exists() else 0,
    )
    if _cache["stamp"] == stamp and _cache["series"]:
        return _cache["series"]
    found = {}
    if PHARMA_BARS.exists():
        found.update(engine.load_csv(PHARMA_BARS))
    if BARS_PATH.exists():
        extra = engine.load_csv(BARS_PATH)
        for symbol, series in extra.items():
            if symbol not in found:
                found[symbol] = series
    _cache["stamp"] = stamp
    _cache["series"] = found
    log.info("loaded price files for the portfolio, %d symbols", len(found))
    return found

"""Weekly top 3.

The rank is the last 90 sessions. The list is the pharma universe plus the
symbols already on the book. The top 3 share the weekly budget by the
network weights, highest weight first, in whole shares. A name whose one
share costs more than its slice waits.

The message does not sell, and it does not change lots or cash. You place
the buys. Prices come from Upstox.
"""

from datetime import date

from assistant.clock import today
from assistant.config import ACTOR_PATH, INDEX_BARS
from assistant.db import get_settings, record_decision
from assistant.engine import engine
from assistant.holdings import load
from assistant.lock import run_lock
from assistant.log import get_logger
from assistant.names import names_for
from assistant.notify import send_week
from assistant.prices import ensure_prices, load_series

log = get_logger()


def run_week(source: str = "schedule") -> dict:
    """Store the top 3 buy lines. Lots and cash stay as they are."""
    with run_lock():
        return _run_week(source)


def _run_week(source: str) -> dict:
    book = load()
    rules = get_settings()
    budget = int(float(rules.get("weekly_cash") or rules.get("monthly_cash") or 0))
    symbols = _symbols(book)
    log.info("loading prices from Upstox")
    ensure_prices(symbols)
    series = load_series(symbols)
    market = engine.Book(series)
    day = _decision_day(series)
    log.info("decision close %s, Upstox prices loaded for %d symbols", day, len(series))

    held = {lot["symbol"] for lot in book["lots"] if lot.get("symbol") and int(lot.get("shares") or 0) > 0}
    ranking = _ranking(market, day, set(engine.MIDCAP), held)
    top = ranking[: engine.N_HOLD]
    log.info("top 3: %s", ", ".join(f"{symbol} {score:.3f}" for symbol, score in top) or "none")

    buys = _top_buys(market, day, top, budget)
    _attach_ranges(buys, market, day)
    top_rows = [{"symbol": symbol, "score": round(score, 4)} for symbol, score in top]
    rank_rows = [{"symbol": symbol, "score": round(score, 4)} for symbol, score in ranking]
    _attach_names(buys + top_rows + rank_rows)
    sends = source in ("schedule", "now")
    status = "sent" if sends else "preview"
    decision = {
        "day": day.isoformat(),
        "source": source,
        "status": status,
        "month": f"{day.year:04d}-{day.month:02d}",
        "invest_rupees": budget,
        "sell_bar": None,
        "top": top_rows,
        "ranking": rank_rows,
        "sells": [],
        "buys": buys,
        "orders_sent": False,
    }
    record_decision(decision)
    if sends:
        try:
            send_week(decision)
        except Exception:
            log.exception("telegram failed")
    else:
        log.info("preview stored. holdings were left as they are")
    _print(decision)
    return decision


def _symbols(book: dict) -> list[str]:
    names = set(engine.MIDCAP)
    for lot in book["lots"]:
        if lot.get("symbol"):
            names.add(lot["symbol"])
    return sorted(names)


def _decision_day(series: dict) -> date:
    # The pharma file is the clock. A newly fetched name must not pull the date forward alone.
    # A frozen ASSISTANT_TODAY keeps the close on or before that day.
    limit = today()
    pharma_days = []
    for symbol in engine.PHARMA_ALL:
        one = series.get(symbol)
        if one is None or not one.dates:
            continue
        on_or_before = [day for day in one.dates if day <= limit]
        if on_or_before:
            pharma_days.append(on_or_before[-1])
    if not pharma_days:
        raise RuntimeError("no pharma close on or before %s" % limit.isoformat())
    return max(pharma_days)


def _ranking(market, day: date, pharma: set[str], held: set[str]) -> list[tuple[str, float]]:
    """Same 90-day score as the tested book. Holdings join the midcap list."""
    log.info("buy rank is current holdings plus the midcap list")
    raw = []
    for symbol, one in market.symbols.items():
        if symbol not in pharma and symbol not in held:
            continue
        # A name you already hold does not wait out the one-year listing rule.
        if symbol not in held and not engine.seasoned(one, day):
            continue
        hist = engine.history_until(one, market.loc[symbol], day, engine.LIM_WINDOW)
        if hist is None:
            log.debug("no 90-day window for %s", symbol)
            continue
        raw.append((symbol, engine.lim_score(hist[0], hist[3])))
    if not raw:
        log.info("no name had 90 sessions")
        return []
    best = max(score for _, score in raw)
    scale = max(1.0, best)
    scored = [(symbol, score / scale) for symbol, score in raw]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored


def _top_buys(market, day: date, top: list, budget: int) -> list:
    """Split the weekly budget across the top 3 by network weight. Whole shares."""
    if budget <= 0:
        log.info("weekly budget is ₹0")
        return []
    if not top:
        log.info("no ranked names")
        return []
    scores = {symbol: score for symbol, score in top}
    weighted = _weights(market, day, [symbol for symbol, _ in top])
    log.info("weekly budget ₹%d across the top %d", budget, len(top))
    buys = []
    for symbol, weight in weighted:
        price = market.close_on_or_before(symbol, day)
        slice_rupees = float(weight) * budget
        if not price:
            log.info("skip %s: no price", symbol)
            continue
        shares = int(slice_rupees // float(price))
        if shares < 1:
            log.info(
                "skip %s: one share is ₹%.2f and its slice is ₹%.0f",
                symbol,
                price,
                slice_rupees,
            )
            continue
        log.info(
            "buy %s weight %.3f amount %d shares, about ₹%.0f at the last close",
            symbol,
            weight,
            shares,
            shares * price,
        )
        buys.append(
            {
                "symbol": symbol,
                "shares": shares,
                "price": round(float(price), 2),
                "rupees": round(shares * float(price), 2),
                "score": round(float(scores.get(symbol, 0.0)), 4),
                "weight": round(float(weight), 4),
                "budget": round(slice_rupees, 2),
            }
        )
    if not buys:
        log.info("no name fits its slice of the weekly budget")
    return buys


def _weights(market, day: date, names: list) -> list:
    """Weights for the top 3, highest first.

    The account inputs are the original ₹10 lakh, with no drawdown and no
    last-day change. The network does not see the live share counts.
    """
    if not names:
        return []
    index = _load_index()
    if ACTOR_PATH.exists() and index is not None and len(names) == engine.N_HOLD:
        actor = engine.load_actor(ACTOR_PATH)
        state = engine.state_vector(
            market,
            index,
            engine.index_of(index),
            day,
            names,
            engine.CAPITAL,
            engine.CAPITAL,
            engine.CAPITAL,
        )
        weights, _, _, _ = engine.actor_weights(actor, state, None)
        pairs = list(zip(names, [float(weight) for weight in weights]))
    else:
        if not ACTOR_PATH.exists():
            log.info("actor file missing, equal weights")
        elif index is None:
            log.info("index file missing, equal weights")
        pairs = [(symbol, 1.0 / len(names)) for symbol in names]
    pairs.sort(key=lambda item: (-item[1], item[0]))
    return pairs


def _load_index():
    if not INDEX_BARS.exists():
        return None
    return engine.load_csv(INDEX_BARS).get(engine.INDEX_SYMBOL)


def _attach_ranges(buys: list, market, day: date) -> None:
    """Last session low, high, and close from the Upstox bars. No invented band."""
    for buy in buys:
        close, low, high = _session(market, buy["symbol"], day)
        if close is not None:
            buy["price"] = round(close, 2)
            buy["rupees"] = round(buy["shares"] * close, 2)
        buy["low"] = round(low, 2) if low is not None else None
        buy["high"] = round(high, 2) if high is not None else None


def _session(market, symbol: str, day: date):
    bar = market.bar(symbol, day)
    if bar is None:
        return None, None, None
    _open, high, low, close = bar
    return float(close), float(low), float(high)


def _attach_names(rows: list) -> None:
    table = names_for([row["symbol"] for row in rows if row.get("symbol")])
    for row in rows:
        official = table.get(row.get("symbol"))
        if official:
            row["name"] = official
        elif not row.get("name"):
            row["name"] = ""


def _print(decision: dict) -> None:
    log.info("AS OF %s close. No broker. Sheet only.", decision["day"])
    log.info("Invest ₹%s. Act at the next NSE cash open, 09:15 IST.", int(decision.get("invest_rupees") or 0))
    if not decision["buys"]:
        log.info("BUY none")
    for buy in decision["buys"]:
        log.info(
            "BUY %s (%s) amount %d  range %s–%s",
            buy.get("name") or buy["symbol"],
            buy["symbol"],
            buy["shares"],
            buy.get("low"),
            buy.get("high"),
        )
    log.info("no sell. you place the buy yourself")

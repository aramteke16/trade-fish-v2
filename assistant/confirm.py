"""Write lots only after you confirm them.

The Friday sheet is a proposal. Done records the shares you actually
bought or sold. A manual purchase adds a lot. A name already in the
pharma list, the electricity list, or the current book does not get a
second listing.
"""

from __future__ import annotations

from datetime import date, timedelta

from assistant.clock import today
from assistant.db import get_decision, insert_fill, list_decisions, load_book, save_book, write_status
from assistant.engine import engine
from assistant.lock import run_lock
from assistant.log import get_logger
from assistant.names import equity_names
from assistant.prices import ensure_prices

log = get_logger()


def expire_before(day: date, book: dict) -> dict:
    """A missed open sheet leaves its ₹20,000 unspent. A same-day re-run replaces the sheet."""
    changed = False
    for row in list_decisions():
        if row.get("status") != "open" or row.get("source") == "manual":
            continue
        if row["day"] >= day.isoformat():
            write_status(row["id"], "replaced")
            log.info("replaced open sheet %s with the new run", row["day"])
            continue
        invest = float(row.get("invest_rupees") or 0)
        if invest:
            book["cash"] = round(float(book["cash"]) + invest, 2)
            if row.get("month"):
                book["last_add_month"] = row["month"]
            log.info("expired %s: ₹%.0f left unspent and not added to the next buy", row["day"], invest)
            changed = True
        else:
            log.info("expired %s", row["day"])
        write_status(row["id"], "expired")
    if changed:
        book["as_of"] = day.isoformat()
        save_book(book)
    return book


def confirm_done(decision_id: int, fill_date: str, lines: list) -> str:
    with run_lock():
        return _confirm_done(decision_id, fill_date, lines)


def add_purchase(query: str, shares: int, rupees: float, fill_date: str) -> str:
    with run_lock():
        return _add_purchase(query, shares, rupees, fill_date)


def set_purchased(lot_id: int, purchased: str) -> None:
    with run_lock():
        _set_purchased(lot_id, purchased)


def next_session(day: date) -> str:
    nxt = day + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt.isoformat()


def classify(symbol: str, book: dict) -> str:
    if symbol in engine.PHARMA_ALL:
        return "pharma"
    if symbol in engine.POWER:
        return "electricity"
    if _held(symbol, book):
        return "personal"
    return ""


def _confirm_done(decision_id: int, fill_date: str, lines: list) -> str:
    decision = get_decision(int(decision_id))
    if decision is None:
        raise ValueError("that sheet does not exist")
    if decision.get("status") != "open" or decision.get("source") == "manual":
        raise ValueError("that sheet is not waiting for Done")
    filled_on = _fill_day(fill_date, date.fromisoformat(decision["day"]))
    expected = {}
    for sale in decision.get("sells") or []:
        expected[("sell", int(sale["lot_id"]))] = sale
    for buy in decision.get("buys") or []:
        expected[("buy", buy["symbol"])] = buy
    if not isinstance(lines, list) or len(lines) != len(expected):
        raise ValueError("send every buy and every sell as filled or skipped")
    seen = set()
    parsed = []
    for line in lines:
        if not isinstance(line, dict):
            raise ValueError("each line must be an object")
        side = line.get("side")
        action = line.get("action")
        if action not in ("fill", "skip"):
            raise ValueError("each line is filled or skipped")
        if side == "sell":
            key = ("sell", _whole(line.get("lot_id"), "lot"))
        elif side == "buy":
            key = ("buy", str(line.get("symbol") or ""))
        else:
            raise ValueError("side is buy or sell")
        if key not in expected or key in seen:
            raise ValueError("a line does not match this sheet")
        seen.add(key)
        parsed.append((key, action, line))
    if seen != set(expected):
        raise ValueError("send every buy and every sell as filled or skipped")

    book = load_book()
    by_id = {lot["id"]: lot for lot in book["lots"]}
    spent = 0.0
    sold_rupees = 0.0
    fill_rows = []
    for key, action, line in parsed:
        proposal = expected[key]
        symbol = proposal["symbol"]
        name = proposal.get("name") or ""
        if action == "skip":
            fill_rows.append(_fill_row(decision, key[0], symbol, name, proposal, filled_on, 0, None, "skipped"))
            log.info("skip %s %s", key[0], symbol)
            continue
        shares = _whole(line.get("shares"), "amount")
        rupees = _rupees(line.get("rupees"))
        if shares < 1:
            raise ValueError(symbol + " amount is at least 1 share")
        if key[0] == "sell":
            lot = by_id.get(key[1])
            if lot is None or lot.get("symbol") != symbol:
                raise ValueError(symbol + " lot is not on the book")
            if shares > int(proposal["shares"]) or shares > int(lot["shares"]):
                raise ValueError(symbol + " amount is above the shares on that lot")
            lot["shares"] -= shares
            sold_rupees += rupees
            fill_rows.append(
                _fill_row(decision, "sell", symbol, name, proposal, filled_on, shares, rupees, "filled", key[1])
            )
            log.info("confirmed sell %s %s amount %d", name, symbol, shares)
        else:
            budget = float(proposal.get("budget") or 0)
            if rupees > budget + 0.05:
                raise ValueError(symbol + " rupees are above this name's budget")
            price = rupees / shares
            lot = {
                "symbol": symbol,
                "isin": None,
                "name": name or symbol,
                "shares": shares,
                "purchased": filled_on.isoformat(),
                "avg_price": round(price, 4),
                "from_book": True,
                "source": "algo",
            }
            book["lots"].append(lot)
            spent += rupees
            fill_rows.append(_fill_row(decision, "buy", symbol, name, proposal, filled_on, shares, rupees, "filled"))
            log.info("confirmed buy %s %s amount %d", name, symbol, shares)

    book["lots"] = [lot for lot in book["lots"] if lot["shares"] > 0]
    book["sale_proceeds"] = round(float(book.get("sale_proceeds") or 0) + sold_rupees, 2)
    invest = float(decision.get("invest_rupees") or 0)
    if invest:
        book["cash"] = round(float(book["cash"]) + max(0.0, invest - spent), 2)
        book["last_add_month"] = decision.get("month")
        log.info("unspent ₹%.0f parked. sale rupees stay out of the buy budget", max(0.0, invest - spent))
    book["as_of"] = filled_on.isoformat()
    save_book(book)
    for row in fill_rows:
        if row["side"] == "buy" and row["note"] == "filled" and row.get("lot_id") is None:
            match = [
                lot for lot in book["lots"]
                if lot.get("symbol") == row["symbol"] and lot.get("purchased") == filled_on.isoformat() and lot.get("from_book")
            ]
            if match:
                row["lot_id"] = match[-1]["id"]
        insert_fill(row)
    write_status(decision["id"], "done", orders_sent=True)
    log.info("Done %s. Holdings updated from the confirmed amounts.", decision["day"])
    return "Done. The confirmed amounts are on the book."


def _add_purchase(query: str, shares: int, rupees: float, fill_date: str) -> str:
    book = load_book()
    symbol, name = resolve_query(query, book)
    amount = _whole(shares, "amount")
    paid = _rupees(rupees)
    if amount < 1:
        raise ValueError("amount is at least 1 share")
    filled_on = date.fromisoformat(str(fill_date))
    if filled_on > today():
        raise ValueError("fill date cannot be in the future")
    where = classify(symbol, book)
    book["lots"].append(
        {
            "symbol": symbol,
            "isin": None,
            "name": name,
            "shares": amount,
            "purchased": filled_on.isoformat(),
            "avg_price": round(paid / amount, 4),
            "from_book": False,
            "source": "manual",
        }
    )
    book["as_of"] = filled_on.isoformat()
    save_book(book)
    try:
        log.info("Upstox price refresh for manual buy %s", symbol)
        ensure_prices([symbol])
    except Exception:
        log.exception("price refresh failed for %s", symbol)
    if where:
        notice = f"Already in {where}. Lot only. {name} ({symbol}) was not added again."
    else:
        notice = f"Added {name} ({symbol}) to the personal book."
    log.info("manual buy %s amount %d. %s", symbol, amount, notice)
    return notice


def _set_purchased(lot_id: int, purchased: str) -> None:
    book = load_book()
    lot = next((item for item in book["lots"] if item["id"] == int(lot_id)), None)
    if lot is None:
        raise ValueError("that lot is not on the book")
    if lot.get("purchased"):
        raise ValueError("this lot already has a purchase date")
    day = date.fromisoformat(str(purchased))
    if day > today():
        raise ValueError("purchase date cannot be in the future")
    lot["purchased"] = day.isoformat()
    save_book(book)
    log.info("purchase date %s set on %s", day.isoformat(), lot.get("symbol"))


def resolve_query(text: str, book: dict) -> tuple:
    query = " ".join(str(text or "").strip().split())
    if not query or len(query) > 80:
        raise ValueError("enter a symbol or company name")
    table = equity_names()
    symbol = query.upper()
    known = set(engine.PHARMA_ALL) | set(engine.POWER) | _held_symbols(book)
    if symbol in table or symbol in known:
        return symbol, table.get(symbol) or _lot_name(symbol, book) or symbol
    folded = query.casefold()
    hits = [item for item, label in table.items() if str(label).casefold() == folded]
    for lot in book["lots"]:
        if lot.get("symbol") and lot.get("name") and str(lot["name"]).casefold() == folded:
            if lot["symbol"] not in hits:
                hits.append(lot["symbol"])
    if len(hits) == 1:
        found = hits[0]
        return found, table.get(found) or _lot_name(found, book) or found
    if len(hits) > 1:
        raise ValueError("that name matches more than one symbol")
    raise ValueError("no NSE equity match")


def _held(symbol: str, book: dict) -> bool:
    return symbol in _held_symbols(book)


def _held_symbols(book: dict) -> set:
    return {lot["symbol"] for lot in book["lots"] if lot.get("symbol") and lot["shares"] > 0}


def _lot_name(symbol: str, book: dict) -> str:
    for lot in book["lots"]:
        if lot.get("symbol") == symbol and lot.get("name"):
            return lot["name"]
    return ""


def _fill_day(value: str, decision_day: date) -> date:
    try:
        filled = date.fromisoformat(str(value))
    except ValueError:
        raise ValueError("fill date must be YYYY-MM-DD") from None
    latest = today() + timedelta(days=7)
    if filled < decision_day or filled > latest:
        raise ValueError("fill date must be on or after the close and within 7 days of today")
    return filled


def _fill_row(decision, side, symbol, name, proposal, filled_on, shares, rupees, note, lot_id=None) -> dict:
    price = None if not shares else round(rupees / shares, 4)
    suggested = proposal.get("price") if side == "buy" else proposal.get("close")
    return {
        "decision_id": decision["id"],
        "side": side,
        "symbol": symbol,
        "name": name,
        "lot_id": lot_id if lot_id is not None else proposal.get("lot_id"),
        "suggested_shares": proposal.get("shares"),
        "filled_shares": shares,
        "suggested_price": suggested,
        "fill_price": price,
        "fill_rupees": None if rupees is None else round(rupees, 2),
        "fill_date": filled_on.isoformat(),
        "note": note,
    }


def _whole(value, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(label + " must be a whole number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(label + " must be a whole number") from None
    if not number.is_integer():
        raise ValueError(label + " must be a whole number")
    return int(number)


def _rupees(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("rupees must be a number") from None
    if number <= 0 or number != number or number == float("inf"):
        raise ValueError("rupees must be above zero")
    return number

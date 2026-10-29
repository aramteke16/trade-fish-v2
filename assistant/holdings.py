"""Lots in SQLite. The ranker does not read the rupee amount invested.

Each lot stores the symbol, the share count, and the purchase date.
The purchase date is the sell window. The share count is used only when
writing how many shares to sell. The average price is kept so the sheet
can show rupees. It is not a ranker input.
"""

import gzip
import json
import urllib.request
from datetime import date

from assistant.config import NSE_INSTRUMENTS
from assistant.db import load_book, save_book
from assistant.log import get_logger

log = get_logger()


def load() -> dict:
    return load_book()


def save(book: dict) -> None:
    save_book(book)


def import_statement(path) -> dict:
    """Read the broker sheet. Purchase dates are not in that sheet, so they stay blank."""
    import pandas as pd

    frame = pd.read_excel(path, header=None)
    header = next(i for i, value in enumerate(frame[0]) if str(value).strip() == "Stock Name")
    rows = frame.iloc[header + 1 :].dropna(subset=[1])
    symbols = _symbols_by_isin({str(isin) for isin in rows[1]})
    lots = []
    for _, row in rows.iterrows():
        isin = str(row[1])
        symbol = symbols.get(isin)
        lots.append(
            {
                "symbol": symbol,
                "isin": isin,
                "name": str(row[0]).strip(),
                "shares": int(row[2]),
                # Blank until you fill it. The sell score refuses a lot with no date.
                "purchased": None,
                "avg_price": float(row[3]) if row[3] == row[3] else None,
                "from_book": False,
            }
        )
        if symbol is None:
            log.warning("no NSE symbol for %s %s", isin, row[0])
    book = {
        "cash": 0.0,
        "sale_proceeds": 0.0,
        "last_add_month": None,
        "as_of": _statement_date(frame),
        "lots": lots,
    }
    save(book)
    log.info("imported %d lots from %s", len(lots), path)
    return book


def _statement_date(frame) -> str:
    """The sheet title carries the date: 'as on 28-10-2026'."""
    for value in frame[0].tolist():
        text = str(value)
        if "as on" not in text:
            continue
        stamp = text.split("as on", 1)[1].strip()
        day, month, year = stamp.split("-")
        return f"{year}-{month}-{day}"
    raise ValueError("holdings sheet has no 'as on' date")


def _symbols_by_isin(wanted: set[str]) -> dict[str, str]:
    log.info("reading NSE instrument list")
    with urllib.request.urlopen(NSE_INSTRUMENTS, timeout=60) as response:
        payload = gzip.decompress(response.read())
    found = {}
    for item in json.loads(payload):
        isin = item.get("isin")
        if isin not in wanted or item.get("segment") != "NSE_EQ":
            continue
        if item.get("instrument_type") not in ("EQ", "BE", "IV"):
            continue
        # Prefer a normal equity line when the ISIN appears more than once.
        if isin not in found or item.get("instrument_type") == "EQ":
            found[isin] = item.get("trading_symbol")
    return found


def apply(book: dict, sells: list[dict], buys: list[dict], day: date) -> None:
    """Change the saved lots to match this week's decision. Sells happen first."""
    by_id = {lot["id"]: lot for lot in book["lots"]}
    for sale in sells:
        lot = by_id[sale["lot_id"]]
        lot["shares"] -= sale["shares"]
        log.info("sell applied %s %d, left %d", lot["symbol"], sale["shares"], lot["shares"])
    book["lots"] = [lot for lot in book["lots"] if lot["shares"] > 0]
    for buy in buys:
        book["lots"].append(
            {
                "symbol": buy["symbol"],
                "isin": buy.get("isin"),
                "name": buy["symbol"],
                "shares": buy["shares"],
                "purchased": day.isoformat(),
                "avg_price": buy["price"],
                "from_book": True,
            }
        )
        book["cash"] = round(book["cash"] - buy["rupees"], 2)
        log.info("buy applied %s %d", buy["symbol"], buy["shares"])
    save(book)

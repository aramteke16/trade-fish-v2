"""NSE/BSE announcement collector (plan §3.1).

Raw API responses are archived immutably under data/raw/announcements before
any normalization. Rows dedupe on content_hash, so re-runs are safe.
"""

import hashlib
import json
import logging
import time
from datetime import date

from tradefish import db

logger = logging.getLogger(__name__)

RAW_DIR = db.ROOT / "data" / "raw" / "announcements"

# candidate field names per source — exchange APIs are not stable contracts
FIELDS = {
    "nse": {
        "ticker": ["symbol"],
        "disclosure": ["exchdisstime", "an_dt", "sort_date"],
        "headline": ["desc", "subject"],
        "text": ["attchmntText"],
        "doc_type": ["desc"],
        "pdf": ["attchmntFile"],
    },
    "bse": {
        "ticker": ["SLONGNAME", "SCRIP_CD"],
        "disclosure": ["News_submission_dt", "DT_TM", "NEWS_DT"],
        "headline": ["NEWSSUB", "HEADLINE"],
        "text": ["HEADLINE", "MORE"],
        "doc_type": ["CATEGORYNAME"],
        "pdf": ["ATTACHMENTNAME"],
    },
}


def _first(item: dict, keys: list[str]) -> str | None:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def normalize(item: dict, source: str) -> dict:
    f = FIELDS[source]
    ticker = _first(item, f["ticker"])
    disclosure = _first(item, f["disclosure"])
    headline = _first(item, f["headline"])
    return {
        "ticker": ticker,
        "source": source,
        "exchange_disclosure_time": disclosure,
        "fetched_at": db.now(),
        "published_at": None,  # media publish time — never trusted for filtering
        "doc_type": _first(item, f["doc_type"]),
        "headline": headline,
        "raw_text": _first(item, f["text"]),
        "pdf_path": _first(item, f["pdf"]),
        "content_hash": hashlib.sha256(
            f"{source}|{ticker}|{disclosure}|{headline}".encode()
        ).hexdigest(),
    }


def store(items: list[dict], source: str) -> int:
    """Insert normalized rows; returns count of new (non-duplicate) rows."""
    stored = 0
    with db.connect() as conn:
        for item in items:
            row = normalize(item, source)
            cur = conn.execute(
                "INSERT OR IGNORE INTO announcements (ticker, source,"
                " exchange_disclosure_time, fetched_at, published_at, doc_type,"
                " headline, raw_text, pdf_path, content_hash)"
                " VALUES (:ticker, :source, :exchange_disclosure_time, :fetched_at,"
                " :published_at, :doc_type, :headline, :raw_text, :pdf_path, :content_hash)",
                row,
            )
            stored += cur.rowcount
    return stored


def fetch_nse(day: date) -> list[dict]:
    from nse import NSE

    with NSE(download_folder=str(RAW_DIR)) as n:
        return n.announcements(index="equities", from_date=day, to_date=day)


def fetch_bse(day: date) -> list[dict]:
    from bse import BSE

    items = []
    with BSE(download_folder=str(RAW_DIR)) as b:
        for page in range(1, 21):
            data = b.announcements(page_no=page, from_date=day, to_date=day)
            rows = data.get("Table", [])
            if not rows:
                break
            items.extend(rows)
            time.sleep(0.6)  # scraping etiquette (plan §3.1)
    return items


FETCHERS = {"nse": fetch_nse, "bse": fetch_bse}


def _archive_raw(items: list, source: str, day: date) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    (RAW_DIR / f"{day}_{source}.json").write_text(json.dumps(items, default=str))


def collect(day: date | None = None, sources: tuple = ("nse", "bse")) -> dict:
    day = day or date.today()
    summary, errors = {"stored": 0}, {}
    for source in sources:
        try:
            items = FETCHERS[source](day)
        except Exception as e:
            logger.exception("%s fetch failed for %s", source, day)
            errors[source] = repr(e)
            summary[source] = 0
            continue
        _archive_raw(items, source, day)
        new = store(items, source)
        logger.info("%s %s: fetched %d, stored %d new", source, day, len(items), new)
        summary[source] = len(items)
        summary["stored"] += new
    if errors and len(errors) == len(sources):
        raise RuntimeError(f"all sources failed: {errors}")
    if errors:
        summary["errors"] = errors
    return summary

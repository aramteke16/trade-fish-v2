"""Evening job: score the day's announcements for universe names through the LLM."""

import logging
from datetime import date

from tradefish import config, db
from tradefish.llm import extractor

logger = logging.getLogger(__name__)

MIN_CHARS = 40    # nothing worth scoring below this
MAX_PER_RUN = 80  # cost guard


def bundles(day: str) -> dict[str, str]:
    """One text bundle per universe ticker from that day's announcements."""
    universe = set(config.universe())
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT ticker, headline, raw_text FROM announcements"
            " WHERE substr(fetched_at, 1, 10) = ?", (day,)
        ).fetchall()
        done = {r["ticker"] for r in conn.execute(
            "SELECT DISTINCT ticker FROM extractions WHERE as_of = ?", (day,)
        )}
    out: dict[str, str] = {}
    outside = 0
    for row in rows:
        if row["ticker"] not in universe or row["ticker"] in done:
            outside += row["ticker"] not in universe
            continue
        text = " ".join(x for x in (row["headline"], row["raw_text"]) if x)
        out[row["ticker"]] = f"{out.get(row['ticker'], '')}\n{text}".strip()
    if outside:
        logger.info("%d announcements outside universe (BSE rows carry company names)", outside)
    return {t: b for t, b in out.items() if len(b) >= MIN_CHARS}


def run() -> str:
    day = date.today().isoformat()
    todo = sorted(bundles(day).items())
    if not todo:
        return "no new universe announcements to score"
    if len(todo) > MAX_PER_RUN:
        logger.warning("%d bundles found, capping this run at %d", len(todo), MAX_PER_RUN)
        todo = todo[:MAX_PER_RUN]

    failed = tokens = 0
    for ticker, text in todo:
        result = extractor.extract(text, ticker, day)
        tokens += result.tokens_used
        failed += result.extraction_failed
    return f"extracted {len(todo)} tickers, {failed} failed, {tokens} tokens"

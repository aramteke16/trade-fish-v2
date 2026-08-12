"""Turn stored extractions into one numeric signal per ticker (plan §4 Stream 3)."""

import json
import logging

from tradefish import db

logger = logging.getLogger(__name__)


def score(e: dict) -> float:
    """Direction x conviction. Scores information only — the prompt forbids price calls."""
    direction = 0.5 * e["sentiment"] + 0.3 * e["surprise"] + 0.2 * e["guidance_delta"]
    return direction * e["magnitude"] * e["novelty"] * (1 - e["uncertainty"])


def signals(since: str) -> dict[str, float]:
    """Strongest signal per ticker since `since`. Failed extractions are excluded."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT ticker, payload FROM extractions WHERE as_of >= ? AND failed = 0",
            (since,),
        ).fetchall()
    out: dict[str, float] = {}
    for row in rows:
        s = score(json.loads(row["payload"]))
        if abs(s) > abs(out.get(row["ticker"], 0.0)):  # one big catalyst beats many small ones
            out[row["ticker"]] = s
    return out

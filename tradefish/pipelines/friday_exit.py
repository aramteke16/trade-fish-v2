"""Fri 15:15 job: time-barrier exit — close every open paper position."""

import logging

from tradefish import db
from tradefish.broker import paper
from tradefish.data import prices

logger = logging.getLogger(__name__)


def run() -> str:
    with db.connect() as conn:
        open_pos = [dict(r) for r in conn.execute(
            "SELECT * FROM positions WHERE status = 'open' AND qty IS NOT NULL"
        )]
    if not open_pos:
        return "no open positions"

    closed = 0
    for pos in open_pos:
        price = prices.latest(pos["ticker"])
        if price is None:  # stays open; next run or manual sell handles it
            logger.error("no quote for %s — position %d left open", pos["ticker"], pos["id"])
            continue
        paper.sell(pos["id"], price, "time")
        closed += 1
    return f"closed {closed}/{len(open_pos)}"

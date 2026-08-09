"""Every 5 min in market hours: exit open paper positions on barrier hits."""

import logging

from tradefish import config, db
from tradefish.broker import paper
from tradefish.data import prices

logger = logging.getLogger(__name__)


def run() -> str:
    upper = config.strategy("upper_barrier")
    lower = config.strategy("lower_barrier")
    with db.connect() as conn:
        open_pos = [dict(r) for r in conn.execute(
            "SELECT * FROM positions WHERE status = 'open' AND qty IS NOT NULL"
        )]
    if not open_pos:
        return "no open positions"

    exits = 0
    for pos in open_pos:
        price = prices.latest(pos["ticker"])
        if price is None:
            continue
        ret = price / pos["entry_price"] - 1
        if ret >= upper:
            paper.sell(pos["id"], price, "take_profit")
            exits += 1
        elif ret <= lower:
            paper.sell(pos["id"], price, "stop_loss")
            exits += 1
    return f"checked {len(open_pos)}, exited {exits}"

"""Mon 09:20 job: rank the universe, buy the top-k paper basket at open."""

import logging
from datetime import date, timedelta

from tradefish import config, db
from tradefish.broker import paper
from tradefish.data import prices
from tradefish.model import baseline

logger = logging.getLogger(__name__)


def run() -> str:
    with db.connect() as conn:
        open_count = conn.execute(
            "SELECT COUNT(*) FROM positions WHERE status = 'open'"
        ).fetchone()[0]
    if open_count:  # never double-buy on re-runs
        return f"skipped — {open_count} positions already open"

    symbols = config.universe()
    hist = prices.history(symbols)
    feats = {s: f for s, df in hist.items() if (f := baseline.features(df))}
    ranked = baseline.rank(feats)
    if not ranked:
        raise RuntimeError(f"no scorable names ({len(hist)}/{len(symbols)} with prices)")

    top_k = config.strategy("top_k")
    monday = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    budget = paper.cash() * 0.99 / top_k  # 1% buffer for charges
    bought = 0
    # walk down the ranking so unaffordable names don't leave slots empty
    for symbol, score in ranked:
        if bought >= top_k:
            break
        price = prices.latest(symbol) or float(hist[symbol]["close"].iloc[-1])
        qty = int(budget / price)
        if qty < 1:
            logger.info("%s skipped — share price %.2f over slot budget %.2f",
                        symbol, price, budget)
            continue
        paper.buy(symbol, price, qty, monday, reason="entry")
        bought += 1
    return f"scored {len(feats)}/{len(symbols)}, bought {bought}/{top_k}"

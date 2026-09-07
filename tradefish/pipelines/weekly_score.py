"""Mon 09:20 job: rank the universe, buy the top-k paper basket at open."""

import logging
from datetime import date, timedelta

from tradefish import config, db, strategy
from tradefish.broker import paper
from tradefish.data import prices
from tradefish.llm import features
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
    if not feats:
        raise RuntimeError(f"no scorable names (0/{len(symbols)} with prices)")

    monday = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    llm_weight = float(config.strategy("llm_weight"))
    # only news disclosed before this morning's decision (plan §3 point-in-time)
    llm = features.signals(since=(date.today() - timedelta(days=7)).isoformat())
    logger.info("llm signals for %d names, weight %.2f", len(llm), llm_weight)

    entry_prices = {s: prices.latest(s) or float(df["close"].iloc[-1]) for s, df in hist.items()}
    top_k = config.strategy("top_k")
    basket = strategy.pick_basket(feats, entry_prices, paper.cash(), top_k, llm, llm_weight)

    for i, pick in enumerate(basket):
        logger.info("pick #%d %s score %.2f llm %.2f", i + 1, pick["ticker"], pick["score"],
                    llm.get(pick["ticker"], 0.0))
        paper.buy(pick["ticker"], pick["price"], pick["qty"], monday, reason="entry")
    return (f"scored {len(feats)}/{len(symbols)}, {len(llm)} with news,"
            f" bought {len(basket)}/{top_k}")

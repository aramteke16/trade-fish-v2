"""Daily 15:45 IST job: quote v5 holdings and append one row to the equity curve."""

import logging
from datetime import date

from tradefish import db
from tradefish.broker import paper
from tradefish.data import prices

logger = logging.getLogger(__name__)

STRATEGY = "v5"


def run() -> str:
    with db.connect() as conn:
        held = [r["ticker"] for r in conn.execute(
            "SELECT DISTINCT ticker FROM positions WHERE status = 'open' AND strategy = ?",
            (STRATEGY,))]
    for ticker in held:
        prices.latest(ticker)  # refreshes the quotes table the snapshot reads

    snap = paper.snapshot(STRATEGY)
    try:
        nifty = float(prices.index_history("^NSEI", weeks=2)["close"].iloc[-1])
    except Exception as e:  # the curve is still useful without the benchmark
        logger.warning("nifty mark failed: %r", e)
        nifty = None

    total = snap["cash"] + snap["market"]
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO v5_equity (day, cash, market, total, open_count, nifty)"
            " VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(day) DO UPDATE SET"
            " cash = excluded.cash, market = excluded.market, total = excluded.total,"
            " open_count = excluded.open_count, nifty = excluded.nifty",
            (date.today().isoformat(), snap["cash"], snap["market"], total,
             snap["open_count"], nifty),
        )
    return f"₹{total:,.0f} ({snap['open_count']} holdings, cash ₹{snap['cash']:,.0f})"

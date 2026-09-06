"""Algo v5 monthly cycle: club check, sells, gates, refill. See docs/algo-v5.md.

Scheduled for the 1st of each month at 15:20 IST; skips itself if it already ran
this month, so a retry after a droplet outage is safe.
"""

import logging
from datetime import date

from tradefish import config, db, v5
from tradefish.broker import paper
from tradefish.data import prices

logger = logging.getLogger(__name__)

STRATEGY = "v5"


def _universe() -> list[str]:
    """v5 universe from the DB; built on first run from the broad pool."""
    with db.connect() as conn:
        rows = [r["symbol"] for r in conn.execute("SELECT symbol FROM v5_universe")]
    if rows:
        return rows
    return rebuild_universe()


def rebuild_universe() -> list[str]:
    """Liquidity filter over the trailing year of the broad pool (annual job)."""
    pool = [line.strip() for line in open(db.ROOT / "config" / "pool.txt")
            if line.strip() and not line.startswith("#")]
    hist = prices.history(pool, weeks=60)
    keep = v5.build_universe(hist)
    with db.connect() as conn:
        conn.execute("DELETE FROM v5_universe")
        conn.executemany("INSERT INTO v5_universe (symbol, built_at) VALUES (?, ?)",
                         [(s, db.now()) for s in keep])
    logger.info("v5 universe rebuilt: %d of %d pool names", len(keep), len(pool))
    return keep


def _already_ran_this_month(today: date) -> bool:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT cycle_date FROM v5_cycles ORDER BY id DESC LIMIT 1").fetchone()
    return bool(row and row["cycle_date"][:7] == today.isoformat()[:7])


def run() -> str:
    today = date.today()
    if _already_ran_this_month(today):
        return f"skipped — cycle already ran in {today.isoformat()[:7]}"

    universe = _universe()
    if not universe:
        raise RuntimeError("v5 universe is empty")

    with db.connect() as conn:
        held = {r["ticker"]: r["id"] for r in conn.execute(
            "SELECT id, ticker FROM positions WHERE status = 'open' AND strategy = ?",
            (STRATEGY,))}

    # need history for the universe plus anything currently held but dropped from it
    symbols = sorted(set(universe) | set(held))
    hist = prices.history(symbols, weeks=60)
    status = v5.club_status(hist)
    if status.empty:
        raise RuntimeError(f"no scorable names (0/{len(symbols)} with usable history)")

    nifty = prices.index_history("^NSEI", weeks=60)
    market = v5.market_state(nifty, float(config.strategy("v5_vol_percentile")))

    # 1. sells — club membership lost
    sells = v5.select_sells(status, list(held))
    sold = 0
    for ticker, reason in sells.items():
        price = prices.latest(ticker)
        if price is None:
            logger.warning("v5 sell skipped, no quote: %s", ticker)
            continue
        paper.sell(held[ticker], price, reason=reason)
        sold += 1

    # 2. buys — only when the market gate is open
    slots = int(config.strategy("v5_slots"))
    still_held = [t for t in held if t not in sells]
    bought = 0
    if market["gate_open"]:
        free = slots - len(still_held)
        # over-request: integer share sizing means some candidates won't fit a slot
        picks = v5.select_buys(hist, status, still_held, free * 3,
                               float(config.strategy("v5_corr_cap")))
        size_mult = 0.5 if market["storm"] else 1.0
        # one budget for the whole round — equal weight is the point of the design,
        # so leftover cash stays cash instead of bloating the last few positions
        budget = (paper.cash(STRATEGY) / free) * size_mult if free > 0 else 0.0
        month = today.replace(day=1).isoformat()
        for ticker in picks:
            if bought >= free:
                break
            price = prices.latest(ticker)
            if price is None:
                continue
            qty = int(budget / (price * 1.002))  # leave room for charges
            if qty < 1:  # one share costs more than a slot — skip, try the next name
                continue
            try:
                paper.buy(ticker, price, qty, month, reason="v5_entry", strategy=STRATEGY)
            except ValueError as e:
                logger.warning("v5 buy rejected %s: %s", ticker, e)
                continue
            bought += 1

    members = int(status["member"].sum())
    detail = (f"members {members}/{len(status)}, sold {sold}, bought {bought}, "
              f"gate {'open' if market['gate_open'] else 'closed'}"
              f"{', storm brake' if market['storm'] else ''}")
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO v5_cycles (cycle_date, gate_open, storm, members, sold, bought,"
            " detail) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (today.isoformat(), int(market["gate_open"]), int(market["storm"]),
             members, sold, bought, detail),
        )
    return detail

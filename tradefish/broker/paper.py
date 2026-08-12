"""Paper broker: fake-money ledger with real Indian transaction charges.

Cash is never stored — it is always reconstructed from the transaction ledger,
so the ledger is the single source of truth. weekly_score / monitor_exits /
friday_exit will call buy()/sell() once the price feed lands.
"""

import logging

from tradefish import config, db
from tradefish.backtest import costs

logger = logging.getLogger(__name__)


def capital() -> float:
    return float(config.strategy("paper_capital"))


def cash() -> float:
    with db.connect() as conn:
        delta = conn.execute(
            "SELECT COALESCE(SUM(cash_delta), 0) FROM paper_transactions"
        ).fetchone()[0]
    return capital() + delta


def buy(ticker: str, price: float, qty: int, week_start: str, reason: str = "entry") -> dict:
    value = qty * price
    charge = costs.side_cost(value, "buy")
    if value + charge > cash():
        raise ValueError(f"insufficient cash: need ₹{value + charge:.2f}, have ₹{cash():.2f}")
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO positions (week_start, ticker, weight, qty, entry_price, status)"
            " VALUES (?, ?, ?, ?, ?, 'open')",
            (week_start, ticker, value / capital(), qty, price),
        )
        conn.execute(
            "INSERT INTO paper_transactions (ts, ticker, side, qty, price, gross_value,"
            " txn_cost, cash_delta, reason, position_id) VALUES (?, ?, 'buy', ?, ?, ?, ?, ?, ?, ?)",
            (db.now(), ticker, qty, price, value, charge, -(value + charge), reason, cur.lastrowid),
        )
        position_id = cur.lastrowid
    logger.info("paper buy %s x%d @ %.2f — charges %.2f, cash left %.2f",
                ticker, qty, price, charge, cash())
    return {"position_id": position_id, "value": value, "charge": charge}


def sell(position_id: int, price: float, reason: str = "manual") -> dict:
    with db.connect() as conn:
        pos = conn.execute(
            "SELECT * FROM positions WHERE id = ? AND status = 'open'", (position_id,)
        ).fetchone()
        if pos is None:
            raise ValueError(f"no open position with id {position_id}")
        qty = pos["qty"] or 0
        proceeds = qty * price
        charge = costs.side_cost(proceeds, "sell")
        conn.execute(
            "UPDATE positions SET exit_price = ?, exit_reason = ?, status = 'closed' WHERE id = ?",
            (price, reason, position_id),
        )
        conn.execute(
            "INSERT INTO paper_transactions (ts, ticker, side, qty, price, gross_value,"
            " txn_cost, cash_delta, reason, position_id) VALUES (?, ?, 'sell', ?, ?, ?, ?, ?, ?, ?)",
            (db.now(), pos["ticker"], qty, price, proceeds, charge, proceeds - charge, reason, position_id),
        )
    pnl = (price - pos["entry_price"]) * qty - charge
    logger.info("paper sell %s x%d @ %.2f (%s) — pnl %.2f after sell charges",
                pos["ticker"], qty, price, reason, pnl)
    return {"position_id": position_id, "proceeds": proceeds, "charge": charge}


def snapshot() -> dict:
    with db.connect() as conn:
        holdings = [dict(r) for r in conn.execute(
            "SELECT p.qty, p.entry_price, q.price, q.ts FROM positions p"
            " LEFT JOIN quotes q ON q.ticker = p.ticker"
            " WHERE p.status = 'open' AND p.qty IS NOT NULL"
        )]
        fees = conn.execute(
            "SELECT COALESCE(SUM(txn_cost), 0) FROM paper_transactions"
        ).fetchone()[0]
    invested = sum(h["qty"] * h["entry_price"] for h in holdings)
    # last cached quote per name; falls back to entry price when never quoted
    market = sum(h["qty"] * (h["price"] or h["entry_price"]) for h in holdings)
    quoted = [h["ts"] for h in holdings if h["ts"]]
    cap, c = capital(), cash()
    return {"capital": cap, "cash": c, "invested": invested, "market": market,
            "unrealized": market - invested, "fees": fees, "open_count": len(holdings),
            "net": c + market - cap, "quote_ts": max(quoted) if quoted else None}

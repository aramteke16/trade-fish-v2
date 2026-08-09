"""Sat 10:00 job: book the week's closed trades into weekly_results."""

import logging
from datetime import date, timedelta

from tradefish import db

logger = logging.getLogger(__name__)


def run() -> str:
    monday = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    with db.connect() as conn:
        closed = [dict(r) for r in conn.execute(
            "SELECT * FROM positions WHERE week_start = ? AND status = 'closed'"
            " AND qty IS NOT NULL AND exit_price IS NOT NULL", (monday,)
        )]
        if not closed:
            return "no closed positions this week"
        ids = [c["id"] for c in closed]
        fees = conn.execute(
            f"SELECT COALESCE(SUM(txn_cost), 0) FROM paper_transactions"
            f" WHERE position_id IN ({','.join('?' * len(ids))})", ids
        ).fetchone()[0]

    entry_value = sum(c["entry_price"] * c["qty"] for c in closed)
    gross = sum((c["exit_price"] - c["entry_price"]) * c["qty"] for c in closed)
    wins = sum(1 for c in closed if c["exit_price"] > c["entry_price"])
    gross_ret, net_ret = gross / entry_value, (gross - fees) / entry_value

    with db.connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO weekly_results"
            " (week_start, gross_return, net_return, hit_rate, cost_drag)"
            " VALUES (?, ?, ?, ?, ?)",
            (monday, gross_ret, net_ret, wins / len(closed), fees / entry_value),
        )
    return f"{len(closed)} trades booked, net {net_ret:+.2%}"

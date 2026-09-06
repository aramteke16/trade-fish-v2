"""Algo v5 page: equity curve, holdings with club status, gate state, cycle log."""

import logging
import threading

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from tradefish import db
from tradefish.broker import paper
from tradefish.pipelines import runner, v5_cycle
from tradefish.web.templating import templates

logger = logging.getLogger(__name__)
router = APIRouter()

STRATEGY = "v5"


@router.get("/v5")
def v5_page(request: Request):
    with db.connect() as conn:
        positions = [dict(r) for r in conn.execute(
            "SELECT p.*, q.price AS last_price FROM positions p"
            " LEFT JOIN quotes q ON q.ticker = p.ticker"
            " WHERE p.status = 'open' AND p.strategy = ? ORDER BY p.ticker", (STRATEGY,)
        )]
        cycles = [dict(r) for r in conn.execute(
            "SELECT * FROM v5_cycles ORDER BY id DESC LIMIT 12")]
        # whole history: P&L buckets measure from inception, so truncating the
        # series would make the first bucket a jump instead of a day's move
        curve = [dict(r) for r in conn.execute(
            "SELECT * FROM v5_equity ORDER BY day")]
        txns = [dict(r) for r in conn.execute(
            "SELECT t.*, p.entry_price FROM paper_transactions t"
            " JOIN positions p ON p.id = t.position_id"
            " WHERE p.strategy = ? ORDER BY t.id DESC LIMIT 25", (STRATEGY,)
        )]
        universe_n = conn.execute("SELECT COUNT(*) FROM v5_universe").fetchone()[0]
        job = conn.execute(
            "SELECT * FROM job_runs WHERE job = 'v5_cycle' ORDER BY id DESC LIMIT 1"
        ).fetchone()

    for p in positions:
        price = p["last_price"] or p["entry_price"]
        p["value"] = (p["qty"] or 0) * price
        p["pnl_pct"] = (price / p["entry_price"] - 1) * 100 if p["entry_price"] else 0
    for t in txns:
        t["pnl"] = ((t["price"] - t["entry_price"]) * t["qty"] - t["txn_cost"]
                    if t["side"] == "sell" and t["entry_price"] else None)

    snap = paper.snapshot(STRATEGY)
    return templates.TemplateResponse(request, "v5.html", {
        "paper": snap, "positions": positions, "cycles": cycles, "curve": curve,
        "txns": txns, "universe_n": universe_n, "job": dict(job) if job else None,
        "chart": _chart_data(curve, snap["capital"]),
    })


@router.get("/api/v5/chart")
def chart_api():
    """Chart series as JSON — same shape the page embeds, for polling refreshes."""
    with db.connect() as conn:
        curve = [dict(r) for r in conn.execute(
            "SELECT * FROM v5_equity ORDER BY day")]
    return _chart_data(curve, paper.capital(STRATEGY))


@router.post("/v5/universe/rebuild")
def rebuild_universe():
    logger.info("manual v5 universe rebuild")
    threading.Thread(target=v5_cycle.rebuild_universe, daemon=True).start()
    return RedirectResponse("/v5", status_code=303)


@router.post("/v5/cycle/run")
def run_cycle():
    logger.info("manual v5 cycle run")
    threading.Thread(target=runner.run_job, args=("v5_cycle",), daemon=True).start()
    return RedirectResponse("/v5", status_code=303)


def _chart_data(curve: list[dict], capital: float) -> dict:
    """Equity series (portfolio vs NIFTY, both indexed to 100) and P&L by period.

    Indexing to a common base keeps both lines on ONE axis — a second y-scale
    would let any pair of series be drawn to tell any story.
    """
    rows = [c for c in curve if c.get("total")]
    equity = _indexed_series(rows, capital)
    return {
        "equity": equity,
        "pnl": {"day": _pnl_by(rows, capital, lambda d: d),
                "month": _pnl_by(rows, capital, lambda d: d[:7]),
                "year": _pnl_by(rows, capital, lambda d: d[:4])},
        "summary": _summary(rows, capital),
    }


def _indexed_series(rows: list[dict], capital: float) -> list[dict]:
    base_nifty = next((r["nifty"] for r in rows if r.get("nifty")), None)
    out = []
    for r in rows:
        point = {"day": r["day"], "portfolio": round(r["total"] / capital * 100, 2)}
        if base_nifty and r.get("nifty"):
            point["nifty"] = round(r["nifty"] / base_nifty * 100, 2)
        out.append(point)
    return out


def _pnl_by(rows: list[dict], capital: float, key) -> list[dict]:
    """Change in portfolio value per bucket; the first bucket starts from capital."""
    buckets: dict[str, dict] = {}
    for r in rows:
        buckets.setdefault(key(r["day"]), {})["last"] = r["total"]
        buckets[key(r["day"])].setdefault("first_seen", r["total"])
    out, previous = [], capital
    for label in sorted(buckets):
        end = buckets[label]["last"]
        out.append({"label": label, "pnl": round(end - previous, 2),
                    "pct": round((end / previous - 1) * 100, 2) if previous else 0.0,
                    "value": round(end, 2)})
        previous = end
    return out


def _summary(rows: list[dict], capital: float) -> dict:
    if not rows:
        return {"total": capital, "pnl": 0.0, "pct": 0.0, "drawdown": 0.0, "days": 0}
    values = [r["total"] for r in rows]
    peak, drawdown = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        drawdown = min(drawdown, v / peak - 1)
    last = values[-1]
    return {"total": last, "pnl": last - capital,
            "pct": (last / capital - 1) * 100,
            "drawdown": drawdown * 100, "days": len(values)}

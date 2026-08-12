import json
import logging
import threading
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from tradefish import db, log
from tradefish.broker import paper
from tradefish.pipelines import runner
from tradefish.web.templating import templates

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/")
def dashboard(request: Request):
    # IST like fetched_at, so the ISO string comparison stays consistent
    day_ago = (datetime.now(db.IST) - timedelta(hours=24)).isoformat()
    with db.connect() as conn:
        jobs = {
            name: _row(conn.execute(
                "SELECT * FROM job_runs WHERE job = ? ORDER BY id DESC LIMIT 1", (name,)
            ).fetchone())
            for name in runner.JOBS
        }
        collector = [_row(r) for r in conn.execute(
            "SELECT source, COUNT(*) n FROM announcements WHERE fetched_at >= ? GROUP BY source",
            (day_ago,),
        )]
        corpus_total = conn.execute("SELECT COUNT(*) FROM announcements").fetchone()[0]
        positions = [_row(r) for r in conn.execute(
            "SELECT p.*, q.price AS last_price FROM positions p"
            " LEFT JOIN quotes q ON q.ticker = p.ticker"
            " WHERE p.status = 'open' ORDER BY p.weight DESC"
        )]
        results = [_row(r) for r in conn.execute(
            "SELECT * FROM weekly_results ORDER BY week_start DESC LIMIT 26"
        )]
        llm = _row(conn.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(failed), 0) f, COALESCE(SUM(tokens_used), 0) t"
            " FROM extractions"
        ).fetchone())
        txns = [_pnl(_row(r)) for r in conn.execute(
            "SELECT t.*, p.entry_price FROM paper_transactions t"
            " LEFT JOIN positions p ON p.id = t.position_id ORDER BY t.id DESC LIMIT 20"
        )]
        reads = [dict(r, **json.loads(r["payload"])) for r in conn.execute(
            "SELECT ticker, as_of, failed, payload FROM extractions"
            " WHERE failed = 0 ORDER BY id DESC LIMIT 15"
        )]
    return templates.TemplateResponse(request, "dashboard.html", {
        "jobs": jobs, "collector": collector, "corpus_total": corpus_total,
        "positions": positions, "results": results, "llm": llm,
        "paper": paper.snapshot(), "txns": txns, "reads": reads,
    })


@router.post("/paper/buy")
def paper_buy(ticker: str = Form(...), qty: int = Form(...), price: float = Form(...)):
    monday = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    try:
        paper.buy(ticker.strip().upper(), price, qty, week_start=monday, reason="manual")
    except ValueError as e:
        logger.warning("paper buy rejected: %s", e)
    return RedirectResponse("/", status_code=303)


@router.post("/paper/sell/{position_id}")
def paper_sell(position_id: int, price: float = Form(...)):
    try:
        paper.sell(position_id, price, reason="manual")
    except ValueError as e:
        logger.warning("paper sell rejected: %s", e)
    return RedirectResponse("/", status_code=303)


@router.get("/api/activity")
def activity(request: Request):
    """Live status + recent logs, polled by the UI."""
    two_hours_ago = (datetime.now(db.IST) - timedelta(hours=2)).isoformat()
    with db.connect() as conn:
        running = [r["job"] for r in conn.execute(
            "SELECT job FROM job_runs WHERE status = 'running' AND started_at >= ?",
            (two_hours_ago,),
        )]
    if running:
        status = {"state": "running", "text": f"running: {', '.join(running)}"}
    else:
        status = {"state": "idle", "text": f"idle — next: {_next_job(request)}"}
    return {"status": status, "logs": log.recent()}


def _next_job(request: Request) -> str:
    sched = getattr(request.app.state, "scheduler", None)
    if not sched:
        return "scheduler off"
    runs = [(j.next_run_time, j.id) for j in sched.get_jobs() if j.next_run_time]
    if not runs:
        return "nothing scheduled"
    when, name = min(runs)
    return f"{name} {when.strftime('%a %H:%M')} IST"


@router.post("/jobs/{name}/run")
def run_now(name: str):
    if name in runner.JOBS:
        logger.info("manual run: %s", name)
        threading.Thread(target=runner.run_job, args=(name,), daemon=True).start()
    return RedirectResponse("/", status_code=303)


def _row(row) -> dict | None:
    return dict(row) if row is not None else None


def _pnl(txn: dict) -> dict:
    """Realized P&L on a sell — cash always rises on a sell, so colour by this instead."""
    if txn["side"] == "sell" and txn.get("entry_price"):
        txn["pnl"] = (txn["price"] - txn["entry_price"]) * txn["qty"] - txn["txn_cost"]
    else:
        txn["pnl"] = None
    return txn

"""Runs a pipeline job and records the outcome in job_runs."""

import logging

from tradefish import db, log
from tradefish.pipelines import (daily_collect, daily_extract, friday_exit,
                                 monitor_exits, weekend_report, weekly_score)

logger = logging.getLogger(__name__)

JOBS = {
    "daily_collect": daily_collect.run,
    "daily_extract": daily_extract.run,
    "weekly_score": weekly_score.run,
    "monitor_exits": monitor_exits.run,
    "friday_exit": friday_exit.run,
    "weekend_report": weekend_report.run,
}


def run_job(name: str) -> None:
    log.setup()  # jobs can also run outside the web app
    if db.get_setting(f"scheduler.{name}.enabled") == "0":
        logger.info("%s skipped (disabled)", name)
        return
    run_id = db.start_job_run(name)
    logger.info("%s started (run %d)", name, run_id)
    try:
        detail = JOBS[name]()
        db.finish_job_run(run_id, "ok", detail=detail)
        logger.info("%s ok: %s", name, detail)
    except Exception as e:
        db.finish_job_run(run_id, "error", error=repr(e))
        logger.exception("%s failed", name)

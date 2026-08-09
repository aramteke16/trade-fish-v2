"""APScheduler wiring: one cron entry per pipeline job, pinned to IST."""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from tradefish import config
from tradefish.pipelines import runner

logger = logging.getLogger(__name__)


def start() -> BackgroundScheduler:
    cfg = config.scheduler_config()
    sched = BackgroundScheduler(timezone=cfg["timezone"])
    for job, cron in cfg["jobs"].items():
        sched.add_job(runner.run_job, CronTrigger.from_crontab(cron, timezone=cfg["timezone"]),
                      args=[job], id=job, name=job)
        logger.info("scheduled %s: %s", job, cron)
    sched.start()
    logger.info("scheduler started (%s)", cfg["timezone"])
    return sched

"""Weekly ticker for the portfolio manager.

No broker. This process sends the top 3. Lots stay as they are.

The India rules file says a decision may see prices only through the last
close. The job sends the buy message on Monday at 09:15 IST, when the cash
market opens. Prices come from the Upstox token.
"""

import time
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from assistant.db import get_settings
from assistant.decide import run_week
from assistant.log import get_logger

log = get_logger()
IST = ZoneInfo("Asia/Kolkata")


def _clock() -> tuple:
    settings = get_settings()
    return (
        int(settings["decision_weekday"]),
        int(settings["decision_hour"]),
        int(settings["decision_minute"]),
    )


def next_run(now: Optional[datetime] = None) -> datetime:
    """Next configured slot. Defaults to Monday 09:15 IST. A passed slot is next week."""
    now = now or datetime.now(IST)
    weekday, hour, minute = _clock()
    days = (weekday - now.weekday()) % 7
    slot = (now + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if slot <= now:
        slot += timedelta(days=7)
    return slot


def serve() -> None:
    log.info("weekly ticker started. top 3 buy message. no broker")
    announced = ""
    while True:
        when = next_run()
        label = when.strftime("%Y-%m-%d %H:%M")
        if label != announced:
            log.info("next decision %s IST", label)
            announced = label
        wait = (when - datetime.now(IST)).total_seconds()
        if wait <= 1:
            try:
                run_week(source="schedule")
            except RuntimeError as exc:
                log.info("%s", exc)
            except Exception:
                log.exception("week failed, will try again next week")
            time.sleep(60)
            continue
        # Short sleeps so a new run time from the config page is noticed.
        time.sleep(min(30.0, max(1.0, wait)))

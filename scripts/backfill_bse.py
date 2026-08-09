"""Backfill BSE announcements day by day (plan §3.1 historical backfill).

Usage: python scripts/backfill_bse.py 2024-01-01 2024-06-30
"""

import logging
import sys
import time
from datetime import date, timedelta

from tradefish import db, log
from tradefish.collectors import announcements

logger = logging.getLogger("tradefish.backfill_bse")

log.setup()
db.init_db()
start, end = date.fromisoformat(sys.argv[1]), date.fromisoformat(sys.argv[2])

day = start
while day <= end:
    try:
        result = announcements.collect(day, sources=("bse",))
        logger.info("%s %s", day, result)
    except RuntimeError as e:
        logger.error("%s failed: %s", day, e)
    day += timedelta(days=1)
    time.sleep(1)  # rate-limit courtesy

"""The book clock. ASSISTANT_TODAY=YYYY-MM-DD freezes it for a test run."""

import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def today() -> date:
    raw = os.environ.get("ASSISTANT_TODAY", "").strip()
    if not raw:
        return datetime.now(IST).date()
    return date.fromisoformat(raw[:10])

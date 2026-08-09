"""Central logging to stdout — `docker logs -f` streams it. Timestamps in IST.

A ring buffer keeps recent records in memory for the dashboard live feed.
"""

import logging
import sys
from collections import deque
from datetime import datetime

from tradefish import config
from tradefish.db import IST

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
BUFFER = deque(maxlen=300)


class BufferHandler(logging.Handler):
    def emit(self, record):
        msg = record.getMessage()
        if record.exc_info and record.exc_info[1]:
            msg += f" — {record.exc_info[1]!r}"
        BUFFER.append({
            "ts": datetime.now(IST).strftime("%H:%M:%S"),
            "level": record.levelname,
            "name": record.name.removeprefix("tradefish."),
            "msg": msg,
        })


def recent() -> list[dict]:
    return list(BUFFER)


def setup() -> None:
    root = logging.getLogger("tradefish")
    if root.handlers:  # already configured
        return
    root.setLevel(config.get("LOG_LEVEL", "INFO").upper())
    root.propagate = False  # keep uvicorn from double-printing our records
    stream = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(FORMAT)
    formatter.converter = lambda *args: datetime.now(IST).timetuple()  # IST even on UTC servers
    stream.setFormatter(formatter)
    root.addHandler(stream)
    root.addHandler(BufferHandler())

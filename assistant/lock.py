"""One run at a time, across the scheduler process and the web process."""

import fcntl
from contextlib import contextmanager

from assistant.config import DATA


@contextmanager
def run_lock():
    DATA.mkdir(parents=True, exist_ok=True)
    handle = open(DATA / "run.lock", "a")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise RuntimeError("A run is already in progress")
    try:
        yield
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()

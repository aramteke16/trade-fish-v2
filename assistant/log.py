"""One logger. Info goes to the terminal. Debug also goes to the log file."""

import logging
from pathlib import Path

from assistant.config import LOG_PATH


def get_logger() -> logging.Logger:
    logger = logging.getLogger("assistant")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(LOG_PATH)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)
    stream = logging.StreamHandler()
    stream.setLevel(logging.INFO)
    stream.setFormatter(fmt)
    logger.addHandler(file_handler)
    logger.addHandler(stream)
    return logger

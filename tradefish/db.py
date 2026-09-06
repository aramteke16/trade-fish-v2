"""SQLite storage: settings, job runs, announcements, positions, results."""

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

IST = ZoneInfo("Asia/Kolkata")

ROOT = Path(os.environ.get("APP_ROOT", Path(__file__).resolve().parent.parent))

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    is_secret INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,             -- running | ok | error
    detail TEXT,
    error TEXT
);

CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT,
    source TEXT NOT NULL,             -- nse | bse
    exchange_disclosure_time TEXT,    -- source of truth for point-in-time filter
    fetched_at TEXT NOT NULL,
    published_at TEXT,
    doc_type TEXT,
    headline TEXT,
    raw_text TEXT,
    pdf_path TEXT,
    content_hash TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL,
    ticker TEXT NOT NULL,
    weight REAL NOT NULL,
    qty REAL,
    entry_price REAL,
    exit_price REAL,
    exit_reason TEXT,                 -- take_profit | stop_loss | time | circuit_breaker
    status TEXT NOT NULL DEFAULT 'open'
);

CREATE TABLE IF NOT EXISTS quotes (
    ticker TEXT PRIMARY KEY,
    price REAL NOT NULL,
    ts TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,               -- buy | sell
    qty REAL NOT NULL,
    price REAL NOT NULL,
    gross_value REAL NOT NULL,
    txn_cost REAL NOT NULL,
    cash_delta REAL NOT NULL,         -- negative on buy
    reason TEXT,                      -- entry | take_profit | stop_loss | time | manual
    position_id INTEGER
);

CREATE TABLE IF NOT EXISTS weekly_results (
    week_start TEXT PRIMARY KEY,
    gross_return REAL,
    net_return REAL,
    hit_rate REAL,
    skew REAL,
    ic REAL,
    cost_drag REAL
);

CREATE TABLE IF NOT EXISTS extractions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    as_of TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    tokens_used INTEGER,
    latency_ms INTEGER,
    failed INTEGER NOT NULL DEFAULT 0,
    payload TEXT                      -- extracted JSON
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    key TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT
);

CREATE TABLE IF NOT EXISTS v5_equity (
    day TEXT PRIMARY KEY,
    cash REAL NOT NULL,
    market REAL NOT NULL,             -- holdings marked to last quote
    total REAL NOT NULL,
    open_count INTEGER NOT NULL,
    nifty REAL
);

CREATE TABLE IF NOT EXISTS v5_universe (
    symbol TEXT PRIMARY KEY,
    built_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS v5_cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_date TEXT NOT NULL,
    gate_open INTEGER NOT NULL,
    storm INTEGER NOT NULL,
    members INTEGER NOT NULL,         -- club size that month
    sold INTEGER NOT NULL,
    bought INTEGER NOT NULL,
    detail TEXT
);
"""


def db_path() -> Path:
    return ROOT / os.environ.get("APP_DB", "data/app.db")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    db_path().parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)
        for column, ddl in (("qty", "ALTER TABLE positions ADD COLUMN qty REAL"),
                            ("strategy", "ALTER TABLE positions ADD COLUMN strategy TEXT"
                                         " NOT NULL DEFAULT 'weekly'")):
            try:  # older DBs predate these columns
                conn.execute(ddl)
            except sqlite3.OperationalError:
                pass
    logger.info("db ready: %s", db_path())


def now() -> str:
    return datetime.now(IST).isoformat()


# --- settings ---

def get_setting(key: str) -> str | None:
    try:
        with connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:  # DB not initialized yet (e.g. at import time)
        return None
    return row["value"] if row else None


def set_setting(key: str, value: str, is_secret: bool = False) -> None:
    with connect() as conn:
        old = conn.execute("SELECT value, is_secret FROM settings WHERE key = ?", (key,)).fetchone()
        conn.execute(
            "INSERT INTO settings (key, value, is_secret, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "is_secret = excluded.is_secret, updated_at = excluded.updated_at",
            (key, value, int(is_secret), now()),
        )
        # secrets never go to the audit log
        if not (is_secret or (old and old["is_secret"])):
            conn.execute(
                "INSERT INTO audit_log (ts, key, old_value, new_value) VALUES (?, ?, ?, ?)",
                (now(), key, old["value"] if old else None, value),
            )
    logger.info("setting %s updated", key)  # key only — values may be secret


# --- job runs ---

def start_job_run(job: str) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO job_runs (job, started_at, status) VALUES (?, ?, 'running')",
            (job, now()),
        )
        return cur.lastrowid


def finish_job_run(run_id: int, status: str, detail: str | None = None, error: str | None = None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE job_runs SET finished_at = ?, status = ?, detail = ?, error = ? WHERE id = ?",
            (now(), status, detail, error, run_id),
        )

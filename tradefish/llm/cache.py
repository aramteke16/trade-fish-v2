"""Disk cache for extractions, keyed on hash(prompt_version + model + text)."""

import sqlite3
from pathlib import Path

from tradefish.db import ROOT, now

CACHE_DB = ROOT / "data" / "cache" / "llm_cache.db"


def _connect() -> sqlite3.Connection:
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(CACHE_DB)
    conn.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, payload TEXT, created_at TEXT)")
    return conn


def get(key: str) -> str | None:
    with _connect() as conn:
        row = conn.execute("SELECT payload FROM cache WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def put(key: str, payload: str) -> None:
    with _connect() as conn:
        conn.execute("INSERT OR REPLACE INTO cache (key, payload, created_at) VALUES (?, ?, ?)",
                     (key, payload, now()))

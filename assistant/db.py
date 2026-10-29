"""SQLite store for the current lots and every weekly decision.

One file, data/assistant/portfolio.db. The price CSVs stay files.
The first open copies holdings.json and decisions.jsonl when the tables are empty.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from assistant.config import (
    DB_PATH,
    DECISION_HOUR,
    DECISION_MINUTE,
    DECISION_WEEKDAY,
    DECISIONS_PATH,
    HOLDINGS_PATH,
    MIN_HOLD_DAYS,
    MONTHLY_CASH,
    WEEKLY_CASH,
)
from assistant.log import get_logger

log = get_logger()
IST = ZoneInfo("Asia/Kolkata")


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # The scheduler and the page share this file.
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS account (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            cash REAL NOT NULL,
            last_add_month TEXT,
            as_of TEXT,
            sale_proceeds REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS lots (
            id INTEGER PRIMARY KEY,
            symbol TEXT,
            isin TEXT,
            name TEXT,
            shares INTEGER NOT NULL,
            purchased TEXT,
            avg_price REAL,
            from_book INTEGER NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'manual'
        );
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY,
            day TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'done',
            body TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fills (
            id INTEGER PRIMARY KEY,
            decision_id INTEGER,
            side TEXT NOT NULL,
            symbol TEXT,
            name TEXT,
            lot_id INTEGER,
            suggested_shares INTEGER,
            filled_shares INTEGER,
            suggested_price REAL,
            fill_price REAL,
            fill_rupees REAL,
            fill_date TEXT,
            confirmed_at TEXT NOT NULL,
            note TEXT
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bot_forms (
            chat_id TEXT PRIMARY KEY,
            state TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    defaults = {
        "decision_weekday": str(DECISION_WEEKDAY),
        "decision_hour": str(DECISION_HOUR),
        "decision_minute": str(DECISION_MINUTE),
        "monthly_cash": str(int(MONTHLY_CASH)),
        "weekly_cash": str(int(WEEKLY_CASH)),
        "min_hold_days": str(MIN_HOLD_DAYS),
        "last_schedule_slot": "",
        "run_state": "idle",
        "run_error": "",
        "notify_on": "1",
        "telegram_chat_id": "",
        "telegram_offset": "0",
    }
    for key, value in defaults.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    _migrate(conn)
    row = conn.execute("SELECT id FROM account WHERE id = 1").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO account (id, cash, last_add_month, as_of, sale_proceeds) VALUES (1, 0, NULL, NULL, 0)"
        )
    _copy_json_once(conn)
    conn.commit()
    return conn


@contextmanager
def session():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _copy_json_once(conn: sqlite3.Connection) -> None:
    """Bring the old files across once. Later edits go to the database only."""
    lot_count = conn.execute("SELECT COUNT(*) AS n FROM lots").fetchone()["n"]
    if lot_count == 0 and HOLDINGS_PATH.exists():
        book = json.loads(HOLDINGS_PATH.read_text())
        conn.execute(
            "UPDATE account SET cash = ?, last_add_month = ?, as_of = ? WHERE id = 1",
            (book.get("cash") or 0, book.get("last_add_month"), book.get("as_of")),
        )
        for lot in book["lots"]:
            _insert_lot(conn, lot)
        log.info("copied %d lots from %s", len(book["lots"]), HOLDINGS_PATH.name)
    decision_count = conn.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"]
    if decision_count == 0 and DECISIONS_PATH.exists():
        copied = 0
        for line in DECISIONS_PATH.read_text().splitlines():
            if not line.strip():
                continue
            body = json.loads(line)
            conn.execute(
                "INSERT INTO decisions (day, recorded_at, body) VALUES (?, ?, ?)",
                (body["day"], body["day"] + "T16:00:00+05:30", line),
            )
            copied += 1
        log.info("copied %d decisions from %s", copied, DECISIONS_PATH.name)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns the first version of the file did not have. Existing rows stay."""
    account_cols = _column_names(conn, "account")
    if "sale_proceeds" not in account_cols:
        conn.execute("ALTER TABLE account ADD COLUMN sale_proceeds REAL NOT NULL DEFAULT 0")
        log.info("added account.sale_proceeds")
    lot_cols = _column_names(conn, "lots")
    if "source" not in lot_cols:
        conn.execute("ALTER TABLE lots ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
        log.info("added lots.source")
    decision_cols = _column_names(conn, "decisions")
    if "status" not in decision_cols:
        conn.execute("ALTER TABLE decisions ADD COLUMN status TEXT NOT NULL DEFAULT 'done'")
        log.info("added decisions.status")


def _column_names(conn: sqlite3.Connection, table: str) -> set:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def load_book() -> dict:
    with session() as conn:
        account = conn.execute(
            "SELECT cash, last_add_month, as_of, sale_proceeds FROM account WHERE id = 1"
        ).fetchone()
        rows = conn.execute("SELECT * FROM lots ORDER BY id").fetchall()
    return {
        "cash": account["cash"],
        "sale_proceeds": account["sale_proceeds"] or 0,
        "last_add_month": account["last_add_month"],
        "as_of": account["as_of"],
        "lots": [_lot(row) for row in rows],
    }


def save_book(book: dict) -> None:
    with session() as conn:
        conn.execute(
            "UPDATE account SET cash = ?, last_add_month = ?, as_of = ?, sale_proceeds = ? WHERE id = 1",
            (book["cash"], book.get("last_add_month"), book.get("as_of"), book.get("sale_proceeds") or 0),
        )
        kept = []
        for lot in book["lots"]:
            if lot.get("id"):
                conn.execute(
                    """
                    UPDATE lots
                    SET symbol = ?, isin = ?, name = ?, shares = ?, purchased = ?, avg_price = ?, from_book = ?, source = ?
                    WHERE id = ?
                    """,
                    _values(lot) + (lot["id"],),
                )
                kept.append(lot["id"])
            else:
                kept.append(_insert_lot(conn, lot))
                lot["id"] = kept[-1]
        if kept:
            marks = ",".join("?" for _ in kept)
            conn.execute(f"DELETE FROM lots WHERE id NOT IN ({marks})", kept)
        else:
            conn.execute("DELETE FROM lots")
    log.info("saved portfolio.db (%d lots, cash %.0f)", len(book["lots"]), book["cash"])


def record_decision(decision: dict) -> int:
    status = decision.get("status") or "preview"
    decision["status"] = status
    body = {key: value for key, value in decision.items() if key != "id"}
    stamp = datetime.now(IST).isoformat(timespec="seconds")
    with session() as conn:
        cursor = conn.execute(
            "INSERT INTO decisions (day, recorded_at, status, body) VALUES (?, ?, ?, ?)",
            (decision["day"], stamp, status, json.dumps(body)),
        )
        decision_id = int(cursor.lastrowid)
    decision["id"] = decision_id
    log.info("stored decision %s status %s", decision["day"], status)
    return decision_id


def list_decisions() -> list[dict]:
    with session() as conn:
        rows = conn.execute(
            "SELECT id, day, recorded_at, status, body FROM decisions ORDER BY id"
        ).fetchall()
    out = []
    for row in rows:
        body = json.loads(row["body"])
        body["id"] = row["id"]
        body["recorded_at"] = row["recorded_at"]
        body["status"] = row["status"] or body.get("status") or "done"
        out.append(body)
    return out


def get_decision(decision_id: int):
    for row in list_decisions():
        if row["id"] == decision_id:
            return row
    return None


def write_status(decision_id: int, status: str, **fields) -> None:
    with session() as conn:
        row = conn.execute("SELECT body FROM decisions WHERE id = ?", (decision_id,)).fetchone()
        if row is None:
            raise KeyError(decision_id)
        body = json.loads(row["body"])
        body.update(fields)
        body["status"] = status
        conn.execute(
            "UPDATE decisions SET status = ?, body = ? WHERE id = ?",
            (status, json.dumps(body), decision_id),
        )
    log.info("decision %s status %s", decision_id, status)


def insert_fill(row: dict) -> None:
    stamp = datetime.now(IST).isoformat(timespec="seconds")
    with session() as conn:
        conn.execute(
            """
            INSERT INTO fills (
                decision_id, side, symbol, name, lot_id, suggested_shares, filled_shares,
                suggested_price, fill_price, fill_rupees, fill_date, confirmed_at, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("decision_id"),
                row["side"],
                row.get("symbol"),
                row.get("name"),
                row.get("lot_id"),
                row.get("suggested_shares"),
                row.get("filled_shares"),
                row.get("suggested_price"),
                row.get("fill_price"),
                row.get("fill_rupees"),
                row.get("fill_date"),
                stamp,
                row.get("note") or "",
            ),
        )


def list_fills(limit: int = 200) -> list[dict]:
    with session() as conn:
        rows = conn.execute(
            "SELECT * FROM fills ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def get_settings() -> dict:
    with session() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


def set_settings(updates: dict) -> None:
    with session() as conn:
        for key, value in updates.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )


def load_form(chat_id: str):
    """Unfinished Telegram fill for this chat. None when the chat has no form open."""
    with session() as conn:
        row = conn.execute("SELECT state FROM bot_forms WHERE chat_id = ?", (str(chat_id),)).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row["state"])
    except json.JSONDecodeError:
        log.warning("dropped a broken telegram form")
        return None


def save_form(chat_id: str, state: dict) -> None:
    stamp = datetime.now(IST).isoformat(timespec="seconds")
    with session() as conn:
        conn.execute(
            """
            INSERT INTO bot_forms (chat_id, state, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET state = excluded.state, updated_at = excluded.updated_at
            """,
            (str(chat_id), json.dumps(state), stamp),
        )


def clear_form(chat_id: str) -> None:
    with session() as conn:
        conn.execute("DELETE FROM bot_forms WHERE chat_id = ?", (str(chat_id),))


def _insert_lot(conn: sqlite3.Connection, lot: dict) -> int:
    cursor = conn.execute(
        """
        INSERT INTO lots (symbol, isin, name, shares, purchased, avg_price, from_book, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        _values(lot),
    )
    return int(cursor.lastrowid)


def _source(lot: dict) -> str:
    source = lot.get("source")
    if source in ("manual", "algo"):
        return source
    return "algo" if lot.get("from_book") else "manual"


def _values(lot: dict) -> tuple:
    return (
        lot.get("symbol"),
        lot.get("isin"),
        lot.get("name"),
        int(lot["shares"]),
        lot.get("purchased"),
        lot.get("avg_price"),
        1 if lot.get("from_book") else 0,
        _source(lot),
    )


def _lot(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "symbol": row["symbol"],
        "isin": row["isin"],
        "name": row["name"],
        "shares": row["shares"],
        "purchased": row["purchased"],
        "avg_price": row["avg_price"],
        "from_book": bool(row["from_book"]),
        "source": row["source"] if "source" in row.keys() else "manual",
    }

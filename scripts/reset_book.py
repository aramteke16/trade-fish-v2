"""Clear a paper-trading book (positions, transactions, results) from the database.

Backs the database up first, prints exactly what it will delete, and refuses to
delete anything unless --yes is passed. The announcement corpus, LLM extractions
and settings are never touched.

    python scripts/reset_book.py weekly            # dry run: show what would go
    python scripts/reset_book.py weekly --yes      # actually clear the old algo
    python scripts/reset_book.py v5 --yes          # clear the v5 book
    python scripts/reset_book.py all --yes         # clear both
"""

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tradefish import db  # noqa: E402

BOOKS = ("weekly", "v5", "all")


def counts(conn, strategy: str) -> dict[str, int]:
    where, args = "", ()
    if strategy != "all":
        where, args = " WHERE COALESCE(strategy, 'weekly') = ?", (strategy,)
    n_pos = conn.execute(f"SELECT COUNT(*) FROM positions{where}", args).fetchone()[0]
    n_txn = conn.execute(
        "SELECT COUNT(*) FROM paper_transactions t LEFT JOIN positions p"
        " ON p.id = t.position_id" +
        (" WHERE COALESCE(p.strategy, 'weekly') = ?" if strategy != "all" else ""),
        args).fetchone()[0]
    out = {"positions": n_pos, "transactions": n_txn}
    if strategy in ("weekly", "all"):
        out["weekly_results"] = conn.execute(
            "SELECT COUNT(*) FROM weekly_results").fetchone()[0]
    if strategy in ("v5", "all"):
        for table in ("v5_equity", "v5_cycles", "v5_universe"):
            out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    return out


def clear(conn, strategy: str) -> None:
    if strategy == "all":
        conn.execute("DELETE FROM paper_transactions")
        conn.execute("DELETE FROM positions")
    else:
        conn.execute(
            "DELETE FROM paper_transactions WHERE position_id IN"
            " (SELECT id FROM positions WHERE COALESCE(strategy, 'weekly') = ?)",
            (strategy,))
        conn.execute("DELETE FROM positions WHERE COALESCE(strategy, 'weekly') = ?",
                     (strategy,))
    if strategy in ("weekly", "all"):
        conn.execute("DELETE FROM weekly_results")
    if strategy in ("v5", "all"):
        for table in ("v5_equity", "v5_cycles", "v5_universe"):
            conn.execute(f"DELETE FROM {table}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("book", choices=BOOKS, help="which book to clear")
    parser.add_argument("--yes", action="store_true", help="actually delete")
    args = parser.parse_args()

    db.init_db()  # make sure the schema (strategy column, v5 tables) exists
    path = db.db_path()
    with db.connect() as conn:
        before = counts(conn, args.book)

    print(f"database: {path}")
    print(f"book:     {args.book}")
    for name, n in before.items():
        print(f"  {name:<16} {n}")
    if not sum(before.values()):
        print("\nnothing to clear.")
        return 0

    if not args.yes:
        print("\ndry run — nothing deleted. Re-run with --yes to delete the rows above.")
        return 0

    backup = path.with_name(
        f"{path.stem}.before-reset-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}")
    shutil.copy2(path, backup)
    print(f"\nbackup written: {backup}")

    with db.connect() as conn:
        clear(conn, args.book)
        after = counts(conn, args.book)
    print("cleared. remaining:")
    for name, n in after.items():
        print(f"  {name:<16} {n}")
    print("\nannouncements, extractions and settings were not touched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""python3 -m assistant now
python3 -m assistant week
python3 -m assistant schedule
python3 -m assistant ui
python3 -m assistant bot

now runs the top 3 at this moment and sends Telegram.
week and the Friday job do the same. None of them move lots.
"""

import sys

from assistant.bot import serve as serve_bot
from assistant.config import STATEMENT
from assistant.db import list_decisions
from assistant.decide import run_week
from assistant.holdings import import_statement
from assistant.log import get_logger
from assistant.schedule import next_run, serve
from assistant.web import serve_web

log = get_logger()


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "week"
    if command == "import":
        import_statement(sys.argv[2] if len(sys.argv) > 2 else STATEMENT)
        return
    if command == "now":
        run_week(source="now")
        return
    if command == "week":
        run_week()
        return
    if command == "schedule":
        serve()
        return
    if command == "ui":
        serve_web()
        return
    if command == "bot":
        serve_bot()
        return
    if command == "next":
        print(next_run().strftime("%Y-%m-%d %H:%M IST"))
        return
    if command == "decisions":
        rows = list_decisions()
        if not rows:
            log.info("no decisions stored")
            return
        for row in rows:
            buys = ", ".join(item["symbol"] for item in row["buys"]) or "none"
            sells = ", ".join(item["symbol"] for item in row["sells"]) or "none"
            top = ", ".join(item["symbol"] for item in row["top"])
            log.info("%s  top %s  buy %s  sell %s", row["day"], top, buys, sells)
        return
    raise SystemExit("use import, now, week, schedule, next, decisions, ui, or bot")


if __name__ == "__main__":
    main()

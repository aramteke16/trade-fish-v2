"""Telegram /now.

Send /now in the saved chat. That runs the same weekly buy as the page
and as `python3 -m assistant now`. The reply is the buy message. This
process does not record an order. The token stays in .env and is never logged.
"""

import time

from assistant.db import get_settings, set_settings
from assistant.decide import run_week
from assistant.log import get_logger
from assistant.notify import _post, call
from assistant.token import read_telegram

log = get_logger()


def serve() -> None:
    """Listen for /now. One poller. Does not record an order."""
    log.info("telegram /now listener started")
    while True:
        if not read_telegram():
            log.info("telegram /now listener: no bot token yet")
            time.sleep(30)
            continue
        try:
            updates = _fetch()
        except Exception:
            log.exception("telegram poll failed")
            time.sleep(5)
            continue
        for update in updates:
            set_settings({"telegram_offset": str(int(update["update_id"]) + 1)})
            try:
                handle_update(update)
            except Exception:
                log.exception("telegram update failed")


def handle_update(update: dict, send=None, answer=None) -> None:
    """Run the week on /now from the saved chat. Any other tap gets a short reply."""
    send = send or _deliver
    answer = answer or _answer
    if "callback_query" in update:
        query = update["callback_query"]
        answer(str(query.get("id") or ""), "Send /now. This chat does not record an order.")
        return
    message = update.get("message") or {}
    chat = (message.get("chat") or {}).get("id")
    if chat is None:
        return
    command = _command(message.get("text") or "")
    if command not in ("now", "run", "start"):
        return
    if not _allowed(chat):
        log.info("ignored /%s from a chat that is not the saved one", command)
        return
    if command == "start":
        send(str(chat), "Send /now to run this week's top 3. The message is the recommendation. It does not place an order.", None)
        return
    _run_now(str(chat), send)


def _run_now(chat: str, send) -> None:
    try:
        run_week(source="now")
    except RuntimeError as exc:
        if "already in progress" in str(exc):
            send(chat, "A run is already in progress.", None)
            return
        log.exception("run now failed")
        send(chat, "The run failed.", None)
    except Exception:
        log.exception("run now failed")
        send(chat, "The run failed.", None)


def _allowed(chat) -> bool:
    saved = (get_settings().get("telegram_chat_id") or "").strip()
    return bool(saved) and str(chat) == saved


def _command(text: str) -> str:
    text = text.strip()
    if not text.startswith("/"):
        return ""
    return text.split()[0][1:].split("@", 1)[0].lower()


def _fetch() -> list:
    offset = int(get_settings().get("telegram_offset") or 0)
    body = call(
        "getUpdates",
        {
            "offset": offset,
            "timeout": 25,
            "limit": 100,
            "allowed_updates": ["message", "callback_query"],
        },
        timeout=40,
    )
    return body.get("result") or []


def _deliver(chat: str, text: str, markup=None) -> None:
    token = read_telegram()
    if not token:
        log.info("telegram reply skipped: no bot token")
        return
    _post(token, str(chat), text, markup)


def _answer(callback_id: str, text: str = "") -> None:
    if not callback_id or not read_telegram():
        return
    try:
        call(
            "answerCallbackQuery",
            {"callback_query_id": callback_id, "text": (text or "")[:180]},
        )
    except Exception:
        log.exception("telegram answer failed")

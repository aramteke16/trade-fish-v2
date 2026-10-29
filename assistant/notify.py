"""One Telegram message for the weekly buy.

Amount is the share count. The price range is the last session low and high.
The message has no buttons. The bot token stays in .env and is never logged.
The request URL contains the token, so it is not logged.
"""

import json
import urllib.error
import urllib.request

from assistant.db import get_settings
from assistant.log import get_logger
from assistant.token import read_telegram

log = get_logger()


def send_week(decision: dict) -> None:
    settings = get_settings()
    if settings.get("notify_on") != "1":
        log.info("telegram off")
        return
    token = read_telegram()
    chat = (settings.get("telegram_chat_id") or "").strip()
    if not token or not chat:
        log.info("telegram skipped: set the bot token and the chat id")
        return
    _post(token, chat, render_week(decision))
    log.info("telegram sent for %s", decision.get("day"))


def send_test() -> None:
    settings = get_settings()
    token = read_telegram()
    chat = (settings.get("telegram_chat_id") or "").strip()
    if not token or not chat:
        raise RuntimeError("set the bot token and the chat id first")
    _post(token, chat, "Assistant test. No order in this message.")
    log.info("telegram test sent")


def render_week(decision: dict) -> str:
    """Top 3 buys. Amount is shares. Price range is the last session low to high."""
    lines = [
        f"Close {decision.get('day')}. Act at the next NSE cash open, 09:15 IST.",
        _invest_line(decision),
        "",
        "BUY",
    ]
    buys = decision.get("buys") or []
    if not buys:
        lines.append("No share fits this budget.")
        return "\n".join(lines)
    for buy in buys:
        lines.append(_label(buy))
        lines.append(f"Amount: {int(buy['shares'])} shares")
        lines.append(f"Price range: {_range(buy, 'price')}")
        lines.append("")
    return "\n".join(lines).rstrip()


def fill_keyboard(decision: dict):
    """Inline button for an open scheduled sheet. None when there is nothing to fill."""
    if decision.get("status") != "open" or decision.get("source") == "manual":
        return None
    if not decision.get("id"):
        return None
    if not (decision.get("buys") or decision.get("sells")):
        return None
    return {
        "inline_keyboard": [[
            {"text": "Fill this sheet", "callback_data": "fill:%d" % int(decision["id"])}
        ]]
    }


def practice_keyboard() -> dict:
    """Test button. Done on this form does not call the book."""
    return {"inline_keyboard": [[{"text": "Fill this sheet", "callback_data": "demo"}]]}


def practice_text() -> str:
    return "\n".join([
        "Test. This is not an order.",
        "",
        "BUY",
        "Morepen Labs (MOREPENLAB)",
        "Amount: 2 shares",
        "Price range: 125.16–135.29",
        "",
        "Press Fill this sheet. Enter the amount and the rupees. Done on this test does not change the book.",
    ])


def _invest_line(decision: dict) -> str:
    invest = int(decision.get("invest_rupees") or 0)
    return f"Budget ₹{invest:,} this week."


def _orders(rows: list, close_key: str) -> list:
    if not rows:
        return ["none", ""]
    lines = []
    for row in rows:
        lines.append(_label(row))
        lines.append(f"Amount: {int(row['shares'])} shares")
        lines.append(f"Price range: {_range(row, close_key)}")
        lines.append("")
    return lines


def _label(item: dict) -> str:
    symbol = item.get("symbol") or ""
    name = item.get("name") or ""
    if name and name.upper() != symbol.upper():
        return f"{name} ({symbol})"
    return symbol or name or "—"


def _range(item: dict, close_key: str) -> str:
    low = item.get("low")
    high = item.get("high")
    close = item.get(close_key)
    if low is None or high is None:
        if close is None:
            return "unavailable"
        return f"unavailable (close {float(close):.2f})"
    return f"{float(low):.2f}–{float(high):.2f}"


def call(method: str, payload: dict, timeout: int = 20) -> dict:
    """One Bot API call. The URL holds the token and is not logged."""
    return _request(method, payload, read_telegram(), timeout)


def _post(token: str, chat: str, text: str, reply_markup: dict = None) -> dict:
    if not token:
        raise RuntimeError("telegram token is not set")
    payload = {"chat_id": chat, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _request("sendMessage", payload, token, 20)


def _request(method: str, payload: dict, token: str, timeout: int) -> dict:
    # The URL contains the bot token. Do not log it or put it on an exception.
    if not token:
        raise RuntimeError("telegram token is not set")
    url = "https://api.telegram.org/bot" + token + "/" + method
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError("telegram %s: %s" % (exc.code, detail)) from None
    except urllib.error.URLError:
        raise RuntimeError("telegram network error") from None
    body = json.loads(raw.decode() or "{}")
    if not body.get("ok"):
        raise RuntimeError("telegram rejected the request")
    return body

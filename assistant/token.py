"""The Upstox token lives in .env. This file never logs the value."""

from assistant.config import ROOT

UPSTOX_KEY = "TRADEFISH_UPSTOX_ACCESS_TOKEN"
TELEGRAM_KEY = "ASSISTANT_TELEGRAM_BOT_TOKEN"


def token_hint() -> str:
    return _hint(_read_key(UPSTOX_KEY))


def telegram_hint() -> str:
    return _hint(_read_key(TELEGRAM_KEY))


def write_token(token: str) -> None:
    _write_key(UPSTOX_KEY, token)


def write_telegram(token: str) -> None:
    _write_key(TELEGRAM_KEY, token)


def read_telegram() -> str:
    return _read_key(TELEGRAM_KEY)


def _hint(token: str) -> str:
    if len(token) < 4:
        return ""
    return "ending " + token[-4:]


def _write_key(key: str, token: str) -> None:
    fresh = token.strip()
    if not fresh:
        return
    path = ROOT / ".env"
    lines = path.read_text().splitlines() if path.exists() else []
    written = []
    found = False
    for line in lines:
        if line.startswith(key + "="):
            written.append(key + "=" + fresh)
            found = True
        else:
            written.append(line)
    if not found:
        written.append(key + "=" + fresh)
    path.write_text("\n".join(written) + "\n")


def _read_key(key: str) -> str:
    path = ROOT / ".env"
    if not path.exists():
        return ""
    for line in path.read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip()
    return ""

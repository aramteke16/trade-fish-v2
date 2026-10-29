"""Page for the weekly buy, the book, and the clock.

The Friday ticker is a separate process: python3 -m assistant schedule.
Run now runs the top 3 at this moment and sends Telegram. It does not
move lots. Tokens stay in .env and are never put in a response.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from assistant.confirm import add_purchase, confirm_done, next_session, set_purchased
from assistant.db import get_settings, list_decisions, list_fills, load_book, set_settings
from assistant.decide import run_week
from assistant.log import get_logger
from assistant.marks import enrich
from assistant.names import names_for
from assistant.notify import send_test
from assistant.schedule import next_run
from assistant.token import telegram_hint, token_hint, write_telegram, write_token

log = get_logger()
HOST = os.environ.get("ASSISTANT_HOST", "127.0.0.1")
PORT = int(os.environ.get("ASSISTANT_PORT", "8080"))
PAGE = Path(__file__).with_name("page.html")

_gate = threading.Lock()
_worker: threading.Thread | None = None


def _split(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    scheduled = []
    manual = []
    for row in rows:
        # Older rows have no source. Those were the Friday job.
        if row.get("source") == "manual":
            manual.append(row)
        else:
            scheduled.append(row)
    return scheduled, manual


def _running() -> bool:
    return _worker is not None and _worker.is_alive()


def _symbols(scheduled: list[dict], manual: list[dict], book: dict) -> set:
    symbols = set()
    for row in scheduled + manual:
        for key in ("top", "ranking", "buys", "sells"):
            for item in row.get(key) or []:
                symbol = item.get("symbol")
                if symbol:
                    symbols.add(symbol)
    for lot in book["lots"]:
        if lot.get("symbol"):
            symbols.add(lot["symbol"])
    return symbols


def state() -> dict:
    settings = get_settings()
    # A crashed page process can leave this flag set. This process is the only writer.
    if settings.get("run_state") == "running" and not _running():
        set_settings({"run_state": "idle"})
        settings["run_state"] = "idle"
    scheduled, manual = _split(list_decisions())
    book = load_book()
    hint = token_hint()
    tg_hint = telegram_hint()
    names = names_for(_symbols(scheduled, manual, book))
    for lot in book["lots"]:
        symbol = lot.get("symbol")
        # The broker sheet name covers a symbol the exchange file missed.
        if symbol and symbol not in names and lot.get("name"):
            names[symbol] = lot["name"]
    open_row = next((row for row in reversed(scheduled) if row.get("status") == "open"), None)
    if open_row is not None:
        open_row = dict(open_row)
        open_row["fill_default"] = next_session(date.fromisoformat(open_row["day"]))
    latest = scheduled[-1] if scheduled else None
    top = {item["symbol"] for item in (latest or {}).get("top") or []}
    sell_bar = (latest or {}).get("sell_bar")
    try:
        portfolio = enrich(book, top, sell_bar, int(settings["min_hold_days"]))
    except Exception:
        log.exception("portfolio figures failed")
        portfolio = {
            "cash": book["cash"],
            "sale_proceeds": book.get("sale_proceeds") or 0,
            "last_add_month": book.get("last_add_month"),
            "as_of": book.get("as_of"),
            "cost": None,
            "market": None,
            "pnl": None,
            "sell_bar": sell_bar,
            "rows": book["lots"],
        }
    return {
        "next_run": next_run().isoformat(timespec="minutes"),
        "scheduled": scheduled,
        "manual": manual,
        "open": open_row,
        "latest": latest,
        "names": names,
        "portfolio": portfolio,
        "fills": list_fills(),
        "holdings": {
            "cash": book["cash"],
            "sale_proceeds": book.get("sale_proceeds") or 0,
            "last_add_month": book.get("last_add_month"),
            "as_of": book.get("as_of"),
            "lots": book["lots"],
        },
        "settings": {
            "decision_weekday": int(settings["decision_weekday"]),
            "decision_hour": int(settings["decision_hour"]),
            "decision_minute": int(settings["decision_minute"]),
            "monthly_cash": int(float(settings["monthly_cash"])),
            "weekly_cash": int(float(settings.get("weekly_cash") or settings["monthly_cash"])),
            "min_hold_days": int(settings["min_hold_days"]),
            "notify_on": settings.get("notify_on") == "1",
            "telegram_chat_id": settings.get("telegram_chat_id") or "",
        },
        "token_set": bool(hint),
        "token_hint": hint,
        "telegram_set": bool(tg_hint),
        "telegram_hint": tg_hint,
        "running": _running(),
        "run_error": settings.get("run_error") or "",
    }


def start_now() -> tuple[bool, str]:
    global _worker
    with _gate:
        if _running():
            return False, "A run is already in progress"
        _worker = threading.Thread(target=_now_job, name="run-now", daemon=False)
        _worker.start()
    return True, ""


def _now_job() -> None:
    set_settings({"run_state": "running", "run_error": ""})
    try:
        run_week(source="now")
    except Exception as exc:
        log.exception("run now failed")
        set_settings({"run_error": str(exc)[:500]})
    finally:
        set_settings({"run_state": "idle"})


def _whole(value, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(label + " must be a whole number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(label + " must be a whole number")
    if not number.is_integer():
        raise ValueError(label + " must be a whole number")
    return int(number)


def save_settings(payload: dict) -> dict:
    weekday = _whole(payload["decision_weekday"], "weekday")
    hour = _whole(payload["decision_hour"], "hour")
    minute = _whole(payload["decision_minute"], "minute")
    weekly = _whole(payload.get("weekly_cash", payload.get("monthly_cash")), "weekly budget")
    if weekday not in range(7):
        raise ValueError("weekday must be 0 (Monday) through 6 (Sunday)")
    if hour not in range(24) or minute not in range(60):
        raise ValueError("hour is 0–23 and minute is 0–59")
    if weekly <= 0:
        raise ValueError("weekly budget must be above zero")
    chat = str(payload.get("telegram_chat_id") or "").strip()
    if len(chat) > 64:
        raise ValueError("chat id is too long")
    notify = payload.get("notify_on")
    set_settings(
        {
            "decision_weekday": weekday,
            "decision_hour": hour,
            "decision_minute": minute,
            "weekly_cash": weekly,
            "notify_on": "1" if notify in (True, 1, "1", "true", "on") else "0",
            "telegram_chat_id": chat,
        }
    )
    token = str(payload.get("token") or "").strip()
    if token:
        write_token(token)
        log.info("Upstox token updated in .env")
    telegram = str(payload.get("telegram_token") or "").strip()
    if telegram:
        write_telegram(telegram)
        log.info("telegram token updated in .env")
    log.info(
        "settings saved: weekday %d %02d:%02d, weekly budget %d",
        weekday,
        hour,
        minute,
        weekly,
    )
    return state()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        log.info("%s %s", self.client_address[0], fmt % args)

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/":
            self._send(200, "text/html; charset=utf-8", PAGE.read_bytes())
            return
        if path == "/api/state":
            self._json(200, state())
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        try:
            payload = self._body()
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        if path in ("/api/run", "/api/now"):
            ok, message = start_now()
            code = 202 if ok else 409
            self._json(code, {"ok": ok, "error": message})
            return
        if path == "/api/settings":
            try:
                self._json(200, save_settings(payload))
            except (ValueError, KeyError) as exc:
                self._json(400, {"error": str(exc)})
            except Exception:
                log.exception("settings save failed")
                self._json(500, {"error": "could not save settings"})
            return
        if path == "/api/done":
            self._act(lambda: confirm_done(payload["decision_id"], payload["fill_date"], payload["lines"]))
            return
        if path == "/api/purchase":
            self._act(lambda: add_purchase(payload["query"], payload["shares"], payload["rupees"], payload["fill_date"]))
            return
        if path == "/api/lot-date":
            self._act(lambda: set_purchased(payload["id"], payload["purchased"]) or "Purchase date saved.")
            return
        if path == "/api/notify-test":
            try:
                send_test()
            except RuntimeError as exc:
                self._json(400, {"error": str(exc)})
                return
            except Exception:
                log.exception("telegram test failed")
                self._json(500, {"error": "telegram test failed"})
                return
            self._json(200, {"ok": True, "notice": "Test message sent.", "state": state()})
            return
        self._json(404, {"error": "not found"})

    def _act(self, call) -> None:
        try:
            notice = call()
        except RuntimeError as exc:
            self._json(409, {"error": str(exc)})
            return
        except (ValueError, KeyError) as exc:
            self._json(400, {"error": str(exc)})
            return
        except Exception:
            log.exception("page action failed")
            self._json(500, {"error": "could not save"})
            return
        self._json(200, {"ok": True, "notice": notice, "state": state()})

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length < 0 or length > 65536:
            raise ValueError("body is too large")
        raw = self.rfile.read(length) if length else b""
        if not raw.strip():
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("expected an object")
        return data

    def _json(self, code: int, payload: dict) -> None:
        self._send(code, "application/json; charset=utf-8", json.dumps(payload).encode())

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def serve_web() -> None:
    set_settings({"run_state": "idle"})
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as exc:
        raise SystemExit(f"page port {PORT} is not available ({exc})")
    log.info("page on http://%s:%d", HOST, PORT)
    log.info("the Friday job is a separate process. this page does not replace it")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("page stopped")
        server.shutdown()

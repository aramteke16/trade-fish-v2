from datetime import datetime
from pathlib import Path

from fastapi.templating import Jinja2Templates

from tradefish.db import IST

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def ist(value: str | None) -> str:
    """ISO timestamp (any offset, incl. old UTC rows) -> 'YYYY-MM-DD HH:MM' IST."""
    if not value:
        return ""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo:
        dt = dt.astimezone(IST)
    return dt.strftime("%Y-%m-%d %H:%M")


templates.env.filters["ist"] = ist

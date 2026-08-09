"""Evening job: pull NSE + BSE announcements, archive and store."""

from tradefish.collectors import announcements


def run() -> str:
    result = announcements.collect()
    parts = [f"{k}={v}" for k, v in result.items() if k != "errors"]
    if "errors" in result:
        parts.append(f"errors={result['errors']}")
    return " ".join(parts)

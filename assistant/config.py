"""Paths and the rules we already agreed. Change a number here, not deep in the code."""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "assistant"

HOLDINGS_PATH = DATA / "holdings.json"
BARS_PATH = DATA / "bars.csv"
DECISIONS_PATH = DATA / "decisions.jsonl"
# ASSISTANT_DB and ASSISTANT_LOG point a test at a temp file. Production leaves them unset.
DB_PATH = Path(os.environ["ASSISTANT_DB"]) if os.environ.get("ASSISTANT_DB") else DATA / "portfolio.db"
LOG_PATH = Path(os.environ["ASSISTANT_LOG"]) if os.environ.get("ASSISTANT_LOG") else DATA / "assistant.log"

# Prices already downloaded for the pharma book. Reused, not fetched again.
PHARMA_BARS = ROOT / "data" / "pharma_all_bars.csv"
INDEX_BARS = ROOT / "data" / "nifty_pharma_index.csv"
ACTOR_PATH = ROOT / "data" / "pharma_all_actor.npz"

# The broker statement to read the first time. Later weeks read holdings.json.
STATEMENT = Path(
    "/Users/aayushramteke/Downloads/Stocks_Holdings_Statement_4531323801_28-10-2026.xlsx"
)

# india-market-learnings.md: a decision may use prices only through the close.
# NSE cash opens 09:15 IST. The message goes out then, so it is not missed
# over the weekend. Monday is 0.
DECISION_WEEKDAY = 0
DECISION_HOUR = 9
DECISION_MINUTE = 15

# Buy rank looks back 84 trading sessions, about four months. 252 sessions is one year.
RANK_SESSIONS = 84
# Weekly buy budget. The settings page stores the live number in the database.
WEEKLY_CASH = 5_000
# Kept so an older database row still has a value. The week no longer spends it.
MONTHLY_CASH = 20_000
# A holding can be sold only after this many calendar days. The week does not sell.
MIN_HOLD_DAYS = 60
# Upstox instrument file. Public. The access token is not in this URL.
NSE_INSTRUMENTS = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"

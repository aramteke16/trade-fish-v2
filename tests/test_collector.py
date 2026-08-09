"""Collector normalization and dedupe tests — no network."""

import pytest

from tradefish import db
from tradefish.collectors.announcements import normalize, store

NSE_ITEM = {
    "symbol": "INFY",
    "desc": "Financial Results",
    "exchdisstime": "05-Aug-2026 18:32:10",
    "attchmntText": "Board approved Q1 results...",
    "attchmntFile": "https://nsearchives.nseindia.com/corporate/xyz.pdf",
}

BSE_ITEM = {
    "SCRIP_CD": 500209,
    "SLONGNAME": "INFOSYS LTD",
    "NEWSSUB": "Financial Results for Q1",
    "News_submission_dt": "2026-08-05T18:32:15",
    "CATEGORYNAME": "Result",
    "ATTACHMENTNAME": "abc.pdf",
}


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB", str(tmp_path / "app.db"))
    db.init_db()


def test_normalize_nse_three_timestamps():
    row = normalize(NSE_ITEM, "nse")
    assert row["ticker"] == "INFY"
    assert row["exchange_disclosure_time"] == "05-Aug-2026 18:32:10"
    assert row["fetched_at"]                  # diagnostic timestamp always set
    assert row["published_at"] is None        # media time — never trusted
    assert row["content_hash"]


def test_normalize_bse():
    row = normalize(BSE_ITEM, "bse")
    assert row["ticker"] == "INFOSYS LTD"
    assert row["exchange_disclosure_time"] == "2026-08-05T18:32:15"
    assert row["doc_type"] == "Result"


def test_store_dedupes_on_rerun():
    assert store([NSE_ITEM], "nse") == 1
    assert store([NSE_ITEM], "nse") == 0     # same item again -> ignored
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] == 1


def test_same_news_from_both_exchanges_kept_separate():
    # cross-source dedupe is a downstream concern; hashes include the source
    store([NSE_ITEM], "nse")
    store([BSE_ITEM], "bse")
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM announcements").fetchone()[0] == 2

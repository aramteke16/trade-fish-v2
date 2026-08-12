"""LLM wired into the weekly decision: extraction job, signals, blended ranking."""

import json
from datetime import date

import pytest

from tradefish import config, db
from tradefish.llm import features
from tradefish.llm.schema import Extraction, ExtractionResult
from tradefish.model import baseline
from tradefish.pipelines import daily_extract


@pytest.fixture(autouse=True)
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB", str(tmp_path / "app.db"))
    db.init_db()
    monkeypatch.setattr(config, "universe", lambda: ["INFY", "TCS"])


def add_announcement(ticker: str, day: str, text: str, source: str = "nse"):
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO announcements (ticker, source, exchange_disclosure_time, fetched_at,"
            " headline, raw_text, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticker, source, f"{day}T18:00:00", f"{day}T19:00:00+05:30",
             "headline", text, f"{ticker}{day}{text[:10]}"),
        )


def test_bundles_only_universe_names_with_enough_text():
    day = "2026-08-12"
    add_announcement("INFY", day, "Large multi-year order win worth 850 crore rupees")
    add_announcement("RELIANCE", day, "Not in this test universe so must be ignored")
    add_announcement("TCS", day, "short")  # below MIN_CHARS
    bundles = daily_extract.bundles(day)
    assert set(bundles) == {"INFY"}


def test_extract_job_records_and_skips_repeats(monkeypatch):
    day = date.today().isoformat()  # the job always scores "today"
    add_announcement("INFY", day, "Large multi-year order win worth 850 crore rupees")
    calls = []

    def fake_extract(text, ticker, as_of):
        calls.append(ticker)
        e = Extraction(catalyst="order_win", sentiment=0.6, surprise=0.5, guidance_delta=0.0,
                       magnitude=0.4, novelty=0.9, uncertainty=0.2, persistence=3)
        with db.connect() as conn:
            conn.execute(
                "INSERT INTO extractions (ticker, as_of, provider, model, prompt_version,"
                " tokens_used, latency_ms, failed, payload) VALUES (?, ?, 'fake', 'm', 'v1',"
                " 10, 5, 0, ?)", (ticker, as_of, e.model_dump_json()))
        return ExtractionResult(extraction=e, provider="fake", model="m", prompt_version="v1",
                                tokens_used=10)

    monkeypatch.setattr(daily_extract.extractor, "extract", fake_extract)
    assert "extracted 1 tickers" in daily_extract.run()
    assert "no new" in daily_extract.run()  # already scored -> no second API call
    assert calls == ["INFY"]


def test_signals_pick_strongest_and_ignore_failures():
    with db.connect() as conn:
        for ticker, sentiment, failed in [("INFY", 0.2, 0), ("INFY", 0.9, 0), ("TCS", 0.9, 1)]:
            payload = json.dumps({"catalyst": "earnings", "sentiment": sentiment, "surprise": 0.0,
                                  "guidance_delta": 0.0, "magnitude": 1.0, "novelty": 1.0,
                                  "uncertainty": 0.0, "persistence": 2, "evidence": ""})
            conn.execute(
                "INSERT INTO extractions (ticker, as_of, provider, model, prompt_version,"
                " failed, payload) VALUES (?, '2026-08-12', 'f', 'm', 'v1', ?, ?)",
                (ticker, failed, payload))
    sig = features.signals("2026-08-05")
    assert sig == pytest.approx({"INFY": 0.45})  # 0.5*0.9, strongest item only


def test_llm_weight_changes_the_basket():
    feats = {s: {"mom_1w": m, "mom_4w": m, "mom_12w": m, "vol": 0.01}
             for s, m in [("A", 0.05), ("B", 0.04), ("C", 0.03)]}
    assert baseline.rank(feats)[0][0] == "A"  # price-only winner
    llm = {"C": 1.0, "A": -1.0}
    assert baseline.rank(feats, llm, llm_weight=0.9)[0][0] == "C"  # news flips it
    assert baseline.rank(feats, llm, llm_weight=0.0)[0][0] == "A"  # weight 0 = baseline

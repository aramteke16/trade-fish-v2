"""LLM extractor tests with a fake provider — no network, no API key."""

import json

import pytest

from tradefish import db
from tradefish.llm import cache, extractor
from tradefish.llm.schema import Extraction

VALID = json.dumps({
    "catalyst": "earnings", "sentiment": 0.5, "surprise": 0.3, "guidance_delta": 0.1,
    "magnitude": 0.4, "novelty": 0.8, "uncertainty": 0.2, "persistence": 2,
    "evidence": "net profit up 24% yoy",
})


@pytest.fixture(autouse=True)
def clean_state(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DB", tmp_path / "llm_cache.db")
    monkeypatch.setenv("APP_DB", str(tmp_path / "app.db"))
    db.init_db()


def fake_provider(responses):
    calls = []

    def complete(prompt, model):
        calls.append(prompt)
        return responses[min(len(calls) - 1, len(responses) - 1)], 10

    return complete, calls


def run(monkeypatch, responses, text="Q1 results announced"):
    complete, calls = fake_provider(responses)
    monkeypatch.setitem(extractor.PROVIDERS, "deepseek", (complete, "test-model"))
    result = extractor.extract(text, "INFY", "2026-08-03")
    return result, calls


def test_valid_response_parsed(monkeypatch):
    result, calls = run(monkeypatch, [VALID])
    assert result.extraction.catalyst == "earnings"
    assert not result.extraction_failed
    assert result.provider == "deepseek" and result.model == "test-model"
    assert len(calls) == 1


def test_retry_after_invalid_then_valid(monkeypatch):
    result, calls = run(monkeypatch, ["not json at all", VALID])
    assert result.extraction.catalyst == "earnings"
    assert len(calls) == 2
    assert "failed validation" in calls[1]


def test_neutral_fallback_marked_failed(monkeypatch):
    result, calls = run(monkeypatch, ["garbage"] * 3)
    assert result.extraction_failed
    assert result.extraction.catalyst == "none"
    assert len(calls) == 3


def test_cache_hit_skips_provider(monkeypatch):
    _, calls_a = run(monkeypatch, [VALID], text="same bundle")
    result, calls_b = run(monkeypatch, [VALID], text="same bundle")
    assert result.cached and len(calls_b) == 0


def test_failed_extraction_not_cached(monkeypatch):
    run(monkeypatch, ["garbage"] * 3, text="bad bundle")
    result, calls = run(monkeypatch, [VALID], text="bad bundle")
    assert not result.extraction_failed and len(calls) == 1


def test_extraction_row_recorded(monkeypatch):
    run(monkeypatch, [VALID])
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM extractions").fetchone()
    assert row["ticker"] == "INFY" and row["provider"] == "deepseek"
    Extraction.model_validate_json(row["payload"])

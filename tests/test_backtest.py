"""Backtest engine: synthetic price history, no network calls."""

import numpy as np
import pandas as pd
import pytest

from backtest import engine, report

DATES = pd.bdate_range("2023-09-01", "2024-01-19")  # ~95 business days of pre-history + 2 weeks
WEEK1_MON = pd.Timestamp("2024-01-01")


def trending_series(daily_return: float, noise_seed: int) -> pd.DataFrame:
    """Flat-intrabar price series compounding a fixed daily return, with tiny noise."""
    rng = np.random.default_rng(noise_seed)
    closes = 100.0 * (1 + daily_return) ** np.arange(len(DATES))
    closes *= 1 + rng.normal(0, 0.0005, len(DATES))
    return pd.DataFrame({"open": closes, "high": closes, "low": closes, "close": closes,
                         "volume": 1_000_000}, index=DATES)


def flat_series(level: float, dates) -> pd.DataFrame:
    """Constant-price series — used where only ticker identity matters, not momentum."""
    vals = np.full(len(dates), float(level))
    return pd.DataFrame({"open": vals, "high": vals, "low": vals, "close": vals,
                         "volume": 1_000_000}, index=dates)


@pytest.fixture
def history():
    # A and B trend up identically before week 1 (similar momentum score, both get picked).
    # C stays flat (lowest score, should never be picked with top_k=2).
    hist = {"A": trending_series(0.004, 1), "B": trending_series(0.004, 2),
            "C": trending_series(0.0, 3)}

    entry_a = float(hist["A"].loc[WEEK1_MON, "open"])
    entry_b = float(hist["B"].loc[WEEK1_MON, "open"])
    # A: wick above +6% on Tuesday -> take-profit
    hist["A"].loc[pd.Timestamp("2024-01-02"), "high"] = entry_a * 1.065
    # B: wick below -3% on Wednesday -> stop-loss
    hist["B"].loc[pd.Timestamp("2024-01-03"), "low"] = entry_b * 0.94
    return hist


@pytest.fixture(autouse=True)
def no_network(monkeypatch, history):
    monkeypatch.setattr(engine.bt_data, "fetch_all", lambda symbols, start, end: history)


def test_engine_picks_top_movers_and_resolves_barriers():
    trades, weekly, weekly_ic = engine.run(["A", "B", "C"], "2024-01-01", "2024-01-05",
                                           capital=30000.0, top_k=2)
    picked = {t["ticker"] for t in trades}
    assert picked == {"A", "B"}  # C's flat history loses the rank, never bought

    outcomes = {t["ticker"]: t["outcome"] for t in trades}
    assert outcomes["A"] == "win"
    assert outcomes["B"] == "loss"
    assert weekly[0]["capital_end"] != 30000.0  # capital actually moved

    assert weekly_ic[0]["n"] == 3  # IC measured across all 3 scored names, not just the 2 picks


def test_engine_skips_weeks_with_no_price_data():
    # window entirely after the synthetic history ends -> no bars that week -> nothing traded
    trades, weekly, _ = engine.run(["A", "B"], "2024-02-05", "2024-02-05", capital=30000.0, top_k=2)
    assert trades == [] and weekly == []


def test_report_rollups_and_summary():
    trades, weekly, weekly_ic = engine.run(["A", "B", "C"], "2024-01-01", "2024-01-05",
                                           capital=30000.0, top_k=2)
    monthly = report.monthly(trades, weekly)
    assert len(monthly) == 1 and monthly.iloc[0]["trades"] == 2

    s = report.summary(trades, weekly, weekly_ic, capital=30000.0)
    assert s["weeks"] == 1 and s["trades"] == 2
    assert s["hit_rate"] == 0.5  # one win (A), one loss (B)
    assert s["max_drawdown"] <= 0


def test_hold_winners_skips_the_rebuy_round_trip(monkeypatch):
    """A re-picked stock is kept across weeks: no trade record, no charges paid."""
    hist = {"A": trending_series(0.003, 1), "B": trending_series(0.0005, 2),
            "C": trending_series(0.0, 3)}
    monkeypatch.setattr(engine.bt_data, "fetch_all", lambda symbols, start, end: hist)

    # churn mode: A is picked, time-exits Friday, rebuys next Monday -> 2 trades
    churn, _, _ = engine.run(["A", "B", "C"], "2024-01-01", "2024-01-12", top_k=1)
    assert len(churn) == 2 and all(t["ticker"] == "A" for t in churn)

    # hold mode: A stays top pick and within barriers -> still held, zero closed trades
    hold, weekly, _ = engine.run(["A", "B", "C"], "2024-01-01", "2024-01-12", top_k=1,
                                 hold_winners=True)
    assert hold == []
    assert weekly[-1]["capital_end"] > 29000  # position marked to market, not lost


def test_engine_detects_a_real_edge_when_one_exists(monkeypatch):
    """A feature_fn that always favours the scripted winner should pick it every time —
    proves the engine can surface a real edge, not just report zero blindly. This is
    what the noise gate leans on: if random features ever behaved like this, it's a bug."""
    dates = pd.bdate_range("2023-09-01", "2024-01-05")
    cheat_hist = {"A": flat_series(100.0, dates), "B": flat_series(200.0, dates),
                 "C": flat_series(300.0, dates)}
    entry_a = float(cheat_hist["A"].loc[WEEK1_MON, "open"])
    cheat_hist["A"].loc[pd.Timestamp("2024-01-02"), "high"] = entry_a * 1.065  # scripted winner
    monkeypatch.setattr(engine.bt_data, "fetch_all", lambda symbols, start, end: cheat_hist)

    def cheat_feature_fn(df):
        # stands in for a look-ahead bug: "knows" which series is the winner via its price level
        favoured = df["close"].iloc[-1] < 150
        score = 10 if favoured else -10
        return {"mom_1w": score, "mom_4w": score, "mom_12w": score, "vol": 1e-9}

    trades, _, _ = engine.run(["A", "B", "C"], "2024-01-01", "2024-01-05", capital=30000.0,
                              top_k=1, feature_fn=cheat_feature_fn)
    assert trades[0]["ticker"] == "A" and trades[0]["outcome"] == "win"

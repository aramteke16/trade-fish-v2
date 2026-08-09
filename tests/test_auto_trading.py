"""Automated weekly paper-trading cycle against a fake price feed."""

import pandas as pd
import pytest

from tradefish import config, db
from tradefish.data import prices
from tradefish.pipelines import friday_exit, monitor_exits, weekend_report, weekly_score


def fake_df(start: float, drift: float) -> pd.DataFrame:
    return pd.DataFrame({"close": [start * (1 + drift) ** i for i in range(70)]})


@pytest.fixture
def market(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DB", str(tmp_path / "app.db"))
    db.init_db()
    symbols = [f"S{i}" for i in range(20)]
    monkeypatch.setattr(config, "universe", lambda: symbols)
    # S0 strongest momentum … S19 weakest
    hist = {s: fake_df(100.0, 0.004 - i * 0.0004) for i, s in enumerate(symbols)}
    quotes = {s: float(hist[s]["close"].iloc[-1]) for s in symbols}
    monkeypatch.setattr(prices, "history", lambda symbols, weeks=30: hist)
    monkeypatch.setattr(prices, "latest", lambda s: quotes.get(s))
    return quotes


def open_tickers():
    with db.connect() as conn:
        return [r["ticker"] for r in conn.execute(
            "SELECT ticker FROM positions WHERE status = 'open'")]


def test_full_week_cycle(market):
    # monday: buys top-k by momentum, skips on re-run
    assert "bought 12/12" in weekly_score.run()
    held = open_tickers()
    assert len(held) == 12 and "S0" in held and "S19" not in held
    assert "skipped" in weekly_score.run()

    # intraday: one hits take profit, one hits stop loss
    market[held[0]] *= 1.07
    market[held[1]] *= 0.95
    assert "exited 2" in monitor_exits.run()
    with db.connect() as conn:
        reasons = {r["exit_reason"] for r in conn.execute(
            "SELECT exit_reason FROM positions WHERE status = 'closed'")}
    assert reasons == {"take_profit", "stop_loss"}

    # friday: everything else closes on the time barrier
    assert "closed 10/10" in friday_exit.run()
    assert open_tickers() == []

    # saturday: results booked
    assert "12 trades booked" in weekend_report.run()
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM weekly_results").fetchone()
    assert row is not None and 0 <= row["hit_rate"] <= 1
    assert row["cost_drag"] > 0


def test_unaffordable_name_replaced_by_next_ranked(market, monkeypatch):
    hist = prices.history([])  # the fixture's dict, symbols arg ignored
    hist["S0"] = fake_df(90000.0, 0.004)  # top momentum but one share > slot budget
    market["S0"] = float(hist["S0"]["close"].iloc[-1])
    assert "bought 12/12" in weekly_score.run()
    held = open_tickers()
    assert "S0" not in held and len(held) == 12


def test_quote_failure_leaves_position_open(market):
    weekly_score.run()
    missing = open_tickers()[0]
    del market[missing]
    friday_exit.run()
    assert open_tickers() == [missing]  # not silently closed at a fake price

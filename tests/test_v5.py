"""Algo v5 rules engine — the club, gates, neutral pick and correlation filter."""

import numpy as np
import pandas as pd
import pytest

from tradefish import v5


def _frame(prices: list[float], volume: float = 1e6) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=len(prices))
    return pd.DataFrame({"open": prices, "high": prices, "low": prices,
                         "close": prices, "volume": volume}, index=idx)


def _rising(n: int = 300, start: float = 100.0, step: float = 0.5) -> pd.DataFrame:
    return _frame([start + step * i for i in range(n)])


def _falling(n: int = 300, start: float = 400.0, step: float = 0.5) -> pd.DataFrame:
    return _frame([start - step * i for i in range(n)])


def test_club_admits_uptrend_and_rejects_downtrend():
    status = v5.club_status({"UP": _rising(), "DOWN": _falling()})
    assert status.loc["UP", "member"]
    assert not status.loc["DOWN", "member"]
    assert status.loc["UP", "mom"] > 0 and status.loc["DOWN", "mom"] < 0


def test_short_history_is_not_scorable():
    assert v5.club_status({"NEW": _rising(n=100)}).empty


def test_trend_break_expels_a_still_positive_momentum_stock():
    # rises for a year, then falls hard enough to break its 200-day average
    prices = [100 + 0.5 * i for i in range(260)] + [230 - 4 * i for i in range(40)]
    status = v5.club_status({"BROKEN": _frame(prices)})
    assert status.loc["BROKEN", "mom"] > 0      # 12-1 momentum still positive
    assert not status.loc["BROKEN", "trend"]    # but the trend has broken
    assert not status.loc["BROKEN", "member"]


def test_select_sells_reports_reasons():
    prices = [100 + 0.5 * i for i in range(260)] + [230 - 4 * i for i in range(40)]
    status = v5.club_status({"UP": _rising(), "DOWN": _falling(),
                             "BROKEN": _frame(prices)})
    sells = v5.select_sells(status, ["UP", "DOWN", "BROKEN", "GONE"])
    assert "UP" not in sells
    assert sells["DOWN"] == "momentum_death"
    assert sells["BROKEN"] == "trend_break"
    assert sells["GONE"] == "no_data"


def test_market_gate_and_storm_brake():
    calm = v5.market_state(_rising(n=400))
    assert calm["gate_open"] and not calm["storm"]

    falling = v5.market_state(_falling(n=400))
    assert not falling["gate_open"]

    rng = np.random.default_rng(0)
    quiet = 100 * np.cumprod(1 + rng.normal(0, 0.002, 380))
    wild = quiet[-1] * np.cumprod(1 + rng.normal(0, 0.05, 20))
    stormy = v5.market_state(_frame(list(quiet) + list(wild)))
    assert stormy["storm"]


def test_neutral_order_is_deterministic_and_not_alphabetical():
    symbols = ["AAA", "BBB", "CCC", "DDD", "EEE"]
    first = v5.neutral_order(symbols)
    assert first == v5.neutral_order(list(reversed(symbols)))
    assert first != sorted(symbols)


def test_select_buys_respects_slots_holdings_and_membership():
    history = {f"S{i}": _rising(start=100 + i) for i in range(8)}
    history["BAD"] = _falling()
    status = v5.club_status(history)
    picks = v5.select_buys(history, status, held=["S0"], n_slots=3, corr_cap=1.1)
    assert len(picks) == 3
    assert "S0" not in picks and "BAD" not in picks


def test_correlation_cap_blocks_lockstep_candidates():
    rng = np.random.default_rng(1)
    base = 100 * np.cumprod(1 + rng.normal(0.001, 0.01, 300))
    history = {"HELD": _frame(list(base)),
               "TWIN": _frame(list(base * 1.5)),  # identical returns
               "OTHER": _frame(list(100 * np.cumprod(1 + rng.normal(0.001, 0.01, 300))))}
    status = v5.club_status(history)
    status["member"] = True  # membership is not what this test is about
    picks = v5.select_buys(history, status, held=["HELD"], n_slots=2, corr_cap=0.6)
    assert "TWIN" not in picks


def test_build_universe_filters_illiquid_and_cheap_names():
    history = {
        "GOOD": _rising(n=300, start=100),
        "CHEAP": _frame([10.0] * 300),
        "THIN": _frame([500.0] * 300, volume=100),
        "SHORT": _rising(n=50),
    }
    keep = v5.build_universe(history)
    assert keep == ["GOOD"]


@pytest.mark.parametrize("n_slots", [0, -1])
def test_no_slots_means_no_buys(n_slots):
    history = {"S1": _rising()}
    assert v5.select_buys(history, v5.club_status(history), [], n_slots) == []


# --- chart aggregation (routes/v5.py) ---

def _curve(pairs, nifty_start=100.0):
    """[(day, total)] -> equity rows shaped like the v5_equity table."""
    return [{"day": d, "cash": 0.0, "market": t, "total": t, "open_count": 12,
             "nifty": nifty_start + i} for i, (d, t) in enumerate(pairs)]


def test_chart_buckets_pnl_by_day_month_and_year():
    from tradefish.web.routes.v5 import _chart_data
    rows = _curve([("2025-12-30", 30_500.0), ("2025-12-31", 31_000.0),
                   ("2026-01-02", 30_800.0), ("2026-02-02", 33_000.0)])
    data = _chart_data(rows, 30_000.0)

    days = data["pnl"]["day"]
    assert [d["label"] for d in days] == ["2025-12-30", "2025-12-31",
                                          "2026-01-02", "2026-02-02"]
    assert days[0]["pnl"] == 500.0        # measured from starting capital
    assert days[2]["pnl"] == -200.0       # and from the previous close after that

    months = data["pnl"]["month"]
    assert [m["label"] for m in months] == ["2025-12", "2026-01", "2026-02"]
    assert months[0]["pnl"] == 1_000.0    # capital -> last mark of December
    assert months[2]["pnl"] == 2_200.0    # January close -> February close

    years = data["pnl"]["year"]
    assert [y["label"] for y in years] == ["2025", "2026"]
    assert years[0]["pnl"] == 1_000.0
    assert years[1]["pnl"] == 2_000.0     # 31,000 -> 33,000


def test_chart_indexes_both_series_to_a_common_base():
    from tradefish.web.routes.v5 import _chart_data
    rows = _curve([("2026-01-01", 30_000.0), ("2026-01-02", 33_000.0)],
                  nifty_start=20_000.0)
    equity = _chart_data(rows, 30_000.0)["equity"]
    assert equity[0]["portfolio"] == 100.0 and equity[0]["nifty"] == 100.0
    assert equity[1]["portfolio"] == 110.0   # +10% portfolio
    assert equity[1]["nifty"] == 100.01      # index barely moved — one scale, no dual axis


def test_chart_summary_tracks_peak_to_trough_drawdown():
    from tradefish.web.routes.v5 import _chart_data
    rows = _curve([("2026-01-01", 30_000.0), ("2026-01-02", 40_000.0),
                   ("2026-01-05", 28_000.0), ("2026-01-06", 36_000.0)])
    summary = _chart_data(rows, 30_000.0)["summary"]
    assert summary["total"] == 36_000.0
    assert summary["pnl"] == 6_000.0
    assert summary["pct"] == pytest.approx(20.0)
    assert summary["drawdown"] == pytest.approx(-30.0)   # 40,000 -> 28,000
    assert summary["days"] == 4


def test_chart_handles_an_empty_curve():
    from tradefish.web.routes.v5 import _chart_data
    data = _chart_data([], 30_000.0)
    assert data["equity"] == []
    assert data["pnl"]["month"] == []
    assert data["summary"]["total"] == 30_000.0

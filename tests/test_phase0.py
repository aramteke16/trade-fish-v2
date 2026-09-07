"""Phase 0 harness sanity tests."""

import pytest

from tradefish.costs import round_trip_pct
from tradefish.metrics import hit_rate, ic, max_drawdown
from tradefish.labels.triple_barrier import label
from tradefish.model.splitter import walk_forward_splits


def test_round_trip_cost_near_22bps():
    # plan §Phase 0: round trip ≈ 0.22% on delivery
    assert 0.0020 < round_trip_pct(1_000_000) < 0.0024


def test_barrier_stop_hit_first():
    outcome, exit_price, day = label(
        entry=100, highs=[101, 102], lows=[96, 95], closes=[97, 96],
        upper=0.06, lower=-0.03,
    )
    assert outcome == "loss" and exit_price == 97.0 and day == 0


def test_barrier_take_profit():
    outcome, exit_price, day = label(
        entry=100, highs=[103, 107], lows=[99, 100], closes=[102, 106],
        upper=0.06, lower=-0.03,
    )
    assert outcome == "win" and exit_price == 106.0 and day == 1


def test_barrier_time_exit():
    outcome, exit_price, day = label(
        entry=100, highs=[102, 103], lows=[99, 100], closes=[101, 102],
        upper=0.06, lower=-0.03,
    )
    assert outcome == "neutral" and exit_price == 102 and day == 1


def test_barrier_both_hit_same_day_is_conservative():
    # stop and take-profit inside one bar -> assume stop first
    outcome, _, _ = label(
        entry=100, highs=[107], lows=[96], closes=[105],
        upper=0.06, lower=-0.03,
    )
    assert outcome == "loss"


def test_splitter_embargo_gap():
    weeks = list(range(10))
    splits = list(walk_forward_splits(weeks, train_window=4, embargo=1))
    for train, test in splits:
        # newest training week resolves before the embargo gap
        assert max(train) <= test - 2
        assert len(train) <= 4


def test_splitter_skips_early_weeks():
    assert list(walk_forward_splits([0, 1], embargo=1)) == []


def test_ic_perfect_and_inverted():
    assert ic([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert ic([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_hit_rate():
    assert hit_rate(["win", "loss", "win", "neutral"]) == pytest.approx(0.5)


def test_max_drawdown():
    # 100 -> 110 -> 88 is a 20% drawdown from the peak
    assert max_drawdown([0.10, -0.20]) == pytest.approx(-0.20)

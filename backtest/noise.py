"""Mandatory gate (plan-backtest §4, plan-v2 §10): the harness must show zero edge
on random features. A real edge here means a look-ahead bug, not a working strategy —
fix the harness before trusting any other number it produces.

Note: "zero edge" does not mean zero return. Every trade pays real charges both
ways, so a truly random strategy should land close to minus the round-trip cost
per week, not exactly zero. A materially positive result is the failure signal.
"""

import numpy as np

from tradefish import costs
from tradefish.model.baseline import MIN_DAYS

from backtest import engine

SEED = 7  # fixed so the gate is reproducible, not flaky


def _random_feature_fn(seed: int):
    """Independent random features per (symbol, week) via one advancing RNG."""
    rng = np.random.default_rng(seed)

    def feature_fn(df):
        if len(df) < MIN_DAYS:
            return None
        return {"mom_1w": rng.normal(), "mom_4w": rng.normal(),
                "mom_12w": rng.normal(), "vol": abs(rng.normal()) + 1e-9}
    return feature_fn


def run(symbols: list[str], start: str, end: str, capital: float = 30000.0,
        top_k: int = 12) -> dict:
    trades, weekly, _ = engine.run(symbols, start, end, capital, top_k,
                                   feature_fn=_random_feature_fn(SEED))
    returns = [w["return"] for w in weekly]
    avg_weekly = sum(returns) / len(returns) if returns else 0.0
    expected_drag = -costs.round_trip_pct(capital / top_k)  # cost-only expectation

    # generous band: real edge should dwarf cost drag, not hide inside it
    passed = avg_weekly < expected_drag + 0.01
    return {
        "weeks": len(weekly), "trades": len(trades), "avg_weekly_return": avg_weekly,
        "expected_from_costs_alone": expected_drag,
        "total_return": weekly[-1]["capital_end"] / capital - 1 if weekly else 0.0,
        "passed": passed,
    }

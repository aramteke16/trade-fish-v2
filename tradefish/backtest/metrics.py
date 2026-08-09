"""Metrics module (plan §Phase 0 / §11): IC, hit rate, skew, net return, drawdown."""

import pandas as pd


def ic(predicted, realized) -> float:
    """Spearman rank correlation between predicted and realized returns."""
    return pd.Series(list(predicted)).rank().corr(pd.Series(list(realized)).rank())


def hit_rate(outcomes) -> float:
    """Fraction of trades labeled 'win'."""
    outcomes = list(outcomes)
    return sum(o == "win" for o in outcomes) / len(outcomes) if outcomes else 0.0


def return_skew(returns) -> float:
    return pd.Series(list(returns)).skew()


def net_return(gross_return: float, cost_pct: float) -> float:
    return gross_return - cost_pct


def max_drawdown(weekly_returns) -> float:
    """Largest peak-to-trough drop of the compounded equity curve (negative)."""
    equity = (1 + pd.Series(list(weekly_returns))).cumprod()
    return (equity / equity.cummax() - 1).min()

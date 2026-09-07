"""Turns raw backtest output into month/year tables, benchmarks, and headline metrics."""

import pandas as pd

from tradefish import metrics

from backtest import data as bt_data


def _rollup(trades: list[dict], weekly: list[dict], freq: str) -> pd.DataFrame:
    """Group weeks into calendar periods ('M' or 'Y'), compounding returns within each."""
    w = pd.DataFrame(weekly)
    if w.empty:
        return pd.DataFrame()
    w["period"] = pd.to_datetime(w["week"]).dt.to_period(freq)
    t = pd.DataFrame(trades)
    if not t.empty:
        t["period"] = pd.to_datetime(t["week"]).dt.to_period(freq)

    rows = []
    for period, grp in w.groupby("period"):
        tg = t[t["period"] == period] if not t.empty else t
        rows.append({
            "period": str(period),
            "return_pct": ((1 + grp["return"]).prod() - 1) * 100,
            "trades": len(tg),
            "wins": int((tg["outcome"] == "win").sum()) if not tg.empty else 0,
            "charges": float(tg["charge"].sum()) if not tg.empty else 0.0,
        })
    return pd.DataFrame(rows)


def monthly(trades: list[dict], weekly: list[dict]) -> pd.DataFrame:
    return _rollup(trades, weekly, "M")


def yearly(trades: list[dict], weekly: list[dict]) -> pd.DataFrame:
    return _rollup(trades, weekly, "Y")


def benchmark_return(symbol: str, start: str, end: str) -> float:
    """Buy-and-hold return of an index (e.g. '^NSEI') over the same window."""
    df = bt_data.fetch_benchmark(symbol, start, end)
    return float(df["close"].iloc[-1] / df["close"].iloc[0] - 1)


def summary(trades: list[dict], weekly: list[dict], weekly_ic: list[dict],
           capital: float) -> dict:
    """Headline numbers: total return, CAGR, drawdown, hit rate, cost drag, IC."""
    if not weekly:
        return {"weeks": 0}
    w = pd.DataFrame(weekly)
    t = pd.DataFrame(trades)
    ic_values = [r["ic"] for r in weekly_ic if r["ic"] is not None]

    total_return = w["capital_end"].iloc[-1] / capital - 1
    years = len(w) / 52
    wins = t[t["outcome"] == "win"]["pnl"] if not t.empty else pd.Series(dtype=float)
    losses = t[t["outcome"] != "win"]["pnl"] if not t.empty else pd.Series(dtype=float)

    return {
        "weeks": len(w), "trades": len(t),
        "total_return": total_return,
        "cagr": (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0,
        "max_drawdown": metrics.max_drawdown(w["return"]),
        "hit_rate": metrics.hit_rate(t["outcome"]) if not t.empty else 0.0,
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "total_charges": float(t["charge"].sum()) if not t.empty else 0.0,
        "mean_weekly_ic": sum(ic_values) / len(ic_values) if ic_values else None,
        "final_capital": float(w["capital_end"].iloc[-1]),
    }

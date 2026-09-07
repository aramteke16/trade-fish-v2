"""Decompose the loss: universe drift vs stock picking vs barrier exits vs fees.

Saves every intermediate to data/backtest_output/ so the numbers can be audited by hand.
Run: python -m backtest.diagnose
"""

import pandas as pd

from tradefish import config, costs, strategy
from tradefish.db import ROOT
from tradefish.labels.triple_barrier import label
from tradefish.model import baseline

from backtest import data as bt_data, engine

OUT = ROOT / "data" / "backtest_output"
START, END, CAPITAL, TOP_K = "2024-01-01", "2026-08-16", 30000.0, 6


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    symbols = config.universe()
    upper, lower = config.strategy("upper_barrier"), config.strategy("lower_barrier")

    fetch_start = (pd.Timestamp(START) - pd.Timedelta(days=engine.PADDING_DAYS)).date().isoformat()
    fetch_end = (pd.Timestamp(END) + pd.Timedelta(days=1)).date().isoformat()
    history = bt_data.fetch_all(symbols, fetch_start, fetch_end)

    rows = []
    for monday in engine.week_mondays(START, END):
        week = bt_data.week_bars(history, monday, monday + pd.Timedelta(days=4))
        if not week:
            continue
        prior = bt_data.as_of(history, monday)
        feats = {s: f for s, df in prior.items() if (f := baseline.features(df))}
        if not feats:
            continue

        entry = {s: float(df["open"].iloc[0]) for s, df in week.items()}
        # raw = what the stock did Mon open -> Fri close, no barriers, no fees
        raw = {s: float(df["close"].iloc[-1] / df["open"].iloc[0] - 1)
               for s, df in week.items() if s in feats}
        if len(raw) < 10:
            continue

        ranked = [(s, sc) for s, sc in baseline.rank(feats) if s in raw]
        picks = [s for s, _ in ranked[:TOP_K]]
        worst = [s for s, _ in ranked[-TOP_K:]]

        # same picks, but exited by the barrier rules instead of held all week
        barrier_rets = []
        for s in picks:
            bars = week[s]
            _, exit_price, _ = label(entry[s], bars["high"].tolist(), bars["low"].tolist(),
                                     bars["close"].tolist(), upper, lower)
            barrier_rets.append(exit_price / entry[s] - 1)

        # weekly high/low swing, to compare against the -3% stop distance
        swings = [float(df["low"].min() / df["open"].iloc[0] - 1) for s, df in week.items()
                  if s in picks]

        rows.append({
            "week": monday.date().isoformat(),
            "universe_raw": sum(raw.values()) / len(raw),
            "top_raw": sum(raw[s] for s in picks) / len(picks),
            "bottom_raw": sum(raw[s] for s in worst) / len(worst),
            "top_barrier": sum(barrier_rets) / len(barrier_rets),
            "median_dip": pd.Series(swings).median(),
            "n_scored": len(raw),
        })

    df = pd.DataFrame(rows)
    df.to_csv(OUT / "diagnosis_weekly.csv", index=False)

    def compound(col):
        return (1 + df[col]).prod() - 1

    print(f"weeks analysed: {len(df)}  (saved to {OUT/'diagnosis_weekly.csv'})\n")
    print("--- where the money goes, step by step (compounded over the window) ---")
    print(f"1. universe itself, equal weight, held every week : {compound('universe_raw'):+.1%}")
    print(f"2. our TOP {TOP_K} picks, held all week, no barriers  : {compound('top_raw'):+.1%}")
    print(f"3. the WORST {TOP_K} names, held all week            : {compound('bottom_raw'):+.1%}")
    print(f"4. our top picks WITH barrier exits               : {compound('top_barrier'):+.1%}")

    fee_pct = costs.round_trip_pct(CAPITAL / TOP_K)
    print(f"5. after fees ({fee_pct:.2%} per round trip)          : see backtest result\n")

    print("--- is the signal predictive? ---")
    edge = df["top_raw"].mean() - df["bottom_raw"].mean()
    print(f"avg weekly return: top {df['top_raw'].mean():+.3%} vs bottom {df['bottom_raw'].mean():+.3%}"
          f" vs universe {df['universe_raw'].mean():+.3%}")
    print(f"top-minus-bottom spread: {edge:+.3%}/week  (positive = signal works)")
    print(f"weeks top beat universe: {(df['top_raw'] > df['universe_raw']).mean():.1%} of weeks\n")

    print("--- is the -3% stop too tight for these stocks? ---")
    print(f"median weekly dip of picked stocks: {df['median_dip'].median():.2%}")
    print(f"weeks where median pick dipped past -3%: {(df['median_dip'] <= -0.03).mean():.1%}")
    print(f"barrier cost vs just holding: {compound('top_barrier') - compound('top_raw'):+.1%}")


if __name__ == "__main__":
    main()

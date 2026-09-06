"""CLI: python -m backtest.run --start 2024-01-01

Runs the mandatory noise gate, prints benchmarks, then the real strategy
backtest with month/year rollups and a trade-by-trade CSV. See docs/research/plan-backtest.md.
"""

import argparse
from datetime import date

import pandas as pd

from tradefish import config
from tradefish.db import ROOT

from backtest import engine, noise, report

OUTPUT_DIR = ROOT / "data" / "backtest_output"


def main():
    parser = argparse.ArgumentParser(description="Walk-forward backtest (docs/research/plan-backtest.md)")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--capital", type=float, default=float(config.strategy("paper_capital")))
    parser.add_argument("--top-k", type=int, default=config.strategy("top_k"))
    parser.add_argument("--llm-weight", type=float, default=0.0)  # price-only until BSE backfill
    parser.add_argument("--skip-noise-gate", action="store_true")
    args = parser.parse_args()

    symbols = config.universe()
    print(f"universe: {len(symbols)} names | window: {args.start} to {args.end}")
    print("NOTE: today's universe is used for the whole window -> survivorship bias")
    print("applies (docs/research/plan-backtest.md §6.1). Treat results as optimistic.\n")

    if not args.skip_noise_gate:
        print("=== gate 1: noise test (random features must show ~zero edge) ===")
        n = noise.run(symbols, args.start, args.end, args.capital, args.top_k)
        print(f"weeks={n['weeks']} trades={n['trades']} "
              f"avg_weekly_return={n['avg_weekly_return']:.4%} "
              f"(cost-only expectation {n['expected_from_costs_alone']:.4%})")
        if not n["passed"]:
            print("\n*** GATE FAILED: random features show a real edge. ***")
            print("*** The harness has a look-ahead bug — stopping here. ***")
            print("*** Fix it before trusting any other backtest number. ***")
            return
        print("PASSED — no look-ahead detected.\n")

    print("=== gate 2: benchmark ===")
    nifty = report.benchmark_return("^NSEI", args.start, args.end)
    print(f"Nifty 50 buy-and-hold: {nifty:.2%}\n")

    print("=== gate 3: strategy backtest ===")
    trades, weekly, weekly_ic = engine.run(symbols, args.start, args.end, args.capital,
                                           args.top_k, llm_weight=args.llm_weight)
    s = report.summary(trades, weekly, weekly_ic, args.capital)
    if s["weeks"] == 0:
        print("no tradeable weeks in this window")
        return

    beat_nifty = "beats" if s["total_return"] > nifty else "trails"
    print(f"weeks={s['weeks']} trades={s['trades']} total_return={s['total_return']:.2%} "
          f"cagr={s['cagr']:.2%} ({beat_nifty} Nifty's {nifty:.2%})")
    print(f"max_drawdown={s['max_drawdown']:.2%} hit_rate={s['hit_rate']:.2%}")
    print(f"avg_win=₹{s['avg_win']:.2f} avg_loss=₹{s['avg_loss']:.2f} "
          f"total_charges=₹{s['total_charges']:.2f}")
    if s["mean_weekly_ic"] is not None:
        print(f"mean_weekly_ic={s['mean_weekly_ic']:.3f}")
    print(f"final_capital=₹{s['final_capital']:.2f} (started ₹{args.capital:.2f})\n")

    print("--- monthly ---")
    print(report.monthly(trades, weekly).to_string(index=False))
    print("\n--- yearly ---")
    print(report.yearly(trades, weekly).to_string(index=False))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"trades_{args.start}_{args.end}.csv"
    pd.DataFrame(trades).to_csv(out_path, index=False)
    print(f"\ntrade log written to {out_path}")


if __name__ == "__main__":
    main()

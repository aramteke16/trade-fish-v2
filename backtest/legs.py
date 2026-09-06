"""Leg decomposition (intrinsic time): does entering EARLY in an up-leg beat entering LATE?

Causal directional-change algorithm — a swing low is only confirmed after price has
risen 1 sigma_week off it, using data available that day. No hindsight zig-zag.
Run: python -m backtest.legs
"""

import numpy as np
import pandas as pd

from tradefish import config
from tradefish.db import ROOT

from backtest import data as bt_data

OUT = ROOT / "data" / "backtest_output"
HORIZON = 20          # barrier walk limit, trading days (~4 weeks)
TARGET_S, STOP_S = 1.5, 1.0


def decompose(close: pd.Series, sigma_week_: pd.Series):
    """Walk the series once; return per-day state dicts (mode, extension, swings seen)."""
    mode, extreme, anchor, swings = None, float(close.iloc[0]), float(close.iloc[0]), 0
    states = []
    for px, sw in zip(close, sigma_week_):
        if np.isnan(sw) or sw <= 0:
            states.append(None)
            continue
        if mode is None:
            mode = "up"
        if mode == "up":
            if px > extreme:
                extreme = px
            elif px <= extreme * (1 - sw):     # fell 1 sigma off the high: swing high confirmed
                mode, anchor, extreme, swings = "down", extreme, px, swings + 1
        else:
            if px < extreme:
                extreme = px
            elif px >= extreme * (1 + sw):     # rose 1 sigma off the low: swing low confirmed
                mode, anchor, extreme, swings = "up", extreme, px, swings + 1
        ext = (px / anchor - 1) / sw           # distance from the leg's origin, in sigma units
        states.append({"mode": mode, "ext": ext, "swings": swings})
    return states


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    hist = bt_data.fetch_all(config.universe(), "2023-06-15", "2026-08-17")

    entries, leg_sizes = [], []
    for sym, df in hist.items():
        close = df["close"]
        sigma_week_ = close.pct_change().rolling(60).std() * np.sqrt(5)
        states = decompose(close, sigma_week_)

        prev_ext = None
        for i, st in enumerate(states):
            if st is None or st["swings"] < 2:  # warm-up: need confirmed structure first
                prev_ext = None
                continue
            # a completed up-leg ends when mode flips down; record its full size
            if prev_ext is not None and st["mode"] == "down" and states[i - 1]["mode"] == "up":
                leg_sizes.append(prev_ext)
            prev_ext = st["ext"] if st["mode"] == "up" else None

            if i + 2 >= len(df):
                continue
            # decision at close of day i -> enter at next day's open (point-in-time honest)
            entry = float(df["open"].iloc[i + 1])
            sw = sigma_week_.iloc[i]
            target, stop = entry * (1 + TARGET_S * sw), entry * (1 - STOP_S * sw)
            outcome, days_held, exit_px = "time", HORIZON, None
            for j in range(i + 1, min(i + 1 + HORIZON, len(df))):
                if df["low"].iloc[j] <= stop:          # stop checked first (conservative)
                    outcome, days_held, exit_px = "stop", j - i, stop
                    break
                if df["high"].iloc[j] >= target:
                    outcome, days_held, exit_px = "target", j - i, target
                    break
            if exit_px is None:
                j = min(i + HORIZON, len(df) - 1)
                exit_px, days_held = float(df["close"].iloc[j]), j - i
            entries.append({
                "sym": sym, "date": df.index[i], "mode": st["mode"], "ext": st["ext"],
                "outcome": outcome, "ret": exit_px / entry - 1, "days": days_held,
            })

    e = pd.DataFrame(entries)
    L = float(np.median(leg_sizes))
    print(f"stocks: {len(hist)} | entry-days: {len(e):,} | completed up-legs: {len(leg_sizes):,}")
    print(f"median full up-leg: {L:.2f} sigma | "
          f"quartiles {np.percentile(leg_sizes, 25):.2f} / {np.percentile(leg_sizes, 75):.2f}\n")

    def bucket(row):
        if row["mode"] == "down":
            return "down-leg (falling)"
        f = row["ext"] / L
        if f < 0.25: return "up-leg: fresh (<25% of typical leg)"
        if f < 0.50: return "up-leg: early (25-50%)"
        if f < 0.80: return "up-leg: mid (50-80%)"
        return "up-leg: late (>80%)"

    e["bucket"] = e.apply(bucket, axis=1)
    order = ["up-leg: fresh (<25% of typical leg)", "up-leg: early (25-50%)",
             "up-leg: mid (50-80%)", "up-leg: late (>80%)", "down-leg (falling)"]

    print(f"{'entry state':<36}{'n':>8}{'target-hit':>11}{'stopped':>9}"
          f"{'avg ret':>9}{'t':>7}{'days':>6}")
    for b in order:
        g = e[e.bucket == b]
        if g.empty:
            continue
        # cluster by date so 141 correlated stocks don't inflate the t-stat
        by_date = g.groupby("date")["ret"].mean()
        t = by_date.mean() / (by_date.std() / np.sqrt(len(by_date)))
        print(f"{b:<36}{len(g):>8,}{(g.outcome == 'target').mean():>10.1%}"
              f"{(g.outcome == 'stop').mean():>8.1%}{g.ret.mean():>8.2%}{t:>7.2f}"
              f"{g.days.mean():>6.1f}")

    e.to_csv(OUT / "leg_entries.csv", index=False)
    print(f"\nper-entry data -> {OUT / 'leg_entries.csv'}")


if __name__ == "__main__":
    main()

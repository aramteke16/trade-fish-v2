"""Algo v5 backtest — "momentum club, no picker" + validated risk rules.

Research reference implementation. The production rules live in `tradefish/v5.py`
and the specification in `docs/algo-v5.md`; this file is the standalone historical
simulator that produced the numbers quoted there. Keep the two in sync by hand —
this one uses fractional shares and cached pickles, production uses whole shares
and the live feed.


WHAT IT IS
    Hold 12 liquid NSE names that are in the "momentum club" (positive 12-1
    momentum), chosen for diversification, NOT ranked by any return signal.
    Refresh monthly, trade as little as possible, brake in bad markets.

RULES
    Universe   liquid NSE stocks, point-in-time (traded ~95% of prior year,
               close >= Rs 30, median daily value >= Rs 1 crore).
    Eligible   12-month momentum skipping last month (mom121) > 0.
    Pick       12 names, Rs 2,500 each, in neutral deterministic order
               (symbol hash — no return signal, no liquidity tilt), skipping
               anything >0.6 correlated to names already held (spread, not rank).
    Monthly    sell holdings whose mom121 <= 0 OR whose price broke below
               their own 200-day average (v5 rule); refill open slots.
    Gates      buy only when NIFTY > 50-day average; half-size new buys when
               NIFTY 21-day volatility is above its 90th trailing percentile
               (v5: was 80th — rarer freeze).
    Exits      momentum death / trend break only. No stop-loss. No target.
    Costs      buy 0.12%; sell 0.103% + flat Rs 15.9 DP fee per sale.

WHY THESE RULES (evidence, 2026-09-05 research quest + 20-config iteration lab)
    - Every return-ranking picker FAILED the locked 2024-26 test window:
      extreme momentum 17th percentile of random, low-vol 10th, strict
      52-week-high (dev-window champion at 100th/90th pct) 0th percentile.
      Rankings concentrate into whatever the last regime rewarded.
    - The structure WITHOUT a picker (this file) measured on 2024-26 as the
      distribution of 30 matched random runs: mean +35.2% vs held index
      +29.6%, NIFTY +11.7%. Dev windows: +110.6% (2020-21), +60.6% (2022-23).
    - Gate removal doubled drawdown for no return gain. Stops sold bottoms
      (avg -16.9%/stop). Quarterly cadence went stale; monthly is right.
    - Breadth beats selection: 12 names > 6; the flat DP fee caps breadth
      (below ~Rs 2.5k/slot the fee alone is ~0.65% of the position).

HONEST EXPECTATIONS
    Index-level returns plus a few points, roughly half the index's worst
    drawdown, ~10-20 round trips/year. Single-run luck spread over 2 years
    is large (sd ~25 points across seeds). Survivorship bias in the pool
    flatters all historical numbers; size expectations down.

    The deterministic pick below is one draw from the measured distribution.
    Single-run results of this exact file (v5 rules):
        2024-01 -> 2026-08 (locked test):   +9.3%  maxDD -30.4%  90 round trips
        2020-01 -> 2021-12 (dev):         +104.5%  maxDD  -7.8%  29 round trips
        2022-01 -> 2023-12 (dev):          +46.1%  maxDD -14.2%  41 round trips
    v4 rules (no trend-break exit, 80th-pct brake) printed +26.4% on the same
    test window with a DIFFERENT lucky draw. Judge rules by ensembles, not
    draws: in matched 6-draw ensembles v5 beat v4 on return AND drawdown on
    all three dev windows and the test window (test: +14.8% vs +9.6%, maxDD
    -31% vs -39%). Draw-to-draw spread (roughly +3% to +35% on 2024-26) is
    larger than any rule effect — expect the deployed outcome to be lottery-
    shaped around the ensemble mean, and never re-tune on a single draw.

    Round-2 iteration lab (25 configs, 3 dev slices, 6-draw ensembles) also
    established negatives worth keeping: stronger/looser momentum clubs, own-
    200dma as an ENTRY filter, 6-month momentum, NIFTY 200-day gate (drawdown
    doubled), full risk-off liquidation, 15 slots, inverse-vol sizing, and
    dropping the correlation cap (adds luck, not edge) all failed to improve
    consistently. First liquidity-ordered pick attempt returned +7.3% — a
    hidden large-cap tilt. ANY ordering correlated with returns is a picker
    in disguise; keep the order neutral.

LIVE EXECUTION RULES (deploy with the algo; research-backed, NOT testable on
daily bars — keep them in the order layer, never mix into the backtest logic)
    1. Place orders in the last ~30 minutes of the session, never at 9:15 —
       spreads are widest at the open, and ~92% of Indian equity gains accrue
       overnight (hold through the night, don't buy into the morning).
    2. If an order must wait, prefer a limit at/near last close for these
       club-member buys; use market orders only when the fill matters more
       than the ~0.1% a limit saves.
    3. Keep the monthly cycle on the first trading day — buys then land
       inside the turn-of-month window (first days of month are the
       statistically strongest in India). Do not drift the schedule.
    4. Any future stop or trigger price: never at a round number (stops
       cluster there and get swept); offset by an irregular amount.

USAGE
    .venv/bin/python backtest/algo_v5_backtest.py 2024-01-01 2026-08-17
    Needs cached pool pickles in data/backtest_cache/ (864-stock pool,
    2019-2026) and internet for the NIFTY benchmark on first run.
"""

import hashlib
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "backtest_cache"

CAPITAL = 30_000.0
SLOTS = 12
BUY_COST = 0.0012
SELL_PCT = 0.00103
SELL_FLAT = 15.9
CORR_CAP = 0.6

POOL_FILES = ["prices_2019-01-01_2026-08-17_8423abb38c.pkl",
              "prices_2019-01-01_2026-08-17_f9139c9119.pkl",
              "prices_2019-01-01_2026-08-17_772743d037.pkl"]


def sell_value(shares, px):
    gross = shares * px
    return gross - gross * SELL_PCT - SELL_FLAT


def load_pool():
    pool = {}
    for f in POOL_FILES:
        pool.update(pd.read_pickle(CACHE / f))
    return pool


def load_nifty():
    cache = CACHE / "nifty_2019_2026.pkl"
    if cache.exists():
        return pd.read_pickle(cache)
    sys.path.insert(0, str(ROOT))
    from backtest.data import fetch_benchmark
    df = fetch_benchmark("^NSEI", "2019-01-01", "2026-08-18")
    pd.to_pickle(df, cache)
    return df


def build_universe(pool, cutoff):
    univ = []
    yr = cutoff - pd.DateOffset(years=1)
    for s, df in pool.items():
        h = df[(df.index >= yr) & (df.index < cutoff)]
        if len(h) < 220 or h["close"].iloc[-1] < 30:
            continue
        if (h["close"] * h["volume"]).median() < 1e7:
            continue
        univ.append(s)
    return sorted(univ)


def metrics_asof(closes, values, day):
    """Per-stock mom121, liquidity, from bars strictly before `day`."""
    h = closes[closes.index < day]
    if len(h) < 260:
        return None
    mom121 = h.iloc[-22] / h.iloc[-252] - 1.0
    liq = values[values.index < day].iloc[-64:].median()
    above200 = h.iloc[-1] > h.iloc[-200:].mean()
    out = pd.DataFrame({"mom121": mom121, "liq": liq, "above200": above200})
    return out.dropna()


def nifty_state(nifty):
    close = nifty["close"]
    dma50 = close.rolling(50).mean()
    vol21 = close.pct_change().rolling(21).std()
    vol_thresh = vol21.expanding(min_periods=252).quantile(0.90)
    trend = (close > dma50).shift(1).fillna(False)
    calm = (vol21 < vol_thresh).shift(1).fillna(False)
    state = pd.Series("closed", index=close.index)
    state[trend & calm] = "open"
    state[trend & ~calm] = "volspike"
    return state


def diversified_pick(closes, day, cands, held, need):
    """Most liquid first, skip anything >0.6 correlated with what we hold."""
    h = closes[closes.index < day].iloc[-126:]
    rets = h.pct_change()
    chosen, out = list(held), []
    for s in cands:
        if len(out) >= need:
            break
        ok = True
        for t in chosen:
            r = rets[[s, t]].dropna()
            if len(r) > 60 and r[s].corr(r[t]) > CORR_CAP:
                ok = False
                break
        if ok:
            out.append(s)
            chosen.append(s)
    return out


def run(pool, nifty, start, end):
    universe = build_universe(pool, start)
    closes = pd.DataFrame({s: pool[s]["close"] for s in universe}).sort_index()
    opens = pd.DataFrame({s: pool[s]["open"] for s in universe}).sort_index()
    values = (closes * pd.DataFrame({s: pool[s]["volume"] for s in universe})
              .sort_index())
    state = nifty_state(nifty)

    days = closes.index[(closes.index >= start) & (closes.index <= end)]
    evals = set(days.to_series().groupby([days.year, days.month]).first())
    cash = CAPITAL
    pos, trades, curve = {}, [], []

    for day in days:
        o, c = opens.loc[day], closes.loc[day]

        if day in evals:
            m = metrics_asof(closes, values, day)
            if m is not None:
                for s in list(pos):
                    dead = (s not in m.index or m.loc[s, "mom121"] <= 0
                            or not m.loc[s, "above200"])
                    if dead and not pd.isna(o[s]):
                        px = o[s]
                        cash += sell_value(pos[s]["shares"], px)
                        trades.append((day, s, "EXIT", px,
                                       (px / pos[s]["entry"] - 1) * 100))
                        del pos[s]

                mkt = state.get(day, "closed")
                if mkt != "closed":
                    size_mult = 0.5 if mkt == "volspike" else 1.0
                    elig = m[(m["mom121"] > 0) & ~m.index.isin(pos)]
                    elig = elig[[not pd.isna(o[s]) for s in elig.index]]
                    # neutral order: any liquidity/return ordering is a hidden picker
                    cands = sorted(elig.index, key=lambda s: hashlib.sha1(
                        s.encode()).hexdigest())
                    picks = diversified_pick(closes, day, cands, list(pos),
                                             SLOTS - len(pos))
                    for s in picks:
                        if cash < 1000:
                            break
                        size = min(cash / (SLOTS - len(pos)), cash) * size_mult
                        px = o[s]
                        cash -= size
                        pos[s] = {"shares": size / (px * (1 + BUY_COST)),
                                  "entry": px}
                        trades.append((day, s, "BUY", px, 0.0))

        val = cash + sum(p["shares"] * c[s] for s, p in pos.items()
                         if not pd.isna(c[s]))
        curve.append((day, val))

    last_c = closes.loc[days[-1]]
    final = cash + sum(sell_value(p["shares"], last_c[s])
                       for s, p in pos.items() if not pd.isna(last_c[s]))
    curve[-1] = (days[-1], final)
    return final, pd.Series(dict(curve)), trades


def main():
    start = pd.Timestamp(sys.argv[1] if len(sys.argv) > 1 else "2024-01-01")
    end = pd.Timestamp(sys.argv[2] if len(sys.argv) > 2 else "2026-08-17")
    pool = load_pool()
    nifty = load_nifty()
    final, eq, trades = run(pool, nifty, start, end)
    ret = final / CAPITAL - 1
    yrs = (end - start).days / 365.25
    dd = ((eq / eq.cummax()) - 1).min()
    sells = [t for t in trades if t[2] != "BUY"]
    print(f"v4 {start.date()} -> {end.date()}: {ret*100:+.1f}% "
          f"(CAGR {((final/CAPITAL)**(1/yrs)-1)*100:+.1f}%)  "
          f"maxDD {dd*100:.1f}%  round trips={len(sells)}  "
          f"final Rs {final:,.0f}")


if __name__ == "__main__":
    main()

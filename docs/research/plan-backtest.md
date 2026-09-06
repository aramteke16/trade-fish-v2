# plan-backtest.md — walk-forward backtest harness

Companion to `plan-v2.md`. This document covers only the testing framework: how we
replay the live strategy over history to get instant answers instead of waiting a
week per data point.

**Window:** Jan 2024 → today (~2.5 years, ~137 weeks).
**First build:** price-only. LLM arm follows once BSE history is backfilled.

---

## 1. Principle: test the real system, not a copy

A backtest that reimplements the strategy tests the reimplementation. So the
decision logic lives in **one** function that both sides call:

```
tradefish/strategy.py
    pick_basket(history, llm_signals, capital, top_k, llm_weight)
        -> [(ticker, qty, price), ...]
```

- Live `weekly_score.py` calls it with today's data, then places paper trades.
- The backtest calls it with a historical slice, then simulates fills.

Same code path, same bugs, same behaviour. Anything that diverges between live and
backtest is a bug in one of them, not a modelling choice.

**Reused unchanged (this is the algorithm):**

| Component | File | Role |
|---|---|---|
| Feature + ranking math | `tradefish/model/baseline.py` | scores the universe |
| Exit simulator | `tradefish/labels/triple_barrier.py` | +6% / −3% / Friday |
| Cost model | `tradefish/costs.py` | real Indian delivery charges |
| Metrics | `tradefish/metrics.py` | IC, hit rate, drawdown |
| LLM signal | `tradefish/llm/features.py` | blended when `llm_weight > 0` |

**New (live code assumes "now", history does not):** the data layer, the week loop,
the report, the noise gate.

---

## 2. Layout

A separate top-level package so harness code can never be imported by live trading:

```
backtest/
  data.py      historical prices: bulk fetch, disk cache, point-in-time slicing
  engine.py    week-by-week simulation loop
  report.py    monthly / yearly rollups, benchmarks, summary metrics
  noise.py     mandatory zero-edge gate
  run.py       CLI: python -m backtest.run --start 2024-01-01
```

`tradefish/backtest/` is flattened to `tradefish/costs.py` and `tradefish/metrics.py`
to free the name — `costs.py` is live code (the paper broker charges through it) and
should not sit in a folder called "backtest".

---

## 3. One simulated week

For each Monday in the window:

1. **Features** from prices through the **previous Friday's close**. Nothing from the
   decision day or later ever enters the score.
2. **Rank and pick** via `pick_basket()`, sized against the current (compounding)
   capital: equal slots, integer share counts, walk down the ranking when a share
   price exceeds a slot.
3. **Enter at Monday's open.** Never the close — at 09:20 the close is future data.
4. **Simulate the week** with `triple_barrier.label()` over that week's daily bars.
   Monday's own bar is included (a name can hit the barrier on day one). When one bar
   straddles both barriers, the stop is assumed to hit first.
5. **Charge both sides** through `costs.side_cost()`, compound into capital, record
   the trade.

Flat every weekend, exactly like live — so there is no overlapping-position
accounting to get wrong.

### Live discipline fix this forces

`weekly_score` currently feeds `prices.history()` straight into scoring, which on a
Monday morning can include a partial Monday bar. The backtest cannot do that, so both
sides now take history explicitly cut at the prior close. This makes live and backtest
identical and removes a small live look-ahead in the process.

---

## 4. Build order (gates)

### Gate 1 — the noise test (mandatory, plan-v2 §10)

Replace momentum features with random numbers and run the entire engine.

> **It must report approximately zero edge.** If random data produces a profitable
> backtest, the harness is lying and every later number is worthless. Nothing is
> believed until this passes.

### Gate 2 — benchmarks

Buy-and-hold Nifty (`^NSEI`) and equal-weight universe over the identical window.
Per plan-v2 §Phase 1, the strategy must beat these. Without them a "+14%" means
nothing.

### Gate 3 — the real run

Jan 2024 → today, price-only, current universe.

---

## 5. Output

- **Month-by-month:** return %, trades, wins, charges.
- **Year-on-year:** 2024, 2025, 2026-to-date, each against Nifty for the same period.
- **Summary:** total return, CAGR, max drawdown, hit rate, average win vs average
  loss, total cost drag, weekly IC (rank correlation between score and realized
  return across the **full** universe, not just the picks).
- **CSV** of every simulated trade, so any week can be audited by hand.

Runtime after the first fetch is seconds — prices cache to disk.

---

## 6. Known limitations (state these next to any result)

1. **Survivorship bias — serious.** `config/universe.txt` is today's liquid names, so
   the 2024 replay only trades companies we already know survived. Results are
   optimistic. Proper fix is point-in-time index membership per week; deferred until
   the numbers justify the work.
2. **No historical news.** The announcement corpus starts 2026-08-08, so the LLM arm
   cannot be tested on 2024 yet. `llm_weight` is a parameter from day one, so enabling
   it later is a flag flip after a BSE backfill.
3. **Daily bars, not ticks.** Intra-bar ordering is unknowable; we assume the stop
   first. Live checks every 5 minutes, so live and backtest exits will not match
   exactly. That gap is what paper trading measures.
4. **Adjusted prices.** yfinance adjusts for later splits and dividends; applied
   consistently on both sides of the simulation.
5. **Fills are frictionless.** Entry at the open, exit at the barrier price, no
   slippage or partial fills beyond the modelled charges.

---

## 7. Later

- LLM arm after BSE backfill → answers plan-v2 §Phase 2b: does the LLM add
  incremental IC over price alone?
- LightGBM ranker replaces the momentum scorer; `walk_forward_splits()` (already
  built, purged + embargoed) becomes live at that point since there is finally
  something to fit.
- Point-in-time universe if results warrant the rigor.
- A dashboard page rendering the latest backtest run.

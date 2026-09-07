# strategy-criteria.md — decisions made, and the evidence behind them

Living document. Every rule here was decided from a backtest result, not from theory.
Numbers in brackets are the evidence. See `plan-backtest.md` for how tests are run.

---

## 1. Position sizing

| Setting | Value | Why |
|---|---|---|
| Paper capital | ₹30,000 | fixed for now |
| Stocks held | **6** | fewer = bigger slots = smaller % fees |
| Slot size | ~₹5,000 | |
| Weighting | equal | conviction-weighting needs a signal that works first |

Fees by slot size (measured): ₹2,475 slot → 0.85% round trip. ₹5,000 → 0.53%. ₹25,000 → 0.28%.
**Fixed charges (₹15.5 DP fee) dominate small trades.** This is why 12 stocks on ₹30k cannot work.

---

## 2. Exit rules — volatility-scaled (replaces fixed +6% / −3%)

The old fixed barriers were calibrated for large-cap volatility and are far too tight for
mid/small caps. Measured: the median weekly dip of our picks was **−3.08%**, sitting exactly on
the −3% stop, so over half of all positions were stopped out by ordinary noise.

```
sigma_week = sigma_daily(trailing 60 days) x sqrt(5)

target = max(5.3%, 1.5 x sigma_week)
stop   = 1.0 x sigma_week
max hold = 4 weeks
```

- **Target floor of 5.3%** comes from the rule below: never target less than 10x the round-trip cost.
- **Hold winners across weeks.** A stock still in the top 6 on Monday is kept, not sold Friday
  and rebought — that round trip is pure cost for no change of opinion.
- Expected time to travel k sigmas is `5 x k²` trading days, so a 1.5σ target implies ~2 weeks
  and the 4-week cap is the backstop, not the plan.

### The 10x cost rule
**Target must be at least 10x the round-trip cost**, so fees cannot decide the outcome of a trade.
At 0.53% cost that is a 5.3% minimum target.

### What exits cannot do
Any target/stop pair is break-even against random prices: 1.5σ/1.0σ wins 40% of the time,
`0.4 x 1.5 − 0.6 x 1.0 = 0`. The old 6%/−3% wins 33%, also zero. **Exit rules cannot create
profit** — they only control trade shape and how often fees are paid. Profit must come from
the entry signal.

---

## 3. Cost model

| Item | Cost | Notes |
|---|---|---|
| Round trip at ₹5,000 slot | **0.53%** | STT, exchange, SEBI, stamp, GST, ₹15.5 DP |
| LLM extraction | ~₹0.02 per stock | ~0.0004% — negligible, do not design around it |

---

## 4. Universe criteria

- **Liquid mid and small caps.** No microcaps — spreads and circuit freezes make fills fiction.
- **No PSUs.** Best sector since 2024 (+47%) but now rolling over: −0.4% over 6 months,
  **−8.8% over 3 months**.
- **Sector focus:** pharma / healthcare, chemicals, EV and auto ancillaries.
- Sector performance measured from our own price data (equal weight, real prices):

| Sector | last 6m | since 2024 |
|---|---|---|
| Pharma / healthcare | +22% | **+81%** |
| Market infrastructure | +8% | **+153%** |
| Auto / EV ancillaries | +9% (+17% last 3m, accelerating) | +34% |
| Chemicals / agri | +5% | +7% (weakest — kept by preference, not evidence) |
| PSU / infra / defence | −0.4% | +47% (removed) |

---

## 5. Findings that drive everything above

1. **The entry signal is backwards.** Over 137 weeks: our top-6 picks returned **−22.6%**, our
   bottom-6 returned **+4.6%**, and the universe held equally returned **+24.0%**. The ranking is
   worse than random, not merely useless.
2. **Fees were over half the loss.** Same run with zero fees: −6.8% instead of −58%.
3. **Long-term trend and weekly trading are different games.** BSE rose **+375%** over the window;
   we traded it 7 times and lost ₹329 (stopped out 5 times). Sector filtering (slow, structural)
   is sound; weekly ranking by recent gains is what loses.
4. Momentum literature splits by horizon: 1w–1m reversal, 3–12m momentum. Our score averages
   `mom_1w`, `mom_4w`, `mom_12w` — mixing both regimes — and holds for exactly 1 week.
   **Not yet verified per component.**

---

## 6. Open questions

- **Which component is backwards?** Needs per-feature IC: `mom_1w`, `mom_4w`, `mom_12w`, `vol`
  measured separately against next-week returns.
- **Does reversal work?** Buying the bottom-ranked beat the top-ranked by 27 points — worth a test.
- **Does the LLM signal add anything?** Untestable until BSE news is backfilled.

---

## 7. Universe filter — look-ahead warning

Proposed filter (from `idea.txt`): keep stocks that rose over the past 3–5 years, judged on data
through Dec 2025.

**This is only valid if the backtest starts after the filter date.** Filtering on data through
Dec 2025 and then testing Jan 2024 → Aug 2026 means the 2024–2025 portion is chosen with
knowledge of how those years ended — the backtest would look good and mean nothing.

Two clean options:
1. Filter on data through **Dec 2023**, test **2024 onward**.
2. Filter on data through **Dec 2025**, test **2026 onward** only (~8 months of test data).

Option 1 gives more test data and is the default unless decided otherwise.


# Algo v5 — "Momentum Club, No Picker"

Production specification. Written 2026-09-06 after a six-agent literature review and
~60 backtested configurations. Read this before changing any rule.

**One line:** own 12 liquid NSE stocks that are in uptrends, chosen with no cleverness,
sell them when their trend breaks, and buy nothing when the market is unhealthy.

---

## 1. Why this design (the short history)

Three earlier designs failed honest testing:

| Design | Idea | Result on unseen data |
|---|---|---|
| v1/v2 "legs" | swing decomposition, dip entries, profit targets | ~50th percentile of random |
| v3 | rank by 12-1 momentum, top 6, 15% stop | −3.8% (17th pct of random) |
| variant E | rank by low volatility, top 6 | −2.2% (10th pct) |
| F14 | rank by 52-week-high proximity, top 12 | +0.8% (0th pct) — despite winning both dev windows |

The pattern is the finding: **every ranking rule concentrated the portfolio into whatever
the previous regime rewarded, and the next regime punished it.** Meanwhile the matched
control runs — same structure, no ranking — beat the index on every window tested.

So v5 deliberately has no stock picker. Its edge is membership + breadth + patience.

---

## 2. Rules

### 2.1 Universe (rebuild annually, January)

From the broad NSE pool (`config/pool.txt`), keep stocks that, over the **previous calendar
year only**:

- traded on at least ~95% of sessions (≥ 220 bars)
- closed at ≥ ₹30 on the last day of that year
- had median daily traded value ≥ ₹1 crore

Excluded by policy: trade-to-trade segment names and 2% / 5% circuit-band names — a
lower-circuit lock means you cannot exit, which is fatal for a long-only book.

Point-in-time discipline: the universe used on any date is built only from data before
that date. Violating this silently turns any strategy positive (see §5).

### 2.2 Club membership (per stock, recomputed monthly)

A stock is a club member when **both** hold:

1. **Momentum**: `close[-22] / close[-252] - 1 > 0` — the 12-month move, skipping the most
   recent month. The skip avoids buying short-term spikes (standard 12-1 construction).
2. **Trend intact**: `close[-1] > mean(close[-200:])` — price above its own 200-day average.

### 2.3 Monthly cycle (first trading day of the month)

Computed from bars strictly before today; orders execute on the next session.

1. **Sell** every holding that has lost club membership (momentum ≤ 0 **or** trend broken).
2. **Market gate** — buying allowed only when NIFTY close > its own 50-day average.
   Gate closed ⇒ no purchases this month. Existing holdings are never force-sold.
3. **Storm brake** — if NIFTY's 21-day return volatility is above its 90th trailing
   percentile, new purchases are made at half size.
4. **Refill** to 12 slots from club members not already held:
   - candidate order = SHA-1 hash of the ticker symbol. **Neutral by design.**
   - skip a candidate whose last-126-day daily returns correlate > 0.6 with any holding
   - position size = available cash ÷ empty slots (× 0.5 if the storm brake is on)

### 2.4 Exits

Club-membership loss only. **No stop-loss. No profit target. No time limit.**

Stops were tested and sold bottoms (average −16.9% per stop, then the freeze locked us out
of recoveries). Profit targets amputate the winners that pay for everything.

### 2.5 Costs (charged in every simulation, matched to a zero-brokerage Indian broker)

Buy 0.12% · Sell 0.103% + flat ₹15.9 depository fee ≈ **₹27 per round trip at ₹2,500**.
The flat fee is why breadth stops at ~12 slots: below ~₹2,500 per position the fee alone
exceeds 0.6% of the position.

---

## 3. Measured results

**Method.** v5 has no picker, so which 12 club members you hold is a draw. One backtest is
one lottery ticket. Every number below is the **mean of 6 runs** with different neutral
orderings ("ensemble"), which is the honest expectation; the range shows draw luck.

### Separate windows (fresh ₹30,000 each)

| Window | Ensemble return | Range across draws | Worst drawdown |
|---|---|---|---|
| 2020–2021 (dev) | +158% | +63% … +220% | −10% |
| 2021–2022 (dev) | +86% | +46% … +172% | −16% |
| 2022–2023 (dev) | +70% | +40% … +96% | −14% |
| **2024 → Aug 2026 (locked test)** | **+15%** | +6% … +34% | −31% |

### Continuous runs (one ₹30,000, never reset)

| Period | Ensemble return | ≈ CAGR | Worst drawdown |
|---|---|---|---|
| Jan 2022 → Aug 2026 (4.6 yr) | +107% (→ ₹62,100) | ~17%/yr | −29% |
| Jan 2020 → Aug 2026 (6.6 yr) | +404% (→ ₹1,51,000) | ~27%/yr | −26% |

### How to read these

- Only the 2024–26 window is a true out-of-sample exam; the rest informed the rules.
- 2024–26 contains the worst Indian momentum stretch in years (the live momentum index
  fell ~31% from its Sep-2024 peak) — it is the pessimistic case, and v5 still beat the
  matched v4 structure (+14.8% vs +9.6%) with a shallower drawdown (−31% vs −39%).
- The 2020-start numbers are flattered by buying the covid bottom.
- **Plan on ~12–15%/yr**, not on the historical 17–27%. Survivorship bias (the pool
  contains only stocks alive in 2026) inflates every backtest here by an unmeasured amount.

---

## 4. What was tested and rejected

Kept here so nobody re-runs them. Each was measured on 3 dev windows with 6-draw ensembles.

**Selection:** ranking by momentum strength, by low volatility, by 52-week-high proximity,
by liquidity (a hidden large-cap tilt that cost 19 points), composite blends, dual-horizon
clubs (6-month AND 12-month), stricter (>10%) or looser (>−10%) club thresholds,
own-200-day-average as an *entry* filter, skipping the extreme top of the ranking.

**Risk:** 10/15/20% stop-losses, profit targets, trailing exits, full risk-off liquidation
when the gate closes (a churn machine: −30 points), NIFTY 200-day gate instead of 50-day
(drawdown doubled), India VIX percentile brake (redundant with realized volatility),
hard "no buying when VIX > 20" (blocks every recovery — halved two windows).

**Structure:** 6, 9, 15 slots (9 raised the ceiling but pushed the worst draw negative),
quarterly cadence, month-end evaluation, inverse-volatility sizing, dropping the
correlation cap (more luck, no more edge), post-stop rebuy freezes, exit hysteresis.

**Retired permanently:** the directional-change / "legs" family. Our own 1.38-million-entry
study found leg features correlate ≤0.07 with outcomes, and the published literature agrees
— the closest paper (Salman et al. 2025, 200 daily NYSE stocks) reports Sharpe −0.82 for
essentially our old rule. All positive directional-change evidence is intraday FX.

**Untestable, therefore excluded:** per-stock news sentiment. No free historical NSE
sentiment data exists, so it cannot be validated. The production LLM pipeline should log
its per-stock scores daily; revisit in 12 months with real history.

---

## 5. Honesty rules for anyone changing this algo

1. **Point-in-time or it's worthless.** `config/universe.txt` (141 hand-picked names) is
   hindsight-contaminated and inflated the old algo by ~65 points. Never quote numbers
   from it. Use `config/pool.txt` + the §2.1 filter.
2. **Never report a number without controls**: random-pick control, held benchmark, NIFTY.
3. **Judge by ensembles, never a single run.** Draw luck (±25 points over 2 years) is
   bigger than any rule effect found in ~60 configurations.
4. **Dev windows for iteration; the 2024–26 window is an exam, not a workbench.** Four
   different designs won dev windows and then inverted on the test window.
5. **Count your experiments.** A 72-config sweep once produced train→validate rank
   correlation of −0.18: the best training configs lost money out of sample.
6. **Costs always on.** Any rule that raises turnover must pay ₹27 per round trip.

---

## 6. Live execution playbook

These cannot be validated on daily bars — they come from the microstructure literature and
belong in the order layer, not the strategy:

1. **Trade in the last ~30 minutes of the session, never at 9:15.** Spreads are widest at
   the open, and ~92% of Indian equity gains historically accrue overnight.
2. Prefer limit orders near the last close for these purchases; market orders only when
   the fill matters more than the ~0.1% a limit saves.
3. Keep the cycle on the first trading day — purchases then land inside the turn-of-month
   window, which is statistically the strongest stretch of the Indian month.
4. Never place a trigger price at a round number (stop clusters get swept there).

---

## 7. Production wiring

| Piece | Where |
|---|---|
| Rules engine | `tradefish/v5.py` |
| Monthly cycle job | `tradefish/pipelines/v5_cycle.py` (1st of month, 15:20 IST) |
| Daily equity mark | `tradefish/pipelines/v5_mark.py` (15:45 IST, weekdays) |
| Broad pool | `config/pool.txt` (864 names) |
| Parameters | `config/settings.yaml` → `v5:` block, DB-overridable |
| Tables | `v5_equity`, `v5_universe`, plus shared `positions` / `paper_transactions` |
| UI | `/v5` — equity curve, holdings with club status, gate state, cycle history |

Positions carry `strategy='v5'` so the v5 book never mixes with the legacy weekly system.

---

## 8. What a 3–4 month paper trial can and cannot prove

3–4 cycles produce ~8–15 trades. Expected drift at 15%/yr is ~+4–5%; ordinary monthly
noise is ±6–8%. **The trial cannot demonstrate profitability — the noise is larger than
the signal.** Judge it on:

1. the machinery runs unattended (data, cycle, orders, logs, alerts)
2. realized slippage versus the modelled 0.53% — the most valuable output of the trial
3. gates and exits firing exactly when the rules say they should
4. whether you can watch a −10% month without intervening

Profitability needs 18–24 months. Anything shorter is a plumbing test.

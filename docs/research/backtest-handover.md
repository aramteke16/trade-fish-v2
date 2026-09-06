# trade-fish-v2 — Backtest & Algo Handover

Written 2026-09-05, end of a long research session. Audience: a fresh Claude session (or
human) picking up the strategy work. Everything here was measured, not assumed; numbers
cite the run that produced them. Read this before touching the algo.

---

## 1. What this project is

Aayush is building an automated NSE trading system on ₹30,000 paper capital (target:
real money if it proves itself, ~20%/yr aspiration). The live system (`tradefish/`)
runs in Docker: nightly news collection, DeepSeek LLM extraction, weekly basket entry,
5-minute barrier checks, dashboard on port 8000. Spec: `plan-v2.md`. Droplet deployment
is out of scope for now ("forget abt droplet, only focus on local").

The session summarized here turned into a full research program: build an honest
backtest, test every idea Aayush proposed, and separate real edge from illusion. The
findings below are the project's most valuable asset — several were expensive to learn.

---

## 2. State of play in one table

| Component | Verdict | Evidence |
|---|---|---|
| Universe selection (sectors + momentum, slow refresh, held) | **WORKS, ~15%/yr** | +37% to +46% held across every honest construction |
| Entry gate: NIFTY > 50-day average | **WORKS** | forward 21d stock return +3.11% above vs +1.67% below, t=3.2 |
| The trading layer (leg timing, targets, time exits, speed rank) | **NO EDGE** | ≈50th percentile vs random picks on every universe; 1.38M-trade study: all leg/momentum correlations ≤ 0.07 |
| Averaging down (idea.txt rule 4) | **HARMFUL** | −₹15,204 on trades where it fired; needs ₹43k cash on ₹30k account |
| Fixed profit targets (+5.3% etc.) | **HARMFUL** | cuts winners at day ~5; −1.05%/trade vs no cap |
| Weekly rotation (original plan-v2 design) | **DEAD** | fees alone ₹9,700 of ₹30k over 2.5y; -58% real run |
| Parameter tuning of the algo | **DEAD END** | 72-config sweep: train→validate correlation −0.18 |

---

## 3. Repo map (backtest-relevant)

- `backtest/engine.py` — original weekly-rotation engine (reproduces the historical
  ₹1,503.44 / 1604-trade run exactly; keep as regression anchor).
- `backtest/data.py` — yfinance bulk fetch with on-disk cache (`data/backtest_cache/`,
  universe-hash in cache key), `fetch_benchmark("^NSEI", ...)`, `as_of()` strict-<
  point-in-time slicing.
- `backtest/legs.py` — causal leg decomposition study (the intrinsic-time test).
- `backtest/noise.py`, `backtest/report.py`, `backtest/run.py` — noise gate, rollups, CLI.
- `backtest/diagnose.py` — weekly loss decomposition.
- `tradefish/strategy.py` — shared `pick_basket()` used by live and backtest.
- `tradefish/costs.py` — Indian delivery cost model (see §5).
- `config/universe.txt` — 141 hand-picked stocks. **CONTAMINATED for backtesting**
  (see §7). Fine for live use.
- `config/sectors.txt` — static sector file (5y evidence in comments), created 2026-09.
- `strategy-criteria.md` — decisions + evidence, older layer of this same knowledge.
- `data/backtest_output/*.csv` — all experiment outputs (index in §10).

The session's experiment scripts lived in the session scratchpad (ephemeral,
`/private/tmp/claude-501/.../scratchpad/`) and may be gone. Everything needed to
re-implement them is specified in §5–6; their outputs persist in `data/backtest_output/`.
If the scratchpad still exists, the key scripts are: `final_backtest.py` (six-rule
engine), `signal_core.py`/`signal_test.py` (universe machinery + runner), `everyday.py`
(1.38M-entry study), `tune.py` (sweep with validation), `reverse.py` (optimal-trade
autopsy).

---

## 4. The backtest framework — discipline rules

These rules exist because each one was violated once and produced a fake result:

1. **Point-in-time only.** Any feature at day *i* uses bars ≤ *i*. Entries fill at day
   *i+1*'s open. Verified by truncated-recompute audit: 48 comparisons, 0 mismatches.
2. **The universe must be constructible by a program from pre-window data.** If a human
   (or Claude) chooses constituents "by judgment," the test is void — see §7.
3. **Always run the two controls:** (a) hold the same universe passively, (b) random
   picks under identical rules (≥12 seeds; report the percentile the algo lands at).
   A strategy is only real if it beats BOTH.
4. **Deterministic tie-breaks.** Candidate sort must be `(key, symbol)`. Python set
   iteration order once swung a result from −22.8% to −8.0% between processes.
5. **Any tuning needs a train/validate split.** Jan24–Jun25 / Jul25–Aug26 was used;
   correlation of train rank to validation outcome was **−0.18** — assume any
   single-window optimum is noise until validated.
6. **Date-cluster all t-stats** (per-date cross-sectional means). 141 correlated stocks
   are not 141 observations; pooled t-stats once inflated to t=21 nonsense.
7. **Costs on every simulated fill** via `tradefish/costs.py`. Flat ₹15.5 DP fee makes
   round trips ~0.53% at ₹5,000 slots (0.85% at ₹2,475; 0.28% at ₹25,000). Fees killed
   more strategies here than bad signals did.
8. Survivorship caveat: all pools come from today's NSE listing — names delisted
   2024–26 are absent. Unsolved; state it in any writeup.

---

## 5. The algo under test ("the six rules", rule 4 removed)

Aayush's design, implemented faithfully and tested to exhaustion:

- **Leg decomposition (rule 1):** σ_week = std(daily returns, 60d) × √5. Causal walk:
  in an up-leg track the running max; a close ≤ max×(1−k·σ) confirms the swing high and
  flips mode down (mirror for lows). k=2.0 default (2.5 also used). Per-stock medians
  over completed legs (≥3 required): up-leg size (σ units), up-leg days, down-leg days.
- **Dynamic target (rule 2):** target% = max(5.3%, median_up_size × σ_today). 5.3% floor
  = 10× round-trip cost rule. Time limit = median_up_days × 2, frozen at entry.
- **Entry (rule 3):** stock in a down-leg whose age ≥ its median down-leg duration
  ("maturity ≥ 1"), AND NIFTY > 50-day average. Rank candidates by median_up_days
  ascending (fastest first), buy next open, 6 slots, budget = cash/free_slots.
- **Exit (rule 5):** first day high ≥ target → sell at target; else sell at close when
  the time limit hits. Nothing else — no stop, no universe-drop selling (verified: 25
  of 26 refresh-crossing positions were held to their own exit).
- **Refill (rule 6):** freed slot refilled same day from the current universe.

**Why it nets ~zero:** ~19 target hits at +25% vs ~51 time-outs at −7% per run. The
mature-dip filter buys weak drifters and structurally never owns runners. Diagnosis is
airtight — see the 1.38M study below.

---

## 6. Universe construction — what was tried

All refreshes pick stocks mechanically: top-141 by trailing 6-month return within the
allowed sectors, among liquid names (traded ≥95% of last 250 sessions, close ≥ ₹30,
median daily traded value ≥ ₹1cr), data through the refresh date only. Pool source:
NSE EQUITY_L list, listed before 2021 → 864 liquid names cached 2019–2026.

Dated news sources used for sector lists (the only honest way found):
- Business Today 2023-12-22 (banking/infra/power/autos/pharma).
- Axis Bank "Investment Perspectives" quarterly PDFs (Jul-Sep-24, Oct-Dec-24,
  Jul-Sep-25, Oct-Dec-25, Jul-Sep-26) — one consistent publisher, explicit
  overweight lists, URLs in `dated_news_universes.csv` sources column. Where a
  quarter's edition is missing, carry the last available (Aayush's rule).

Fixed sector→Yahoo mapping (do not freelance): banking/BFSI/NBFC→Financial Services;
infra/capital goods/manufacturing/defence/rail→Industrials; power→Utilities;
auto/consumption/discretionary→Consumer Cyclical; FMCG/staples→Consumer Defensive;
pharma/hospitals→Healthcare; IT/tech→Technology; telecom→Communication Services;
metals/chemicals/cement→Basic Materials; oil&gas/energy→Energy; realty→Real Estate.

---

## 7. THE contamination lesson (most
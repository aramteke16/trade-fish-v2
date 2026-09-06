# trade-fish-v2 — Backtest & Algorithm Handoff

Written 2026-09-05 for a fresh Claude session. Read this before touching the algo.
It records what the system is, how the backtest works, and — most importantly — what
has already been proven dead so you do not re-run it.

---

## 0. What we are trying to do

Grow ₹30,000 of paper capital automatically on NSE stocks, ~20%/year target, no daily
human input. The real project underneath: find out whether the trading rules have a true
edge or just look like one. The backtest framework exists to answer that honestly
(point-in-time discipline + random/benchmark controls).

**The one-line conclusion after ~30 experiments:** the *universe selection* (which stocks
to own) earns ~15%/yr and survives every honest test. The *trading layer* (leg timing,
targets, exits) adds zero — it lands at the ~50th percentile of random picks on every
clean universe, every refresh cadence, and every parameter setting. See §6.

---

## 1. The algorithm (rules as currently defined)

The strategy the user designed, in their numbering:

- **Rule 0 — universe.** Every N months pick "emerging sectors" (from dated news OR
  trailing 6-month sector momentum), then take the top ~141 liquid stocks in those
  sectors by trailing 6-month price momentum. Point-in-time: only data ≤ refresh date.
- **Rule 1 — legs.** Per stock, causal directional-change decomposition. A swing is
  confirmed only after price reverses `THRESH × sigma_week` off the extreme
  (THRESH=2.0). From completed legs compute median up-leg SIZE (in σ) and DURATION (days).
- **Rule 2 — dynamic target & hold.** target = max(5.3%, median_up_leg_size × sigma_week);
  time limit = median_up_leg_days × MULT (MULT=2.0). Both frozen at entry. 5.3% = 10× the
  round-trip cost floor.
- **Rule 3 — entry.** Buy only when the stock is in a *down-leg* that has lasted ≥ its own
  median down-leg length (maturity ≥ 1.0), AND NIFTY > its 50-day average (sentiment gate).
- **Rule 4 — averaging down.** REMOVED by user. Made rupee returns worse (buys more of
  losers, needs cash it doesn't have). Do not reintroduce without strong new evidence.
- **Rule 5 — exit.** Sell only when high ≥ target OR day-count ≥ time limit. No stop-loss.
- **Rule 6 — slots.** Always hold exactly 6 names. On any free slot, refill same day from
  the *current* universe, ranked fastest-predicted-to-target first (= smallest median
  up-leg days). Deterministic tie-break: (predicted_days, symbol).

Sizing: 6 slots, ~₹5,000 each, equal weight. Fees: Indian delivery model, ~0.53%
round trip at ₹5k (flat ₹15.5 DP fee dominates small slots — this is why >6 names on ₹30k
cannot work, and why turnover is the enemy; see §7).

**Holdings survive universe refresh.** A stock dropped from the universe is NOT force-sold;
it runs to its own target/time exit. Verified in code and trade logs.

---

## 2. Code layout

Production system (live paper trading, separate from backtest):
- `tradefish/` — strategy.py (shared `pick_basket`), costs.py, metrics.py, broker/paper.py,
  log.py, db.py, config.py. Universe in `config/universe.txt`.
- Price feed: yfinance `.NS` suffix (openchart's NSE API is broken — returns same list for
  any query).

Backtest framework:
- `backtest/data.py` — `fetch_all` (disk cache, universe-hash in key), `fetch_benchmark`
  (`^NSEI`), `as_of` (strict `<`), `week_bars`.
- `backtest/legs.py` — the causal leg decomposition (canonical implementation of Rule 1).
- `backtest/engine.py` — unified week loop (older weekly system; regression-verified).
- `backtest/diagnose.py`, `noise.py`, `report.py`, `run.py` — loss decomposition, noise
  gate, rollups, CLI.

**All the recent research (§6) lives in the SCRATCHPAD, not the repo.** Path:
`/private/tmp/claude-501/-Users-aayushramteke-workspace-trade-fish-v2/<session>/scratchpad/`.
Key scripts there: `signal_core.py`/`signal_test.py` (shared harness), `everyday.py`
(1.4M-trade correlation study), `news_proper.py` (dated-news universe), `additive.py`,
`tune.py` (train/validate sweep), `reverse.py` (optimal-trade reverse-engineering).
Outputs (CSVs) are in `data/backtest_output/`.

**Universe pool for honest tests:** 864 liquid NSE stocks (listed pre-2021, ≥95% of 2023
sessions traded, close ≥ ₹30, median daily value ≥ ₹1cr). Cached as `pool2023_*.pkl` in
scratchpad. Sector labels (Yahoo) in `sector_labels.pkl`. Full history 2019–2026 cached
via `fetch_all`.

---

## 3. How the backtest works (and its honesty rules)

1. **Point-in-time everything.** Any value used on day D is computed only from bars with
   index < D (leg stats, momentum, universe membership, sigma). Entries fill at next day's
   OPEN, never day-D close. Verified: recompute-on-truncated-history matched full-run
   values 48/48 times.
2. **Universe must be built before the test window.** Filtering stocks on data that
   includes the test period is the #1 trap and it silently turns any strategy positive.
3. **Controls are mandatory. Never report a strategy number alone.** Always show:
   - **Random control**: same rules, but pick randomly among eligible stocks (12–30 seeds).
     If the strategy isn't clearly above the random distribution, it has no edge.
   - **Held benchmark**: same universe, equal-weight, no trading. This is the bar to beat.
   - **Train/validate split** when tuning: tune on early data, check on held-out later data.
4. **Determinism.** Equal-speed candidates MUST tie-break by symbol. A set-iteration
   tie-break made the same config swing ±15 points between runs (real bug we hit).
5. **Costs always on.** 0.53% round trip. Zero-fee runs are for diagnosis only.
6. **Date-clustered t-stats.** 141 correlated stocks on one day ≠ 141 independent samples.
   Cluster by date (per-date cross-sectional mean, then t over dates).

---

## 4. THE CONTAMINATION STORY (read this or you will be fooled)

`config/universe.txt` is 141 stocks the assistant hand-picked in 2026 using knowledge of
which sectors/stocks won 2024–2026. Any backtest on it prints beautiful numbers.

Proof it's poison, isolated cleanly:
| Universe (same sectors, same algo, same rules) | Algo | Held |
|---|---|---|
| Stocks picked with 2026 hindsight (universe.txt) | **+70.9%** | +44.2% |
| Stocks picked with only ≤2023 data | **+5.4%** | +47.2% |

The *held* return barely moves (~45% either way) — so hindsight did NOT inflate the
universe. It inflated the ALGO: a buy-the-dip algo fed stocks that were destined to win is
fed stocks whose every dip was destined to recover. That fake edge is worth ~65 points and
is entirely an artifact.

**Rule for the new session: never quote a number from `universe.txt`. Only trust numbers
from a universe built point-in-time (pre-window data only).**

---

## 5. Verified results table (all point-in-time, honest)

Window Jan-2024 → Aug-2026, ₹30k, 6 slots, algo = rules above (2.0σ, MULT 2.0).

| Universe construction | Algo | Held (no trading) | Notes |
|---|---|---|---|
| News sectors, replaced every 6mo | −22.8% | +37.2% | analyst switches sell winners late |
| News sectors, ADDITIVE every 6mo | −5.8% | +45.6% | user's "add don't replace" idea — best held |
| News sectors, YEARLY refresh | +6.8% | +44.8% | algo = 50th pct of random |
| Dec-2023 news, never refreshed | −17.4% | +53.5% | one lucky durable sector set |
| Static 5yr sectors, dynamic stocks | +7.7% | +36.1% | algo = 55th pct of random |
| Price-momentum sectors, monthly | −15.2% | +45.0% | |

Every row: held ≈ +37–54%, algo ≈ 0 ± 15%, random control sits right where the algo does.

---

## 6. WHAT IS PROVEN DEAD (do not re-test without a genuinely new idea)

1. **Leg-day timing carries no information.** 1,384,391 simulated entries (every stock,
   every day, 2020–2026): Spearman correlation of every leg feature (mode, age, maturity,
   depth, fold) vs (hit target? / days-to-target / return) is ≤ 0.07. A tradeable signal
   is ~0.15–0.30. Buying on ANY random day hits the exit-rule profit 49% in ~44 days;
   the "perfect" leg state does the same. `everyday.py` / `everyday_entries.csv`.
2. **The maturity≥1.0 entry rule selects the WORST pocket.** Perfect buys are 30% "mature",
   ordinary days 16% — 2× enrichment, but our rule *rejects 70% of perfect buys*. Mature
   dips returned +7.5% vs +10.6% for buying already-extended strength.
3. **Fixed/dynamic profit targets, leg-clock time exits — all EV-zero.** Target/stop pairs
   are break-even vs random prices by construction. Exits only shape trades, they don't
   create profit. Confirmed empirically many times.
4. **Parameter tuning does not transfer.** 72-config sweep, train Jan24–Jun25 / validate
   Jul25–Aug26: correlation(train rank, validate result) = −0.18. Top-10 train configs
   (avg +58% train) validated at −9.7%. Any "best params" are fit to noise. `tune.py`.
5. **Faster "emerging sector" detection hurts.** Acceleration/1m/3m sector signals all did
   worse than plain 6-month trailing; being early = sitting through chop. News-driven
   sector switching underperformed never-switching.
6. **Weekly/high-turnover trading cannot work on ₹30k.** 377 trades → −7%, 69 → +43%,
   0 → +45%. India cost stack (STT, ±price bands, F&O ban, ₹15.5 DP fee) punishes turnover.

---

## 7. WHAT IS PROVEN ALIVE (build on these)

1. **Universe selection is the whole edge.** Emerging sectors (6–12mo momentum) + hold.
   ~+45% over 2.5y / ~15%/yr, no hindsight, survives random & benchmark controls.
2. **The "add, don't replace" universe (user's idea) is best.** Keeps working sectors
   available instead of force-rotating out of them. Held +45.6%, shallowest drawdown.
3. **NIFTY 50-day sentiment gate works.** Locally: avg stock +21d return +3.11% when NIFTY
   > 50dma vs +1.67% below, t=3.2. KEEP THIS. (But NOT the 200-day filter — it inverts:
   below-200dma had HIGHER forward returns. Deep bears are buying zones in India.)
4. **The "smile" (short-term reversal + long-term momentum).** 6-month momentum deciles:
   decile 1 (crashed) +14.5%, decile 10 (strong) +15.1%, middle deciles +6%. Money is at
   BOTH extremes; our system fished the dead middle. This is the #1 untested lead.
5. **India factor research agrees with us:** momentum has highest IC but dies on turnover
   costs; LOW-VOLATILITY and QUALITY are the factors that survive in India (slow, low
   rebalance). Net Alpha = Gross Alpha − Turnover×Cost. Untested locally = lead #2.

---

## 8. Recommended next moves (in priority order)

1. **Test the smile as a portfolio.** Hold decile-1 (deep 6-mo losers) + decile-10 (strong
   6-mo winners), skip the middle, long holds, monthly-or-slower rebalance. Random +
   benchmark controls. This is the strongest data-backed lead we have.
2. **Test low-volatility / quality tilt** inside the universe (rank by trailing vol, hold
   the calm half). India research's #1 surviving factor; never tested on our data.
3. **Turnover budget as a hard constraint.** At ₹30k, ~12–20 trades/year is the ceiling the
   cost math allows. Design to that, not to signal frequency.
4. **If keeping the leg algo at all:** the ONLY change §6.2 supports is dropping the
   maturity threshold (buy any dip, not just "mature" ones) — but expect it to still not
   beat held. Don't spend long here.
5. **Reality check before real money:** survivorship bias is still unmeasured (all 864
   stocks are alive in 2026; delisted losers are absent). Every held number above is
   somewhat flattered by this. Size expectations down.

---

## 9. Working style (user preferences — honor these)

- Verdict first, plain language, small tables. No walls of analysis unless asked.
- Show the number they asked for immediately; caveats after.
- Attack every good-looking result with controls before believing it. The user explicitly
  values honesty over impressive numbers and has caught overclaims — earn that trust.
- Propose, get approval, then build. Ask before large or destructive actions.
- Scratchpad for all throwaway analysis; never touch production flow when only testing.
- Caveman terse mode is active this session (user's global setting).

# Weekly Cross-Sectional Alpha System — Implementation Spec

**Market:** Indian equities (NSE)
**Horizon:** weekly (enter Monday open, exit by Friday close)
**Core idea:** a cross-sectional ranker that scores a liquid universe every Monday, holds a top-k basket for one week, and shapes the payoff with asymmetric barrier exits.

This document is a build spec. It is deliberately written so that each phase is a **kill-gate**: if the gate fails, stop and diagnose rather than proceeding. The purpose of the system is first to *measure honestly* what edge exists, and only second to trade it.

---

## 0. Non-negotiable principles

These override convenience at every point in the build.

1. **Point-in-time contract.** At the Monday 09:00 decision moment, the only data that exists is: price/volume bars through the prior Friday close, and text items with a verified publish timestamp <= Monday 09:00. Any violation invalidates every downstream number.
2. **Label barriers == execution barriers.** The model is trained to predict the exact payoff structure that is actually executed. If these drift apart, the edge evaporates.
3. **The LLM scores information, never price.** The LLM describes documents (catalyst, surprise, magnitude). It never emits a directional call. This is the firewall against the LLM's contaminated price memory leaking into the signal.
4. **Costs are modeled from day one**, not added later. A gross edge that dies after costs is not an edge.
5. **Every result is net of costs, out-of-sample, and purged.** Numbers that are not all three are not reported.
6. **Log every experiment** — parameters tried, variants rejected, and why. Untracked repeated testing is how multiple-comparisons overfitting enters through the back door.

---

## 1. System architecture

```
price/vol          Kronos TSFM         point-in-time text
    |                   |                       |
[microstructure]  [forecast feats]     [LLM extractor -> JSON]
    |                   |                       |
    +-------------------+-----------------------+
                        v
              feature matrix X_t  (N stocks x F features)
                        v
              LightGBM combiner -> two heads:
                 P(win) (classifier)  +  rank score (LambdaRank)
                        v
              rank -> top-k basket
                        v
        conviction x inverse-vol weighting (+ caps)
                        v
        triple-barrier exits + regime gate    <- shapes the skew
                        v
            weekly P&L -> IC/decay log -> retrain loop
```

### Execution clock (one cycle)

| When | What happens |
|---|---|
| Fri 15:30 (prior week) | Market closes. All price/vol features computable through this bar and no further. |
| Weekend -> Mon 09:00 | Earnings, exchange announcements, news arrive, each timestamped. |
| Mon 09:00–09:15 | Pipeline runs: build `X_t`, score, rank, size. **Decision moment.** |
| Mon 09:15 | Enter basket (use first 15–30 min VWAP, not the opening auction tick). |
| Mon–Fri intraday | Monitor daily bars for barrier hits. Cut losers, let winners run. |
| Fri 15:15 | Exit remaining positions at time barrier. Book P&L. |
| Weekend | Log results, update IC/decay, retrain on cadence. |

---

## 2. Baseline parameters

Starting values. Barriers must be **derived from realized volatility**, not tuned for a pretty backtest (see §9).

| Parameter | Value | Notes |
|---|---|---|
| Universe size N | ~150 | Liquid NSE names (F&O list / Nifty 200 filtered by ADV) |
| Feature count F | ~40 | Across three streams |
| Hold period | 5 trading days | Mon open -> Fri close |
| Upper barrier | +6% | Take profit |
| Lower barrier | -3% | Stop loss |
| Ratio | 2:1 | The engine of positive skew |
| Basket size k | ~12 | Top-k by rank score |
| Rolling train window | ~52 weeks | |
| Refit cadence | every 4 weeks | |
| Embargo | 1 week | Between training labels and traded week |

**Why the 2:1 ratio matters:** at a 40% hit rate, `0.40 x 6 - 0.60 x 3 = +0.6%` per trade before costs. You can be wrong more often than right and still be positive, purely from payoff asymmetry. This is the mechanism, not a tuning knob.

---

## 3. Data layer

Already settled; listed for the implementing session's reference.

- **Price/volume:** `openchart` (NSE + NFO, EOD and intraday, MIT licensed) as primary; broker API (Kite Connect / SmartAPI / Upstox / Fyers / Dhan) for live data and execution.

Store raw data immutably. All transformations downstream and reproducible.

### 3.1 Text acquisition — the critical path

There are **two distinct problems** here and conflating them is a common failure: *live* news collection is easy; *historical* news with trustworthy timestamps is hard. Phase 2b depends entirely on the second.

#### Tier 1 — Exchange filings (primary source)

NSE/BSE corporate announcements are the backbone, for one dominant reason: **the exchange records the disclosure time as an official field.** No ambiguity between publish time and scrape time. This is the only source trustworthy enough to anchor a backtest.

| Source | Install | Notes |
|---|---|---|
| `NseIndiaApi` | `pip install nse` | `nse.announcements()` returns filings with PDF attachment links; `nse.download_document()` fetches them. `nse.actions()` for corporate actions. |
| `BseIndiaApi` | `pip install bse` | Same author. Scrip-code lookup, announcements, corporate actions. Ships sample JSON responses in `src/samples` for parser development. |

Pull **both and dedupe** — BSE's announcement feed is often richer than NSE's.

Coverage maps almost one-for-one onto the `catalyst` taxonomy: results, board meetings, dividends, allotments, order wins, management changes, regulatory notices.

**Scraping etiquette (from the library author, follow it):** run large pulls after market hours (late evening), add 0.5–1s sleep between requests, and persist everything rather than re-downloading.

#### Tier 2 — Commercial APIs (optional shortcut)

- **stockinsights.ai** — real-time tagged BSE/NSE filing feed with summaries, 26 category tags, sentiment; filterable by ticker, date range, category, sector. **Caution:** it ships pre-computed sentiment, which partly duplicates the Stream 3 extractor. Acceptable as fallback or as a benchmark to beat; do **not** let a third party's sentiment model silently become the signal — it destroys auditability.
- **Apify NSE/BSE announcement scrapers** — live filings with PDF URLs, price-sensitive flags, watch mode. Pay-per-use; removes scraper maintenance.

#### Tier 3 — News media (supplementary only, treat as unreliable)

Moneycontrol / Economic Times / Livemint / Business Standard RSS; GDELT (free, timestamped, weak Indian coverage); NewsAPI / GNews (limited free tiers, shallow archives).

Three structural problems: timestamps are often crawl/index time rather than true publication; articles are silently edited post-publication; and media **lags the filing** — by the time it is written up, the exchange disclosure has already moved the price. Media is a stale echo of Tier 1.

#### Historical backfill strategy

Live collection is trivial; deep history is the bottleneck. NSE's announcement endpoint effectively serves recent data only.

**Do both of these in parallel, starting immediately:**

1. **Start the daily collector now**, before any other Phase 0 work. Every day of delay is training data permanently lost. A cron job pulling NSE + BSE announcements and archiving with exchange disclosure timestamps.
2. **Backfill from BSE's archive** — BSE historical announcement pages reach further back than NSE's and are more scrapeable. Slow and rate-limited, but free.

Note that **Phase 2a (numeric PEAD) requires no news text at all**, so gated progress continues while the text corpus accumulates.

#### Storage schema — three timestamps, always

Every text item stores **three separate timestamps**:

| Field | Meaning | Trust |
|---|---|---|
| `exchange_disclosure_time` | From the filing itself | **Source of truth — point-in-time filter keys off this, always** |
| `fetched_at` | When the collector pulled it | Diagnostic |
| `published_at` | Media-reported publish time | Unreliable — never use for filtering |

Also store: `ticker`, `source`, `raw_text` / `pdf_path`, `doc_type`, `content_hash`.

**Audit procedure (Phase 2b gate):** manually sample ~30 items and verify `exchange_disclosure_time < decision_time`. Look specifically for rows where `fetched_at` and `exchange_disclosure_time` diverge oddly — that pattern is the fingerprint of the silent look-ahead bias listed as risk #1.

#### Earnings-call transcripts

Easy to overlook, potentially the highest-value text source. Filed on exchanges as PDFs, typically a few days after results. Far richer than a numeric surprise figure — management's actual language on guidance and margins is where an LLM could plausibly beat a naive beat/miss number. **This is the strongest form of the Phase 2b hypothesis.** Their delayed arrival suits a 1–4 week drift trade rather than a same-week reaction, which fits the weekly horizon.

---

## 4. Feature streams

### Stream 1 — price/microstructure (~18 features)

Momentum (1w / 4w / 12w / 26w), realized volatility, vol-of-vol, z-distance to 20/50/200 DMA, turnover, Amihud illiquidity, delivery %, recent-return skew, beta to Nifty.

**Mandatory transform:** standardize every feature **cross-sectionally within each week's universe** (z-score or rank). This converts absolute statements ("+9% momentum") into relative ones ("85th percentile among peers this week"), stripping market beta. Only the relative version is tradable market-neutrally.

### Stream 2 — Kronos forecast features (~5 features)

Feed each name's last ~250 daily OHLCV bars to Kronos (finance-specific time-series foundation model, MIT licensed, small/base sizes run on modest GPU). Extract from the forecast distribution: expected 5-day return, forecast volatility, quantile spread, P(up).

Batch inference across the universe. These are **features, not decisions** — Kronos has strong benchmark numbers but near-zero live track record.

### Stream 3 — LLM extractor (~12 features)

For each stock, bundle text items timestamped <= decision moment. LLM emits structured JSON per stock:

```json
{
  "catalyst": "earnings|guidance|order_win|mgmt_change|regulatory|rating|none",
  "sentiment": 0.0,
  "surprise": 0.0,
  "guidance_delta": 0.0,
  "magnitude": 0.0,
  "novelty": 0.0,
  "uncertainty": 0.0,
  "persistence": 0,
  "evidence": "short quote or paraphrase supporting the scores"
}
```

Encode to numerics: one-hot the catalyst, scalars for the rest. Low temperature, fixed rubric, few-shot calibration examples, `evidence` field retained for audit.

**Most stocks have no news in a given week** — their Stream 3 features are neutral/null. That is a valid, informative state; do not impute it away.

### Stream 3a — LLM provider abstraction

The extractor must run behind a **provider interface**, not a hardcoded SDK call. Two providers supported: **DeepSeek (default)** and **Claude**. Selection is a single environment variable flip, with no other code change.

```
LLM_PROVIDER=deepseek     # default; alternatives: anthropic
DEEPSEEK_API_KEY=...
ANTHROPIC_API_KEY=...
LLM_MODEL=                # optional per-provider model override
LLM_TEMPERATURE=0.0
LLM_MAX_RETRIES=3
```

**Interface contract.** One function, provider-agnostic:

```python
extract(text_bundle: str, ticker: str, as_of: datetime) -> ExtractionResult
```

Returns the validated Stream 3 JSON schema plus metadata: `provider`, `model`, `prompt_version`, `tokens_used`, `latency_ms`. Implementations live behind a registry (`PROVIDERS = {"deepseek": ..., "anthropic": ...}`) resolved at runtime from `LLM_PROVIDER`. Adding a third provider must require only a new adapter, never a change to calling code.

**Requirements for both adapters:**

1. **Identical prompt and rubric.** The same prompt template, few-shot calibration examples, and JSON schema go to both providers. Any prompt divergence makes cross-provider results incomparable.
2. **Strict schema validation.** Parse into a Pydantic model; on validation failure, retry with the parse error appended, then fall back to a neutral/null extraction rather than crashing the weekly run. A malformed extraction must never silently become a zero-valued feature that looks like real data — mark it `extraction_failed=True` and treat as missing (NaN).
3. **Temperature 0** (or provider minimum) for reproducibility.
4. **Persistent cache keyed on `hash(prompt_version + model + text_bundle)`.** Extraction is the dominant cost in the whole pipeline; re-running a backtest must not re-pay for it. Cache to disk/SQLite, never in-memory only.
5. **Record `provider` and `model` on every stored extraction row.** Feature values are only comparable within the same provider/model/prompt_version triple.

**Why DeepSeek as default:** bulk historical extraction across (universe x years of weeks) is the single largest cost line in the build, and DeepSeek's pricing makes full-history backfill affordable. Claude is the higher-quality comparison arm.

**Required experiment (Phase 2b).** Do not assume the providers are interchangeable. Run both on an identical sample (~200 stock-weeks with real catalysts) and measure:
- **Agreement:** correlation of `surprise` / `guidance_delta` / `sentiment` scores between providers.
- **Schema reliability:** parse-failure rate per provider.
- **Downstream IC:** incremental IC contributed by each provider's features.

If agreement is high, run DeepSeek for everything and treat the choice as settled. If they diverge materially, that divergence is itself a finding — extraction is then model-sensitive, which weakens confidence in the signal's robustness and must be recorded as a risk. **Log the outcome either way; do not skip this comparison because DeepSeek "seems fine."**

**Cost control for backfill:** batch requests, run extraction only for stock-weeks that actually have text (most do not), and checkpoint progress so an interrupted backfill resumes rather than restarts.

### Assembly

Stack into `X_t` (N x F). Add meta-columns: `is_earnings_week`, `days_since_earnings`, `sector_id`. **Leave missing values as NaN** — LightGBM handles missingness natively, and imputation risks introducing look-ahead.

---

## 5. Labels — triple barrier

For each stock at each week's entry, set three barriers: upper (+6%), lower (-3%), and time (Friday close). The label is **which barrier is hit first**, evaluated on daily bars (check daily low against the stop, daily high against the take-profit).

- **Primary label:** win / loss / neutral -> trains the classifier head -> `P(win)`.
- **Secondary label:** cross-sectional rank of realized forward return -> trains the ranker head.

This label choice is the reason the model and the execution agree: the model learns the exact asymmetric payoff that will actually be taken.

---

## 6. The combiner — LightGBM, two heads

- **Head A (classifier):** target = triple-barrier outcome. Output = calibrated `P(win)`. Used for **sizing**.
- **Head B (ranker):** LambdaRank objective, target = cross-sectional forward-return rank. Output = rank score. Used for **selection**.

Keep selection and sizing separate (cleaner than blending into a single score, though `s_i = a*P(win) + (1-a)*rank` is an acceptable alternative).

Why GBM rather than a neural net or the LLM: the data is small and tabular (weekly x a few years = hundreds of rows per name), GBM is robust in low signal-to-noise regimes, handles NaN natively, and gives SHAP for interpretability. The combiner's real job is learning **conditional weighting** — e.g. "in an earnings week trust the LLM surprise feature; otherwise lean on momentum and Kronos." That interaction structure is where the value is.

### Training discipline (mandatory)

- **Purged, embargoed, walk-forward CV.** To predict week `t`, train only on weeks whose barrier outcomes fully resolved before `t` minus the embargo. No training label's 5-day window may overlap the predicted week.
- Rolling refit every ~4 weeks.
- Ensemble across seeds / feature subsets to reduce variance.

Skipping the purge produces a beautiful backtest that dies immediately in live trading.

---

## 7. Portfolio construction

Rank all N, take top-k. Optionally short bottom-k via futures (long-short version is also the primary defense against the strategy being disguised beta).

**Weighting:** `w_i ∝ P(win)_i x (1 / vol_i)`, then clip to caps and renormalize.

**Caps:** max weight per name, max exposure per sector, max position as % of ADV.

Conviction x inverse-vol tilts toward high-signal, low-volatility names — improving skew before the exits even engage.

---

## 8. Risk overlay — where the skew is manufactured

The combiner picks *what to hold*; this stage shapes *the payoff*. Deliberately separate concerns.

- **Per-name triple-barrier exits, intra-week, on daily bars.** Daily low pierces `entry x 0.97` -> cut immediately. Daily high tags `entry x 1.06` -> take profit or switch to trailing stop. Still open Friday -> exit at time barrier. Uses the **same barriers the labels were built on**.
- **Portfolio circuit breaker.** If the basket draws down past a weekly threshold mid-week, flatten everything. This is the rule that prevents one bad week from consuming ten good ones.
- **Regime gate**, evaluated **before entry**, multiplies total gross exposure. Inputs: India VIX percentile, market breadth, index trend, Kronos aggregate volatility forecast. Benign -> full gross. Hostile -> scale down or stand aside.

---

## 9. Setting the barriers honestly

Do **not** backtest 50 barrier combinations and pick the best performer — that selects the ratio that best fit past noise.

Derive them from data structure instead:
- Lower barrier ≈ 1 sigma of typical weekly volatility for the universe (so normal noise does not stop you out).
- Upper barrier from how far winning names empirically travel within a week.

Then lock them, and keep labels and execution synchronized to the locked values.

---

## 10. Build phases (kill-gates)

Ordered so the cheapest build is the one most likely to prove the idea dead.

### Phase 0 — Truth harness

**Do this first, before anything else in Phase 0:** stand up the daily NSE/BSE announcement collector (§3.1) with the three-timestamp schema and let it run continuously from day one. It accumulates training data in the background while the rest of the build proceeds, and every day it is not running is data permanently lost.

Then build, before any signal work: cost model, triple-barrier labeler, purged/embargoed walk-forward splitter, metrics module (IC, hit rate, skew, net return, max drawdown), and the LLM provider abstraction (§Stream 3a) with its extraction cache.

**Cost model (Indian cash equity / delivery), verify against a real contract note:**

| Component | Rate |
|---|---|
| Brokerage | 0 on delivery at discount brokers (cap ~Rs 20/order if applicable) |
| STT | 0.1% buy + 0.1% sell |
| Exchange transaction | ~0.00297% both sides |
| SEBI charges | ~Rs 10 per crore both sides |
| Stamp duty | 0.015% buy side only |
| GST | 18% on (brokerage + exchange + SEBI) |
| DP charge | ~Rs 15.5 flat per scrip on sell |

Round trip ≈ **0.22%** on delivery. This is the number the edge must clear.

> **GATE (mandatory): the noise test.** Run the entire pipeline on pure random noise features. It **must** report zero edge. If random data yields a profitable backtest, the harness is lying and every subsequent number is worthless. Do this first.

### Phase 1 — Price-only baseline
No LLM, no Kronos. Universe + Stream 1 features + LightGBM ranker + top-k + barrier exits.

Record dumb benchmarks: buy-and-hold Nifty, equal-weight top-momentum basket.

> **GATE:** positive net IC on purged out-of-sample data, **and** the model beats the dumb benchmarks. If a simple momentum rule matches the GBM, the GBM is decoration.

### Phase 2 — Earnings-surprise engine (the beachhead)

**2a — numeric PEAD only.** Earnings dates + reported vs. expected -> standardized surprise. Does drift exist in this universe, net of costs? No LLM yet.

**2b — add the LLM extractor.** The decisive question: does the LLM's `surprise` / `guidance_delta` add **incremental IC above the numeric surprise from 2a**? If numeric surprise already captures it, the LLM is expensive decoration — cut it.

**Timestamp audit:** manually sample ~30 text items and verify publish time precedes decision time.

> **GATE:** 2a shows drift net of costs; 2b adds measurable incremental IC.

This is the highest-information gate in the whole build — it resolves the biggest open question (does LLM-read Indian filing text carry alpha?), which is unpublished either way.

### Phase 3 — Integration
Add Kronos features, regime gate, conviction x inverse-vol sizing, sector caps. Test each addition as an **ablation**: does removing it hurt? Anything that does not earn its place gets cut.

> **GATE:** full stack beats Phase 1 baseline net of costs, and every component justifies inclusion.

### Phase 4 — Honest out-of-sample
Run once on a hold-out period quarantined since Phase 0 (ideally the most recent 6–12 months). **No tuning after seeing it** — tuning burns the hold-out and you no longer have an out-of-sample estimate.

> **GATE:** results roughly match walk-forward estimates. A large gap means upstream overfitting — go back, do not proceed.

### Phase 5 — Paper trading
Live data, simulated fills, real timing. Catches what backtests structurally cannot: late data, illiquid fills, job failures, symbol changes, corporate actions.

> **GATE:** live IC within shouting distance of backtest IC. Operations run unattended for 12 consecutive weeks.

### Phase 6 — Small real capital
Start at an amount where total loss is genuinely acceptable. Pre-commit both a scaling rule (e.g. "+25% size after 8 weeks of live results matching expectation") and a **kill rule** (drawdown at which you stop) — both decided while calm, before starting.

---

## 11. Monitoring loop

Log weekly: predictions (`P(win)`, rank), realized barrier hits, basket return **gross and net**, realized skew, hit rate, cost drag.

Compute **rolling IC** (Spearman between predicted and realized forward-return ranks), overall and per feature. When a feature's IC decays toward zero, retire it. Refit GBM on cadence; periodically re-run factor generation to propose replacements.

**Calibration note:** realistic average cross-sectional IC for equity signals is roughly **0.03–0.08** over hundreds of weeks. Any single week's IC is noise. A backtest showing sustained IC far above this band is evidence of a bug or leakage, not a discovery.

---

## 12. Known risks

1. **Silent look-ahead in the text pipeline.** One mislabeled timestamp (indexed time recorded as publish time) inflates results invisibly. Highest-priority audit target.
2. **Regime dependence.** Indian equities have been in a broadly friendly regime for years; a long-only weekly basket can look like alpha while actually being beta. Mitigations: long-short variant, regime gate. No backtest on recent NSE data can fully stress a true bear market.
3. **Alpha decay.** Indian anomalies including PEAD show evidence of weakening over time and are cost- and liquidity-sensitive. The monitoring loop exists to detect decay before it bleeds capital.
4. **Costs.** ~0.22% round trip means a gross edge must be several times larger than typical realistic signals to net a large weekly number. This is why the horizon is weekly rather than intraday.
5. **Overfitting through repeated testing.** Every untracked variant tried inflates the chance a spurious result looks real. Mitigation: the experiment log (§0.6).
6. **LLM provider/model sensitivity.** If DeepSeek and Claude produce materially different extractions from identical text, the signal depends on an arbitrary vendor choice rather than on the information itself — a robustness problem, not a tuning opportunity. Provider and model version are pinned and recorded per extraction; a provider or model change invalidates comparability and requires re-extraction of the affected window. Measured in the Phase 2b comparison (§Stream 3a).

---

## 13. Evidence base

| Component | Backing | Strength |
|---|---|---|
| Cross-sectional ML ranker; momentum/liquidity/vol features; trees best | Gu, Kelly & Xiu (2020), *Review of Financial Studies* | Strong (mostly US data) |
| Triple-barrier labels, purged CV, meta-labeling | Lopez de Prado, *Advances in Financial Machine Learning* (2018) | Strong for **method correctness**; not a profit claim |
| PEAD in India | Multiple NSE studies (2002–2017 significant; 2014–2018 weaker/contrarian) | Moderate, mixed, decaying, cost-sensitive |
| LLM text -> return predictability | Lopez-Lira & Tang (2023); LLMFactor (2024); LLM-embedding cross-sectional work | Contested; no clean Indian weekly-horizon result |
| LLM look-ahead contamination (motivates the "score information, not price" rule) | Look-Ahead-Bench; TradeTrap; FINSABER | Strong — this is why the firewall exists |
| Kronos financial TSFM | AAAI 2026; pretrained on ~12B K-lines from 45 exchanges | Strong benchmarks, near-zero live track record |
| Volatility-managed exposure | Moreira & Muir (2017), *Journal of Finance* | Moderate |
| Inverse-vol / low-vol tilt | Frazzini & Pedersen (2014), betting-against-beta | Moderate |

**Honest status:** the components are individually grounded (one pillar strongly, the methodology solidly, the anchor anomaly moderately with real Indian caveats, the LLM layer on contested ground). The *assembly* for an India-weekly horizon is unproven and is exactly what this build is designed to test.

---

## 14. Expectation setting

The system's first job is to **measure honestly what edge exists**, not to hit a return target.

- Realistic expectation for a well-built version: roughly **0.2–0.5% per week average with meaningful variance**, net of costs.
- A sustained 1%/week is unlikely without either an unusually strong signal or leverage/concentration that reintroduces blow-up risk.
- If the honest backtest returns "no edge," the pipeline has **succeeded** — it delivered the truth before real capital did.

Every design choice above serves measurement integrity first and returns second. That ordering is deliberate and should not be relaxed under time pressure.
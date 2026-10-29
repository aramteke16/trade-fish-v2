# Indian market facts and rules

Checked through 17 October 2026. Index returns below are from NSE total-return factsheets dated 30 September 2026 unless another date is given. Rates and circulars change. Re-check NSE, SEBI, and the Finance Act before sizing real money.

Two kinds of statement live here.

- **Law.** Compliance, tax, and exchange product rules. These stay binding.
- **Rule of thumb.** Research about what has paid and what usually loses. These bias design. A costed walk-forward test, or an explicit choice, can override them. The aspirational target for this project remains about 60% on invested capital. That number is not a forecast.

## Universes

| Bucket | What it is |
|---|---|
| Nifty 50 / Nifty 100 | Largest, most liquid names |
| Nifty Midcap 150 | Full-market-cap ranks 101–250 inside the Nifty 500 |
| Nifty Smallcap 250 | Ranks 251–500 |
| Below the Nifty 500 | Micro caps. No public rule as clean as the factor indices below |

Nifty 500 itself is not a strategy. It is the top 500 by full market cap after liquidity screens: traded on at least 90% of days in the prior six months, average impact cost no worse than 1%, inside the top 800 by both average daily turnover and average daily full market cap, and free float at least 10% (or a free-float size test against the smallest member). Weights are free-float market cap. Membership is reviewed on six-month data ending January and July. At most 25 names are replaced at a review.

Nifty 500 total return, April 2005–March 2026, was about **13.7%** a year (Value Research: 13.74%). A factor note on the same window printed 13.6%.

## What has actually compounded

These are index total returns. Dividends are reinvested. Brokerage, STT, stamp duty, GST, DP charges, and capital-gains tax are not deducted. A personal account running the same rules will net less. The since-2005 figures are not the recent run rate.

| Series | 1 year | 5 years | Since 1 Apr 2005 |
|---|---|---|---|
| Nifty 500 Momentum 50 | 5.08% | 12.38% a year | 21.35% a year |
| Nifty Midcap150 Momentum 50 | 4.08% | 15.13% a year | 22.22% a year |
| Nifty Smallcap250 Momentum Quality 100 | 8.42% | 11.87% a year | 21.37% a year |

Midcap momentum, same factsheet, was −3.70% for the quarter and −1.35% for 2026 through 30 September. Small-cap momentum-quality was +3.49% and +9.46% over those same windows.

Academic India momentum (Agarwalla, Jacob, Varma) is a different object. Winners-minus-losers was about 17% a year from 1994 to 2017, and 21.9% in the 1994–2013 sample. That is long winners and short losers, top and bottom 30%, prior 11 months **skipping the latest month**, equal weight inside size buckets, before costs. It is not a portfolio a retail delivery account can hold. The NSE indexes are the long-only, tradable version, and they do **not** skip the latest month.

A careful retail-style stack on five Nifty 50 names (Prakhar, 2021–2024) made low single digits and lost to buy-and-hold Nifty. Complexity is not an edge by itself.

## Retail derivatives base rate

SEBI’s study of individual equity F&O traders, FY 2025–26:

- **87.7%** lost money. Net losses **₹91,685 crore**. Average loss per trader **₹1.17 lakh**.
- Options caused about **92%** of those losses. About **97%** of traders were mainly option buyers.
- Futures traders still lost often (about **66%**), less often than options traders.
- Only about **0.5%** were profitable in every year from FY 2021–22 through FY 2025–26.
- Traders active more than 100 days made most of the turnover and most of the losses.
- Proprietary desks were on the other side of this flow.

Rule of thumb: do not use short-dated option buying as the return engine. F&O belongs, if at all, as a small hedge or a slow futures-trend sleeve. One Nifty lot is already about ₹15 lakh of exposure.

## Published rules worth cloning

### Mid caps — Nifty Midcap150 Momentum 50

Same momentum score as the Nifty 500 Momentum 50, on the Midcap 150 only.

- 12-month price return and 6-month price return, each divided by the stock’s own one-year volatility of daily log returns.
- Z-score each ratio against the eligible universe. Blend half and half.
- Positive blend: score = 1 + z. Negative blend: score = 1 / (1 − z).
- Listed at least one year. Drop non-F&O names that hit an upper or lower circuit on 20% or more of sessions in the last six months (both circuits in one day count as two).
- Top 50. Weight = free-float market cap × score.
- At the June and December rebalance, cap each name at the lower of 5% or five times its free-float-only weight. Weights may drift through the cap between reviews.
- Cut-off is the last trading day of May and of November. The market gets about four weeks’ notice.
- The signal uses price return, not dividend-inclusive total return. The published performance figure is the total-return index.

For the broader Nifty 500 Momentum 50, membership also has a buffer: stay if rank is still inside the top 75, force in any new name in the top 25, force out if rank falls past 75. Confirm the buffer in the Midcap 150 methodology PDF before copying it onto mid caps. The factsheet states the score, the 50-name cut, the cap, and the June/December cycle.

### Small caps — Nifty Smallcap250 Momentum Quality 100

Pure momentum is a rougher rule here, so the published base adds quality.

Dropped before ranking:

- Listing history under one year
- Promoter pledge above 20%
- Bottom 10% by six-month average daily turnover
- Bottom 10% by turnover ratio (traded value relative to free float)
- Non-F&O names with circuit hits on 20% or more of recent sessions

Momentum score is the same 6-month and 12-month return divided by volatility. Quality is an equal blend of high return on equity, low debt-to-equity (debt-to-equity is skipped for financials), and steady EPS growth over five years. Hold the top 100 on the combined score. Weight is free-float market cap times that score, capped at **3%** on the June and December rebalance.

A 100-name book trades a lot of lines twice a year. Costs will matter more than in the 50-name mid-cap book.

### Later changes, not part of the base

Run the published rules through the backtester first, after fees and tax, on the four-year test window. Only then consider: a smaller small-cap book than 100, skipping the most recent month in the momentum score, or cutting the book when the mid-cap or small-cap index itself breaks its trend.

## Costs that decide short-horizon trades

Zerodha NSE equity delivery, as used in the backtester. Exchange transaction charges move; this is the figure Zerodha was publishing.

| Charge | Delivery equity |
|---|---|
| Brokerage | ₹0 |
| STT | 0.1% on buy and 0.1% on sell |
| NSE transaction charge | 0.00307% of turnover |
| SEBI | ₹10 per crore |
| IPFT | ₹10 per crore |
| Stamp duty | 0.015% on the buy only |
| GST | 18% on brokerage + exchange transaction charge + SEBI. Not on STT, stamp, or IPFT |
| DP | ₹15.34 per scrip per day on a delivery sell (GST already inside). Once per symbol per day |

Other statutory rates, from 1 April 2026 unless noted:

| Product | STT | Stamp (buy side only) |
|---|---|---|
| Equity intraday | 0.025% on the sell | 0.003% |
| Equity futures | 0.05% on the sell, on notional | 0.002% |
| Equity options | 0.15% of premium on the sell; 0.15% on exercise | 0.003% of premium |

Intraday and F&O brokerage at Zerodha is the lower of 0.03% and ₹20 per executed order, except options, which are a flat ₹20.

Nifty lot size was **65** in October 2026 (Bank Nifty 30, Sensex 20). Lots are reset so an index contract stays in the ₹15–20 lakh band. One Nifty point is ₹65 per lot. At about 22,625 the contract is about ₹14.7 lakh, and STT on the futures sell alone is about ₹735. A 10-point round trip makes ₹650 before any other charge. The signal can be right and the trade still loses. From 5 October 2026 a single Nifty order cannot exceed **3,510** units (54 lots). A retail book will not hit that. An order slicer still has to.

Rule of thumb: scalp and any other high-turnover intraday rule are guilty until a costed test shows they clear STT. Transaction costs, not the signal, usually decide those strategies (Subramanya, 2026, on post-2025 Nifty scalping).

## Tax, FY 2026–27

Listed equity where STT is paid. Confirm with a chartered accountant. This is the treatment the backtester uses.

- Held **12 months or less**: short-term capital gain at **20%** (section 111A). No annual exemption. A sale on the one-year anniversary is still short-term. Long-term starts the day after.
- Held **more than 12 months**: long-term capital gain at **12.5%** (section 112A) on gains above **₹1.25 lakh** in that financial year. The year is 1 April–31 March. The exemption resets every year and is per person, not per stock.
- Add **4%** health and education cess. Surcharge depends on total income and is not assumed.
- STT is **not** deducted again inside the capital-gains calculation. Brokerage, stamp, exchange fees, SEBI, IPFT, GST, and DP are.
- Short-term losses offset short-term gains, then long-term gains. Long-term losses offset long-term gains only. Leftover capital losses carry forward up to 8 following financial years.
- Same-day equity square-off is speculative business income at the slab rate, not STCG. Exchange-traded F&O is non-speculative business income at the slab rate. STT on F&O is generally a business expense. The backtester does not model those products yet.
- Section 87A rebate does not wipe 111A / 112A tax.
- Dividends are taxable at the slab and are **not** credited in the current backtester. Index total-return numbers include them. Our results will look lower than the factsheet for that reason too.

## Algo trading law

Personal, self-coded, family-only. SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 (4 February 2025), NSE implementation NSE/INVG/67858 (5 May 2025) and operational modalities NSE/INVG/69255 (22 July 2025). The framework is in force.

- The broker is the principal. Connect only through that broker’s API. No open APIs.
- Client-specific API key, OAuth, and two-factor authentication.
- A static IP whitelisted to that key. It can be changed once a calendar week. A backup IP is allowed.
- Every API order is an algo order and carries an exchange algo ID.
- **At or under 10 orders per second** per exchange, measured on the broker’s clock: generic algo ID, no per-strategy registration, and only one API key may carry these unregistered algos. The broker must reject anything faster.
- **Above 10 orders per second**: register the strategy with each exchange through the broker. A logic change needs fresh approval. The exchange can kill orders from that algo ID.
- The same registered algo may be used for self, spouse, dependent children, and dependent parents. Not for anyone else.
- Selling the strategy, or hiding the logic from the person whose money it trades, means algo-provider empanelment. A black box also needs SEBI Research Analyst registration and a research report per strategy.
- The broker’s risk system still applies: margins, position limits, banned scrips, kill switch. Profit and loss on a self-coded algo sit with the client.
- Spoofing, layering, circular trades, and marking the close are illegal under the PFUTP regulations whether a script sends them or a person does. Do not market a guaranteed or fixed return.

## F&O product rules, if a sleeve uses them

SEBI index-derivatives circular, 1 October 2024.

- One weekly expiry per exchange. NSE Nifty (Tuesday). BSE Sensex (Thursday). Bank Nifty, Fin Nifty, and Midcap Nifty are monthly.
- New index contracts must be worth at least ₹15 lakh, and the lot is set so value stays in the ₹15–20 lakh band.
- Extra extreme-loss margin of about 2% on short options on expiry day.
- Option premium is collected from the buyer up front (from 1 February 2025).
- No calendar-spread margin benefit on expiry day.
- Position limits are watched intraday.

## How the backtester is allowed to claim a profit

`python -m backtester`. Test window is the most recent **4 years**. Train length is chosen per idea (`--train-years`). The split is one calendar cut for every symbol, not a shuffled row split.

- Fit once on train. A decision at a close may see prices only up to that close. Orders fill at the next open.
- The book is sold at the last test close so the reported profit is realized.
- Whole shares. Delivery equity only. Negative weights are rejected. A same-day round trip is rejected.
- Buys that would fill on the final session are skipped, so the last day does not become an intraday trade.
- Headline profit is after the Zerodha delivery schedule and after the capital-gains tax above. Tax is subtracted from the claim. It is not taken out of cash during the path, so it does not shrink later position size.
- No dividends, no slippage unless asked, no surcharge unless a rate is passed in.

The first live data run was not a strategy. It was equal-weight buy-and-hold of RELIANCE, TCS, HDFCBANK, INFY, and ICICIBANK, ₹10 lakh, test window 9 October 2022–9 October 2026. Net profit **₹1,229** after ₹2,266 of costs (STT ₹1,967) and ₹0 tax, because long-term gain was ₹3,196. Over that window ICICI was up about 54%, Reliance about 2%, HDFC Bank flat, Infosys and TCS each down about 30%. A flat basket does not survive costs.

Upstox daily candles (API v3) go back to January 2000, one decade per request. The token stays in `TRADEFISH_UPSTOX_ACCESS_TOKEN` or a gitignored `.env`. It does not go in source.

## Sources

- SEBI, “Safer participation of retail investors in Algorithmic trading,” 4 February 2025, SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013
- NSE, NSE/INVG/67858 (5 May 2025) and NSE/INVG/69255 (22 July 2025)
- SEBI index-derivatives framework, 1 October 2024
- SEBI, profitability of individual traders in equity derivatives, FY 2025–26 (released August 2026)
- NSE Indices methodology (September 2026 edition) and factsheets for Nifty 500 Momentum 50, Nifty Midcap150 Momentum 50, and Nifty Smallcap250 Momentum Quality 100, 30 September 2026
- Agarwalla, Jacob, and Varma, “Four factor model in Indian equities market,” IIMA working paper, and the IIMA factor library
- Jegadeesh and Titman (1993); Carhart (1997); Moskowitz, Ooi, and Pedersen (2012)
- Bailey, Borwein, López de Prado, and Zhu on backtest overfitting; Harvey, Liu, and Zhu (2016) on multiple testing
- Finance Act rates for FY 2026–27: STCG 20%, LTCG 12.5% above ₹1.25 lakh, STT on futures 0.05% and on options premium 0.15% from 1 April 2026
- Zerodha published equity-delivery charge schedule (brokerage ₹0, NSE transaction charge 0.00307%, DP ₹15.34)

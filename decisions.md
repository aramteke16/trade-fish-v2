# Decisions

Locked 28 October 2026. This is the record of what was decided. Later code follows this file. A change is a new decision written here first, not a silent edit in the code.

You place the delivery orders yourself. This system writes a sheet. It does not send an order to a broker.

## 1. What this is

- A personal NSE cash book. Delivery only. Long only. Whole shares.
- One decision a week, using prices through that week's close. The order is filled at the next NSE cash open, 09:15 IST. No same-day round trip. No buy on a day that has no following session.
- The tested path and the live sheet are different. The test put in ₹10,00,000 once on 15 May 2018 and left the profit invested. Your live book adds ₹20,000 on the first week of each month. The test's after-tax profit of ₹44,94,224 is not the expected profit on the ₹20,000 path. That monthly path has not been backtested.

## 2. Left out

- No live broker orders. Upstox is the price source. The token stays in `.env` and is never printed.
- No F&O. No FMCG book. No skip-month rule. No trend-to-cash filter. No copy of the Nifty Midcap 150 Momentum 50.
- The network is not retrained. Fit only on data before 1 January 2024. Seed 7. The 2024–2026 window has already been seen, so it is not a clean test. Do not add epochs or change the reward to chase a higher print.
- Large caps are not added to the pharma universe: SUNPHARMA, DIVISLAB, TORNTPHARM, ZYDUSLIFE, CIPLA, DRREDDY.
- Hospitals, diagnostics, devices, and ADVENZYMES stay out of the universe.

## 3. Universe

Three lists. They stay separate. The buy ranker in section 4 reads the pharma list only. Written 28 October 2026. This section is not in the code yet. Code it only when asked.

### Pharma

The pharma list is `PHARMA_ALL` in `research/pharma_dasrl.py`. It is every current NSE EQ and BE pharma name outside the Nifty 100. There are 118. The large-cap names and the other exclusions in section 2 stay out. Delisted and BSE-only names are absent.

A name in that list may be scored once it is one year old. A file that starts on 1 January 2018 means the company was already listed. A later first bar is the listing, and the year is counted from that bar.

### Personal holdings

The personal list is the current book. The ranker does not choose these names.

Each lot records who suggested it.

- `manual`: you added it. The broker sheet of 17 October 2026 is manual.
- `algo`: a buy this book itself wrote onto the lots.

A line with no NSE equity symbol stays on the book and is not scored.

When the sell list in section 7 names a manual lot, that name is deleted from the personal list. When the sell list names an algo lot, that name stays on the pharma list or the electricity list. Selling shares of an algo name does not remove it from its sector list.

### Electricity

One list. It covers generation, transmission, and the equipment that builds turbines, transformers, cables, and lines. Current NSE EQ and BE names. Outside the Nifty 100. Large caps stay out.

Out of this list: oil, gas, and lenders, including PFC, REC, and IREDA. Home-appliance brands stay out, including Crompton, Voltas, Havells, Bajaj Electricals, and Orient Electric. Large generators stay out: NTPC, TATAPOWER, ADANIPOWER, ADANIGREEN. Large transmission and heavy equipment stay out: POWERGRID, ADANIENSOL, ABB, BHEL, CGPOWER, ENRIN, POWERINDIA, POLYCAB. BHEL is a large cap and is not in the Nifty 100. Siemens Ltd stays out. The power company in that group is Siemens Energy, ENRIN, and ENRIN is a large cap. GVT&D stays in. Its market-cap prints sit on the large-cap line, and it is not in the Nifty 100.

The names that match this rule are `POWER` in `research/pharma_dasrl.py`. There are 148. That includes the NSE Power industry and the NSE Electrical Equipment industry, heavy and other, on the main board and on NSE SME, after the large-cap cut. The SME names are small caps. InvITs and BSE-only names from those industries are not in the list. The old 23-name result in `data/power_dasrl_result.json` stays as it is. Prices for this list have not been fetched.

## 4. Buy pick

Input: the pharma list in section 3, priced through the decision close. The personal list and the electricity list are not inputs to this ranker.

Each name is scored on its own last 90 sessions. For each session:

`f = (close / open) × (1 − 0.003)²`

A session counts only when `f` is at least 1. That is a close about 0.6% above the open. Every other session is dropped. A down day is not punished. The raw score is the product of the sessions that counted. If none counted, the raw score is 1.

Divide every raw score by the best raw score that week. If the best is below 1, divide by 1 instead. Sort by score, highest first. If two scores match, the symbol that comes first alphabetically ranks higher. A name with fewer than 90 sessions is left out.

Output: the first three names, each with its score. If fewer than three qualify, the list is shorter. These three are the only buy picks that week.

The ranker does not read rupees invested, average price, share count, cash, or the network weights. The network does not choose the names.

## 5. Buy money

This is locked. A later week does not raise cash by selling so it can buy the new top 3.

- New money is ₹20,000. It is added only when the decision date falls on day 1–7, and only once that month.
- That ₹20,000 is spent on the three picks, highest network weight first, whole shares. Each name's budget is its weight times ₹20,000. A share that costs more than the cash left for that name waits.
- Any other week of the month buys nothing. The new top 3 are still computed and shown. They are not bought.
- Cash left over from an earlier month is not part of the ₹20,000 budget. It stays unspent.
- A sale reduces the share count. The rupees from the sale are not added to cash, so they cannot fund a later buy.
- The next month's ₹20,000 is a fresh deposit.

The Friday job is the run that writes these buys onto the book. A manual run stores the same sheet and does not change cash or lots.

## 6. Weights

The frozen network sets the three weights only when the ₹20,000 is being spent. The weights are positive numbers that sum to 1, in the same order as the ranker.

It reads 24 numbers:

- Three market numbers from Nifty Pharma over 21 sessions: last-day return, the standard deviation of daily returns, and the 21-session return.
- Six numbers for each of the three names, from 30 sessions: last-day return, the standard deviation of the last 20 daily returns, 14-day RSI divided by 100, MACD (12-day EMA minus 26-day EMA) divided by price, the 20-close band width (4 times the standard deviation, divided by the mean), and 14-day ATR divided by price. The 21-day momentum figure is computed and then dropped.
- Three account numbers: equity divided by the original ₹10,00,000, drawdown from the peak, and the last change in equity. Equity here is the unspent cash plus the value of shares already held in the three picks. The network does not see share counts. A missing name is zeros.

The saved actor is `data/pharma_all_actor.npz`.

On the live sheet the peak and the previous equity are currently passed in as the same number as today's equity, so the drawdown and the last change go in as zero. The decision is that those two inputs are the real drawdown and the real last change. The code does not do that yet.

## 7. Sell

The sell rule is separate. It was not part of the tested backtest. It does not exist to fund the next buy.

- It looks only at your lots.
- A name in that week's top 3 is never a sell.
- A lot from the broker sheet needs a purchase date and 60 days held. Its score is the share of sessions in that holding when the close finished about 0.6% above the open, using the same day test as the buy score. Down days are ignored. The whole-life score is a separate number. It is shown beside the holding and is not part of the sell rank. The sheet does not show that lifetime number yet.
- "Still producing" means that holding-period share is at least the median of the same share for the pharma names over their last 252 sessions. On the 16 October 2026 run that median was 31.7%. A name still producing is not sold, even if the price is down.
- At most three sells. Of the names under that bar, the quietest three. If you hold one share, sell it. Otherwise sell half the lot, at least one share.
- The other holdings are not sold to force the account down to three names.
- A lot that this book itself bought, and that has left the top 3, also takes a sell slot. The reason is "left the top 3." Original broker-sheet lots are not sold for that reason.
- Section 3 says a manual name on this list is deleted from the personal book, and an algo name stays on its sector list. That part is not in the code. Until it is coded, a sell only cuts the share count, by the half-lot rule above.
- Every purchase date is still blank. The broker sheet did not have them. Until a lot has `purchased` as YYYY-MM-DD, it cannot be sold. Dates are not invented.

### A one-year gain

Written 29 October 2026. This does not change the sell rule above. The 60 days are the earliest a broker-sheet lot may be sold. They are not a maximum hold, and they are not a target exit.

A name that is still in that week's buy top 3 is never sold. It can be held for a year, and a first-week buy can add shares, for as long as the 90-day score keeps it in the top 3.

A broker-sheet lot past 60 days is also kept when it is still producing. The sell score does not look at the price against the cost, and it does not look forward to a one-year gain.

Two exits can cut a name before that year:

- A lot this book itself bought, once it has left the top 3, is sold with no 60-day wait. The reason is "left the top 3." A large one-year return does not save it.
- A broker-sheet lot past 60 days, with an up-day share under the bar, is a quiet sell. Half the lot is sold. A slow rise made of days under the 0.6% test looks quiet, so it can be sold on the way to a later gain.

Measured on `data/pharma_all_bars.csv`, entries every fifth session after 90 sessions, buy at that open, gain checked on later closes only. A 0.5% rise, enough to clear delivery costs, has a median of 3 sessions. That is not a holding period. A 10% price rise, before tax, on entries whose next year ends before 1 January 2024: 35% within 21 sessions, 49% within 42, 56% within 63, 67% within 126, 77% within 252. 23% are not up 10% after that year. Among the entries that hit 10%, the median wait is 26 sessions and the mean is 52. A strong week, prior 90 sessions with an up-day share of at least 30%, moves the median only to 24 sessions. Across names, that median clusters between 20 and 34 sessions. The average of the winners is the wrong clock: Gland was up 10% within a year on 28% of those entries, while the hits that did land had a median of 19 sessions. About 42 sessions is 60 calendar days, and only about half the entries are up 10% by then. At 252 sessions, about four in five have had the 10% price gain. That price gain is before tax. A sale on or before the 12-month anniversary is short-term.

## 8. Your book

- The broker sheet of 17 October 2026 is the starting book. 73 lines. The invested rupees on that sheet are about ₹4.07 lakh. The ranker does not use that figure.
- Six lines have no NSE equity symbol and stay unscored: Basant Agro, the MML NCD, the second Natco line, National Oxygen, Sanmit Infra, Spandana. PGINVIT did not resolve. It is an InvIT, not an NSE equity.
- The first stored decision is the 16 October 2026 close. Top 3: MOREPENLAB, PAR, INDSWFTLAB. Buy none, because the 16th is outside day 1–7. Sell none, because there are no purchase dates. Cash is ₹0.

## 9. Clock

- Default decision time is Friday 16:00 IST, after the 15:30 cash close, so the daily candle exists. The sheet is for the next cash open.
- The page can change the weekday, the hour, the minute, the ₹20,000, and the 60-day hold. The Friday job reads those on its next wake, within 30 seconds. It is not restarted.
- The job fires the next future slot only. Starting it after 16:00 on Friday does not run a missed week.
- A manual run and the Friday job cannot score at the same time.

## 10. What is stored

- Lots, cash, the month of the last ₹20,000, the clock settings, and every decision live in `data/assistant/portfolio.db`.
- Daily prices stay in files. Pharma history is `data/pharma_all_bars.csv`. Other holdings are appended to `data/assistant/bars.csv`. The Nifty Pharma index stays a file. The 118 pharma names stay in code. The electricity tuple in that same file is `POWER`, 148 names, and it matches section 3.
- Each decision stores the close date, whether it was the Friday job or a manual run, the top 3, the full ranking, the buys, the sells, and `orders_sent: false`.
- A Friday run updates lots and cash. A manual run only stores the decision.

## 11. The page

- `python3 -m assistant ui` serves the page. The Friday job is `python3 -m assistant schedule`. They are separate processes.
- The header has the chart mark, the last run, and the next run. A manual run does not move the next Friday slot.
- Scheduled sheets and manual sheets are separate. Each sheet shows the top 3, a score chart, the full ranked list, the buys, the sells, and the close it used. The symbol is shown with the company name.
- The holdings book is on the same page. Config edits the clock, the monthly cash, the minimum hold, and the Upstox token. A blank token box leaves the current token in place.
- The page is one centered column and stacks on a phone. It has no login. On the droplet, port 8080 is bound to localhost.
- Docker Compose is written and has not been started. `manager` is the Friday job. `web` is the page. `.env` is mounted so a token saved on the page is the file both processes read.

## 12. Costs and tax, for the test only

The live sheet does not compute tax. The tested path uses Zerodha NSE delivery costs and FY 2026–27 tax rates, including on the old years. Brokerage is ₹0. STT is 0.1% on both sides and is paid in cash, then not deducted again inside the gain. A sale held 12 months or less, including the anniversary, is short-term at 20% plus 4% cess. Long-term is 12.5% above ₹1.25 lakh in a financial year, after set-off, plus cess. Short-term losses offset short-term gains and then long-term gains. Long-term losses offset long-term gains only. Losses carry for 8 following financial years. Dividends are not credited. Confirm the tax with a CA.

On that tested path, 15 May 2018 through 15 October 2026, from ₹10,00,000 once: yearly return before tax 24.6%, yearly return after tax 22.8%, end value before tax ₹62,00,351, profit before tax ₹52,00,351, tax ₹7,06,127, profit after tax ₹44,94,224. 2018–2023 on that path is in-sample.

## 13. Still open

- Purchase dates for the 73 lots. You supply them. The sell list stays empty until then.
- The live weight call still passes a zero drawdown and a zero last change. Section 6 is the rule.
- The lifetime score is not on the sheet yet. Section 7 is the rule.
- The pharma list and the electricity list in section 3 are in the code. The buy pass still scores personal holdings in the same pass as the 118, and a holding still skips the one-year wait. The manual-or-algo tag is not used. The live `lots` table has a leftover `source` column. Every current lot is `manual`. The code does not read that column.

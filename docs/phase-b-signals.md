# Phase B: Signal Lab and Prediction Engine (Modules 4 and 5)

Weeks 5–9 of the [platform PRD](PRD.md). Started early, alongside Phase A, on the 29 FinanceBench companies with warehouse data. That is enough to build and test the machinery; it is **not** a universe, and no backtest numbers from it should be reported.

## Leakage guarantees (written first)

`tests/test_leakage.py` pins down the panel and walk-forward contracts before any model code. Each was mutation-checked by breaking it on purpose.

| Guarantee | Test | Break it and... |
|---|---|---|
| Every feature was public by its month-end (`info_date <= month`) | `test_every_feature_was_public_by_its_month_end` | features built on unfiled facts fail |
| The target starts one month after the feature date and spans 12 months | `test_target_starts_after_the_embargo_and_spans_the_horizon` | removing the embargo fails |
| Training rows whose label window reaches the test year are purged | `test_walk_forward_folds_purge_overlapping_targets` | removing the purge fails |
| Shuffling the target within each month drives rank IC to ~0 | `test_shuffled_target_has_no_rank_ic` | |

Timeline for a panel row at month-end *t*: features use facts with `available_at <= t`; the target is the total return over trading days in (end of month *t+1*, end of month *t+13*], minus SPY's over the same days. Rows whose window runs past the last price have no target; they are never truncated.

## Built so far

- `models/panel.py`: monthly panel builder with the audit column `info_date`
- `models/walkforward.py`: expanding-window folds, one test year each, purged; monthly rank IC
- `warehouse/fundamentals.py`: 22 standard annual line items mapped from XBRL with per-year fallbacks. Coverage was measured on the 29 companies first: revenue alone appears under 7 concept names.
- `signals/accounting.py`: Piotroski F-score, Altman Z-score, Beneish M-score, accruals ratio, each with hand-computed tests
- `signals/fundamentals.py`: revenue and asset growth; gross, operating and net margins; ROE (on average equity), ROA (on beginning assets), leverage, debt-to-equity; and the year-over-year change of each
- `signals/valuation.py`: earnings yield, book-to-market, free-cash-flow yield, sales-to-price
- `signals/base.py`: shared inputs and market cap, which carries the cover-page share count through any stock split before the feature date
- `signals/text.py`: similarity of Risk Factors and MD&A to the previous 10-K ("Lazy Prices"), Risk Factors length and its change, MD&A Gunning Fog readability; from the latest 10-K public the day after filing
- `warehouse/sectors.py`: SEC SIC code → 11 GICS-like sectors, stored on `companies`
- `models/ranks.py`: monthly percentile ranks, raw and within sector
- `models/study.py`: single-signal study (monthly rank IC, yearly t-statistic, top-minus-bottom quintile spread, raw and sector-neutral)
- `models/ranker.py`: LightGBM LambdaRank walk-forward (months as queries, within-month quintile labels), tuned per fold on the last two training years with the same purge; baselines F-score, ridge, random. Folds with under 24 purged months of inner history use default settings.
- `models/backtest.py`: monthly long/short backtest from out-of-sample predictions; positions formed at month-end close and held over the next month; turnover and costs; annualised return, volatility, Sharpe, max drawdown, before and after costs

**Real-data findings that changed the code**

- Some 10-Qs tag trailing-twelve-month figures (Amazon), which looked like extra fiscal years. Only 10-K/20-F/40-F filings now define fiscal years.
- J&J, Pfizer, Nike and AES don't tag operating income; EBIT falls back to pre-tax income plus interest expense.
- A score is NaN when an input is structurally missing (banks have no current assets; PayPal, Verizon and MGM have no cost of goods sold), never computed from a subset.
- Point-in-time works as intended on real cases: Kraft Heinz's FY2018 10-K was delayed to June 2019, so in March 2019 its features still come from FY2017.
- Market cap was 20× too small for Amazon in mid-2022: the April 10-Q counted pre-split shares, the June price was post-split. Split days are now detected from the stored data (raw close vs. total return) and applied to the share count. A scan of all stored prices finds only real splits (Amazon, Walmart, Netflix ×2, Nike ×2, Coca-Cola, General Mills, Amcor's reverse split).
- SIC codes put some companies in a different sector than GICS would: 3M in Health Care (SIC 3841), Corning in Materials, PayPal in Industrials, CVS in Consumer Staples, Amcor in Consumer Discretionary. Accepted: sector-neutral ranks need a peer group, not an official label.
- Altman Z puts utilities (American Water, AES) in the "distress zone" because it was built for manufacturers. That is expected and is why the PRD keeps sector-neutral ranks.

**First single-signal study run (machinery check, not a result).** 24 signals over 29 companies × 189 months (2011–2026), output in `data/study/signals.csv`. With ~29 names a month the figures are noise; the one visible pattern (growth beat cheapness and profitability among these megacaps since 2011: revenue growth IC +0.09, earnings yield −0.10) is the well-known growth era, not evidence about the signals. Rerun with the text family (97% coverage): Risk Factors similarity (+0.09) and Risk Factors growth (−0.08) have the signs "Lazy Prices" predicts, which on 29 names is a coincidence rather than a replication. The run takes a few minutes; at S&P 500 scale the per-month snapshots will need caching (~30 minutes otherwise).

**First ranker and backtest runs (machinery check, not a result).** Test years 2015–2025, quintile legs (deciles would be 2 stocks). The random baseline's yearly IC swings between −0.11 and +0.13 while averaging 0.004: with 29 names, a single year's IC means little. Its turnover of 3.3 a month is near the maximum of 4, as fresh random ranks should be, which checks the turnover arithmetic.

## S&P 500 results (2011–2024; built on the proposed universe, pending sign-off)

> **Correction, 2 October 2026.** Results reported before this date were wrong. 71 current index members (Bank of America, Citigroup, Goldman Sachs, Berkshire Hathaway, Alphabet, Ford and others) were priced with a preferred share or note instead of their common stock, because the ticker lookup kept the last of a company's SEC tickers rather than the primary one. Fixed in `warehouse/universe.py` (`primary_tickers`, with a regression test) and everything was rebuilt. The earlier figures (ranker IC 0.028; long-short 5.0% a year, Sharpe 0.61) overstated the model. The numbers below replace them.

Panel: 94,090 stock-months, about 498 members a month, 29 signals; 80.2% of rows have a 12-month target. Audited on the real panel: no row uses information dated after its month (0 of 93,986), and no target starts early. The figures below are from the rebuild after predecessor companies were linked (see [phase-a-warehouse.md](phase-a-warehouse.md)), which raised fundamentals coverage from 97% to 99% of stock-months.

**Survivorship.** 11.7% of member-months have no price history (Yahoo drops acquired and delisted names): 23% in 2010, falling to 1% by 2025. Those names drop out of that month's cross-section, so early test years lean towards survivors.

**Single signals** (monthly rank IC against 12-month excess return, t-statistic on yearly means; `data/study/sp500/signals.csv`):
- Leverage change holds up best: IC +0.046, t = 4.5 (within sector +0.039, t = 5.2, positive in 14 of 15 years). It holds outside Financials (+0.056, versus −0.006 inside) and fades when lagged a year (+0.031): a real, decaying effect, plausibly buybacks (shrinking equity raises leverage).
- Leverage level: IC +0.046, t = 2.2. Free-cash-flow yield: +0.035, t = 1.2.
- Book-to-market is mildly negative (−0.026, t = −0.4): value did not pay in this period.
- Most classic anomalies are near zero among large caps: F-score (−0.004), accruals (+0.002), and the text signals (Risk Factors similarity +0.011, MD&A similarity +0.007, Fog +0.001). That matches the literature on anomalies decaying in large caps.

**Ranker (walk-forward, test years 2015–2024, configuration chosen inside each fold).** Mean monthly rank IC: LightGBM −0.004, ridge 0.009, F-score 0.009, best single signal chosen in-fold −0.035, random 0.000. **The combined model has no measurable ranking skill across the cross-section.** The in-fold best signal is negative because the signal that looked best in the past did not carry forward.

**Backtest (top and bottom deciles, monthly, 10 bps).**

| Model | Before costs | After costs | Sharpe | Max drawdown | Turnover |
|---|---|---|---|---|---|
| LightGBM ranker | +2.4% | +1.5% | 0.21 | −17% | 0.74 |
| Ridge | +0.1% | −0.6% | 0.02 | −47% | 0.57 |
| Best single signal | −0.4% | −0.8% | −0.01 | −32% | 0.38 |
| F-score alone | −4.6% | −5.6% | −0.49 | −53% | 0.85 |
| Random ranks | −1.6% | −5.7% | −1.04 | −47% | 3.60 |

The ranker's long leg returned 13.1% a year against SPY's 13.6%. A Sharpe of 0.21 over ten years is about t = 0.7: no evidence of skill. By year, after costs: 2015 −12.7%, 2016 +14.7%, 2017 +4.3%, 2018 −1.9%, 2019 +3.9%, 2020 +20.9%, 2021 −9.5%, 2022 +3.5%, 2023 −0.2%, 2024 −3.2%. Random ranks lose about their trading costs (turnover 3.6 of a maximum 4), which checks the cost arithmetic.

**Honest summary.** The pipeline is leak-free and the baselines behave, but on S&P 500 large caps with these 29 signals there is no return-prediction edge. Each data correction made the result weaker, not stronger (mean IC 0.028 with the wrong prices, 0.006 with correct prices, −0.004 with predecessor fundamentals linked), which is what a spurious edge looks like. What survives is a small number of single signals (leverage and its change).

**Holdout disclosure.** The first ranker run included 2025, which the PRD reserves as the holdout for one final run. Nothing was tuned on it, but the holdout has been seen once. Development runs stop at 2024 by default (`--last-test-year`).

**Iterations disclosed.** The ranker's configuration choice (number of signals, market or sector labels) was added after the first test-year results had been seen; it is chosen inside each fold's training window.

## Next

The universe was since widened to the S&P 400 and 600; the ranker shows no edge there either. See [phase-d-universe.md](phase-d-universe.md). The items below predate that.

1. Loughran-McDonald tone: waiting on a licence decision. The dictionary is free for academic use; commercial use needs permission from its authors. A portfolio project is arguably fine, but it's @Srikar's call.
2. Improve the ranker without touching the test years: feature selection inside each fold's training window (the model dilutes the one strong signal among ~30 weak ones), and a sector-neutral target.
3. Phase B2 Risk Engine on this panel and these folds (volatility and severe-loss targets; the distress classifier lives there).

## Backtest configuration: DRAFT, needs @Srikar's sign-off

Per the PRD, the feature list and backtest configuration are decisions you defend in interviews, so they are frozen by you before the first test-year run. Proposed values, all taken from the PRD:

| Setting | Proposed | Notes |
|---|---|---|
| Universe | S&P 500 members since 2010, including later removals | Awaiting decision |
| Feature list | The PRD's Signal Lab table, as ranked percentiles plus sector-neutral versions | Guidance hit rate stays a stretch goal |
| Target | 12-month total return minus SPY, starting one month after the feature date | |
| Walk-forward | Expanding window, one test year per fold, first test year 2015 | Gives 5 training years |
| Holdout | Most recent full year, run once at the very end | |
| Rebalance | Monthly, equal-weight top and bottom deciles, one-month hold | |
| Costs | 10 bps per trade, results before and after | |
| Tuning | Nested inside each fold's training window only | |
| Sectors | SEC SIC codes mapped to 11 GICS-like sectors | Free; GICS itself is licensed |

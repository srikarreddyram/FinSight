# Phase D: Wider universe (S&P 500, 400 and 600)

The return ranker found no edge among S&P 500 large caps (mean rank IC −0.004 on test years 2015–2024; see [phase-b-signals.md](phase-b-signals.md)). Accounting and valuation signals have historically worked better in smaller companies, where fewer analysts follow each stock, so the whole study was repeated on the S&P 500, 400 and 600 together. Every result is also reported inside each index, so a large-cap null result can't be hidden by a mid-cap one or the other way round.

## Membership

`warehouse/universe.py` rebuilds each index the way it already rebuilt the S&P 500: today's constituents from Wikipedia, walked backwards through the dated change log, on SEC IDs rather than tickers.

**How far back each index goes.** Only as far as its change log is complete. Before that date a company is not counted as a member of that index, because who belonged then isn't known; filling the gap with today's members would select the survivors.

| Index | Change log reaches | Rows a year | Membership from |
|---|---|---|---|
| S&P 500 | 2000s | 20–40 | 2010 |
| S&P 400 | January 2012 | 16–25 before 2016, 40–60 after | 2016 |
| S&P 600 | December 2019 | 50–95 | 2020 |

So the cross-section grows: about 500 companies a month through 2015, 900 from 2016 and 1,500 from 2020. The S&P 600's results rest on five test years (2020–2024), the S&P 400's on nine.

**Members on each check date** (target 500 / 400 / 600):

| Date | S&P 500 | S&P 400 | S&P 600 | All |
|---|---|---|---|---|
| 4 Jan 2010 | 499 | – | – | 499 |
| 30 Jun 2016 | 499 | 401 | – | 900 |
| 30 Jun 2020 | 500 | 397 | 602 | 1,497 |
| 30 Jun 2023 | 500 | 399 | 601 | 1,498 |
| 3 Oct 2026 | 500 | 400 | 600 | 1,498 |

2,213 companies were members of at least one index at some point since 2010 (805 for the S&P 500 alone); 36 are linked to a predecessor they reorganised from.

**What the wider change logs exposed, and the fixes** (each with a regression test in `tests/test_universe.py`):

- *Failed SEC lookups were remembered as "no filings".* A burst of failed requests during the first run left about 85 S&P 600 removals unresolved. A lookup now counts as an answer only when SEC answers (a 404 means no such filer); anything else is retried with backoff (`ingest/fetch_edgar.py`) and never cached.
- *Tickers that passed to another company that was filing at the same time.* WTW was Weight Watchers until 2019 and is Willis Towers Watson now; COR was CoreSite Realty and is Cencora. When the current holder's SEC names share no word with the row's name, the name search adds its own candidates: a removal takes the name match, and an addition takes the first candidate with a share line to give. This also corrected two S&P 500 rows that had been matched to shell companies that hold the old tickers today (Compuware and El Paso).
- *Reorganisations that changed the name as well as the SEC ID* (WWE became TKO; HollyFrontier became HF Sinclair). A member whose 10-Ks start years after its membership is linked to a company that was added to an index but never left it under its own ID, stopped filing as the member began, and is the only one that did. Its start date becomes the day that predecessor joined, or the day it left another index.
- *Delisted companies priced with someone else's history.* Yahoo keeps no prices for delisted shares, so a request for an old symbol returns whichever company uses it now: the S&P 500 study had attached later companies' prices to King Pharmaceuticals, Genzyme and 21st Century Fox, among about 30 others (few rows had a complete window, so the effect on earlier results was small). A company SEC no longer lists is now stored as `SYMBOL~CIK` and nothing is fetched for it.
- Smaller fixes: possessive names ("Sotheby's" files as SOTHEBYS), short all-consonant names matched as written before being read as initials (CSG Systems, SJW Group), and a few SEC name aliases.

About 20 S&P 400 and 600 changes since each index's start date stay unresolved, mostly fresh spin-offs moved between indexes before their first 10-K (Vestis, RXO) and banks that file with their regulator rather than the SEC (Cadence Bank, Signature Bank).

## Data loaded

| Table | Rows | Companies |
|---|---|---|
| XBRL facts | 45.2M | 2,248 |
| 10-K text (Items 1A, 3, 7, 7A, 9A) | 22,686 filings | 2,246 |
| Daily prices | 6.7M | 1,814 tickers |
| Filing index (8-Ks, late filings, amendments) | 758k | 2,253 |

519 of the 2,213 companies are no longer listed and have no price history (see Limits).

The 10-K text load fetches each company's filings only for the years the study can use: from two and a half years before it first joined an index (the text signals compare a filing with the one before it) to a year after it last left (`warehouse/tenk.py`, `windows`).

## Results

Panel: 194,357 stock-months (about 6,000 a year through 2015, 10,800 from 2016, 18,000 from 2020), 76.1% with a 12-month target. Audited: no row uses information dated after its month (0 of 193,301). Test years 2015–2024, as before; 2025 stays held out.

### The return ranker: still no edge

Mean monthly rank IC on the test years (`data/study/sp1500/predictions.parquet`):

| | All three | Inside S&P 500 | Inside S&P 400 | Inside S&P 600 |
|---|---|---|---|---|
| LightGBM ranker | −0.000 | +0.016 | −0.005 | −0.012 |
| Ridge regression | +0.001 | +0.013 | −0.002 | −0.041 |
| F-score alone | +0.020 | +0.009 | +0.025 | +0.022 |
| Random ranks | −0.002 | | | |
| Test years | 2015–2024 | 2015–2024 | 2016–2024 | 2020–2024 |

The ranker's yearly ICs swing between −0.13 and +0.10 and average zero. The long-short backtest (top and bottom tenths, monthly, 10 bps) makes +2.3% a year after costs, Sharpe 0.27, maximum drawdown −22%; inside the S&P 400 +5.0% (Sharpe 0.44), inside the S&P 600 +5.4% (Sharpe 0.38, five years). All of it comes from one year: 2020 returned +59%, and the other nine years compound to a loss. Widening the universe did not give the return model an edge.

**An early result that did not survive.** A first run on a snapshot taken before the new companies' 10-K text was loaded (and before the final membership pass) gave the ranker an IC of 0.058 inside the S&P 400, still 0.070 (t = 3.5) after removing size, volatility, momentum and beta. With the text signals and final membership in place it is −0.005. One added signal family moved the result by 0.06: that is how much a fitted model's IC can move without anything real behind it, and why only the full, final run is reported.

### Single signals: some differ by size

Rank IC against 12-month excess return, feature months up to 2024, t-statistic on yearly means (`signals_sp500.csv`, `signals_sp400.csv`, `signals_sp600.csv`). These were recomputed without 2025, the holdout, after it was used ([`phase-f-price-insider.md`](phase-f-price-insider.md)); the figures moved by up to 0.013 and none changed sign:

| Signal | S&P 500 | S&P 400 | S&P 600 |
|---|---|---|---|
| Leverage change | +0.045 (t 4.1) | +0.017 (t 1.0) | +0.033 (t 1.5) |
| Leverage | +0.049 (t 2.3) | +0.044 (t 1.1) | +0.057 (t 1.1) |
| Earnings yield | +0.008 (t 0.2) | +0.053 (t 1.5) | +0.069 (t 3.3) |
| Book-to-market | −0.039 (t −0.8) | −0.020 (t −0.4) | +0.088 (t 1.7) |
| Sales-to-price | +0.001 (t 0.0) | +0.028 (t 0.6) | +0.091 (t 1.4) |
| Gross margin | +0.032 (t 1.3) | −0.035 (t −0.7) | −0.113 (t −4.9) |
| Risk Factors length | +0.006 (t 0.4) | −0.048 (t −1.8) | −0.077 (t −3.0) |
| MD&A similarity | +0.004 (t 0.2) | +0.008 (t 0.4) | +0.051 (t 1.8) |

- Leverage change, the one signal that held up in large caps, does not carry over to mid and small caps.
- Cheapness (earnings yield, book-to-market, sales-to-price) works in small caps and not in large ones, which is the textbook pattern. So does the "Lazy Prices" direction for 10-K text: longer Risk Factors and less-similar MD&A go with worse returns in the S&P 600.
- Small caps with high gross margins did badly (t = −4.9). The S&P 600 sample is 2020–2024, when profitable-looking growth companies fell hard after 2021; this is more likely that one episode than a lasting effect.
- With 174 comparisons, several of these clear t = 2 by chance alone, and the S&P 600 rests on five years. Patterns worth testing on new data, not findings.

### Risk Engine on 1,500 companies

| | Used in grades (blend) | Model alone | Past-year volatility |
|---|---|---|---|
| Volatility rank IC | 0.777 | 0.766 | 0.779 |
| Downside AUC, within month | 0.787 | 0.767 | 0.791 |
| Downside AUC, pooled | 0.731 | 0.717 | 0.665 |
| Severe-loss rate, riskiest 10% | 51.4% | 49.0% | 52.2% |

The grades sort risk well: the severe-loss rate rises from 7.2% (Low) to 13.1%, 18.8%, 27.3% and 47.2% (Severe), and realised volatility from 25% to 64%. Within each month the blend matches past-year volatility but does not beat it, the same conclusion as on the S&P 500 alone. Inside each index the picture is the same (downside AUC 0.787 vs 0.793 in the S&P 500, 0.771 vs 0.773 in the 400, 0.744 vs 0.734 in the 600). Grades are ranked across all three indexes, so small caps take more of the Severe grades: 31% of S&P 600 stock-months against 12% of S&P 500 ones. 9.5% of companies change grade in a month with three-month smoothing.

## Robustness checks (`models/checks.py`)

A ranker can score a positive IC by leaning on a known return pattern rather than on anything in the filings: smaller, more volatile or recently rising stocks did better in some years. Each month the prediction's rank is regressed on the ranks of size (traded dollar volume), past-year volatility, past-year return and beta, plus the stock's index, and the IC of what is left is reported next to the raw IC.

| Ranker IC | As predicted | t | Style removed | t | Stock-months with no return |
|---|---|---|---|---|---|
| All three | −0.000 | −0.0 | +0.008 | 0.4 | |
| S&P 500 | +0.016 | 0.6 | +0.020 | 0.9 | 9% |
| S&P 400 | −0.005 | −0.2 | +0.002 | 0.1 | 17% |
| S&P 600 | −0.012 | −0.3 | −0.004 | −0.1 | 16% |

The ranker leans towards volatile stocks (rank correlation 0.21 with past-year volatility, 0.11 with beta), which is why its top names are often loss-makers with Severe risk grades; removing that lean changes nothing. The share of stock-months with no return falls with time: 33% of S&P 400 rows in 2016 and 26% of S&P 600 rows in 2020, down to 7% and 10% by 2024.

## Limits

- **Survivorship.** Yahoo has no prices for companies that were acquired or went bankrupt, so their stock-months have features but no outcome and drop out of the cross-section. The share is large early in each index's history (see the table above) and shrinks towards the present. Acquired companies tend to end on a takeover premium and bankrupt ones on a large loss, so the missing rows are not a random sample; results from the years with the fewest gaps are reported separately for that reason.
- **Short histories.** Five test years for the S&P 600 and nine for the 400. A t-statistic on five yearly means is weak evidence whatever its size.
- **Many comparisons.** 29 signals × 3 indexes × 2 scopes is 174 single-signal ICs; at the 5% level about nine would clear |t| > 2 by chance alone. The single-signal tables are for reading patterns, not for picking winners.
- **One model for all three indexes.** The ranker is trained on the whole cross-section and judged inside each index; it was not tuned per index, so the per-index results are not the product of a separate search.

# Phase J: The return ranker at a one-month horizon

The return ranker found no edge ([phase-d-universe.md](phase-d-universe.md), [holdout-2025.md](holdout-2025.md)).
This phase changes the design of the test rather than tuning the model again, and fixes the rules for judging it
before any result exists. **The "Design and protocol" section was written and committed before the panel was
built**; results are added below it afterwards.

## Why a new design

The 12-month study has three weaknesses that have nothing to do with the signals:

- **Ten observations.** A 12-month return sampled every month overlaps 11 months with its neighbour, so the ten
  test years are about ten independent observations. A real but modest edge (rank IC 0.02) could not be told
  from zero, and a null result is weak for the same reason.
- **The model and the backtest disagree.** The ranker is fitted to 12-month returns; the backtest holds for one
  month.
- **No short-horizon signals.** The filings signals move once a year. The return patterns with the most evidence
  behind them at short horizons (drift after earnings, low risk, reversal) were either missing or tested against
  a 12-month return.

## Design and protocol (fixed in advance)

**Target.** The stock's return over the month after each month-end, minus SPY's. Features use information public
at the month-end, as before. The position is entered at the close of the *first trading day after* the
month-end and held to the close of the next month-end, so nothing is traded at the price the features were
computed from (this matters for the reversal and volatility signals, which bid-ask bounce flatters).

**Panel.** The study panel as it stands: the same companies and months (S&P 500 from 2011, S&P 400 from 2016,
S&P 600 from 2020), the same 34 signals, each already point-in-time. A stock-month counts when the stock has
prices through the whole target month.

**New signals.** Two families, chosen for their prior evidence at this horizon and before looking at any data:

| Signal | Definition | Expected sign |
|---|---|---|
| `ear` | Stock return minus SPY's from the close before the latest earnings 8-K (item 2.02) to the close of the trading day after it; missing if over 100 days old | + (post-earnings drift) |
| `ivol_1m` | Volatility over the past month of the part of daily returns that beta × SPY doesn't explain | − |
| `vol_1y` | Volatility of daily returns over the past year | − |
| `beta_1y` | Slope of daily returns on SPY's over the past year | − |

**Model.** The procedure of `models/ranker.py`, unchanged: LightGBM LambdaRank on within-month quintiles, every
fold choosing its tree settings, feature count and label inside its own training window, with purged validation.
Baselines as before: ridge on the ranks, the best single signal of the training window, random ranks. Training
rows are purged when their target month reaches the test year (December's row for January's fold).

**Development period.** Test years 2015–2024, walk-forward. These years have been looked at many times under the
old design, and this design may be revised while looking at them; every revision is logged below.

**Confirmatory test.** Feature months January 2025 to August 2026: 20 months whose target month has closed in the
price data (to 2 October 2026). It is run **once**, after the design is frozen, by passing
`--last-test-year 2026` to the ranker and `--last-month 2026-08-31` to the report. Nothing is changed afterwards.

- *Primary measure:* the LightGBM ranker's mean monthly rank IC across all three indexes.
- *What counts as an edge:* a development IC with t > 2 on monthly ICs, **and** a confirmatory IC that is
  positive with t > 1.7 (one-sided 5% on 20 months). Anything else is reported as no edge.
- *Secondary:* the same inside each index; the IC after removing size, volatility, momentum and beta; the
  long-short decile portfolio after 10 bps a trade, with its turnover; the ridge baseline.

**What this test can and can't show.** Twenty months measure an IC to about ±0.02 (one standard error, if
monthly ICs vary as they do in development). A true IC of 0.03 would clear the bar about half the time; one of
0.05 nearly always. So the confirmatory test can confirm a strong edge and reject a spurious one, but a weak real
edge may fail it. That is the honest size of the data.

**Already known about this period.** The months of 2025 were scored once under the old design
([holdout-2025.md](holdout-2025.md)): the 12-month ranker's IC there was −0.085. Their one-month returns have
not been looked at, but this is a second look at the same period, and should be read as one.

**Known limits carried over.** Companies that were acquired or went bankrupt have no price history (Yahoo), so
their months are missing; a stock that stops trading inside a target month drops out of that month. Costs are
a flat 10 bps a trade, which understates small-cap trading costs.

## Revision log

*(Each change made while looking at the development years, with the reason. Empty at the first commit.)*

## Results

*(Added after the runs.)*

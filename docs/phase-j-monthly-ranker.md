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

**Revision 1 (12 November 2026): a symmetric objective.** The first development run gave the LightGBM ranker a
rank IC of −0.014 (t −1.1), and a rank correlation of +0.51 between its scores and past-year volatility. The cause
is the objective, not the data: LambdaRank is scored from the top of each month's ranking down, and a volatile
stock is in the top return quintile more often than a calm one simply because it moves more (it is in the bottom
quintile more often too, which the objective cares less about). So the model learns to put volatile stocks first.
The 12-month ranker shows the same lean (+0.24). The revision fits the same trees to each stock's return
*percentile* within the month with a squared-error objective (`--objective regression`), which treats both ends of
the ranking alike. Everything else in the protocol is unchanged, including the bar. No signal was added, dropped
or re-signed.

## Results

**No edge at one month either, and the confirmatory test was not run.** The design needed a development IC with
t > 2 before its out-of-sample months would be scored. Nothing came close, so the 20 months from January 2025
stay unseen for a design that earns them.

### The panel

194,357 stock-months, 83.8% with a one-month return up to December 2024 (the rest are companies with no price
history). The new signals cover 81% (earnings reaction) and 83% (the low-risk three) of them.

### Single signals

Rank IC against next month's excess return, feature months 2011–2024 (168 months), t-statistic on monthly ICs
(`signals_1m.csv`):

| Signal | Rank IC | t | Sector-neutral IC | t |
|---|---|---|---|---|
| Leverage | +0.016 | 2.2 | +0.011 | 2.3 |
| Leverage change | +0.011 | 2.1 | +0.008 | 2.0 |
| Net margin change | −0.012 | −1.9 | −0.006 | −1.2 |
| Past month's return (reversal) | −0.017 | −1.5 | −0.009 | −1.0 |
| **Idiosyncratic volatility, 1 month** | −0.016 | −1.3 | −0.016 | −1.6 |
| **Volatility, 1 year** | −0.018 | −1.0 | −0.017 | −1.2 |
| **Earnings reaction** | +0.003 | 0.6 | +0.004 | 1.0 |
| 12-1 momentum | +0.006 | 0.4 | +0.009 | 0.8 |
| **Beta, 1 year** | −0.007 | −0.3 | −0.007 | −0.5 |

The new signals (bold) have the signs the literature expects, and none is distinguishable from zero. Two of 38
signals clear |t| = 2, which is what chance gives at the 5% level. Leverage and its change are the same two that
stood out at 12 months in large caps.

### The ranker

Test years 2015–2024, 120 months, about 118,800 stock-months (`monthly.json`, `monthly_old.json`,
`monthly_reg.json`):

| Mean monthly rank IC (t) | LambdaRank, 38 signals | LambdaRank, the old 34 | Revision 1: symmetric objective |
|---|---|---|---|
| LightGBM, all three indexes | −0.014 (−1.1) | −0.011 (−1.0) | **−0.001 (−0.1)** |
| after removing size, volatility, momentum, beta | −0.003 (−0.7) | +0.001 (0.3) | +0.000 (0.0) |
| inside S&P 500 / 400 / 600 | −0.015 / +0.001 / −0.012 | −0.011 / +0.004 / −0.010 | −0.012 / −0.006 / +0.006 |
| Ridge baseline | +0.008 (0.7) | +0.012 (1.3) | +0.008 (0.7) |
| Rank correlation of scores with past-year volatility | +0.51 | +0.35 | −0.18 |
| Long-short deciles, after 10 bps | +2.6% a year (Sharpe 0.23) | +1.0% (0.14) | −2.4% (−0.12) |
| of which 2020 | +74% | +75% | −3% |
| Monthly turnover (both legs) | 162% | 157% | 198% |

- **The ranker has no edge at this horizon.** With the symmetric objective the IC is −0.001 with a standard error
  of 0.011: an IC above about +0.016 can be ruled out at the 5% level. The ridge baseline is the best of the lot
  at +0.008, and its 5% upper bound is +0.024.
- **The new signal families did not help.** With them the LambdaRank IC is −0.014; without, −0.011.
- **Revision 1 did what it was meant to and no more.** The lean towards volatile stocks went from +0.51 to −0.18.
  That removed the negative IC, and with it the profit of 2020.
- **The earlier backtests' one good year was the objective.** Every backtest so far has made its whole return in
  2020 (+59% at 12 months, +74% here). That was the volatile stocks the LambdaRank model favoured rebounding
  after March 2020. Under the symmetric objective 2020 returns −3% and the strategy loses money after costs.
- **Turnover is the other half.** A monthly signal turns the whole book over about twice a month. At 10 bps a
  trade that costs 2.3 points a year, more than any gross return here.

### What this means for the 12-month ranker

The watchlist's ranker uses the same LambdaRank objective and shows the same lean (+0.24), which is why its top
names are often loss-makers with Severe risk grades ([phase-d-universe.md](phase-d-universe.md)). Refitting it
with the symmetric objective would remove that. It is not done here: it changes every 12-month figure already
reported, and the 2025 holdout for that design has been used.

### What the protocol got wrong

The power estimate assumed monthly ICs vary less than they do. Their standard deviation is 0.12, so 20 months
measure an IC to ±0.026, not ±0.02: the confirmatory test would have been weaker than stated. It makes no
difference to the outcome, since the development bar was not met.

## Reproduce

    uv run python -m models.monthly build
    uv run python -m models.monthly signals
    uv run python -m models.ranker --panel data/study/sp1500/panel_1m.parquet --out data/study/sp1500/predictions_1m.parquet
    uv run python -m models.ranker --panel data/study/sp1500/panel_1m.parquet --out data/study/sp1500/predictions_1m_reg.parquet --objective regression
    uv run python -m models.monthly report --predictions data/study/sp1500/predictions_1m_reg.parquet

`tests/test_monthly.py` checks the earnings reaction and low-risk measures by hand, that the target skips the
first trading day, that only December is purged from a one-month fold, and that the symmetric labels give a
volatile stock no advantage where the ranking labels' top bucket is 80% volatile stocks.

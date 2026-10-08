# Phase F: Price and insider signals

Two signal families from outside the filings' accounting numbers, added to the Signal Lab and the ranker: price
momentum, the best-documented return pattern in the literature, and open-market buying by insiders. Neither
gave the return model an edge. All results below are on feature months up to 2024; 2025 is the holdout, already
used once ([`holdout-2025.md`](holdout-2025.md)), and stays out of every comparison.

## Signals

**Price** (`signals/momentum.py`), from daily total returns up to the month-end (public the day they trade; a
month is 21 trading days):

- `mom_12_1`: return over the past twelve months, skipping the most recent month (classic 12-1 momentum)
- `rev_1m`: return over the most recent month (the short-term reversal literature expects a negative IC)
- `high_52w`: price relative to its 52-week high (1 at the high)

**Insider activity** (`signals/insider.py`), over the six months before the month-end, counting only trades filed
by the day before:

- `insider_buyers_6m`: how many directors and officers bought shares on the open market
- `insider_net_6m`: (buyers − sellers) / (buyers + sellers), from −1 to 1; missing when nobody traded

The trades come from the SEC's quarterly Form 3/4/5 data sets (`warehouse/insiders.py`): Form 4 and 4/A,
non-derivative open-market purchases (code P) and sales (code S), by directors and officers of universe companies
and their predecessors, from 2009. The load holds 86,935 purchases across 2,135 companies and 867,357 sales across
2,203. The filing date is when a trade became public, so it is the date the signal uses.

## Single signals

Rank IC against the next 12 months' excess return, feature months 2011–2024, t-statistic on yearly means
(`data/study/sp1500/signals_*.csv`):

| Signal | S&P 500 | S&P 400 | S&P 600 |
|---|---|---|---|
| Near the 52-week high | +0.010 (t 0.3) | +0.031 (t 0.7) | +0.025 (t 0.3) |
| Past month's return | +0.006 (t 0.6) | +0.016 (t 1.4) | +0.022 (t 1.3) |
| 12-1 momentum | −0.006 (t −0.2) | −0.008 (t −0.2) | +0.001 (t 0.0) |
| Insider buyers, 6 months | +0.005 (t 0.3) | +0.019 (t 1.0) | +0.018 (t 0.5) |
| Insider net buying, 6 months | +0.001 (t 0.1) | +0.015 (t 0.7) | +0.028 (t 0.6) |

None is significant. 12-1 momentum is flat, which matches its well-known weakness in US stocks since 2009 (the
2009 momentum crash, then a long period of weak returns). The past month's return has the opposite sign from
the reversal the literature expects, and isn't significant either. Insider buying is slightly positive in mid
and small caps, where the literature finds it strongest, but at t = 1 it is not distinguishable from noise.

## The ranker with them

Test years 2015–2024, the same walk-forward as before (purged folds, tuning nested in each fold):

| | Before | With price and insider signals |
|---|---|---|
| Ranker mean rank IC | −0.000 | +0.005 (t 0.2) |
| After removing size, volatility, momentum and beta | | +0.012 (t 0.6) |
| Inside S&P 500 / 400 / 600 | +0.016 / −0.005 / −0.012 | +0.018 / +0.011 / −0.002 |
| Long-short return after costs | +2.3% a year (Sharpe 0.27) | +4.5% a year (Sharpe 0.42) |
| Without 2020 | a loss | −0.3% a year |

The IC moved by 0.005, well inside the 0.06 that one signal family moved an earlier run
([`phase-d-universe.md`](phase-d-universe.md)). The backtest is still one year: 2020 returned +59%, and the other
nine years compound to −0.3% a year. The fitted model leans slightly towards last year's losers (rank correlation
with the 12-month return −0.14) and towards volatile stocks (+0.24).

The conclusion stands: no return edge from these signals in large, mid or small caps.

## Also changed

The Signal Lab's IC tables now stop at the last test year (`models/study.py --last-year`, default 2024). Before,
they included every month with a closed 12-month label, which by now reaches into 2025. That was harmless before
the holdout ran. Afterwards, it would let the holdout's months steer which signals look good. The universe study's
table was recomputed this way; its eight signals moved by up to 0.013 and none changed sign.

## Checks

`tests/test_momentum_insider.py`: momentum at known points of a synthetic series, no value without a year of
history, insider counts that ignore trades filed on or after the month-end and anything older than six months,
and the Form 4 parsing (open-market purchases and sales by directors and officers of universe companies only).

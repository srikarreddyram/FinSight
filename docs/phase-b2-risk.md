# Phase B2: Risk Engine (Module 7)

Spec: [platform PRD, Module 7](PRD.md). Built on the S&P 500 panel (2011–2026; universe pending @Srikar's sign-off), with the Signal Lab's point-in-time rules, purged walk-forward folds (purged on the 12-month risk window) and tuning inside each fold's training window only. Test years 2015–2024; 2025 is the holdout.

## Built

| Piece | File | Notes |
|---|---|---|
| Market pillar and targets | `risk/market.py` | Trailing 12-month volatility, beta to SPY, max drawdown, downside deviation, 3-month dollar volume, 12-month return. Targets over (t, t+12m]: realised volatility; severe loss = drawdown of 40% or worse. A stock whose prices stop inside the window counts as severe only if it had already fallen 40%, otherwise unknown |
| Health and quality pillars | `risk/pillars.py` | Net debt/EBITDA (negative EBITDA with net debt = worst bucket), interest coverage (no debt = full coverage), current and quick ratios, cash burn, earnings volatility (5-year ROA), dividend cuts; plus Altman Z, leverage, accruals, Beneish M from the Signal Lab |
| Disclosure pillar | `risk/pillars.py` | 10-K similarity, Risk Factors growth, MD&A Fog (Signal Lab); going-concern doubt stated as fact (hedged "could raise substantial doubt" excluded); Loughran-McDonald tone waits on the licence |
| Event pillar | `warehouse/events.py`, `risk/pillars.py` | EDGAR filing index for 805 companies (230,649 8-Ks, 2,212 10-K/As, 525 late-filing notices): late filings and amended 10-Ks in 12 months, auditor changes (8-K 4.01) and non-reliance (8-K 4.02) in 24 months, material weakness in Item 9A (negation-aware) |
| Panel | `risk/panel.py` | 93,899 stock-months; severe-loss rate 12.8%, median forward volatility 26% |
| Models, grades, report | `risk/models.py` | Scorecard; LightGBM volatility regression and class-weighted downside classifier; grade = within-month quintile of the averaged component ranks |

## Results (test years 2015–2024)

> **Correction, 2 October 2026.** Figures reported earlier used wrong prices for 71 index members (preferred shares or notes instead of common stock; see [phase-b-signals.md](phase-b-signals.md)). Everything was rebuilt. The conclusions did not change; the numbers below replace the earlier ones.

Two iterations. The first used raw features and absolute targets. The second, added after the first's test results had been seen, also lets each fold choose (on validation only) within-month ranked features and a volatility target relative to the month's median, and scores the downside model on within-month AUC, which is what a within-month grade needs. The figures are from the second iteration on corrected data.

| | Model | Trailing volatility alone | Scorecard | Altman Z alone |
|---|---|---|---|---|
| Volatility rank IC | 0.737 | **0.756** | 0.404 | – |
| Downside AUC, within month | 0.769 | **0.796** | 0.691 | 0.548 |
| Downside AUC, pooled | **0.676** | 0.639 | 0.644 | 0.522 |
| Severe-loss rate in riskiest 10% | 36.7% | **42.1%** | 31.5% | – |

Base rate of a severe loss: 15.0%. Grades change for 18.1% of companies month to month.

**Calibration: monotonic at every step.**

| Grade | Stock-months | Realised volatility | Severe-loss rate |
|---|---|---|---|
| Low | 11,998 | 23.0% | 5.4% |
| Moderate | 11,925 | 26.8% | 9.3% |
| Elevated | 11,932 | 29.9% | 12.5% |
| High | 11,925 | 32.9% | 16.1% |
| Severe | 11,988 | 42.0% | 33.0% |

**What this says.** Among S&P 500 large caps, trailing volatility is the best single risk measure, and the filing pillars do not add to it out of sample: the models beat the scorecard and Altman Z clearly but not trailing volatility within a month, so they fail the PRD's bar (downside AUC is also short of the 0.70 pooled target at 0.676). The grade still sorts risk well (the calibration table), but that is largely trailing volatility's doing.

- By year: 2019's forward windows run into the 2020 crash (49% severe), and both the model and trailing volatility are weakest there (within-month AUC 0.66). Trailing volatility's pooled AUC in 2020 is 0.29, because the crash hit calm stocks too; within the month it still sorts well (0.83).
- By sector (pooled AUC): weakest in Real Estate (0.43), Energy (0.51), Financials (0.55), where leverage and liquidity ratios mean something different; strongest in Communication Services (0.79), IT (0.75), Consumer Staples (0.74), Health Care (0.73).
- Altman Z alone is close to random (0.52–0.55), as expected outside manufacturers.

## Next (needs a decision)

1. Make trailing volatility a candidate the folds can choose, or blend model and trailing volatility with a weight chosen on validation. This nests the baseline, so the grade can't do worse than it; it is another change after seeing test years, so it would be iteration 3 and disclosed as such.
2. Sector-specific measures for banks, REITs and energy (capital ratios, FFO, reserves), where generic ratios fail.
3. Loughran-McDonald tone (licence decision pending).
4. Grade stability: smooth the grade (e.g. three-month average of component ranks) and report the trade-off with calibration.

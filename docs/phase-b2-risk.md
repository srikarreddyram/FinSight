# Phase B2: Risk Engine (Module 7)

Spec: [platform PRD, Module 7](PRD.md). Built on the S&P 500 panel (2011–2026; universe pending @Srikar's sign-off), with the Signal Lab's point-in-time rules, purged walk-forward folds (purged on the 12-month risk window) and tuning inside each fold's training window only. Test years 2015–2024; 2025 is the holdout.

## Built

| Piece | File | Notes |
|---|---|---|
| Market pillar and targets | `risk/market.py` | Trailing 12-month volatility, beta to SPY, max drawdown, downside deviation, 3-month dollar volume, 12-month return. Targets over (t, t+12m]: realised volatility; severe loss = drawdown of 40% or worse. A stock whose prices stop inside the window counts as severe only if it had already fallen 40%, otherwise unknown |
| Health and quality pillars | `risk/pillars.py` | Net debt/EBITDA (negative EBITDA with net debt = worst bucket), interest coverage (no debt = full coverage), current and quick ratios, cash burn, earnings volatility (5-year ROA), dividend cuts; plus Altman Z, leverage, accruals, Beneish M from the Signal Lab |
| Disclosure pillar | `risk/pillars.py` | 10-K similarity, Risk Factors growth, MD&A Fog (Signal Lab); going-concern doubt stated as fact (hedged "could raise substantial doubt" excluded); Loughran-McDonald tone waits on the licence |
| Event pillar | `warehouse/events.py`, `risk/pillars.py` | EDGAR filing index for 805 companies (230,649 8-Ks, 2,212 10-K/As, 525 late-filing notices): late filings and amended 10-Ks in 12 months, auditor changes (8-K 4.01) and non-reliance (8-K 4.02) in 24 months, material weakness in Item 9A (negation-aware) |
| Panel | `risk/panel.py` | 94,090 stock-months; severe-loss rate 12.7%, median forward volatility 26% |
| Models, grades, report | `risk/models.py` | Scorecard; LightGBM volatility regression and class-weighted downside classifier, each blended with trailing volatility at a weight chosen on validation; grade = within-month quintile of the averaged component ranks, smoothed over three months |

## Results (test years 2015–2024)

> **Correction, 2 October 2026.** Figures reported earlier used wrong prices for 71 index members (preferred shares or notes instead of common stock; see [phase-b-signals.md](phase-b-signals.md)). Everything was rebuilt. The conclusions did not change; the numbers below replace the earlier ones.

Three iterations, each added after the previous one's test-year results had been seen, and each choosing its options inside the training window on validation only:

1. Raw features, absolute targets.
2. Each fold may use within-month ranked features and a volatility target relative to the month's median; the downside model is scored on within-month AUC, which is what a within-month grade needs.
3. Each fold also chooses how much weight the model gets in a blend of its within-month rank with trailing volatility's (1, 0.75, 0.5, 0.25 or 0). A weight of 0 is trailing volatility alone, so what the grade uses is never chosen to be worse than the baseline. The grade is cut from the latest three months' average of the combined rank (past months only).

The figures are from the third iteration, on corrected data with predecessor companies linked.

| | Used in grades (blend) | Model alone | Trailing volatility alone | Scorecard | Altman Z alone |
|---|---|---|---|---|---|
| Volatility rank IC | **0.760** | 0.744 | 0.755 | 0.400 | – |
| Downside AUC, within month | **0.796** | 0.771 | 0.794 | 0.685 | 0.551 |
| Downside AUC, pooled | **0.709** | 0.688 | 0.637 | 0.640 | 0.527 |
| Severe-loss rate in riskiest 10% | 40.2% | 36.6% | **41.2%** | 30.0% | – |

Base rate of a severe loss: 14.9%. The folds chose model weights between 0.25 and 1.0 for volatility and between 0 and 0.5 for downside (0 in 2024: trailing volatility alone).

**Calibration: monotonic at every step.**

| Grade | Stock-months | Realised volatility | Severe-loss rate |
|---|---|---|---|
| Low | 12,000 | 22.9% | 5.6% |
| Moderate | 11,945 | 26.5% | 8.9% |
| Elevated | 11,938 | 29.7% | 12.7% |
| High | 11,945 | 32.8% | 15.7% |
| Severe | 11,998 | 41.9% | 32.3% |

**Stability.** Smoothing costs almost nothing in sharpness, so three months is in use.

| Smoothing | Grades that change each month | Severe-loss rate, Low | Severe-loss rate, Severe |
|---|---|---|---|
| None | 14.2% | 5.6% | 32.5% |
| 3 months (in use) | 10.0% | 5.6% | 32.3% |
| 6 months | 7.7% | 5.5% | 31.9% |

**What this says.** The blend is at least as good as trailing volatility on volatility and on within-month downside ranking, but by margins (0.005 and 0.002) too small to call a win, and it is slightly behind in the riskiest 10%. On its own the model is behind trailing volatility. So the PRD's bar is met only in the weakest sense: the filing pillars add little to what a stock's own past-year volatility already says. Pooled downside AUC does clear the 0.70 target (0.709), because the model is better than trailing volatility at telling bad years from good ones (trailing volatility's pooled AUC is 0.637).

- By year: 2019's forward windows run into the 2020 crash (49% severe), and everything is weakest there (within-month AUC 0.66).
- By sector (pooled AUC of the blend): weakest in Real Estate (0.36, below a coin flip, and trailing volatility is no better at 0.38), Financials (0.54) and Energy (0.59), where leverage and liquidity ratios mean something different; strongest in Communication Services (0.79), IT (0.78), Health Care (0.76) and Consumer Staples (0.75).
- Altman Z alone is close to random (0.53–0.55), as expected outside manufacturers.

## Next

1. Sector-specific measures for real-estate trusts, banks and energy (funds from operations, capital ratios, reserves), where the grade is weakest and Real Estate is worse than a coin flip.
2. Loughran-McDonald tone (licence decision pending).
3. The one-time 2025 holdout evaluation, once the modelling choices are frozen.

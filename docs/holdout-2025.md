# The 2025 holdout

The [platform PRD](PRD.md) keeps the most recent full year out of every development run and scores it once, at
the end, with the procedure fixed. Development stopped at test year 2024 (`--last-test-year 2024`). On 6 October
2026 the holdout was run once, on the S&P 500, 400 and 600 panel:

    uv run python -m models.ranker --first-test-year 2025 --last-test-year 2025 --out …/predictions_holdout_2025.parquet
    uv run python -m models.backtest --predictions …/predictions_holdout_2025.parquet --q 0.1
    uv run python -m risk.models --first-test-year 2025 --last-test-year 2025 --out …/risk_predictions_holdout_2025.parquet

One fold, trained on every stock-month whose 12-month outcome ended before 1 January 2025, with the same nested
tuning as the walk-forward folds. Prices run to 5 October 2026, so the months with a complete 12-month outcome are
January to August 2025 (about 18,000 stock-months). Nothing was tuned after seeing these numbers, and the dashboard
still shows the 2015–2024 results.

## Return ranker

| Mean rank IC, Jan–Aug 2025 | All three | Inside S&P 500 | Inside S&P 400 | Inside S&P 600 |
|---|---|---|---|---|
| LightGBM ranker | −0.085 | −0.080 | −0.117 | −0.070 |
| Ridge regression | −0.037 | −0.038 | −0.079 | +0.001 |
| Best single signal | +0.032 | +0.061 | +0.003 | +0.001 |
| F-score alone | −0.103 | −0.149 | −0.162 | −0.010 |
| Random ranks | −0.002 | | | |

The ranker pointed the wrong way in 2025. Its monthly long-short portfolio (top and bottom tenths, 10 bps) made
+3.3% annualised after costs over the eight months (Sharpe 0.43), a different horizon from the 12-month IC and
well within noise. The conclusion from the test years stands out of sample: **no edge**.

## Risk engine

| Grade | Low | Moderate | Elevated | High | Severe |
|---|---|---|---|---|---|
| Fell 40%+ within 12 months | 5.7% | 10.5% | 15.3% | 24.9% | 50.9% |
| Realised volatility | 24% | 30% | 36% | 44% | 60% |

| | Used in grades | Model alone | Trailing volatility alone |
|---|---|---|---|
| Volatility rank IC | 0.853 | 0.853 | 0.841 |
| Downside AUC, within month | 0.762 | 0.757 | 0.759 |
| Severe-loss rate, riskiest 10% | 60.5% | 59.3% | 58.8% |

The grades sort risk cleanly out of sample, every step in order, and the blend sits at or slightly above trailing
volatility on every measure, the same picture as the test years: well calibrated, but most of the information is
in the stock's own past volatility. With three-month smoothing, 7.1% of companies changed grade in a month.

## What this closes

Both models' results are now final for this design. The return ranker's null result is confirmed on a year it never
saw; the risk grades' calibration is confirmed too. Further work on returns goes into new signal families (momentum,
insider buying) rather than more tuning of these.

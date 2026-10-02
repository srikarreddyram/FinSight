# Phase C: Recommendation Layer and dashboard (Module 6)

Spec: [platform PRD, Module 6](PRD.md). The output is a ranked research watchlist where every score comes with its reasons; it never says "buy".

## Built

| Piece | File | Notes |
|---|---|---|
| Latest-month scoring | `recs/build.py` | Refits the return ranker and both risk models on every stock-month with a known 12-month outcome (same tuning and feature selection as a walk-forward fold) and scores the newest month. Writes `data/recs/*.json` |
| Drivers | `recs/build.py`, `recs/labels.py` | The three largest SHAP contributions per stock (exact for trees, from LightGBM itself) in plain words. A signal's market and sector versions count as one driver; an event that didn't happen is never listed |
| Confidence band | `recs/build.py` | What stocks in the same predicted decile actually returned in the walk-forward test years (quartiles of 12-month excess return) |
| Risk components | `recs/build.py` | Realised volatility and severe-loss rate of the same predicted decile in the test years. The classifier's raw scores are class-weighted, so they are never shown as probabilities |
| API | `recs/api.py` | `/recs/meta`, `/recs/watchlist`, `/recs/company/{ticker}`, `/recs/signals`, `/recs/backtest`, `/recs/risk`, mounted on the Copilot's FastAPI app |
| Dashboard | `web/src/pages/` | Watchlist (filters by sector, risk grade, market cap; risk-adjusted view), Company, Signal Lab, Backtest, Risk, Methodology, behind a hash router; the Copilot stays at `/` |
| Charts | `web/src/charts/` | Line, column, heatmap and stacked bars in plain SVG/HTML: crosshair or per-mark hover, keyboard focus, a legend for two or more series, and a table view of the same numbers |

Run it: `uv run python -m recs.build`, `uv run uvicorn app.api:app`, and `npm run dev` in `web/`. `FINSIGHT_THREADS` caps the threads and workers the builds use (default 6; 3 keeps a laptop cool and was no slower).

## Design decisions

- **Honesty in the product.** With corrected prices the return model has no proven edge, so the Watchlist, Company and Methodology pages say so directly, and the Risk page states that the models do not beat trailing volatility. Every page carries the research-and-education disclaimer.
- **Chart colours are validated, not picked.** A positive/negative pair and a five-step single-hue ramp for the ordered risk grades, each checked for colour-blind separation and contrast on the light and dark card surfaces. Grades always show their number and name beside the colour.
- **Baselines in one gray.** On the backtest chart the question is whether the ranker separates from the baselines, so they share the de-emphasis colour and the table view names each one.

## Not built (stated on the Company page)

- The Analyst Agent's cited thesis (Module 2 is still a side track).
- The XBRL cross-check status for each figure shown.
- The Copilot chat is offered only for companies whose filings are in its index (the FinanceBench set).

## Checks

- `tests/test_recs.py`, `tests/test_recs_api.py`: formats, deciles, driver merging and non-event filtering, API payloads and nulls, 404 and not-built responses.
- Pages reviewed in a browser in light and dark mode. The light-mode check caught the grade colours being dropped by Tailwind's theme tree-shaking (the variable names are computed), fixed by defining them in plain `:root`.

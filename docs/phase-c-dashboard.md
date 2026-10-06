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
| Dashboard | `web/src/pages/` | Watchlist (filters by sector, index, risk grade, market cap; risk-adjusted view), Company, Signal Lab, Backtest, Risk, behind a hash router; the Copilot stays at `/` |
| Charts | `web/src/charts/` | Line, column, heatmap and stacked bars in plain SVG/HTML: crosshair or per-mark hover, keyboard focus, a legend for two or more series, and a table view of the same numbers |

Run it: `uv run python -m recs.build`, `uv run uvicorn app.api:app`, and `npm run dev` in `web/`. `FINSIGHT_THREADS` caps the threads and workers the builds use (default 6; 3 keeps a laptop cool and was no slower).

Since [Phase D](phase-d-universe.md) the dashboard runs on the S&P 500, 400 and 600 (about 1,500 companies): the Watchlist has an index column and filter, the Signal Lab can show the study inside one index, and the Backtest and Risk pages add a table of the same test inside each index, with the style-neutral ICs and survivorship gaps from `models/checks.py`.

## Interface

The web app is one product with a fixed left rail and a top bar, not a set of separate pages:

- **Navigation.** Styled after consumer investing apps (Groww was the reference): a white top bar with text tabs (Copilot, Watchlist, Movers, Signal Lab, Backtest, Risk) underlined in green, a wide search, the filing library, a theme button and the API status. On phones it becomes a slim top bar and a bottom tab bar (Copilot, Watchlist, Movers, Risk, More).
- **Look.** White surfaces, mint green as the brand and gain colour, coral red for losses (both checked for colour-blind separation and contrast in light and dark), rounded cards without shadows, pill buttons for time ranges and views, and company avatars made from initials.
- **Search (⌘K or Ctrl+K).** Finds any of the ~1,500 companies by ticker or name, jumps to any page, or hands the text to the Copilot as a question. Arrow keys and Enter, Escape to close.
- **Theme.** Light, dark or follow the OS, chosen in the sidebar and remembered per browser; applied before first paint, so a reload never flashes the other theme.
- **Type and controls.** Inter throughout, with tabular figures in numeric columns and a true minus sign for negatives; JetBrains Mono only for commands and IDs. One set of controls (`.control`, `.btn`, `.chip` in `index.css`, `Segmented`, `Badge`, `Panel` in `design/primitives.tsx`), so every filter and button behaves the same.
- **Watchlist.** Sortable, 50 rows a page, whole rows open the company page, a clear-filters action and an empty state, and CSV export of exactly the filtered rows.
- **Company page.** An avatar header with ticker, index, sector and market cap, the live price and the day's change, then tabs: Overview (key figures, drivers, rank and grade history), Price move & news (see [phase-e-news.md](phase-e-news.md)) and Signals.
- **No explanations in the app.** Pages show titles, figures, charts, tables and actions only; there is no methodology page, no captions explaining the models, no validation verdicts and no pipeline trace in the Copilot (it always runs the full pipeline, E). How the numbers are made, their caveats and the honest model results live in these docs. The footer carries one line: "For research only. Not investment advice."
- **Copilot.** An ask box, example questions and recent questions; the answer with its verified-figure badges and page citations beside the source page, rows used highlighted.
- **Loading and errors.** Skeletons in the shape of the page while data loads; an error names what to check (the API, or the data build) rather than "something went wrong".
- **Keyboard and motion.** Every control is reachable by keyboard with a visible focus ring; drawers and dialogs close with Escape; motion is short and switched off under reduced-motion settings.

- **Price chart.** 1M / 6M / 1Y / 5Y on every company page, green when the range ended up and red when down, with the days the company reported earnings (8-K item 2.02) marked.
- **Hosted demo.** [srikarreddyram.github.io/FinSight](https://srikarreddyram.github.io/FinSight/) is the same build reading a static snapshot (`web/src/demo.ts`, `scripts/build_demo.py`, `scripts/deploy_demo.sh`): every company page with a year of prices, the Movers lists, about 90 price-move panels with 40 AI explanations, and the Copilot's example answers with their cited pages. Histories are stored as columns (about 25 KB a company instead of 140), and anything outside the snapshot says it needs a local run.

Checked by screenshots of every page in light and dark at desktop width, phone layouts at 390px, the search palette, the mobile menu, the library drawer and an answered Copilot question.

## Design decisions

- **Honesty lives in the docs.** The return model has no proven edge and the risk grades add little to trailing volatility; [phase-b-signals.md](phase-b-signals.md), [phase-b2-risk.md](phase-b2-risk.md) and [phase-d-universe.md](phase-d-universe.md) say so with the numbers and baselines. The app itself is kept to the product (an earlier version explained all of this on every page; that was removed at the user's request).
- **Chart colours are validated, not picked.** A positive/negative pair and a five-step single-hue ramp for the ordered risk grades, each checked for colour-blind separation and contrast on the light and dark card surfaces. Grades always show their number and name beside the colour.
- **Baselines in one gray.** On the backtest chart the question is whether the ranker separates from the baselines, so they share the de-emphasis colour and the table view names each one.

## Not built

- The Analyst Agent's cited thesis (Module 2 is still a side track).
- The XBRL cross-check status for each figure shown.
- The Copilot chat is offered only for companies whose filings are in its index (the FinanceBench set).

## Checks

- `tests/test_recs.py`, `tests/test_recs_api.py`: formats, deciles, driver merging and non-event filtering, API payloads and nulls, 404 and not-built responses.
- Pages reviewed by screenshot in light and dark mode, at desktop width and in a 390px phone frame. The light-mode check caught the grade colours being dropped by Tailwind's theme tree-shaking (the variable names are computed), fixed by defining them in plain `:root`.

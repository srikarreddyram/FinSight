# PRD: FinSight Platform — Filings-Driven Investment Research

Sep 29, 2026 · @Srikar

## Overview

FinSight grows from a filings Q&A copilot into an investment research platform. It turns SEC filings into verified answers, backtested stock rankings, investment risk grades, and cited investment theses. The existing copilot becomes Module 1 of seven; its spec lives in [PRD-copilot.md](PRD-copilot.md).

**The research question.** Do signals in company filings predict which stocks outperform over the next 6–12 months, and how confident can we be? The platform is built to answer that honestly, with a walk-forward backtest, not to claim it can predict prices.

**Why this framing.** Student "stock predictor" projects usually report inflated accuracy from look-ahead bias, and interviewers know it. A small, properly measured edge, plus a clear account of where the model fails, is the stronger result.

**Grounding in research.** Cohen, Malloy and Nguyen's "Lazy Prices" paper found that firms which change their 10-K language tend to underperform afterwards. The Signal Lab tests that finding on our own data alongside classic accounting scores.

**Target users.**

- Equity research analysts and students screening companies
- Interviewers at banks, analytics consultancies and fintechs reviewing the work

**One-line pitch.** "An investment research platform that turns SEC filings into verified answers, explainable stock rankings, risk grades and cited theses, backtested walk-forward over 10+ years."

## Goals, non-goals, success metrics

The platform succeeds if the backtest is trustworthy, whatever the size of the edge: a clean null result, reported honestly, still counts.

**Goals**

- Store fundamentals and filing text point-in-time, stamped with the date each filing became public
- Build explainable signals from filing numbers and filing language
- Rank stocks by expected 12-month excess return, validated walk-forward
- Grade every company's investment risk (volatility and downside) from its filings and price history, validated against what actually happened
- Explain every ranking with feature attributions and a cited thesis tied to filing pages
- Keep the Research Copilot and Analyst Agent as the verified evidence layer under every recommendation

**Non-goals**

- No live trading, broker integration or real money
- No personalised financial advice: the output is a research watchlist, labelled as such
- No intraday or price-pattern models; signals come from filings only, prices are only the target

**Headline metrics**

| Metric | What it tells you | Credible target |
|---|---|---|
| Rank information coefficient (IC), monthly | Correlation between predicted and actual return ranks | Mean 0.02–0.05, positive in most years |
| Top-minus-bottom decile spread | Annual return gap between highest- and lowest-ranked stocks | Positive after costs |
| Long-short Sharpe ratio, after costs | Risk-adjusted return of the spread portfolio | Above 0.5 |
| Risk grade calibration | Realised volatility and severe-loss rate by risk grade | Both rise with every grade |
| Volatility model rank IC | Predicted versus realised 12-month volatility ranks | Above 0.5, and above trailing volatility alone |
| Downside model AUC | How well it flags future 40%+ drawdowns or delistings | Above 0.70, and above the hand-weighted scorecard |
| Copilot answer accuracy (FinanceBench) | Evidence-layer quality | Reported, per the Copilot PRD |

> If a backtest shows a Sharpe above 2 or an IC above 0.10, treat it as a bug until proven otherwise.

## Platform architecture

Seven modules sit on three free data sources; the Copilot and the Warehouse are the evidence layer, and every recommendation traces back through them to a filing page.

```
 SEC EDGAR filings      SEC XBRL companyfacts      Prices (yfinance)
        │                        │                           │
        ▼                        ▼                           │
 M1 Research Copilot ──▶ M3 Fundamentals Warehouse ◀─────────┘
   (parsed filings,        (point-in-time facts,
    sections, citations)    filing_text, prices)
        │                        │
        │                        ▼
        │                 M4 Signal Lab (~40 features)
        │                   │                  │
        │                   ▼                  ▼
        │   M5 Prediction Engine        M7 Risk Engine
        │   (return ranker, backtest)   (volatility + downside → grade 1–5)
        │                   │  SHAP drivers    │
        ▼                   ▼                  ▼
 M2 Analyst Agent ─────▶ M6 Recommendation Layer + dashboard
   (cited thesis per stock)
```
The Analyst Agent runs as a side track: it reuses the Copilot and writes the cited thesis attached to each ranked stock.

## Modules 1 and 2: Research Copilot and Analyst Agent

Module 1 is built and only needs its answer-accuracy benchmark; Module 2 grows alongside the rest as a side track.

**M1 Research Copilot (built).** Cited, verified Q&A over 10-Ks, 10-Qs and earnings calls, specified in [PRD-copilot.md](PRD-copilot.md): Docling parsing, hybrid search, reranking, an evidence gate, and Python-verified numbers. Retrieval recall@10 is 83% versus 41% for naive RAG.

- Remaining: the FinanceBench answer-accuracy run on free Gemini quota
- New role in the platform: the parsed filings and section tags it stores feed the Signal Lab's text signals

**M2 Analyst Agent (side track).** Answers open-ended questions ("Is 3M's dividend sustainable?") with a one-page memo where every line is cited and verified.

1. A planner splits the question into 4–6 sub-questions (payout ratio, free cash flow trend, debt maturities, management commentary).
2. Each sub-question runs through the Copilot, inheriting its citations and number checks.
3. Ratios come from the Warehouse, not from the model.
4. A writer assembles the memo; any sentence without a source is removed.

In the platform, the Agent writes the thesis shown next to each ranked stock, taking the model's top SHAP drivers as its sub-questions.

## Module 3: Fundamentals Warehouse

The Warehouse stores every financial fact with the date the market could first see it; this single rule is what makes the backtest honest.

**Universe.** About 500 US large and mid caps, 2010 to today. Include companies that were later delisted or acquired, so the backtest isn't limited to survivors.

**Tables (DuckDB)**

| Table | Grain | Key columns |
|---|---|---|
| `companies` | one row per company | cik, ticker history, sector, listed_from, delisted_on |
| `filings` | one row per filing | cik, form (10-K, 10-Q), period_end, filed_at (public date), accession number |
| `facts` | one row per XBRL value per filing | cik, concept (e.g. Revenues), value, unit, period_start, period_end, filed_at |
| `prices` | one row per ticker per day | raw close, daily total return, raw volume (values that never change after the fact; see the Phase A spec) |
| `filing_text` | one row per filing section | section (Risk Factors, MD&A), cleaned text, word count |

**Point-in-time rule.** A feature for date *t* may only use facts with `filed_at` before *t*. Restated numbers are stored as new rows, never overwriting the original, so the model sees what investors saw at the time.

**XBRL cross-check.** Each number the Copilot extracts from a PDF is compared with the matching XBRL value and tagged *matches*, *differs* or *no tag*. The same data auto-generates hundreds of numeric Q&A pairs ("What was Nike's FY2018 revenue?") with gold answers, extending the Copilot's eval without hand-labelling.

**Data access.** The SEC's free XBRL companyfacts endpoint returns a company's full fact history as JSON; it needs the same User-Agent header the Copilot already uses and allows about 10 requests per second.

## Module 4: Signal Lab

The Signal Lab turns filings into about 40 features in four families, each tested on its own before it enters the model.

| Family | Feature | Built from | Idea behind it |
|---|---|---|---|
| Accounting quality | Piotroski F-score (0–9) | XBRL facts | Improving profitability, leverage and efficiency |
| Accounting quality | Altman Z-score | XBRL facts + market cap | Bankruptcy and distress risk |
| Accounting quality | Beneish M-score | XBRL facts | Likelihood of earnings manipulation |
| Accounting quality | Accruals ratio | XBRL facts | Earnings backed by cash versus accounting choices |
| Fundamentals | Growth, margins, ROE, leverage, their year-over-year changes | XBRL facts | Standard fundamental factors |
| Valuation | Earnings yield, book-to-market, free-cash-flow yield | XBRL facts + prices | Cheap versus expensive, as a control |
| Filing text | 10-K similarity to last year (cosine, Jaccard) | filing_text | "Lazy Prices": big changes tend to precede underperformance |
| Filing text | Loughran-McDonald sentiment (negative, uncertainty, litigious word shares) | filing_text | Finance-specific tone, not general sentiment |
| Filing text | New risk factors count, removed risk factors count | Risk Factors sections | What management started warning about |
| Filing text | Readability (Fog index), length change | filing_text | Obfuscation hypothesis |
| Management (stretch) | Guidance hit rate: past guidance versus reported actuals | Earnings calls + facts | Management credibility |

**Processing rules.** Each feature is ranked within its month across the universe (0–1 percentile) so the model learns relative position, not raw scale. Sector-neutral versions are kept alongside, because an F-score of 7 means different things for a bank and a retailer.

**Single-signal tests.** Before modelling, each feature gets its own monthly rank IC and decile spread over the full history. This produces the "which signals actually work" chart, a strong result by itself even if the combined model disappoints.

## Module 5: Prediction Engine

The return ranker runs on the Signal Lab's features. The distress model first planned here became the downside half of the Risk Engine (Module 7).

**Return ranker.** Predicts each stock's rank on 12-month return in excess of the S&P 500, measured from the month after its filing. LightGBM with a ranking objective (LambdaRank), grouped by month. Baselines to beat: a single-factor model (F-score alone), a linear model on the same features, and random ranks.

**Backtest protocol**

- Rebalance monthly: rank the universe on data public by month end, form equal-weight top-decile and bottom-decile portfolios, hold one month
- Deduct 10 basis points per trade for costs; report results before and after
- Tune hyperparameters only inside each fold's training window (nested), never on test years
- Report per-year IC and spread, not just the average, so bad years stay visible

**Explainability.** SHAP values per stock per month feed the Recommendation Layer and the Agent's thesis.

## Module 6: Recommendation Layer and dashboard

The output is a ranked research watchlist where every score comes with its reasons and the filing pages behind them; it never says "buy".

**Per-stock card**

- Return rank (percentile), with the model's confidence band from the backtest
- Risk grade (1–5) with its two components, expected volatility and severe-loss probability, and the pillar driving it
- Top 3 SHAP drivers in plain words ("F-score improved from 4 to 7", "10-K Risk Factors changed 38% versus last year")
- A cited thesis from the Analyst Agent, with each claim linked to its filing page
- XBRL cross-check status for every number shown

**Dashboard pages (React + TypeScript, extending the Copilot web app)**

| Page | What it shows |
|---|---|
| Watchlist | Universe ranked this month; filters by sector, risk grade, market cap; a risk-adjusted view that ranks within each risk grade |
| Company | Card above, signal history over time, and the Copilot chat scoped to that company |
| Signal Lab | IC and decile spread per signal, per year |
| Backtest | Cumulative long-short return, drawdowns, per-year table, before and after costs |
| Risk | Grade distribution this month, the calibration table (realised volatility and severe-loss rate by grade), pillar breakdown, grade changes |
| Methodology | Point-in-time rules, universe, known biases, disclaimer |

**Framing.** Every page carries a line stating this is a research and education tool, not personal financial advice. There is no risk-profile questionnaire or position sizing in v1.

## Module 7: Risk Engine

Grades every company's investment risk each month on a 1–5 scale (Low, Moderate, Elevated, High, Severe) from its filings and price history. It serves the Recommendation Layer: the grade sits next to each return rank on the watchlist and drives the risk filters and the risk-adjusted view. It is a research measure, not a credit rating, so it never uses AAA-style letters. Built after Phase B on the Signal Lab's features; it replaces the distress model first planned in Module 5.

**Two components, one grade**

- **Volatility:** expected annualised volatility of the stock over the next 12 months
- **Downside risk:** probability of a severe loss over the next 12 months, meaning a drawdown of more than 40% or a delisting for cause
- **Grade:** each component is ranked within the month's universe, the two ranks are averaged, and the result is cut into quintiles. The card always shows both components, so the grade never hides which one drives it.

**Five pillars of inputs**, all point-in-time through the Warehouse

| Pillar | Measures | Built from |
|---|---|---|
| Financial health | Leverage, net debt to EBITDA, interest coverage, current and quick ratios, cash burn, Altman Z-score | XBRL facts + market cap |
| Earnings quality | Accruals ratio, Beneish M-score, earnings volatility, dividend cuts | XBRL facts |
| Market risk | Trailing 12-month volatility, beta to the S&P 500, maximum drawdown, downside deviation, dollar volume | Prices |
| Disclosure risk | New and removed risk factors, Loughran-McDonald negative and uncertainty tone, 10-K change versus last year, going-concern language | filing_text |
| Event risk | Late-filing notices (NT 10-K), amended 10-Ks, auditor changes (8-K Item 4.01), non-reliance on past financials (8-K Item 4.02), material weaknesses (Item 9A) | EDGAR filing index + filing_text |

**Combining the pillars: a validated model**

- **Baseline scorecard:** each measure ranked within the month, averaged within its pillar, pillars averaged. Transparent, and the benchmark the models must beat.
- **Volatility model:** LightGBM regression on the pillar measures, target realised 12-month volatility. It must also beat trailing volatility alone, a strong baseline because volatility persists.
- **Downside model:** LightGBM classifier with class weights, target a severe loss within 12 months. It must beat the scorecard and Altman Z alone.
- Same panel, point-in-time features, purged walk-forward folds and nested tuning as Module 5; SHAP drivers per company per month become plain-language reasons linked to filing pages through the Copilot.

**Validation**

- Realised volatility and the severe-loss rate rise with every grade: the calibration table, the headline chart
- Volatility: rank IC between predicted and realised 12-month volatility; downside: AUC and precision in the riskiest 10%
- Results by year (including 2020) and by sector
- Grade stability: how often a company changes grade month to month, since grades that jump around are no use for recommendations

## Data sources and tech stack

Everything stays free: public SEC data, free price history, and the free Gemini and Ollama setup the Copilot already uses.

| Layer | Choice | Notes |
|---|---|---|
| Filings text | SEC EDGAR 10-K HTML, split into Items | The Copilot's 84 parsed filings are the test set; the universe's ~7,500 10-Ks come from EDGAR HTML (Docling at ~2 min per filing is too slow) |
| Financial facts | SEC XBRL companyfacts API | JSON per company; User-Agent header required |
| Prices | yfinance | Daily total returns and raw closes cached to Parquet, append-only. Stooq now sits behind a browser challenge, so there is no scripted backup |
| Sentiment lexicon | Loughran-McDonald master dictionary | Free for academic use |
| Storage | DuckDB + Parquet | Fast analytics on a laptop, no server |
| Vector search | Qdrant | Existing Copilot index |
| Modelling | LightGBM, scikit-learn, SHAP | Ranker, classifier, explanations |
| Backtesting | Custom vectorised engine in pandas | Small enough to own and explain; no black-box library |
| Pipelines | Prefect (or plain Makefile) | Monthly refresh: fetch, features, score |
| LLM | Gemini free tier, Gemma via Ollama | Agent and Copilot only; never used for numbers |
| Backend / frontend | FastAPI, React + TypeScript | Extends the existing Copilot app |
| Experiment tracking | MLflow (local) | Every backtest run logged with its config |

## Bias guardrails and evaluation

Each known way a backtest lies gets a named guard and an automated test; interviewers will ask about these by name.

| Bias | What goes wrong | Guard |
|---|---|---|
| Look-ahead | Using numbers before they were public | Features join on `filed_at`; a unit test fails if any feature date precedes its filing date |
| Survivorship | Testing only on companies that still exist | Universe includes delisted firms; report how many and their return treatment |
| Restatement | Using corrected numbers investors didn't have | Keep the first-reported value; restatements are new rows |
| Data snooping | Trying many features until one looks good | Fix the feature list before the first test-year run; report every signal tested, including failures |
| Overfitting | Tuning on test years | Nested tuning inside each training window only |
| Cost blindness | Ignoring trading costs and turnover | 10 bps per trade deducted; turnover reported |
| Leaky target | Return window overlapping the feature window | Returns measured from the month after the filing date, with a 1-month embargo |

**Sanity checks run on every backtest**

- Shuffle the target: IC must fall to about zero
- Random ranks as a baseline portfolio
- Results by sector and by year, to catch one sector or one year carrying everything
- A holdout of the most recent year, run once, at the very end

**Also evaluated.** The Copilot's FinanceBench score, the XBRL cross-check agreement rate, and a manual review of 20 Agent theses for unsupported claims.

## Phased roadmap and repo layout

Four phases of about 13 weeks in total, each ending in something you can demo, with the Agent growing alongside.

| Phase | Scope | Demo at the end | Exit criteria | Weeks |
|---|---|---|---|---|
| A — Warehouse | M3: universe incl. delisted names, point-in-time XBRL facts, filings, prices, filing_text; XBRL cross-check and auto-generated numeric Q&A. M1's FinanceBench accuracy run finishes here. | "What did investors know about company X on date t?" plus the cross-check agreement rate | Look-ahead and restatement tests pass; 20 companies hand-checked against their 10-Ks | 1–4 |
| B — Signals and models | M4 single-signal study, then M5 return ranker and walk-forward backtest with every sanity check; runs logged in MLflow | "Which signals actually work" chart and the backtest report, before and after costs | Feature list and backtest config frozen by @Srikar before the first test-year run; shuffled-target IC ≈ 0 | 5–9 |
| B2 — Risk Engine | M7 pillars, scorecard baseline, volatility and downside models, grades 1–5 | The calibration table: realised volatility and severe-loss rate by grade | Both rise with every grade; each model beats its baseline out of sample | 10–11 |
| C — Recommendation layer | M6 watchlist with return rank and risk grade, company card, SHAP drivers in plain words, Signal Lab, Backtest, Risk and Methodology pages in the existing web app | Ranked watchlist with a risk grade and a cited thesis per stock | Disclaimer on every page; 20 theses reviewed for unsupported claims | 12–13 |
| Side track — Agent | M2 planner and memo writer on top of the Copilot | A cited memo for an open-ended question | Never blocks Phase B | throughout |

Each phase gets its own spec in `docs/` (`docs/phase-a-warehouse.md` first).

The Copilot keeps its current packages (`app/`, `ingest/`, `eval/`) rather than moving into `copilot/`; the new modules sit beside it:

```
finsight/
├── app/                # Module 1 Copilot: query path, API (existing)
├── ingest/             # Module 1 Copilot: parsing, chunking, indexing (existing)
├── eval/               # Module 1 Copilot: FinanceBench harness (existing)
├── agent/              # Module 2: planner, memo writer
├── warehouse/          # Module 3
│   ├── db.py           # DuckDB schema
│   ├── xbrl.py         # companyfacts fetch + parse
│   ├── prices.py
│   ├── universe.py
│   ├── pit.py          # point-in-time queries
│   └── crosscheck.py
├── signals/            # Module 4: one file per feature family
├── models/             # Module 5
│   ├── ranker.py
│   └── backtest.py
├── risk/               # Module 7
│   ├── pillars.py      # market, health, quality, disclosure, event measures
│   ├── scorecard.py    # hand-weighted baseline
│   ├── models.py       # volatility regression, downside classifier
│   └── grades.py       # components → grade 1–5, calibration table
├── web/                # Module 6: React + TypeScript (extends the Copilot app)
├── tests/              # incl. look-ahead and leakage tests
└── docs/               # PRD.md, PRD-copilot.md, one spec per phase
```

**Claude Code tip.** Keep one PRD per phase in `docs/`, and have Claude Code write the look-ahead unit test before any feature code. Write the feature list and the backtest config yourself, since those are the decisions you will defend in interviews.

## Risks and resume framing

The biggest risk is a weak or null backtest result, and the plan treats that as a publishable finding rather than a failure.

| Risk | Mitigation |
|---|---|
| Return ranker shows no real edge | The Risk Engine and the single-signal study still stand as results; write up the null honestly |
| Free price data misses delisted stocks | Confirmed: Yahoo returns nothing for acquired names (Activision, Foot Locker, Celgene) and Stooq is closed to scripts. Renamed tickers are recovered through the ticker-history table (SQ → XYZ). Report the count of universe names without prices, their share of the universe, and the likely direction of the bias; exclude them from returns, never back-fill |
| XBRL concept names vary across companies | A mapping table for ~30 core concepts, with fallbacks, tested on 20 companies by hand |
| Scope sprawl across seven modules | Phases gate each other; the Agent stays a side track and never blocks Phase B |
| Free LLM quota limits | LLMs only in the Copilot and Agent; the whole prediction pipeline runs without any LLM |
| Output mistaken for advice | Disclaimer on every page; watchlist language, no "buy" or "sell" |
| Risk grades read as credit ratings | Numeric grades named Low to Severe, never AAA-style letters; the Methodology page explains what the grade measures and how it was validated |

**Resume bullets (fill in real numbers)**

- Built a filings-driven investment research platform over ~500 US stocks and 15 years of SEC data: point-in-time XBRL warehouse, 40 accounting and text signals, and a LightGBM ranker validated with a 10-fold walk-forward backtest (IC X, after-cost long-short Sharpe Y).
- Built a risk engine grading each company's investment risk from 5 pillars of filing and market data (volatility and downside models validated walk-forward: vol rank IC X, downside AUC Y), with realised risk rising across every grade.
- Tested the "Lazy Prices" 10-K text-change effect and 3 accounting scores individually, and documented which held up out of sample.
- Paired every ranked stock with SHAP explanations and an LLM-written thesis cited to filing pages, with numbers cross-checked against SEC XBRL data.

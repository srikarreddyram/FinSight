# FinSight — financial filings analyst copilot

A citation-first RAG copilot over 10-Ks, 10-Qs, 20-Fs and earnings calls, with table-aware parsing,
hybrid retrieval and cross-encoder reranking, benchmarked on [FinanceBench](https://github.com/patronus-ai/financebench).

Every answer is either correct and cited to a page you can click through to, or an honest
**"Not found in the filings."** The LLM never types a number from a source and never does
arithmetic: it names figures and calculations, and Python verifies each figure against its cited page
and computes the result.

## How an answer is built

```
question
  └─ query parser ── companies, fiscal years ("last year" resolved per company), section hints
       └─ hybrid search ── BM25 (Qdrant sparse) + bge-base dense, filtered, fused with RRF → top 30
            └─ bge-reranker-base cross-encoder → top 8   (tables fed as linearized rows)
                 └─ evidence gate ── best passage too weak? → "Not found in the filings" + closest passages
                      └─ LLM (structured output): figures + quotes, calculation names, prose with
                         {fig:x}/{calc:y} placeholders and [S#] citations
                           └─ Python: verify each figure is printed in its source, compute growth /
                              margins / CAGR, fill placeholders, strip any sentence that is uncited,
                              cites a missing source, or contains a number its source doesn't have
                                └─ answer with [Company FY p.N] citations → source viewer
```

Comparison questions ("Compare TCS and Infosys revenue growth…") fan out into one sub-query per
company, so each company gets its own evidence, and the answer includes a table.

## Quickstart

```bash
uv sync --all-extras                        # Python 3.11, installs Docling, Streamlit, etc.
cp .env.example .env                        # add a free GEMINI_API_KEY (aistudio.google.com) and FINSIGHT_SEC_USER_AGENT

# Benchmark corpus: 150 questions, 84 filings
uv run python -m eval.financebench_loader
uv run python -m ingest.parse --all         # Docling, ~2 min per 10-K on an M-series Mac, cached
uv run python -m ingest.inspect 3M_2018_10K --page 60     # eyeball a parsed page before trusting it
uv run python -m ingest.index --all         # embeddings + BM25 into Qdrant
uv run python -m ingest.index --all --naive # naive baseline for ablation run A

# Serve
uv run uvicorn app.api:app                  # API on http://localhost:8000/docs
cd web && npm install && npm run dev        # React UI on http://localhost:5173: answer left, cited page right
```

By default Qdrant runs embedded on disk (one process at a time). For the API and eval side by side:
`docker compose up -d` and set `FINSIGHT_QDRANT_URL=http://localhost:6333` before indexing.

More filings:

```bash
uv run python -m ingest.fetch_edgar AAPL MSFT NVDA --years 3                       # US 10-Ks
uv run python -m ingest.fetch_edgar INFY HDB IBN WIT RDY MMYT --forms 20-F --track india
```

EDGAR serves HTML without pages, so filings are printed to PDF with headless Chrome, which follows
the filings' page-break CSS. PDF page numbers then match the filing's own pagination.

## Evaluation

```bash
uv run python -m eval.run --runs A B C D E --sets financebench unanswerable
uv run python -m eval.run --runs A B C D E --retrieval-only     # recall@10, no API calls
uv run python -m eval.report                                    # → eval/REPORT.md
```

| Run | Parsing | Retrieval | Reranker | Filters |
|---|---|---|---|---|
| A: naive baseline | PyPDF, fixed 1,000-token chunks | Dense only | No | No |
| B | Docling, section + table chunks | Dense only | No | No |
| C | Docling | Hybrid (BM25 + dense) | No | No |
| D | Docling | Hybrid | Yes | No |
| E: full system | Docling | Hybrid | Yes | Yes |

Metrics: answer accuracy (Gemma 4 judge with a strict rubric, plus a manual check of 30),
numeric match within 1% on the numeric subset, recall@10 against FinanceBench's gold evidence pages,
citation precision (a judge reads each cited page), correct refusals on 15 unanswerable questions,
latency and cost. Every failure is tagged parsing / retrieval / reasoning / citation, using the gold
evidence to tell parsing losses from retrieval misses. Results are in [eval/REPORT.md](eval/REPORT.md).

## Design notes

- **Tables stay tables.** Docling extracts cells; each table is one chunk holding Markdown for the
  LLM, plus a one-line summary and the row labels for the dense embedding, plus the full table for
  BM25 so exact figures and line-item names match. Large tables split into row groups that repeat
  the header.
- **Cross-encoders are bad at grids.** bge-reranker-base scored the 3M cash-flow statement 18th for
  a capex question when fed Markdown. Linearizing rows ("Purchases of PP&E: 2018 (1,577); 2017
  (1,373)") moved it to 11th. The reranker reads that form.
- **One page per text chunk.** Text chunks (~500 tokens, 15% overlap, grouped by section) never
  cross a page boundary, so a citation always names one page.
- **Sections come from 10-K/20-F item structure.** Only "Item N", statement titles, the notes header
  and the auditor's report switch sections, so a "Legal Proceedings" note stays under Notes.
  Section hints boost retrieval scores but never filter, because a wrong tag would silently drop the
  right page.
- **Fiscal years.** `fiscal_year` is the year a fiscal year ends in (Infosys FY26 = Apr 2025–Mar
  2026). Calendar periods are stored separately, and "last year" resolves per company to the latest
  fiscal year that is indexed. If the requested year isn't indexed, the filter falls back to the next
  one or two filings, which carry that year as comparatives.
- **One LLM call per answer.** The Copilot PRD sketched extract → compute → write as separate calls. A
  single structured call with placeholders gives the same guarantee (every number comes from a
  verified source or from Python) at roughly half the latency.
- **Local models run on ONNX.** fastembed provides bge-base, BM25 and bge-reranker-base. Bulk
  indexing uses torch on the Mac GPU when available (about 4× faster, identical vectors).
- **Free LLM stack.** Every LLM role runs on the Gemini API free tier. Answers use Gemini 3.5
  Flash-Lite (500 requests/day). Query parsing and the eval judge use Gemma 4 26B (14,400/day, 16K
  tokens/minute); having a different model family grade the answers also reduces self-grading bias.
  One-off table summaries use Flash-Lite in large batches. Calls are throttled per model by requests and
  tokens per minute. A spent daily quota stops the eval cleanly, and rerunning the same command the next
  day resumes it. Set `FINSIGHT_MODEL_OVERRIDE=ollama:llama3.1:8b` for unlimited local runs, or
  `anthropic:claude-opus-5` for a paid model.

## Research platform (in progress)

The Copilot is the first module of a filings-driven research platform ([docs/PRD.md](docs/PRD.md)). The rest
runs on S&P 500 members since 2010, with every figure used only from the day after its filing reached the SEC:

- **Warehouse**: XBRL facts, prices, 10-K text and EDGAR's filing index in DuckDB ([docs/phase-a-warehouse.md](docs/phase-a-warehouse.md))
- **Signals, ranker, backtest**: 29 signals, a walk-forward LightGBM ranker and a monthly long-short backtest ([docs/phase-b-signals.md](docs/phase-b-signals.md))
- **Risk Engine**: a 1–5 risk grade from expected volatility and severe-loss risk ([docs/phase-b2-risk.md](docs/phase-b2-risk.md))
- **Dashboard**: watchlist, company cards, signal lab, backtest and risk pages ([docs/phase-c-dashboard.md](docs/phase-c-dashboard.md))

The results so far are reported as they are: the return ranker shows no edge on large caps, and the
risk grades add almost nothing to a stock's own trailing volatility. The docs give the numbers and the baselines.

```bash
uv sync --all-extras
uv run python -m warehouse.universe          # S&P 500 membership since 2010
uv run python -m warehouse.xbrl --universe   # then: warehouse.sectors, warehouse.prices --universe SPY,
                                             #       warehouse.tenk --universe, warehouse.events
uv run python -m models.study                # signal panel and single-signal study
uv run python -m models.ranker && uv run python -m models.backtest
uv run python -m risk.panel && uv run python -m risk.models
uv run python -m recs.build                  # this month's watchlist and the dashboard's data
```

Set `FINSIGHT_THREADS=3` to keep a laptop cool during the builds. Research and education only; not financial advice.

## Layout

```
app/        query path: config, fiscal, query_parser, retrieve, rerank, answer, numbers, pipeline, api, viewer
ingest/     fetch_edgar, parse, chunk, index, inspect, manifest
eval/       financebench_loader, run, judge, metrics, report, unanswerable.yaml, india_set.yaml
warehouse/  point-in-time store: db, pit, xbrl, prices, sections, tenk, events, universe, sectors, fundamentals
signals/    accounting, fundamentals, valuation, text
models/     panel, ranks, walkforward, study, ranker, backtest
risk/       pillars, market, panel, models
recs/       build (latest-month scoring, drivers), api (dashboard endpoints), labels
web/        React + TypeScript front end (Vite, Tailwind)
ui/         streamlit_app.py (the original PRD prototype UI)
data/       manifest*.yaml (URLs and metadata; PDFs are downloaded, never committed)
tests/      unit tests + integration tests on known financial-statement tables
docs/       PRD.md (platform roadmap), PRD-copilot.md (this copilot's spec)
```

# PRD: FinSight — Financial Filings Analyst Copilot (RAG)

Sep 27, 2026 · @Srikar

> Module 1 of the FinSight Platform. The platform PRD is [PRD.md](PRD.md).

## Overview

FinSight answers analyst questions about company filings and earnings calls with page-level citations, pulls numbers out of financial tables accurately, and compares companies side by side. Its quality is benchmarked on FinanceBench, a public question set built on real SEC filings.

**Problem.** Annual reports run 200–400 pages, and the numbers analysts need sit in tables that naive PDF-to-text RAG mangles. Generic "chat with your PDF" tools miss exact terms like "EBITDA", confuse fiscal years, and cite nothing, so their answers can't be trusted.

**Target users.**

- Equity research and credit analysts screening companies
- Business and finance students preparing company deep-dives
- Interviewers reviewing the project, who should be able to ask a question and click through to the exact source page

**One-line pitch.** "A citation-first RAG copilot over 10-Ks and earnings calls with table-aware parsing, hybrid retrieval, and reranking, benchmarked on FinanceBench."

## Goals, non-goals, success metrics

The project succeeds if every answer is either correct and cited to the right page, or an honest "not found in the filings".

**Goals**

- Parse filings with tables preserved as structured data, not flattened text
- Retrieve with hybrid search (BM25 + dense) and a cross-encoder reranker
- Cite every claim to document, fiscal year, section, and page
- Answer multi-company and multi-year comparison questions
- Refuse when the evidence isn't there instead of guessing
- Report accuracy on FinanceBench and a custom set, with an ablation

**Non-goals (v1)**

- No investment recommendations or price predictions
- No real-time market data or stock prices
- No scanned or image-only PDFs (OCR is a stretch goal)

**Success metrics**

| Metric | Target | How measured |
| --- | --- | --- |
| Answer accuracy (FinanceBench sample) | ≥ 60% | LLM judge + manual spot-check of 30 answers |
| Numeric exact match | ≥ 80% on the numeric subset | Parsed number within 1% of gold |
| Citation precision | ≥ 90% | Cited page actually contains the supporting text |
| Retrieval recall@10 | ≥ 85% | Gold evidence page appears in top 10 chunks |
| Correct refusals | ≥ 80% | On 15 unanswerable questions |
| Median latency | < 10 s | Question to cited answer |

For context, the FinanceBench paper reported that GPT-4-Turbo with a basic shared vector store got most questions wrong, so beating a naive baseline by a clear margin is the real story, not an absolute number.

## Document corpus and data sources

The corpus has two tracks: US filings that match FinanceBench for benchmarking, and Indian company reports for a demo that interviewers here will recognise.

| Track | Source | Scope | Format |
| --- | --- | --- | --- |
| Benchmark | FinanceBench open-source sample (GitHub / Hugging Face) | Its question set plus the linked filings | PDF |
| US filings | SEC EDGAR (free API, set a User-Agent header) | 10-Ks and 10-Qs for \~10 companies, 3 fiscal years | HTML / PDF |
| India demo | Company investor-relations pages, NSE / BSE filings | Annual reports for \~6 companies (e.g. Infosys, TCS, HDFC Bank), 3 years | PDF |
| Earnings calls | Company IR sites (transcripts published as PDF) | Latest 4 quarters for the India demo companies | PDF |

**Metadata stored per chunk:** company, ticker, document type, fiscal year and period, section (e.g. MD&A, Risk Factors, Notes), page number, and chunk type (text or table).

**Fiscal-year gotcha.** Indian companies mostly report April–March (FY26 = Apr 2025–Mar 2026) while many US companies use calendar years or odd fiscal years. Store fiscal labels and calendar periods separately so "last year" questions resolve correctly.

## Functional requirements and user stories

Every answer carries clickable citations that open the source PDF at the cited page.

| ID | Requirement | Priority |
| --- | --- | --- |
| FR1 | Ingest a filing PDF: extract text by section and tables as structured rows, with page numbers | P0 |
| FR2 | Chunk text by section (\~500 tokens, 15% overlap); store each table as one chunk with a Markdown rendering plus an LLM-written one-line summary | P0 |
| FR3 | Hybrid retrieval: BM25 and dense search, merged with reciprocal rank fusion | P0 |
| FR4 | Metadata filters parsed from the question (company, fiscal year, section) before search | P0 |
| FR5 | Cross-encoder reranking of the top 30 down to the top 8 | P0 |
| FR6 | Answers with inline citations `[Company FY Page]`; claims without a citation are stripped | P0 |
| FR7 | Refuse with "not found in the filings" when evidence scores are below a threshold | P0 |
| FR8 | Compute derived numbers (growth, margins, ratios) in Python, not in the LLM | P1 |
| FR9 | Comparison mode: split a multi-company question into per-company sub-queries, then merge into a table | P1 |
| FR10 | Source viewer: side panel showing the cited PDF page with the passage highlighted | P1 |
| FR11 | Upload your own filing PDF and query it within a minute | P2 |

**User stories**

- As an analyst, I ask "What was Infosys's operating margin in FY24 and FY25, and what did management say drove the change?" and get both numbers, the explanation, and three citations.
- As a student, I ask "Compare TCS and Infosys revenue growth over three years" and get a table plus a short commentary.
- As a credit analyst, I ask "What are the top risk factors HDFC Bank lists about asset quality?" and get a cited summary of the Risk Factors section.
- As a skeptic, I ask something the filings don't cover and the system says so instead of inventing an answer.

## System architecture

Two pipelines share one index: ingestion does the expensive parsing once per filing, and the query path filters, searches, reranks, and gates on evidence before answering.

&#91;embedded content: ingestion and query pipelines · sharing one Qdrant index\]

**Component notes**

- **Parsing.** Docling extracts section headings, reading order, and tables as structured cells with page numbers. Keep pdfplumber as a fallback for PDFs Docling handles badly.
- **Table chunks.** Each table is stored whole as Markdown plus a one-line LLM summary ("Consolidated income statement, FY23–FY25, ₹ crore"). The summary is what gets embedded; the Markdown is what the LLM reads.
- **Query parser.** A small LLM call returns JSON with company, fiscal years, and section hints, which become Qdrant payload filters. Comparison questions fan out into one sub-query per company.
- **Evidence gate.** If the top reranker score is below a tuned threshold, the system answers "not found in the filings" and shows the closest passages.
- **Answer step.** The LLM extracts the raw figures with citations as JSON; Python does the arithmetic (growth, margins); a final call writes the prose around the verified numbers.

## Tech stack

Everything runs locally except the LLM, and even that has a free Ollama fallback for development.

| Layer | Choice | Why |
| --- | --- | --- |
| Language | Python 3.11 | Same as project 1; reuse your LLM wrapper |
| PDF parsing | Docling (pdfplumber fallback) | Table structure and reading order out of the box |
| Vector DB | Qdrant (Docker) | Native hybrid search (dense + sparse), payload filters |
| Embeddings | `BAAI/bge-base-en-v1.5` | Free, local, good on financial prose |
| Sparse / BM25 | Qdrant sparse vectors via fastembed | Exact matches on tickers, "EBITDA", line-item names |
| Reranker | `BAAI/bge-reranker-base` cross-encoder | Biggest single accuracy gain in most RAG ablations |
| LLM | Claude or GPT-class API for answers; Ollama (Llama 3.1 8B) for dev runs | Quality where it counts, free while iterating |
| Backend | FastAPI | `/ingest`, `/ask`, `/documents` |
| Frontend | Streamlit with a PDF page viewer | Answer on the left, cited page on the right |
| Eval | Custom harness + RAGAS for retrieval metrics | Reproducible benchmark numbers |
| Tooling | uv, ruff, pytest, GitHub Actions | Same setup as project 1 |

Share a small `common/` package (LLM wrapper, eval utilities, config) between both projects: it saves time and is a nice engineering talking point.

## Evaluation plan

The headline result is an ablation on the FinanceBench open sample, showing accuracy climb as each retrieval upgrade is added.

**Question sets**

| Set | Size | Purpose |
| --- | --- | --- |
| FinanceBench open sample | \~150 questions with gold answers and evidence pages | Public benchmark; comparable to the paper |
| India custom set | 40 questions you write on the demo companies | Proves the system works on the corpus you demo |
| Unanswerable set | 15 questions the filings can't answer | Measures honest refusals |

**Metrics.** Answer accuracy (LLM judge with a strict rubric, plus a manual check of 30), numeric match within 1%, retrieval recall@10 against gold evidence pages, citation precision, refusal rate, latency, cost.

**Ablation runs**

| Run | Parsing | Retrieval | Reranker | Metadata filters |
| --- | --- | --- | --- | --- |
| A: naive baseline | PyPDF text, fixed 1,000-token chunks | Dense only | No | No |
| B | Docling, section + table chunks | Dense only | No | No |
| C | Docling | Hybrid (BM25 + dense) | No | No |
| D | Docling | Hybrid | Yes | No |
| E: full system | Docling | Hybrid | Yes | Yes |

**Error analysis.** Tag every failure as parsing, retrieval, reasoning, or citation. A short "where it still fails" section in the README reads as more senior than a perfect-looking score.

## Repo structure and milestones for Claude Code

Build this after Ask Your Data so you can reuse the LLM wrapper and eval harness; four one-week phases, each ending in something runnable.

```
finsight/
├── CLAUDE.md               # project rules for Claude Code
├── docker-compose.yml      # qdrant
├── pyproject.toml
├── data/
│   ├── filings/            # downloaded PDFs (gitignored)
│   └── manifest.yaml       # company, ticker, doc type, fiscal year, URL
├── ingest/
│   ├── fetch_edgar.py
│   ├── parse.py            # Docling + fallback
│   ├── chunk.py            # section + table chunks, metadata
│   └── index.py            # embeddings + sparse vectors into Qdrant
├── app/
│   ├── api.py
│   ├── query_parser.py
│   ├── retrieve.py         # hybrid search + RRF
│   ├── rerank.py
│   ├── answer.py           # evidence gate, citations, Python math
│   └── llm.py
├── ui/streamlit_app.py
├── eval/
│   ├── financebench_loader.py
│   ├── india_set.yaml
│   ├── unanswerable.yaml
│   ├── run.py
│   └── REPORT.md
└── tests/
```

&#91;embedded content: build roadmap · 4 weekly phases\]

**Claude Code tips.** Put this PRD in `docs/PRD.md`, reference it from `CLAUDE.md`, and prompt one phase at a time. Before Week 2, open 3 parsed filings and eyeball the table chunks yourself: parsing bugs are silent and poison everything downstream.

## Risks, stretch goals, resume framing

| Risk | Mitigation |
| --- | --- |
| Tables parsed wrong, numbers silently off | Unit tests on 5 known tables (e.g. revenue lines checked against the report); pdfplumber fallback |
| LLM hallucinates or miscalculates numbers | LLM only extracts cited figures; Python does all arithmetic; uncited claims stripped |
| Fiscal-year confusion across US and Indian companies | Separate fiscal label and calendar period fields; parser resolves "last year" per company |
| Large PDFs slow to ingest | Ingest once, cache parsed JSON; index is rebuilt only when the manifest changes |
| Judge-model bias in accuracy scoring | Strict rubric plus manual review of 30 answers; report both numbers |
| Copyright or terms of IR documents | Don't commit PDFs to the repo; the manifest stores URLs and a download script fetches them |

**Stretch goals**

- Earnings-call tone tracker: management sentiment per quarter, charted over time
- "What changed" diff between two years' Risk Factors sections
- OCR for scanned PDFs
- Agentic mode that calls the Ask Your Data SQL tool for structured financial data (links your two projects)

**Resume bullets (fill in real numbers)**

- Built a citation-first RAG copilot over SEC 10-Ks and Indian annual reports with table-aware parsing, hybrid BM25 + dense retrieval, and cross-encoder reranking; raised FinanceBench accuracy from X% (naive RAG) to Y%.
- Designed an evidence gate and Python-verified numeric pipeline, achieving Z% citation precision and correct refusals on N% of unanswerable questions.

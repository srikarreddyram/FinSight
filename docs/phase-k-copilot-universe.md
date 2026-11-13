# Phase K: The Copilot on the warehouse

Until this phase the Copilot and the research platform shared nothing: the Copilot searched 84 parsed PDFs from
32 companies, and the warehouse's 45 million XBRL facts and 22,686 10-Ks fed only the signals. Two changes join
them. The Copilot now reads a company's standard financials from the warehouse as a source, and it answers about
every company still filing, from the 10-K text the warehouse already holds.

## Facts as a source (`app/facts.py`, run G)

For each company a question names, the model also gets a table of 26 standard line items (revenue, cost of sales,
operating income, receivables, payables, capex and so on) for the fiscal year asked about and the two before it,
in $ millions. It quotes them like any table, Python verifies them the same way, and the citation reads
"3M FY18 XBRL"; the source viewer shows the table with the rows used highlighted.

- **As the 10-K reported them.** The table is read point-in-time on the day after that year's 10-K was filed, so
  a later restatement can't replace the figure the filing printed. The warehouse was built for this.
- **No year in the question** means the latest 10-K held for the company. Quarterly questions get no table: annual
  figures would answer them with the wrong period.
- Accounts payable and short-term investments joined the warehouse's standard items, for days-payable and
  quick-ratio questions.

## Every company (`ingest/sections.py`)

The warehouse keeps Items 1, 1A, 3, 7, 7A and 9A of every 10-K. For each of the 1,606 companies that filed one in
the last 18 months, the latest is chunked with the same chunker and contextual headers as the parsed filings:
131,608 chunks, embedded in about an hour on an Apple GPU, with no LLM calls. That is too many points for
Qdrant's embedded mode, so they live on the Qdrant server from `docker-compose.yml`; `ingest.move_index` copies
the FinanceBench collections there without re-embedding (the server returns the same dense and BM25 results as
the embedded store, scores included, on the questions checked).

- **No pages, no tables.** A citation names the item ("Nvidia FY26 10-K Item 7") and the viewer shows the passage
  with a link to EDGAR. Figures come from the facts source.
- **A company with both** parsed filings and a newer 10-K is searched in both collections; the year filter and
  the reranker choose.
- **Benchmarks stay on the parsed filings** (`Settings.sections` off): their gold answers come from those
  documents. `eval.run --universe` turns the rest on.

### Finding the company among 1,615 names

With 39 hand-vetted companies, any capitalisation of a name and any ticker in capitals could match. With 1,615
that breaks: 111 one-word names are ordinary words (Target, Post, News, People), 121 tickers have one or two
letters (K, A, IT, GM), and others are words or acronyms (COST, ALL, ARR). "What does the 10-K say" would have
matched Kellanova.

`ingest.sections` measures which words are ordinary from the filings themselves: of 400 sampled 10-Ks, 294 use
"target" in lower case, 218 "post" and 13 "visa"; none uses "apple" or "nvidia". 155 write "IT" in capitals and
9 "ARR"; 3 write "IBM". The matcher (`app/query_parser.py`) then applies, to the companies nobody vetted:

| Rule | Example |
|---|---|
| A name of several words matches in any capitalisation | "dollar general" |
| A one-word name needs a capital first letter | "Target", not a "target margin" |
| A short name or an acronym that is also a word needs its exact capitals | "NOW", not "Now" |
| A bare ticker needs three letters and must not be a word or acronym in filings | "NVDA"; not K, COST or ARR |
| Any ticker matches after a dollar sign | "$K" |
| A name inside a longer one belongs to the longer | "Fox Factory" is not Fox; "H&R Block" is not Block |
| A name that shortening would turn into an ordinary word keeps its suffix | "Post Holdings", "News Corp" |

Filings under-count everyday words ("crown", "guess"), so a lower-case one-word name is never matched by rule.
It goes to the query parser's model, which must quote the words that refer to the company; Python checks the
quote is in the question. "what was hilton's revenue last year?" and "How did UPS do?" resolve this way. Without
a model there is a last pass that accepts lower-case names unless they are ordinary words.

**A question that names no company** gets "Which company is this about?" instead of a search of everything.

**Checked without an LLM:** all 278 benchmark questions parse exactly as before on the closed corpus. With the
universe on, two gain a second company, and both do mention it (Kenvue in a J&J question, Southwest Airlines in
a Boeing one).

## Results

Answers by Gemini 3.5 Flash-Lite, graded by Gemma 4 26B, no fallback model for either.

### FinanceBench (150 questions, parsed filings only)

| | Run F: retry | Run G: retry + facts |
|---|---|---|
| Correct, graded answers | 118 of 147 (80.3%) | **116 of 138 (84.1%)** |
| Ungraded counted wrong | 78.7% | 77.3% |
| Graded in both runs (137) | 111 | **115**: 8 fixed, 4 broken |
| Numeric match (within 1%; target 80%) | 46 of 59 (78%) | **49 of 59 (83%)** |
| Citation precision | 210 of 211 | 188 of 189 |
| Refused | 6 | 6, of which 3 ask which company |
| Retries | 18, 11 then correct | 10, 7 then correct |
| Median latency (target under 10 s) | 12.1 s | **9.6 s** |
| 90th percentile latency | 22.4 s | 17.7 s |
| By type: metrics / domain / novel | 42 of 49 / 36 of 49 / 40 of 49 | 45 of 47 / 34 of 45 / 37 of 46 |

- **The gain is on numbers.** Numeric match and latency clear their targets for the first time: with the line
  items in front of it the model needs fewer retries (10 against 18). The eight fixed include Walmart's
  days-payable (cost of sales is now a lookup) and Netflix's EBITDA margin (XBRL's depreciation excludes content
  amortization, as the benchmark's definition does).
- **Twelve answers went ungraded.** The judge's server returned errors on the same twelve through repeated
  retries. Read by hand, seven are clearly right (three match the gold number exactly), one is arguable and four are wrong,
  which would put run G at about 123 of 150 (82%). The table reports only what the judge graded.
- **"Which company?" costs two answers.** Three benchmark questions name no company. Run F answered two of them
  correctly by searching all 84 filings and the third about the wrong company (Amcor). All three now get the
  clarifying question, which the benchmark counts as wrong.
- **The fourth broken answer** lists PepsiCo's revenue by country where the gold lists regions.

### Other sets

| Set | Result |
|---|---|
| Unanswerable (30) | 30 refused. Every one went through the retry, and none was answered |
| Universe (40 lookups about companies outside the parsed filings, `eval/universe_set.py`) | 39 of 39 scored are correct; one lost to a provider outage |

The universe set's answers come from XBRL, which is where the facts source reads them, so it does not test the
data. It tests what stands between a question and the data: finding the company by the name people use, picking
the year (half the questions give none), choosing the line and getting the units right.

### Asked live

Ten questions about companies that were never parsed. Eight were handled correctly: Nvidia's FY2026 revenue and
growth, its export-control risks, Apple's gross margin, the drivers of Target's comparable sales, Hilton and UPS
by name and ticker in lower case, a refusal for Nvidia's revenue in Germany, and "Which company?" for a question
that named none. One was lost to a provider outage.

The tenth shows a limit. Asked to compare Costco's and Walmart's operating margins, the model wrote the right
figures (3.77% and 4.18%, from XBRL) and also that Costco's was "slightly higher". That sentence was removed, but
only because it had no citation. The checks verify numbers; they do not check the words around them.

## Evaluation changes

- **No fallback model in benchmarks.** During one Gemini outage about a third of a run's calls went to the
  fallback model, and that run refused twelve questions the answer model went on to answer. A row lost to an outage is now left
  unscored and filled in on the next run.
- **Runs resume only from the same corpus and settings.**
- **One rate limiter per process** (`app/llm.py`). Each client had its own, so the judge and the system under
  test each spent Gemma's 16,000 tokens a minute; the provider's dashboard showed a peak of 21,400. The query
  parser moved to Gemma 4 31B, which has its own budget. The judge's model is unchanged.
- **A placeholder with spaces in its name** was printed as written instead of failing its sentence. Fixed, with a
  test.

## Limits

- **Direction words are not checked** (the Costco example).
- **Text for the universe is the latest 10-K only.** Older years have figures (XBRL goes back to 2009) but no
  passages, and there are no 10-Qs or earnings calls outside the parsed filings.
- **Fiscal-year names for January year-ends.** The repo names a fiscal year by the year it ends in; Target and
  Ulta name theirs by the year it starts in. The facts table states the period's end date, which usually settles
  it, but not always.
- **Lower-case and short-form names depend on a free-tier model** that is sometimes unavailable; then the answer
  is "Which company?".
- **A wrong name in the warehouse.** Ribbon Communications carries the name of the company that replaced it in
  the S&P 600 (Solstice Advanced Materials). A name two companies share is skipped, so neither is covered.
- **The judge** still fails on some answers whatever the retry count, and has not been checked against a human
  sample beyond the twelve read here.

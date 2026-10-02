# Phase A: Fundamentals Warehouse (Module 3)

Weeks 1–4 of the [platform PRD](PRD.md). Goal: store every financial fact with the date the market could first see it, so Phase B can build features that never peek at the future.

## Point-in-time rules

These are the rules the look-ahead tests (`tests/test_lookahead.py`) enforce. They were written before any feature code.

1. **Public date.** Every fact carries `filed_at`, the date EDGAR accepted the filing that reported it (the `filed` field in SEC companyfacts).
2. **Available date.** A fact becomes usable on `available_at = filed_at + 1 day`. Filings accepted after the close can't be traded the same day, so same-day use would be a small look-ahead.
3. **As-of queries.** A feature for date *t* may only use rows with `available_at <= t`. All reads go through `warehouse.pit`, never raw SQL on `facts`.
4. **Restatements.** Every reported value is a separate row keyed by its accession number; nothing is overwritten. As of *t*, a period's value is the latest version already public at *t*. That equals the first-reported value unless a restatement was already public, so later corrections never leak backwards. `pit.first_reported()` is also kept for the restatement study.

## Data model (DuckDB, `data/warehouse.duckdb`)

| Table | Grain | Notes |
|---|---|---|
| `companies` | one row per CIK | ticker, name, sector, `listed_from`, `delisted_on`, `in_universe_from/to` |
| `filings` | one row per accession | form, `period_end`, `filed_at`, fiscal year and period |
| `facts` | one row per (accession, concept, unit, period) | taxonomy (`us-gaap`, `dei`), value, `period_start` (null for balance-sheet instants), `period_end`, `filed_at`, `available_at`, form, fy, fp |
| `prices` | one row per ticker per day | `raw_close` (as traded, later splits undone), `ret` (daily total return), `raw_volume`, source |
| `filing_text` | one row per filing section | reused from the Copilot's parsed filings |

## Universe (built on the proposed default; awaiting @Srikar's confirmation)

About 500 US large and mid caps from 2010 to today, **including names later removed**. Proposed source: historical S&P 500 membership rebuilt from today's constituents plus the published list of additions and removals, with each company's `in_universe_from/to`. Removed names keep their XBRL facts; their prices come from yfinance. Yahoo drops acquired and delisted names entirely (Activision, Foot Locker and Celgene return nothing) and Stooq now blocks scripts, so any name with no price history is counted and reported as a survivorship limit. Renamed tickers are recovered through ticker history (Block: SQ → XYZ).

## Build order

1. ✅ Look-ahead and restatement tests, written first and mutation-checked (allowing same-day use fails them).
2. ✅ DuckDB schema (`warehouse/db.py`) and point-in-time query layer (`warehouse/pit.py`).
3. ✅ XBRL companyfacts parser and fetcher (`warehouse/xbrl.py`). The parser is tested on a fixture; the fetcher is untested live until `FINSIGHT_SEC_USER_AGENT` is set.
4. ✅ Universe table (`warehouse/universe.py`, tables `universe` and `cik_links`), built on the proposed default so the pipeline could proceed; switching universes later means rebuilding this table and rerunning the loaders. Wikipedia's constituents (with CIKs) plus its dated change log (now the article "Historical components of the S&P 500"), walked backwards from today on CIKs, not tickers:
   - Share lines are counted per company, so GOOG joining in 2014 doesn't end Alphabet's membership.
   - Removed companies get their CIK from the name they had then, searched across every name SEC has on file (state tags like "/PA/", share-class words and "21st" normalised; initials like "CR Bard" matched to "BARD C R INC"). A candidate counts only if it filed a 10-K within two years of the change, and for a removal only before it. That rejects reused tickers (today's IR only exists since 2017) and look-alike names (subsidiaries, trusts).
   - Within a day, removals are undone before additions, and an addition may only take a share line that existed just after that day. This keeps a rename (KFT to MDLZ) as one stay and sends the same-day spin-off that Wikipedia also calls "Kraft Foods" to Kraft Foods Group.
   - Reorganisations under a new CIK (Broadcom from Avago, BlackRock's 2024 holding company) are recorded in `cik_links` so the predecessor's filings can be joined in; a removed company (21st Century Fox) is never linked to a spin-off that kept its ticker (Fox Corp).
   - Fresh spin-offs are accepted by ticker before their first 10-K (Honeywell Aerospace, 2026); a first-word name match must be nearly the whole name, so "Solstice Advanced Materials" no longer lands on Ribbon Communications' old shell name; DowDuPont (DWDP) is told apart from the DuPont it replaced by a small table of historical tickers.
   - Predecessors (`find_predecessors`). 27 members had 10-Ks starting years after their membership: reorganisations that issue a new SEC ID with no index change, including Alphabet (2015), Disney (2019), Cigna, Linde, Medtronic, Eaton, Walgreens, ICE, Viatris and ExxonMobil's 2026 redomicile. A predecessor is the filer of the same name (or the old name, from a table keyed by SEC ID where the name changed) that filed 10-Ks for years and up to the successor's first one; chains are followed (Viatris ← Mylan N.V. ← Mylan Inc). 25 links are stored in `cik_links`, the loaders fetch the predecessors' facts, 10-Ks and filing index, and `fundamentals.lineage()` joins them in, keeping the latest-filed version where both IDs report a period.
   - Result: 805 companies since 2010; 500 members in January 2010, 498 in mid-2015, 500 in 2020 and today. About six change events stay unresolved and are logged (Signature Bank and MasterBrand, which never filed a 10-K with the SEC as index members; Perrigo's 2011 addition; Solstice).
5. ✅ Prices (`warehouse/prices.py`): yfinance to an append-only Parquet cache. Yahoo re-scales its adjusted history after every dividend and split, so the cache stores values that never change: daily total returns computed within one download, and raw closes with later splits undone (needed for market cap). Checked: 3M's 2018 close is $190.54; Amazon's 20:1 split shows $2,447 → $124.79 with a +2% return. 29 of 32 FinanceBench companies have history from 2009.
6. `filing_text`. ✅ The 10-K Item splitter (`warehouse/sections.py`) finds Risk Factors and MD&A in 62 of 64 test 10-Ks. ✅ `warehouse/tenk.py` fetches every 10-K filed since 2009 from EDGAR (496 filings for the 29 companies, 10,257 Item sections) and records each filing's date in `filings`. Where Item 7 only says "incorporated by reference", MD&A is cut from Exhibit 13 (CVS, Pfizer, Walmart, American Express, whose annual reports call it "Financial Review") or, for 10-Ks laid out as the annual report (JPMorgan), from its own heading in the main document. MD&A coverage: 494 of 496; CVS FY2008 and Pfizer FY2012 are left missing. Johnson & Johnson's Risk Factors were a one-paragraph pointer until FY2016, which is real, not a parsing gap. The Copilot's parsed PDFs can't be the source: only 84 filings, no filing dates, and Docling is too slow for ~7,500 10-Ks.
7. XBRL cross-check against the Copilot's extracted figures, and auto-generated numeric Q&A for the Copilot eval.

## Exit criteria

- Look-ahead and restatement tests pass in CI
- 20 companies hand-checked: revenue, net income, total assets and operating cash flow match their 10-Ks
- Point-in-time demo: "what did investors know about company X on date t?"
- Cross-check agreement rate reported for the Copilot's FinanceBench filings

# FinSight evaluation report

Generated 2026-11-03 from `eval/results/`. Answer model `gemini:gemini-3.5-flash-lite`, query parser / table summaries `gemini:gemma-4-26b-a4b-it`, judge `gemini:gemma-4-26b-a4b-it`.

## Ablation (FinanceBench open sample)

| Run | Parsing | Retrieval | Reranker | Filters | Retry | N | Accuracy | Numeric EM | Citation precision | Recall@10 | All evidence read | Median latency | Cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | PyPDF, 1,000-token chunks | Dense only | No | No | No | 150 | – | – | – | 41% | – | 0.03 s | – |
| B | Docling, section + table chunks | Dense only | No | No | No | 150 | – | – | – | 55% | – | 0.05 s | – |
| C | Docling, section + table chunks | Hybrid (BM25 + dense) | No | No | No | 150 | – | – | – | 50% | – | 0.43 s | – |
| D | Docling, section + table chunks | Hybrid (BM25 + dense) | Yes | No | No | 150 | – | – | – | 59% | – | 4.64 s | – |
| E | Docling, section + table chunks | Hybrid (BM25 + dense) | Yes | Yes | No | 150 | 66% | 59% | 99% | 81% | 69% | 13.05 s | free (284 calls) |
| F | Docling, section + table chunks | Hybrid (BM25 + dense) | Yes | Yes | Yes | 150 | 80% | 78% | 99.5% | 84% | 79% | 12.11 s | free (171 calls) |

Targets: accuracy ≥ 60%, numeric match ≥ 80%, citation precision ≥ 90%, recall at 10 ≥ 85%, correct refusals ≥ 80%, median latency < 10 s.

## Other sets

| Run / set | N | Accuracy | Correct refusals | False refusals | Recall@10 |
|---|---|---|---|---|---|
| A/unanswerable | 15 | – | – | – | – |
| B/unanswerable | 15 | – | – | – | – |
| C/unanswerable | 15 | – | – | – | – |
| D/unanswerable | 15 | – | – | – | – |
| E/unanswerable | 15 | – | 100% | – | – |
| F/unanswerable | 30 | – | 100% | – | – |
| F/xbrl | 98 | 98% | – | 0% | 97% |

## Where it still fails (run F)

| Category | Count |
|---|---|
| reasoning | 17 |
| retrieval | 8 |
| over-refusal | 6 |
| ungraded | 3 |

Examples:

- **reasoning** — What was Ulta Beauty's capital expenditure in FY2023?  
  gold: 312126000  
  ours: Ulta Beauty budgeted fiscal 2023 capital expenditures at $475 million [Ulta Beauty FY23 p.42], with an outlook range of $400 million to $475 million [Ulta Beauty Q4 FY23 p.3].
- **retrieval** — What was Adobe's depreciation and amortization in FY2017?  
  gold: 325997000  
  ours: In fiscal 2017, Adobe's depreciation and amortization of property and equipment was $156.9 million [Adobe FY17 p.78], and amortization of purchased and other intangible assets was $153.6 million [Adobe FY17 p.79], bringi
- **reasoning** — Is 3M a capital-intensive business based on FY2022 data?  
  gold: No, the company is managing its CAPEX and Fixed Assets pretty efficiently, which is evident from below key metrics:
CAPEX/Revenue Ratio: 5.1%
Fixed assets/Total  
  ours: 3M operates as a capital-intensive business, with net property, plant, and equipment representing 19.76% of total assets [3M FY22 p.50].
- **reasoning** — Does 3M have a reasonably healthy liquidity profile based on its quick ratio for Q2 of FY2023? If the quick ratio is not relevant to measure liquidity, please s  
  gold: No. The quick ratio for 3M was 0.96 by Jun'23 close, which needs a bit of an improvement to touch the 1x mark  
  ours: Yes, 3M maintains a reasonably healthy liquidity profile supported by a quick ratio of 0.847x for Q2 of FY2023 [3M Q2 FY23 p.5]. Furthermore, the company has significant cash reserves of $4,258 million and robust ongoing
- **ungraded** — What drove operating margin change as of FY2022 for 3M? If operating margin is not a useful metric for a company like this, then please state that and explain w  
  gold: Operating Margin for 3M in FY2022 has decreased by 1.7% primarily due to: 
-Decrease in gross Margin
-mostly one-off charges including Combat Arms Earplugs liti  
  ours: Operating income margin decreased to 19.1% in 2022 from 20.8% in 2021 [3M FY22 p.27]. Key drivers included raw material pressures (-2.4%) and litigation costs, offset by gains on business divestitures (8%) [3M FY22 p.27;
- **reasoning** — Roughly how many times has AES Corporation sold its inventory in FY2022? Calculate inventory turnover ratio for the FY2022; if conventional inventory management  
  gold: AES has converted inventory 9.5 times in FY 2022.  
  ours: AES Corporation's inventory turnover ratio for FY2022 was 12.14x, derived from total cost of sales of $10,069 million and an average inventory of $829.5 million [AES Corporation FY22 p.132; AES Corporation FY22 p.149]. I
- **reasoning** — Based on the information provided primarily in the statement of financial position and the statement of income, what is AES's FY2022 return on assets (ROA)? ROA  
  gold: -0.02  
  ours: AES Corporation's return on assets (ROA) for FY2022 was -1.42%, based on a net income of -$505 million and average total assets of $35,663 million between FY2021 ($32,963 million) and FY2022 ($38,363 million) [AES Corpor
- **over-refusal** — What are major acquisitions that AMCOR has done in FY2023, FY2022 and FY2021?  
  gold: Amcor completed these acquisitions during FY2023:
-100% equity interest of a flexibles manufacturing company in the Czech Republic
- 100% equity interest in a m  
  ours: Not found in the filings. The closest passages are listed below.
- **reasoning** — Has AMCOR's quick ratio improved or declined between FY2023 and FY2022? If the quick ratio is not something that a financial analyst would ask about a company l  
  gold: The quick ratio has slightly improved from 0.67 times to 0.69 times between FY 2023 and FY 2022.(3.4% jump)  
  ours: Amcor's quick ratio improved between FY2022 and FY2023 [Amcor FY23 p.52]. The quick ratio rose from 0.531x in fiscal year 2022 to 0.573x in fiscal year 2023 [Amcor FY23 p.52].
- **retrieval** — Does AMEX have an improving operating margin profile as of 2022? If operating margin is not a useful metric for a company like this, then state that and explain  
  gold: Performance is not measured through operating margin  
  ours: No, American Express does not have an improving operating margin profile as of 2022, as its pretax income margin decreased year-over-year [American Express FY22 p.44]. The pretax income margin declined from 25.22% in 202
- **reasoning** — How much (in USD billions) did American Water Works pay out in cash dividends for FY2020? Compute or extract the answer by primarily using the details outlined   
  gold: $0.40  
  ours: American Water Works paid $0.39 billion in cash dividends for FY2020 [American Water Works FY20 p.86].
- **ungraded** — In agreement with the information outlined in the income statement, what is the FY2015 - FY2017 3 year average net profit margin (as a %) for Best Buy? Answer i  
  gold: 2.8%  
  ours: Best Buy's 3-year average net profit margin for the period FY2015 to FY2017 was 2.8% [Best Buy FY17 p.56].

## Evidence-gate calibration

Median top reranker score (sigmoid) of the best retrieved passage. The gate threshold (`FINSIGHT_EVIDENCE_THRESHOLD`) should sit between the two.

| Run / set | Answerable | Unanswerable |
|---|---|---|
| D/financebench | 0.98 | – |
| D/unanswerable | – | 0.87 |
| E/financebench | 0.98 | – |
| E/unanswerable | – | 0.82 |
| F/financebench | 0.98 | – |
| F/unanswerable | – | 0.97 |
| F/xbrl | 1.0 | – |

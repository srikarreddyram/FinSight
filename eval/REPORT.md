# FinSight evaluation report

Generated 2026-09-30 from `eval/results/`. Answer model `gemini:gemini-3.5-flash-lite`, query parser / table summaries `gemini:gemma-4-26b-a4b-it`, judge `gemini:gemma-4-26b-a4b-it`.

## Ablation (FinanceBench open sample)

| Run | Parsing | Retrieval | Reranker | Filters | N | Accuracy | Numeric EM | Citation precision | Recall@10 | Median latency | Cost |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A | PyPDF, 1,000-token chunks | Dense only | No | No | 150 | – | – | – | 41% | 0.03 s | – |
| B | Docling, section + table chunks | Dense only | No | No | 150 | – | – | – | 55% | 0.05 s | – |
| C | Docling, section + table chunks | Hybrid (BM25 + dense) | No | No | 150 | – | – | – | 50% | 0.43 s | – |
| D | Docling, section + table chunks | Hybrid (BM25 + dense) | Yes | No | 150 | – | – | – | 59% | 4.64 s | – |
| E | Docling, section + table chunks | Hybrid (BM25 + dense) | Yes | Yes | 150 | 64% | 59% | 96% | 81% | 13.05 s | free (284 calls) |

Targets: accuracy ≥ 60%, numeric match ≥ 80%, citation precision ≥ 90%, recall at 10 ≥ 85%, correct refusals ≥ 80%, median latency < 10 s.

## Other sets

| Run / set | N | Accuracy | Correct refusals | False refusals | Recall@10 |
|---|---|---|---|---|---|
| A/unanswerable | 15 | – | – | – | – |
| B/unanswerable | 15 | – | – | – | – |
| C/unanswerable | 15 | – | – | – | – |
| D/unanswerable | 15 | – | – | – | – |
| E/unanswerable | 15 | – | 100% | – | – |

## Where it still fails (run E)

| Category | Count |
|---|---|
| reasoning | 26 |
| over-refusal | 18 |
| retrieval | 18 |
| citation | 3 |

Examples:

- **over-refusal** — What is Amazon's FY2017 days payable outstanding (DPO)? DPO is defined as: 365 * (average accounts payable between FY2016 and FY2017) / (FY2017 COGS + change in  
  gold: 93.86  
  ours: Not found in the filings. The model's answer could not be supported by the retrieved passages. The closest passages are listed below.
- **retrieval** — Which debt securities are registered to trade on a national securities exchange under American Express' name as of 2022?  
  gold: There are none  
  ours: Not found in the filings. The closest passages are listed below.
- **over-refusal** — Is 3M a capital-intensive business based on FY2022 data?  
  gold: No, the company is managing its CAPEX and Fixed Assets pretty efficiently, which is evident from below key metrics:
CAPEX/Revenue Ratio: 5.1%
Fixed assets/Total  
  ours: Not found in the filings. The closest passages are listed below.
- **retrieval** — If we exclude the impact of M&A, which segment has dragged down 3M's overall growth in 2022?  
  gold: The consumer segment shrunk by 0.9% organically.  
  ours: Not found in the filings. The closest passages are listed below.
- **reasoning** — Assume that you are a public equities analyst. Answer the following question by primarily using information that is shown in the balance sheet: what is the year  
  gold: $8.70  
  ours: At December 31, 2018, 3M's net property, plant and equipment was $8.74 million [3M FY18 p.58].
- **over-refusal** — Which debt securities are registered to trade on a national securities exchange under 3M's name as of Q2 of 2023?  
  gold: Following debt securities registered under 3M's name are listed to trade on the New York Stock Exchange:
-1.500% Notes due 2026 (Trading Symbol: MMM26)
-1.750%   
  ours: Not found in the filings. The closest passages are listed below.
- **reasoning** — Does 3M have a reasonably healthy liquidity profile based on its quick ratio for Q2 of FY2023? If the quick ratio is not relevant to measure liquidity, please s  
  gold: No. The quick ratio for 3M was 0.96 by Jun'23 close, which needs a bit of an improvement to touch the 1x mark  
  ours: 3M maintains a strong liquidity profile supported by cash and cash equivalents of $4,258 million and access to commercial paper [3M Q2 FY23 p.70]. While the company does not explicitly cite the quick ratio in its disclos
- **over-refusal** — What is the FY2019 fixed asset turnover ratio for Activision Blizzard? Fixed asset turnover ratio is defined as: FY2019 revenue / (average PP&E between FY2018 a  
  gold: 24.26  
  ours: Not found in the filings. The closest passages are listed below.
- **reasoning** — Roughly how many times has AES Corporation sold its inventory in FY2022? Calculate inventory turnover ratio for the FY2022; if conventional inventory management  
  gold: AES has converted inventory 9.5 times in FY 2022.  
  ours: AES Corporation turned over its inventory approximately 12.14x times in FY2022, derived from total cost of sales of $10,069 million and an average inventory of $829.5 million [AES Corporation FY22 p.130; AES Corporation 
- **reasoning** — Based on the information provided primarily in the statement of financial position and the statement of income, what is AES's FY2022 return on assets (ROA)? ROA  
  gold: -0.02  
  ours: AES's FY2022 return on assets (ROA) was -0.01x, based on FY2022 net income of -$505 million and average total assets of $35,663 million between FY2021 and FY2022 [AES Corporation FY22 p.130; AES Corporation FY22 p.132].
- **reasoning** — Has AMCOR's quick ratio improved or declined between FY2023 and FY2022? If the quick ratio is not something that a financial analyst would ask about a company l  
  gold: The quick ratio has slightly improved from 0.67 times to 0.69 times between FY 2023 and FY 2022.(3.4% jump)  
  ours: Amcor's quick ratio improved between FY2022 and FY2023 [Amcor FY23 p.52]. The quick ratio rose from 0.53x in FY2022 to 0.57x in FY2023 due to a larger decrease in current liabilities relative to quick assets [Amcor FY23 
- **over-refusal** — What are major acquisitions that AMCOR has done in FY2023, FY2022 and FY2021?  
  gold: Amcor completed these acquisitions during FY2023:
-100% equity interest of a flexibles manufacturing company in the Czech Republic
- 100% equity interest in a m  
  ours: Not found in the filings. The closest passages are listed below.

## Evidence-gate calibration

Median top reranker score (sigmoid) of the best retrieved passage. The gate threshold (`FINSIGHT_EVIDENCE_THRESHOLD`) should sit between the two.

| Run / set | Answerable | Unanswerable |
|---|---|---|
| D/financebench | 0.98 | – |
| D/unanswerable | – | 0.87 |
| E/financebench | 0.98 | – |
| E/unanswerable | – | 0.82 |

# FinSight evaluation report

Generated 2026-11-13 from `eval/results/`. Answer model `gemini:gemini-3.5-flash-lite`, query parser / table summaries `gemini:gemma-4-26b-a4b-it`, judge `gemini:gemma-4-26b-a4b-it`.

## Ablation (FinanceBench open sample)

| Run | Parsing | Retrieval | Reranker | Filters | Retry | XBRL facts | N | Accuracy | Numeric EM | Citation precision | Recall@10 | All evidence read | Median latency | Cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A | PyPDF, 1,000-token chunks | Dense only | No | No | No | No | 150 | – | – | – | 41% | – | 0.03 s | – |
| B | Docling, section + table chunks | Dense only | No | No | No | No | 150 | – | – | – | 55% | – | 0.05 s | – |
| C | Docling, section + table chunks | Hybrid (BM25 + dense) | No | No | No | No | 150 | – | – | – | 50% | – | 0.43 s | – |
| D | Docling, section + table chunks | Hybrid (BM25 + dense) | Yes | No | No | No | 150 | – | – | – | 59% | – | 4.64 s | – |
| E | Docling, section + table chunks | Hybrid (BM25 + dense) | Yes | Yes | No | No | 150 | 66% | 59% | 99% | 81% | 69% | 13.05 s | free (284 calls) |
| F | Docling, section + table chunks | Hybrid (BM25 + dense) | Yes | Yes | Yes | No | 150 | 80% | 78% | 99.5% | 84% | 79% | 12.11 s | free (171 calls) |
| G | Docling, section + table chunks | Hybrid (BM25 + dense) | Yes | Yes | Yes | Yes | 150 | 84% | 83% | 99.5% | 83% | 75% | 9.57 s | free (160 calls) |

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
| G/unanswerable | 30 | – | 100% | – | – |
| G/universe | 39 | 100% | – | 0% | – |

## Where it still fails (run G)

| Category | Count |
|---|---|
| reasoning | 14 |
| ungraded | 12 |
| retrieval | 7 |
| citation | 1 |
| over-refusal | 1 |

Examples:

- **reasoning** — Is 3M a capital-intensive business based on FY2022 data?  
  gold: No, the company is managing its CAPEX and Fixed Assets pretty efficiently, which is evident from below key metrics:
CAPEX/Revenue Ratio: 5.1%
Fixed assets/Total  
  ours: 3M operates as a moderately capital-intensive business in FY2022, with capital expenditures accounting for 5.11% of total revenue and net property, plant, and equipment representing 26.81% of total revenue [3M FY22 XBRL]
- **ungraded** — What drove operating margin change as of FY2022 for 3M? If operating margin is not a useful metric for a company like this, then please state that and explain w  
  gold: Operating Margin for 3M in FY2022 has decreased by 1.7% primarily due to: 
-Decrease in gross Margin
-mostly one-off charges including Combat Arms Earplugs liti  
  ours: Operating income margin for 3M decreased to 19.1% in FY2022 from 20.8% in FY2021 [3M FY22 p.27]. Key drivers included negative raw material impacts of -2.4%, net costs for significant litigation of -6.7%, and PFAS manufa
- **retrieval** — If we exclude the impact of M&A, which segment has dragged down 3M's overall growth in 2022?  
  gold: The consumer segment shrunk by 0.9% organically.  
  ours: Not found in the filings. The closest passages are listed below.
- **reasoning** — Does 3M have a reasonably healthy liquidity profile based on its quick ratio for Q2 of FY2023? If the quick ratio is not relevant to measure liquidity, please s  
  gold: No. The quick ratio for 3M was 0.96 by Jun'23 close, which needs a bit of an improvement to touch the 1x mark  
  ours: 3M maintains a reasonably healthy liquidity profile [3M Q2 FY23 p.70], supported by strong ongoing cash flows, cash on hand, and continuous access to capital markets [3M Q2 FY23 p.70], resulting in a quick ratio of 0.847
- **citation** — Which debt securities are registered to trade on a national securities exchange under 3M's name as of Q2 of 2023?  
  gold: Following debt securities registered under 3M's name are listed to trade on the New York Stock Exchange:
-1.500% Notes due 2026 (Trading Symbol: MMM26)
-1.750%   
  ours: As of June 30, 2,023, 3M has three classes of debt securities registered on the New York Stock Exchange: the 1.5% Notes due 2,026, the 1.75% Notes due 2,030, and the 1.5% Notes due 2,031 [3M Q2 FY23 p.70; 3M Q2 FY23 p.1]
- **reasoning** — Roughly how many times has AES Corporation sold its inventory in FY2022? Calculate inventory turnover ratio for the FY2022; if conventional inventory management  
  gold: AES has converted inventory 9.5 times in FY 2022.  
  ours: AES Corporation's inventory turnover ratio for FY2022 was approximately 12.14x [AES Corporation FY22 XBRL]. While conventional inventory management is less traditional for an energy and utility company since inventories 
- **reasoning** — Based on the information provided primarily in the statement of financial position and the statement of income, what is AES's FY2022 return on assets (ROA)? ROA  
  gold: -0.02  
  ours: AES's FY2022 return on assets (ROA) was -1.42%, calculated from a net income of -$505 million and average total assets of $35,663 million between FY2021 ($32,963 million) and FY2022 ($38,363 million) [AES Corporation FY2
- **reasoning** — Has AMCOR's quick ratio improved or declined between FY2023 and FY2022? If the quick ratio is not something that a financial analyst would ask about a company l  
  gold: The quick ratio has slightly improved from 0.67 times to 0.69 times between FY 2023 and FY 2022.(3.4% jump)  
  ours: Amcor's quick ratio improved between FY2022 and FY2023 [Amcor FY23 p.52]. The quick ratio increased from 0.531x in FY2022 to 0.573x in FY2023 [Amcor FY23 p.52], driven by a reduction in current liabilities that outpaced 
- **over-refusal** — What are major acquisitions that AMCOR has done in FY2023, FY2022 and FY2021?  
  gold: Amcor completed these acquisitions during FY2023:
-100% equity interest of a flexibles manufacturing company in the Czech Republic
- 100% equity interest in a m  
  ours: Not found in the filings. The closest passages are listed below.
- **reasoning** — How much (in USD billions) did American Water Works pay out in cash dividends for FY2020? Compute or extract the answer by primarily using the details outlined   
  gold: $0.40  
  ours: American Water Works paid $0.39 billion in cash dividends for FY2020 [American Water Works FY20 p.86].
- **retrieval** — Was there any drop in Cash & Cash equivalents between FY 2023 and Q2 of FY2024?  
  gold: Yes, there was a decline of ~42% between FY2023 and Q2 of FY 2024.  
  ours: Which company is this about? Name it, or give its ticker with a dollar sign ($NVDA).
- **ungraded** — Are there any product categories / service categories that represent more than 20% of Boeing's revenue for FY2022?  
  gold: Yes. Boeing has product and service categories that represent more than 20% of Boeing's revenue for FY2022. These categories are Commercial Airplanes which comp  
  ours: Yes, product sales represent more than 20% of Boeing's total revenue for FY2022 at 83.91%, whereas service sales account for 16.09% [Boeing FY22 p.55].

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
| G/financebench | 0.98 | – |
| G/unanswerable | – | 0.97 |
| G/universe | 1.0 | – |

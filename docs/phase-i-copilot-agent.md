# Phase I: The Copilot as an agent

The Copilot used to search once and get one shot at answering. It now gets a second attempt when the first one
fails: the model says what it couldn't find, Python searches for exactly that and deeper for the question, and
the model tries once more with the new passages and a note of what went wrong. Every answer still passes the
same checks. With a handful of fixes found on the way, FinanceBench accuracy rose from 66% to 80% under the same
judge, answerable questions refused fell from 30 to 6, and all 30 unanswerable questions were still refused.

## What was actually failing

The run E results (`eval/results/20260930-110737`) were read question by question before changing anything,
and they didn't match the README's own account ("reasoning slips on ratio questions, and over-refusals where the
evidence gate or the figure check was too strict").

**Missing evidence, not reasoning, was the biggest loss.** Recall@10 counts a question as found when any one
gold page is in the top 10. For the 35 questions whose evidence spans two or three pages, that was 86%, but only
46% had every gold page among the 8 passages the model read. Across all 150, 47 questions were short of
evidence, and outcomes split on it:

| Gold pages among the passages the model read | Questions | Correct (graded) | Refused |
|---|---|---|---|
| All of them | 103 | 73 of 94 (78%) | 6 |
| Some or none | 47 | 15 of 44 (34%) | 24 |

**Refusals were mostly the model being right.** 22 of the 30 refusals were the model's own `answerable=false`,
4 were Python removing every sentence, 3 were the evidence gate and 1 a model error. The figure check never
rejected a figure on an answered question (318 of 318 verified).

**Where the missing pages were** (the worst page per question, re-run from the stored query filters):

| Missing page | Questions | Of those refused |
|---|---|---|
| Ranked 9th or 10th, just cut off | 8 | 5 |
| In the top 30, ranked too low | 12 | 5 |
| In the top 200, never reached the reranker | 21 | 10 |
| Not in the top 200 | 3 | 2 |
| Excluded by the company/year filter | 3 | 2 |

So fine-tuning the reranker could reach at most 12 of the 47; most of the gap was further down the search.

**The 20 wrong answers**, read one by one: 3 were a units bug (below), 1 a rounding mismatch, 2 correct answers
the judge marked wrong, 2 gold answers that look wrong, 2 answers with no verdict, 2 defensible formula choices,
3 wrong line items, 1 wrong conclusion and 4 retrieval misses. None was a figure taken from the wrong year's
column.

## Changes

### Fixes (`app/answer.py`, `app/numbers.py`, `app/query_parser.py`, `app/fiscal.py`, `app/config.py`)

- **A year followed by a comma counted as an unsourced number.** "On May 3, 2023, the proposal…" read `2023,`
  as a number rather than a year, and the sentence was removed when its source didn't print 2023. This cut the
  key sentence from four answers (PepsiCo's AGM vote, Best Buy's categories, Activision's capex, Amcor's
  restructuring).
- **Unit conversions kept the old label.** The model converts with `multiply` by 0.001; Python kept "million",
  so $8,738 million became "$8.74 million". A power-of-a-thousand factor now moves the scale with the digits.
- **Results follow the rounding the question asks for**, and ratios under 1 keep a third decimal (0.014x and
  0.008x no longer both read 0.01x).
- **A sentence with a placeholder but no tag cites the sources of its figures**, which Python knows exactly. An
  uncited opening verdict is still removed.
- **Numbers restated from the question are allowed** ("more than 20% of revenue"), and initials ("Mary N.
  Dillon") no longer split sentences.
- **Prompt:** percentages use `margin`, multiples use `ratio`; judgement questions ("is it capital-intensive?")
  get a plain verdict instead of a refusal; a metric that doesn't suit the company is an answer, not a refusal.
- **The query parser's LLM call only runs when the question names no company.** The regex pass retrieved as well
  for no call (all gold pages in the top 8: 71.3% vs 68.7%). The LLM had also filtered two questions that name
  no company to Adobe, the first ticker in its list, so it must now quote the words that refer to the company
  and Python checks they are in the question.
- **Guidance questions also search the year before**: the FY2023 outlook is in the FY2022 results. "FY2023Q1" and
  "Q22023" now parse.
- **The model reads 10 passages, not 8**, and the evidence gate's threshold fell from 0.05 to 0.01. Reranker
  scores don't separate answerable from unanswerable questions (medians 0.98 and 0.82); at 0.05 the gate refused
  three answerable questions and no unanswerable ones.

### The retry (`app/pipeline.py`)

When the first attempt refuses, or Python rejects everything it wrote, `_look_further` adds passages the model
hasn't read: the best 3 for each fact it listed as missing (up to three facts), and the best 4 from a search 50
deep for the question itself. On the 30 questions run E refused, a pool of 50 completed the evidence for 18,
against 11 with the first 10 passages; pools of 100 and 200 also gave 18. The second attempt sees everything
with the same source numbers, plus a note of what failed: what was missing, which figures weren't printed where
cited, which sentences were rejected and why. There is no third attempt. Run F in `RUNS` is this pipeline, and
the API and web app now use it; run E keeps 8 passages and no retry for comparison.

## Evaluation changes (`eval/`)

- **The judge grades the answer, not its citations.** Two correct answers had been marked wrong because a cited
  page didn't support them.
- **Pages are compacted before the judge's 5,000-character limit.** Docling pads table cells, and the padding
  cut tables off before the line the answer used.
- **Ungraded answers are tagged `ungraded`**, not counted as reasoning failures; 10 of run E's 26 "reasoning"
  failures had never been graded.
- **"All evidence read"** reports whether the model read every gold page, alongside recall@10.
- **15 more unanswerable questions**, nearer misses that ask for the overlap of things a filing reports
  separately (AWS revenue in Germany, gross margin on Air Jordan 1s).
- **A second test set with an exact answer key** (`eval/xbrl_set.py`): 98 lookups whose answers and gold pages
  come from each filing's own XBRL data, graded by numeric match with no judge. The first version of the key had
  two errors of its own: it matched periods by calendar year, so Johnson & Johnson's FY2022 (ended 1 January
  2023) got FY2021's balances, and "net income" was ambiguous for companies with minority interests.

Run E's answers were re-graded with the fixed judge (`eval.regrade --all`, into a copy), so both runs are
scored the same way.

## Results

| | Run E | Run F |
|---|---|---|
| Accuracy, graded answers | 93 of 141 (66.0%) | **118 of 147 (80.3%)** |
| Accuracy, ungraded counted wrong | 62.0% | **78.7%** |
| Numeric match (within 1%) | 35 of 59 (59%) | **46 of 59 (78%)** |
| Citation precision | 98.7% | **99.5% (210 of 211)** |
| Recall@10 | 80.7% | 84.0% |
| All gold evidence read | 68.7% | 78.7% |
| Answerable questions refused | 30 | **6** |
| Unanswerable questions refused | 15 of 15 | **30 of 30** |
| Median latency (p90) | 13.1 s (22.0 s) | 12.1 s (22.4 s); 30.8 s when it retries |
| LLM calls for the run | 284 | 171 |

- **Same questions, same judge:** of the 138 graded in both runs, 26 went from wrong to right and 5 from right to
  wrong.
- **The fixes and the retry contribute about equally:** the first attempt alone scores 72.8% (107 of 147); the
  retry ran on 18 questions and 11 of them ended correct.
- **By FinanceBench question type:** metrics-generated 31 of 47 → 42 of 49, domain-relevant 33 of 48 → 36 of 49,
  novel-generated 29 of 46 → 40 of 49.
- **The XBRL set:** 96 of 98 correct, no refusals, median 9.9 s. Ulta Beauty calls the year ending January 2023
  "fiscal 2022", so the model took next year's capex budget; Adobe's cash-flow page wasn't retrieved.
- **Fewer calls:** the parser no longer calls an LLM for named companies, which more than pays for the retries.

## What still fails (run F)

32 of 150 FinanceBench questions:

- **16 wrong answers with the evidence in hand.** By my reading: 6 verdicts the gold disagrees with (3M and CVS
  capital intensity, 3M and Verizon liquidity, Pfizer's spin-off, J&J's EPS outlook), 5 formula or line-item
  choices (average vs year-end inventory, which net income, what counts as a quick asset, EBITDA with content
  amortization), 4 where the judge or the gold looks off, and 1 genuine miss (PepsiCo's restructuring costs).
- **7 retrieval misses**, including one question that names no company ("What drove the reduction in SG&A
  expense…"), which the system answered about Amcor.
- **6 refusals after the retry**, each naming a figure it still couldn't find.
- **3 the judge couldn't grade.**

## Limits and next steps

- **FinanceBench is now partly a development set.** The verdict rule, the rounding rule and several fixes were
  written after reading its failures, so its gain overstates what a new question would see. The XBRL set and the
  15 new unanswerable questions played no part in designing the changes.
- **Verdict questions cut both ways.** "Lead with a plain verdict" ended refusals on judgement questions but
  produced six verdicts the gold disagrees with, and two of the five regressions.
- **Latency is still over the 10-second target**, and a retry takes about 31 s. Most of it is the CPU reranker.
- **Retry depth:** a smoke test with a 100-deep search and 6 passages answered Walmart's DPO question, which the
  full run at 50 and 4 refused. One question proves nothing, but it's worth a test.
- **Fiscal-year names for January year-ends** (Ulta, Best Buy, Walmart) still confuse the model.
- **A question that names no company** should ask which company, not answer about whichever one search finds.
- **The judge** (Gemma 4 on the free tier) still times out on a few answers after retries, and its verdicts
  haven't been checked against a human sample.

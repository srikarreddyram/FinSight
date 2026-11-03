# Phase H: Research tools

Five features that use what FinSight has and a trading app doesn't: every 10-K split into sections, a
point-in-time warehouse with each fact's filing, the Form 4 insider data, and the walk-forward history of the
models. They live on company pages (three new tabs), a Compare page and a time machine (`research/`, served
under `/research`).

## 10-K changes (`research/changes.py`)

This year's Risk Factors (Item 1A) against last year's, paragraph by paragraph. Both are split into paragraphs
(page furniture and fragments of under six words dropped). Each new paragraph is matched to its closest old one
by word overlap (Jaccard similarity of their word sets):

| Overlap | Shown as |
|---|---|
| 0.92 or more | unchanged (collapsed) |
| 0.5 to 0.92 | reworded, with the words added and removed marked (a word-level diff) |
| below 0.5 | new |
| an old paragraph nothing matches at 0.5 | dropped |

On Nike, the 10-K filed 15 July 2026 against the one filed 17 July 2025: 7 new paragraphs, 37 reworded,
14 dropped, 91 unchanged, about 14,500 words each year. The reworded competition risk now names artificial
intelligence, and a new paragraph covers the company's own use of AI tools. A comparison takes about half a
second.

Matching by word overlap finds rewording and moved text but can pair a paragraph with the wrong one when a
section is reorganised; the full-text view shows everything in order.

## Event timeline (`research/timeline.py`)

Three years of a company's own disclosures on one track, each linking to the filing on EDGAR:

- 10-K and 10-Q filings, and late-filing notices
- 8-Ks named by what they announce (EDGAR's item codes): results, leadership changes, deals, other events
- for each earnings report, the stock's two-session move and the move against the S&P 500, from the
  warehouse's daily returns (a second results filing within ten days counts as the same report)
- insider purchases and sales, one per Form 4, with the insider's name and title, the shares and the value

Insider names and titles come from the SEC's Form 3/4/5 data sets; `warehouse.insiders --rebuild` reloads every
quarter from the cached files after the two columns were added. Nike over three years: 87 events, among them
46 insider trades and 11 earnings reports; in the past year 9 insider purchases ($9.2M) and 11 sales ($7.7M).

## Sourced financials (`research/financials.py`)

Four fiscal years of ten lines (revenue, gross profit, operating and net income, operating cash flow, capital
expenditure, cash, long-term debt, equity, dividends) and the margins computed from them. Every figure carries
the filing that reported it, the latest filing to report that period, so a prior year often comes from this
year's 10-K. Hovering a figure shows the form, accession and filing date; clicking opens the filing on SEC.gov.
The research note's facts link to their filings the same way.

## Compare

Two companies side by side: a year of prices from the same starting point, then risk grade, expected and past
volatility, how often similarly graded stocks fell 40% or more, market cap, the latest year's revenue, net
income, cash and debt, margins, insider purchases and sales over the past year, and each company's latest
research note. Each measure has a two-sided bar.

## Time machine (`research/history.py`)

The watchlist as it stood in any month from January 2015 to December 2024, from the walk-forward run: each
month's return ranks and risk grades come from models trained only on earlier data (grades use the risk engine's
own rule), next to what happened over the following 12 months, the return against the S&P 500 and whether the
stock fell 40% or more at some point. A summary row shows each grade's outcome:

| Month | Fell 40%+ in the next year, grades 1 → 5 |
|---|---|
| June 2017 | 2%, 2%, 1%, 3%, 14% |
| December 2019 | 49%, 58%, 63%, 74%, 83% (the COVID crash) |
| December 2021 | 12%, 27%, 32%, 55%, 73% |

2025 is not offered: it is the holdout.

## Research, not trading

The app shows evidence and grades, not instructions: no buy or sell buttons, no price targets, no "top picks".
The only buy and sell language describes what insiders did, from their filings. This is deliberate and should
stay that way.

## Checks

`tests/test_research.py`: paragraph splitting, the four statuses on a constructed pair of sections, the word
diff, headings, and insider names and titles. The Form 4 parsing test now checks the owner's name.

# Phase E: What is moving a stock (Module 8)

For any company in the universe, and for a window of one day, one week or one month, FinSight answers two
questions: how much of the price move was the market, the sector, or the company itself; and, for the company
part, what the news and filings say drove it. The Movers screen applies the first question to all ~1,500
companies at once.

## Move breakdown (`news/moves.py`)

Live adjusted daily closes come from Yahoo Finance. Over the year before the window, the stock's daily log
returns are regressed on the market and on its sector's excess over the market:

    r_stock = a + b_m * r_SPY + b_s * (r_sectorETF - r_SPY) + e

The sector ETF is the SPDR fund for the company's sector (XLK, XLF, XLY, …). Over the window, the market part is
`b_m * sum(r_SPY)`, the sector part `b_s * sum(r_sectorETF - r_SPY)`, and the rest is company-specific. Log
returns add up, so the three parts sum exactly to the total; they are scaled to the simple percentage change
shown. The three days with the largest residuals are the key days to look at, and a company-specific part more
than two standard deviations of its usual size for that many days is flagged as unusual.

On Nike for the week to 5 October 2026: −6.7% in all, of which +0.6% market, +0.1% sector and −7.4%
company-specific, with the largest company-specific fall on 2 October (−4.2%), the day after its earnings.

## Evidence (`news/sources.py`)

- **News:** Google News RSS for `"<company name>" stock`, no key needed; headline, publisher, link and time,
  newest first, with near-duplicate headlines removed. Requests carry a generic User-Agent.
- **Filings:** the company's 8-Ks from EDGAR's submissions API, live, each named by what its items announce
  ("8-K: Results of operations", "Executive or director change", "Acquisition or disposal completed").

Evidence runs from three days before the window to now (this morning's article can explain yesterday's close).
A source that fails is skipped, and interactive requests use short timeouts and retries, so a slow source never
holds a page.

## Investigation (`news/investigate.py`)

One structured LLM call (Gemini Flash-Lite on the free tier, effort low, about 2–3 seconds). The model sees the
move's numbers and key days and up to 30 numbered items: every filing, then the headlines dated closest to the
key days (the newest headlines are often commentary written afterwards). It returns a summary and up to four
drivers, each citing evidence IDs. Python keeps only citations to evidence that was given and drops any driver
left without one, so every claim on screen links to a source. Results are cached per ticker, day and window.

## Movers (`/moves/scan`)

Closes for every current member plus SPY and the sector ETFs, downloaded in chunks (about 45 seconds), give each
company's change over the window against the market and its sector. The screen lists the largest falls and gains
against the sector; a row opens the company page on the same window. The scan runs in its own process, because
yfinance can't download in two threads at once and a scan inside the API process would make company pages wait,
and it is cached for three hours.

## Corporate actions

Yahoo adjusts its history for splits and dividends but not always for spin-offs. Corteva's spin-off of Vylor on
1 October 2026 shows as a one-day −84% that was not a loss to shareholders. Size alone can't separate that from a
real collapse (Liquidia fell 57% on a patent ruling the day before), so the app states the fact rather than a
guess: Movers marks any single day of ±40% or more, and a company page flags a possible spin-off when such a day
sits within a week of an 8-K reporting a completed acquisition or disposal. The investigation sees the same 8-K
and headlines, and for Corteva names the spin-off.

## Earnings reactions (`news/earnings.py`, `/moves/{ticker}/earnings`)

An earnings report is a day the company filed an 8-K with item 2.02; a second results filing within ten days is
the same report. Companies report before the open or after the close and the filing date doesn't say which, so the
reaction is measured over two sessions, from the close before the filing date to the close of the trading day
after it, and set against the S&P 500 over the same days. The company page shows five years of reactions with the
typical (median absolute) move, how often the stock rose, the worst reaction, and whether the latest is the biggest
in that direction since some date. Nike: ±6.5% typical, up after 7 of 21 reports, worst −19.6% (June 2024).

## Checks

`tests/test_news.py`: RSS parsing and de-duplication, 8-K item naming, a synthetic stock with known betas and a
planted company shock (the parts sum to the total, the shock is the key day), the market-only fallback, short
histories refused, the scan's comparisons, citation filtering, evidence selection around key days, and the API
with a cached investigation.

## Limits

- News coverage is whatever Google News indexes for the company name; small companies get fewer stories, and
  common-word names can pull in unrelated ones (the model is told to ignore other companies).
- Headlines are evidence of what was reported, not proof of cause. Drivers are the model's reading of dated
  sources and carry a confidence level.
- Yahoo and Google News are free, unofficial endpoints that can change or throttle without notice.

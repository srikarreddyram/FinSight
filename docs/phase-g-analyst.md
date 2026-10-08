# Phase G: Research notes (Module 2, first version)

For any company in the universe, one click writes a research note: a headline, a short summary, the key numbers,
a bull case, a bear case and what to watch. It is written from the company's latest 10-K, its financial
statements, the past month's news and FinSight's own data. Every point cites the sources listed under the note,
and every figure in the note was either filled in by Python or found in a source the sentence cites.

The PRD's Module 2 has two parts: the thesis shown next to each stock, and open-ended questions ("Is 3M's dividend
sustainable?") answered by a planner that sends sub-questions through the Copilot. This phase builds the first
part. The question-driven memo is still to do.

## Sources (`analyst/context.py`)

Each source becomes a numbered item that the note cites by ID.

| ID | Source | What goes in |
|---|---|---|
| K | The latest 10-K, from the warehouse, following predecessor CIKs | Up to ten risk headings from Item 1A, and the Item 7 (MD&A) passages closest to four questions |
| X | XBRL financial facts, point-in-time | Ten line items for the last three fiscal years, plus revenue growth, margins and free cash flow |
| N | Google News and EDGAR 8-Ks (the Moves module's sources) | Up to 14 items from the past 30 days |
| D | FinSight's data | Risk grade, expected volatility, severe-loss rate, top risk drivers, the past month's move split into market, sector and company parts, earnings reactions |

- **Risk headings.** Item 1A states each risk as a one-sentence heading followed by its explanation. The headings
  are found as one-sentence lines of 8–50 words, skipping bullets, page furniture and the forward-looking-statements
  boilerplate.
- **MD&A passages.** Item 7 is split into passages of about 170 words along line boundaries. The three passages
  closest to each of four questions are kept: the year's results, what moved revenue and gross margin, the outlook,
  and liquidity and capital returns. Closeness is cosine similarity of bge-base embeddings, the Copilot's embedder.
  Nike's 10-K gives 54 passages, of which 11 are kept.
- **Facts.** Revenue, gross profit, operating income, net income, operating cash flow, capital expenditure, cash,
  long-term debt, equity and dividends paid, as the warehouse's `Snapshot` sees them today. Growth, margins and free
  cash flow are computed from them.

The three source groups are fetched in parallel: about 15 seconds, most of it Yahoo prices for the move and the
earnings reactions.

## Writing and checking (`analyst/note.py`)

One structured call to the answer model (Gemini Flash-Lite on the free tier, temperature 0, medium thinking),
about 10 seconds. The model returns a headline, a summary, two to four bull and bear points, two or three things
to watch, and the IDs of the four to six facts that matter most.

The model is told never to type an X or D figure. It writes the item's placeholder instead, and Python fills in
the value:

    model:   Net income fell to {X7} in fiscal 2026 [X7] ...
    page:    Net income fell to $3.11B in fiscal 2026 [X7] ...

The 10-K passages hold the detail a note needs (segment, channel and regional figures) and have no placeholders.
The model may quote a figure from a passage or headline it cites, exactly as written there. Python then checks
every sentence:

- Every number that isn't a filled placeholder must appear, with the same unit, in an item the sentence cites.
  "$27.5 billion" and "$27.50B" match; "$27.5 million" does not. Years, "10-K", "Item 7", "Q3" and index names are
  not figures. A sentence that fails is removed.
- A placeholder for an item that has no single value (a 10-K passage, a driver) removes its sentence.
- A filled figure cites the item it came from, even when the model forgot to.
- Citations to items that weren't given are removed, and a point left without a citation is dropped.
- Key numbers shown above the note can only be X facts.

On Nike, the first prompt let the model use `{K11}` as if a passage were a figure, and the checks removed those
sentences, leaving one bull point. The prompt now says which items have placeholders and how to quote a passage.
The next note kept every point. Checked by hand against the 10-K, each of its figures (wholesale $27.5 billion,
gross margin up 20 basis points to 42.9%, NIKE Direct $17.7 billion, Greater China down 11%) was in the passage it
cited and meant what the note said.

The checks make every figure traceable to a source. They don't make the sentence around it true: a figure from the
right passage can still be attached to the wrong line of a table, and words like "fell" or "improved" are not
checked against the numbers. On Nike, two such claims were checked by hand (net income $3.22B → $3.11B, "declined";
gross profit $19.79B → $19.91B, "ticked up") and were right. The citation chips are there so a reader can do the
same.

## API and app

    GET  /analyst/{ticker}            the latest note, or null
    POST /analyst/{ticker}/context    read the sources; returns counts (about 15 s)
    POST /analyst/{ticker}            write today's note from them (about 10 s); ?refresh=true rewrites it

A note is cached per company per day in `data/analyst/`, so the page opens on the latest note and a second click
costs nothing. Notes are written on request, one model call each, rather than for all 1,500 companies every day,
which the free tier's daily request limit wouldn't allow.

The company page has a **Research note** tab. Before a note exists it offers to write one. While writing, it shows
the two steps as they happen, with the counts from the first ("21 passages from the 10-K filed Jul 15, 2026 · 30
financial facts · 14 news items · 13 FinSight figures"). The note shows key numbers, bull and bear cards, what to
watch, and the sources grouped by kind. Cited sources show by default; a 10-K passage expands to its full text with
a link to the filing.

The hosted demo includes notes for ten well-known companies and the week's three largest gainers and losers.

## Checks

`tests/test_analyst.py`: figure matching across formats and units; placeholders that fill and cite; quoted figures
that must be in a cited item; what can't be filled is dropped; years and filing names pass; `clean` on a mixed
response; risk headings, MD&A passages and passage titles; money formatting; and the API's two steps with a
stand-in model (the note reuses the gathered sources, is cached for the day, and is rewritten on refresh).

## Limits

- One 10-K, the latest. Quarterly filings, earnings calls and older 10-Ks aren't read yet, so a note written
  months after the 10-K leans on the news for anything since.
- Retrieval picks MD&A passages by four fixed questions. A company whose story sits elsewhere (Item 1's business
  description, or a note to the financial statements) gets less of it.
- Directional words aren't checked against the figures, as above.
- News is whatever Google News returns for the company name, as in Module 8.

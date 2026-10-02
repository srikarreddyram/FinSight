"""10-K text from EDGAR into `filing_text`, one row per Item, for the Signal Lab's text features.

    uv run python -m warehouse.tenk                   # every company in the warehouse, 10-Ks filed since 2009
    uv run python -m warehouse.tenk MMM JPM --since 2015

The primary document is split into Items with `sections.split_10k`. Some companies put MD&A (Item 7) in
Exhibit 13, the annual report to shareholders, and the 10-K only says "incorporated by reference"; for those
the MD&A is cut out of the exhibit instead. Filings already in `filing_text` are skipped, so a run resumes.
Each filing is also recorded in `filings` with its filing date, which is when its text became public.
"""

from __future__ import annotations

import argparse
import logging
import math
import re
from dataclasses import dataclass
from datetime import date

import duckdb

from app.config import get_settings
from warehouse import db
from warehouse.sections import Section, html_to_text, split_10k, store

log = logging.getLogger(__name__)

FORMS = ("10-K", "10-K405")
MIN_MDA_WORDS = 500  # below this, Item 7 is a cross-reference to Exhibit 13
INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{accn}-index.htm"
OLDER_URL = "https://data.sec.gov/submissions/{name}"


@dataclass(frozen=True)
class Filing:
    accn: str
    form: str
    filed_at: date
    period_end: date | None
    primary: str


def _rows(block: dict) -> list[dict]:
    return [dict(zip(block.keys(), vals, strict=True)) for vals in zip(*block.values(), strict=True)]


def list_10ks(sub: dict, older: list[dict], since: date) -> list[Filing]:
    """Every original 10-K filed on or after `since`, newest first, from the submissions JSON and its older
    pages (EDGAR keeps the latest ~1,000 filings in `recent` and the rest in separate files)."""
    out = {}
    for r in _rows(sub["filings"]["recent"]) + [r for page in older for r in _rows(page)]:
        if r["form"] not in FORMS or not r.get("primaryDocument"):
            continue
        filed = date.fromisoformat(r["filingDate"])
        if filed < since:
            continue
        period = date.fromisoformat(r["reportDate"]) if r.get("reportDate") else None
        out[r["accessionNumber"]] = Filing(r["accessionNumber"], r["form"], filed, period, r["primaryDocument"])
    return sorted(out.values(), key=lambda f: f.filed_at, reverse=True)


_EX13_ROW = re.compile(r"(?is)<tr[^>]*>(?:(?!</tr>).)*?>\s*EX-13[^<]*<(?:(?!</tr>).)*?</tr>")
_HREF = re.compile(r'(?i)href="([^"]+)"')


def exhibit_13_urls(index_html: str) -> list[str]:
    """URLs of the EX-13 documents listed on a filing's index page. Inline-XBRL filings link through the
    viewer ("/ix?doc=/Archives/..."), which is a stub page; the document itself is the part after doc=."""
    out = []
    for row in _EX13_ROW.findall(index_html):
        for link in _HREF.findall(row):
            link = link.removeprefix("/ix?doc=")
            if not link.endswith((".pdf", ".jpg", ".gif")):
                out.append(link if link.startswith("http") else f"https://www.sec.gov{link}")
    return out


_MDA_HEAD = re.compile(
    # Any Item number: Walmart's annual-report exhibit numbers its own sections ("Item 2. Management's...").
    r"(?im)^\s*(?:(?:item\s*\d{1,2}[a-c]?\.?\s*)?management[’']?s\s+discussion\s+and\s+analysis\b.*|"
    r"financial\s+review[ \t]*)$"  # American Express and Pfizer title their MD&A "Financial Review"
)
_MDA_END = re.compile(
    r"(?im)^\s*(?:report\s+of\s+independent\s+registered\s+public\s+accounting\s+firm|"
    r"management[’']?s\s+report\s+on\s+internal\s+control|consolidated\s+statements?\s+of\b|"
    r"consolidated\s+balance\s+sheets?[ \t]*(?:\(continued\))?[ \t]*$)"  # whole line: not "...Balance Sheets Analysis"
)


_ITEM_LINE = re.compile(r"(?im)^\s*item\s*\d{1,2}[a-c]?\b")


def _end_heading(text: str, pos: int) -> int | None:
    """Start of the first financial-statements heading after pos. A heading starts with a capital and is a
    short line of its own; table rows like "...reflected in our / consolidated balance sheet / 806" are not."""
    for m in _MDA_END.finditer(text, pos):
        line_end = text.find("\n", m.start())
        line = text[m.start() : line_end if line_end != -1 else len(text)].strip()
        if line[:1].isupper() and len(line) < 120:
            return m.start()
    return None


def mda_from_exhibit(text: str) -> Section | None:
    """MD&A cut from an annual-report exhibit: from a "Management's Discussion and Analysis" heading to the
    next financial-statements heading. Tables of contents list both close together, so the longest span wins.
    A heading with no statements after it (a 10-K's cross-reference index) is not an MD&A, and neither is a
    span that crosses other 10-K Items (a table-of-contents entry followed, much later, by Item 15's list of
    financial statements)."""
    best = None
    for m in _MDA_HEAD.finditer(text):
        stop = _end_heading(text, m.end())
        if stop is None or len(_ITEM_LINE.findall(text, m.end(), stop)) >= 3:
            continue
        if best is None or stop - m.start() > best[1] - best[0]:
            best = (m.start(), stop)
    if best is None or math.log1p(best[1] - best[0]) < math.log1p(2000):
        return None
    return Section(
        item="7", name="Management's Discussion and Analysis", start=best[0], end=best[1], text=text[best[0] : best[1]].strip()
    )


def fetch_filing(edgar, cik: int, f: Filing) -> dict[str, Section]:
    from ingest.fetch_edgar import ARCHIVE_URL

    acc = f.accn.replace("-", "")
    primary = html_to_text(edgar.get(ARCHIVE_URL.format(cik=cik, acc=acc, doc=f.primary)).text)
    sections = split_10k(primary)
    mda = sections.get("7")
    if mda is None or mda.word_count < MIN_MDA_WORDS:
        # MD&A lives in Exhibit 13 (Pfizer, older CVS) or, for 10-Ks laid out as the annual report with a
        # cross-reference index (JPMorgan), under its own heading in the main document.
        index = edgar.get(INDEX_URL.format(cik=cik, acc=acc, accn=f.accn)).text
        texts = (html_to_text(edgar.get(url).text) for url in exhibit_13_urls(index))
        for text in (*texts, primary):
            found = mda_from_exhibit(text)
            if found:
                sections["7"] = found
                break
    return sections


def fetch(
    con: duckdb.DuckDBPyConnection, tickers: list[str] | None, since: date, universe: bool = False, items: set[str] | None = None
) -> None:
    from ingest.fetch_edgar import SUBMISSIONS_URL, Edgar

    s = get_settings()
    if not s.sec_user_agent:
        raise SystemExit('Set FINSIGHT_SEC_USER_AGENT in .env, e.g. "FinSight research you@example.com" (SEC requires it)')
    edgar = Edgar(s.sec_user_agent)
    # Universe companies and the predecessors they reorganised from (warehouse.universe's cik_links).
    where = "where cik in (select cik from universe union select predecessor from cik_links)" if universe else ""
    companies = con.execute(f"select cik, ticker from companies {where} order by ticker").fetchall()
    if tickers:
        companies = [(c, t) for c, t in companies if t in tickers]
    done = {r[0] for r in con.execute("select distinct accn from filing_text").fetchall()}
    for cik, ticker in companies:
        sub = edgar.get(SUBMISSIONS_URL.format(cik=cik)).json()
        older = [edgar.get(OLDER_URL.format(name=p["name"])).json() for p in sub["filings"].get("files", [])
                 if date.fromisoformat(p["filingTo"]) >= since]  # fmt: skip
        filings = list_10ks(sub, older, since)
        new = [f for f in filings if f.accn not in done]
        log.info("%s: %d 10-Ks since %s, %d to fetch", ticker, len(filings), since, len(new))
        for f in new:
            try:
                sections = fetch_filing(edgar, cik, f)
            except Exception as e:  # one bad document shouldn't stop the run
                log.warning("%s %s: %s", ticker, f.accn, e)
                continue
            con.execute(
                "insert into filings (accn, cik, form, period_end, filed_at) values (?, ?, ?, ?, ?) on conflict do nothing",
                [f.accn, cik, f.form, f.period_end, f.filed_at],
            )
            store(con, f.accn, cik, {k: v for k, v in sections.items() if items is None or k in items})
            mda = sections.get("7")
            log.info("  %s %s: items %s; MD&A %s words", f.filed_at, f.accn, ",".join(sections), mda.word_count if mda else 0)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tickers", nargs="*")
    ap.add_argument("--since", default="2009-01-01", type=date.fromisoformat, help="earliest filing date")
    ap.add_argument("--universe", action="store_true", help="every company in the universe table")
    ap.add_argument("--items", help="comma-separated Items to store (default: all), e.g. 1A,3,7,7A,9A")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    con = db.connect()
    items = set(args.items.split(",")) if args.items else None
    fetch(con, [t.upper() for t in args.tickers] or None, args.since, args.universe, items)
    n = con.execute("select count(distinct accn), count(*) from filing_text").fetchone()
    log.info("filing_text: %d filings, %d sections", *n)
    con.close()


if __name__ == "__main__":
    main()

"""Index the 10-K text the warehouse already holds, so the Copilot can answer about any company in the universe.

The warehouse keeps the main items of every 10-K (warehouse.tenk). For each company still filing, its latest
10-K's business, risk factors, legal proceedings, MD&A, market risk and controls become text chunks like the
FinanceBench filings' (~500 tokens, by section, with the company and fiscal year in each), embedded and
BM25-indexed in their own collection. They have no page numbers, so a citation names the item and links to the
filing on EDGAR. Figures come from the XBRL facts source (app/facts.py), so tables aren't needed here.

About 1,600 companies and 150,000 chunks, an hour of embedding on an Apple GPU: too many points for Qdrant's
embedded mode, so this needs the server (copy the FinanceBench collections over first with ingest.move_index).

    docker compose up -d qdrant
    FINSIGHT_QDRANT_URL=http://localhost:6333 uv run python -m ingest.sections
    FINSIGHT_QDRANT_URL=http://localhost:6333 uv run python -m ingest.sections --tickers NVDA AAPL
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from datetime import date, timedelta
from functools import lru_cache

import duckdb

from app.config import get_settings
from app.schemas import Company, DocMeta, Element, ParsedDoc
from ingest.chunk import text_chunks
from ingest.index import _hash, _load_state, _save_state, delete_doc, upsert_chunks
from warehouse import db

log = logging.getLogger(__name__)

ITEMS = {"1": "Business", "1A": "Risk Factors", "3": "Legal Proceedings", "7": "MD&A", "7A": "Market Risk", "9A": "Controls"}
FILED_WITHIN_DAYS = 550  # a company whose latest 10-K is older than this has stopped filing

_SUFFIX = re.compile(
    r",?\s+(Inc\.?|Incorporated|Corporation|Corp\.?|Company|Co\.?|Ltd\.?|Limited|plc|N\.V\.|S\.A\.|L\.P\.|Holdings?|Group)$",
    re.I,
)
# One-word names too common to match on their own ("Southern" for The Southern Company): these keep their suffix.
_GENERIC = {
    "american", "bank", "brands", "central", "citizens", "commerce", "community", "consolidated", "eastern", "energy",
    "federal", "financial", "first", "general", "global", "health", "independent", "industries", "insurance",
    "international", "national", "northern", "pacific", "progressive", "public", "regional", "republic", "resources",
    "select", "services", "southern", "standard", "systems", "technologies", "united", "universal", "western",
}  # fmt: skip


def clean_name(name: str) -> str:
    """'Coca-Cola Company (The)' -> 'Coca-Cola', 'Ichor Holdings, Ltd.' -> 'Ichor'."""
    full = re.sub(r"\s*\(The\)$", "", name).strip()
    short, prev = re.sub(r"^The\s+", "", full), None
    while short != prev:
        prev, short = short, _SUFFIX.sub("", short).strip().rstrip(",")
    if not short or (" " not in short and short.lower() in _GENERIC):
        return full
    return short


def fiscal_year_of(period_end: date) -> tuple[int, int]:
    """(fiscal year, fiscal-year-end month) of a 10-K's period. A 52/53-week year that ends in the first days of a
    month belongs to the month before: Johnson & Johnson's FY2022 ended on 1 January 2023."""
    nominal = period_end - timedelta(days=7) if period_end.day <= 7 else period_end
    return nominal.year, nominal.month


def edgar_url(cik: int, accn: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/{accn}-index.htm"


def latest_10ks(con: duckdb.DuckDBPyConnection, tickers: list[str] | None = None) -> list[dict]:
    """Each company's newest 10-K with text in the warehouse, if it was filed within FILED_WITHIN_DAYS."""
    # The filings index rarely records the period; the newest annual period the 10-K's own facts report is it.
    rows = con.execute(
        """
        with latest as (
            select f.cik, f.accn, f.period_end, f.filed_at,
                   row_number() over (partition by f.cik order by f.filed_at desc) as rn
            from filings f
            where f.form like '10-K%' and exists (select 1 from filing_text t where t.accn = f.accn)
        ),
        ends as (
            select accn, max(period_end) as period_end from facts
            where period_start is not null and accn in (select accn from latest where rn = 1)
            group by accn
        )
        select l.cik, l.accn, coalesce(l.period_end, e.period_end), l.filed_at, c.ticker, c.name
        from latest l join companies c using (cik) left join ends e using (accn)
        where l.rn = 1 and c.ticker is not null
          and l.filed_at >= (select max(filed_at) from filings where form like '10-K%') - ?::integer
        order by c.ticker
        """,
        [FILED_WITHIN_DAYS],
    ).fetchall()
    out = []
    for cik, accn, period_end, filed_at, ticker, name in rows:
        if (tickers and ticker not in tickers) or period_end is None:
            continue
        year, fye = fiscal_year_of(period_end)
        out.append(
            {
                "ticker": ticker,
                "name": clean_name(name),
                "legal_name": name,
                "cik": cik,
                "accn": accn,
                "doc_id": f"edgar:{cik}:{accn}",
                "fiscal_year": year,
                "fye_month": fye,
                "filed": filed_at.isoformat(),
            }
        )
    return out


def parsed(con: duckdb.DuckDBPyConnection, filing: dict) -> ParsedDoc:
    """The filing's items as a ParsedDoc, one element per line of text, so ingest.chunk can chunk it."""
    meta = DocMeta(
        doc_id=filing["doc_id"],
        ticker=filing["ticker"],
        company=filing["name"],
        doc_type="10-K",
        fiscal_year=filing["fiscal_year"],
        fiscal_year_end_month=filing["fye_month"],
        url=edgar_url(filing["cik"], filing["accn"]),
        track="sections",
    )
    texts = dict(con.execute("select item, text from filing_text where accn = ?", [filing["accn"]]).fetchall())
    elements: list[Element] = []
    for item, section in ITEMS.items():
        text = texts.get(item)
        if not text:
            continue
        heading = f"Item {item}. {section}"
        elements.append(Element(kind="heading", text=heading, page=0, section=section, heading=heading))
        for line in text.splitlines():
            line = line.strip()
            if len(line.split()) >= 4:  # page furniture and stray numbers carry nothing
                elements.append(Element(kind="text", text=line, page=0, section=section, heading=heading))
    return ParsedDoc(meta=meta, parser="warehouse", page_count=0, elements=elements)


def manifest_path():
    return get_settings().cache_dir / "sections.json"


@lru_cache(maxsize=1)
def indexed() -> dict[str, dict]:
    """ticker -> the 10-K whose sections are indexed, for every company ingest.sections has run on."""
    p = manifest_path()
    return {f["ticker"]: f for f in json.loads(p.read_text())} if p.exists() else {}


def companies() -> dict[str, Company]:
    return {
        t: Company(ticker=t, name=f["name"], fiscal_year_end_month=f["fye_month"], aliases=[f["legal_name"]])
        for t, f in indexed().items()
    }


def main() -> None:
    from app.store import get_embedders

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*", help="only these companies")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    s = get_settings()
    if not s.qdrant_url:
        raise SystemExit("set FINSIGHT_QDRANT_URL (the Qdrant server): this is too many points for the embedded store")
    con = duckdb.connect(str(db.default_path()), read_only=True)
    filings = latest_10ks(con, args.tickers)
    emb, collection = get_embedders(), s.sections_collection
    done = {f["ticker"]: f for f in (json.loads(manifest_path().read_text()) if manifest_path().exists() else [])}
    t0, chunks_total = time.time(), 0
    for n, f in enumerate(filings, 1):
        old = done.get(f["ticker"])
        if old and old["doc_id"] != f["doc_id"]:
            delete_doc(collection, old["doc_id"])  # a newer 10-K replaces the company's previous one
        chunks = text_chunks(parsed(con, f), s)
        digest = _hash(chunks)
        if chunks and _load_state().get(collection, {}).get(f["doc_id"]) != digest:
            delete_doc(collection, f["doc_id"])
            upsert_chunks(collection, chunks, emb)
            state = _load_state()
            state.setdefault(collection, {})[f["doc_id"]] = digest
            _save_state(state)
            chunks_total += len(chunks)
        if chunks:
            done[f["ticker"]] = f
            manifest_path().parent.mkdir(parents=True, exist_ok=True)
            manifest_path().write_text(json.dumps(sorted(done.values(), key=lambda x: x["ticker"]), indent=1))
        if n % 25 == 0 or n == len(filings):
            rate = chunks_total / max(time.time() - t0, 1)
            log.info("[%d/%d] %s: %d chunks indexed (%.0f a second)", n, len(filings), f["ticker"], chunks_total, rate)


if __name__ == "__main__":
    main()

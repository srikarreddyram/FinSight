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
    uv run python -m ingest.sections --vocab        # only rebuild the vocabulary of ordinary words

With this many companies, names and tickers collide with ordinary words ("Target", "Post", the ticker COST), so
the run also measures which words filings themselves use as ordinary words (`vocabulary`). The query parser uses
that to decide what can name a company on its own (app/query_parser.py).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
import re
import time
from collections import Counter
from collections.abc import Collection
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import duckdb

from app.config import get_settings
from app.query_parser import Vocab
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
# Ordinary words that are better known as the company: these stay one word.
_HOUSEHOLD = {"target", "visa", "gap", "block"}
_TOKEN = re.compile(r"[A-Za-z0-9&]+")


def clean_name(name: str, plain: Collection[str] = frozenset()) -> str:
    """'Coca-Cola Company (The)' -> 'Coca-Cola', 'Ichor Holdings, Ltd.' -> 'Ichor'. Suffixes come off until what
    is left would be an ordinary word (`plain`, or a generic one): 'Post Holdings', 'News Corp' and 'Southern
    Company' stay whole, because "Post" or "News" alone would match half the questions anyone asks."""
    short = re.sub(r"^The\s+", "", re.sub(r"\s*\(The\)$", "", name).strip())
    while True:
        cut = _SUFFIX.sub("", short).strip().rstrip(",")
        word = cut.lower()
        if not cut or cut == short:
            return short
        if " " not in cut and (word in _GENERIC or (word in plain and word not in _HOUSEHOLD)):
            return short
        short = cut


def fiscal_year_of(period_end: date) -> tuple[int, int]:
    """(fiscal year, fiscal-year-end month) of a 10-K's period. A 52/53-week year that ends in the first days of a
    month belongs to the month before: Johnson & Johnson's FY2022 ended on 1 January 2023."""
    nominal = period_end - timedelta(days=7) if period_end.day <= 7 else period_end
    return nominal.year, nominal.month


def edgar_url(cik: int, accn: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/{accn}-index.htm"


def latest_10ks(
    con: duckdb.DuckDBPyConnection, tickers: list[str] | None = None, plain: Collection[str] = frozenset()
) -> list[dict]:
    """Each company's newest 10-K with text in the warehouse, if it was filed within FILED_WITHIN_DAYS.
    plain: ordinary words (see `vocabulary`), which a company name isn't shortened to."""
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
        if period_end is None:
            continue
        year, fye = fiscal_year_of(period_end)
        out.append(
            {
                "ticker": ticker,
                "name": clean_name(name, plain),
                "legal_name": name,
                "cik": cik,
                "accn": accn,
                "doc_id": f"edgar:{cik}:{accn}",
                "fiscal_year": year,
                "fye_month": fye,
                "filed": filed_at.isoformat(),
            }
        )
    # A name two companies share can't say which one a question means, and one of them has the wrong name
    # (the warehouse lists Ribbon Communications under the name of the company that replaced it in the index).
    shared = {n for n, k in Counter(f["name"].lower() for f in out).items() if k > 1}
    for f in out:
        if f["name"].lower() in shared:
            log.warning("skipping %s: the name %r is shared with another company", f["ticker"], f["name"])
    return [f for f in out if f["name"].lower() not in shared and (not tickers or f["ticker"] in tickers)]


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


# --------------------------------------------------------------------------------------------
# Which words are ordinary
# --------------------------------------------------------------------------------------------


def vocabulary(con: duckdb.DuckDBPyConnection, filings: list[dict], sample: int = 400, share: float = 0.01) -> dict:
    """Words that can't name a company on their own, measured on the filings themselves: the lower-case words
    (`plain`) and all-capital tokens (`caps`) that at least `share` of a sample of 10-Ks use in their MD&A and risk
    factors. Of 400 filings, 294 write "target" and 218 "post"; none writes "apple" or "nvidia" in lower case.
    155 write "IT" and 9 "ARR"; 3 write "IBM"."""
    picked = random.Random(7).sample(filings, min(sample, len(filings)))
    lower: Counter[str] = Counter()
    upper: Counter[str] = Counter()
    for f in picked:
        rows = con.execute("select text from filing_text where accn = ? and item in ('7', '1A')", [f["accn"]]).fetchall()
        tokens = set(_TOKEN.findall(" ".join(r[0] or "" for r in rows)))
        lower.update(t for t in tokens if t.islower())
        upper.update(t for t in tokens if t.isupper() and len(t) >= 2)
    floor = max(2, math.ceil(share * len(picked)))
    return {
        "sampled": len(picked),
        "share": share,
        "plain": sorted(w for w, n in lower.items() if n >= floor),
        "caps": sorted(w for w, n in upper.items() if n >= floor),
    }


def vocab_path() -> Path:
    return get_settings().cache_dir / "name_vocab.json"


@lru_cache(maxsize=1)
def vocab() -> Vocab | None:
    """The vocabulary `ingest.sections` measured, or None before it has run."""
    p = vocab_path()
    if not p.exists():
        return None
    v = json.loads(p.read_text())
    return Vocab(plain=frozenset(v["plain"]), caps=frozenset(v["caps"]))


# --------------------------------------------------------------------------------------------
# What is indexed
# --------------------------------------------------------------------------------------------


def manifest_path() -> Path:
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


def _forget(collection: str, doc_id: str) -> None:
    delete_doc(collection, doc_id)
    state = _load_state()
    if state.get(collection, {}).pop(doc_id, None) is not None:
        _save_state(state)


def main() -> None:
    from app.store import get_embedders

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*", help="only these companies")
    ap.add_argument("--vocab", action="store_true", help="only rebuild the vocabulary of ordinary words")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    s = get_settings()
    con = duckdb.connect(str(db.default_path()), read_only=True)
    if args.vocab or not vocab_path().exists():
        v = vocabulary(con, latest_10ks(con))
        vocab_path().parent.mkdir(parents=True, exist_ok=True)
        vocab_path().write_text(json.dumps(v))
        vocab.cache_clear()
        log.info("vocabulary from %d filings: %d ordinary words, %d acronyms", v["sampled"], len(v["plain"]), len(v["caps"]))
        if args.vocab:
            return
    if not s.qdrant_url:
        raise SystemExit("set FINSIGHT_QDRANT_URL (the Qdrant server): this is too many points for the embedded store")
    filings = latest_10ks(con, args.tickers, vocab().plain)
    emb, collection = get_embedders(), s.sections_collection
    done = {f["ticker"]: f for f in (json.loads(manifest_path().read_text()) if manifest_path().exists() else [])}

    def save() -> None:
        manifest_path().parent.mkdir(parents=True, exist_ok=True)
        manifest_path().write_text(json.dumps(sorted(done.values(), key=lambda x: x["ticker"]), indent=1))

    t0, chunks_total = time.time(), 0
    for n, f in enumerate(filings, 1):
        old = done.get(f["ticker"])
        if old and old["doc_id"] != f["doc_id"]:
            _forget(collection, old["doc_id"])  # a newer 10-K replaces the company's previous one
        chunks = text_chunks(parsed(con, f), s)
        digest = _hash(chunks)
        if chunks and _load_state().get(collection, {}).get(f["doc_id"]) != digest:
            delete_doc(collection, f["doc_id"])
            upsert_chunks(collection, chunks, emb)
            state = _load_state()
            state.setdefault(collection, {})[f["doc_id"]] = digest
            _save_state(state)
            chunks_total += len(chunks)
        if chunks and old != f:
            done[f["ticker"]] = f
            save()
        if n % 25 == 0 or n == len(filings):
            rate = chunks_total / max(time.time() - t0, 1)
            log.info("[%d/%d] %s: %d chunks indexed (%.0f a second)", n, len(filings), f["ticker"], chunks_total, rate)
    if not args.tickers:
        # Companies that stopped filing, or whose name turned out to be shared, leave the index.
        for t in sorted(set(done) - {f["ticker"] for f in filings}):
            _forget(collection, done.pop(t)["doc_id"])
            log.info("removed %s", t)
        save()


if __name__ == "__main__":
    main()

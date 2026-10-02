"""FinanceBench open-source sample: questions, gold evidence pages, and the underlying filing PDFs.

    uv run python -m eval.financebench_loader            # questions + manifest + all 84 PDFs
    uv run python -m eval.financebench_loader --docs 3M_2018_10K PEPSICO_2022_10K

Gold evidence pages in the dataset are 0-indexed; they are converted to 1-indexed here, matching
the page numbers used everywhere else in FinSight.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path

import httpx
from pydantic import BaseModel

from app.config import get_settings
from app.schemas import Company, DocMeta

log = logging.getLogger(__name__)

RAW = "https://raw.githubusercontent.com/patronus-ai/financebench/main"
QUESTIONS_URL = f"{RAW}/data/financebench_open_source.jsonl"
DOCINFO_URL = f"{RAW}/data/financebench_document_information.jsonl"

# company name in the dataset -> (ticker, fiscal-year-end month)
COMPANIES: dict[str, tuple[str, int]] = {
    "3M": ("MMM", 12),
    "AES Corporation": ("AES", 12),
    "AMD": ("AMD", 12),
    "Activision Blizzard": ("ATVI", 12),
    "Adobe": ("ADBE", 11),
    "Amazon": ("AMZN", 12),
    "Amcor": ("AMCR", 6),
    "American Express": ("AXP", 12),
    "American Water Works": ("AWK", 12),
    "Best Buy": ("BBY", 1),
    "Block": ("SQ", 12),
    "Boeing": ("BA", 12),
    "CVS Health": ("CVS", 12),
    "Coca-Cola": ("KO", 12),
    "Corning": ("GLW", 12),
    "Costco": ("COST", 8),
    "Foot Locker": ("FL", 1),
    "General Mills": ("GIS", 5),
    "JPMorgan": ("JPM", 12),
    "Johnson & Johnson": ("JNJ", 12),
    "Kraft Heinz": ("KHC", 12),
    "Lockheed Martin": ("LMT", 12),
    "MGM Resorts": ("MGM", 12),
    "Microsoft": ("MSFT", 6),
    "Netflix": ("NFLX", 12),
    "Nike": ("NKE", 5),
    "Paypal": ("PYPL", 12),
    "PepsiCo": ("PEP", 12),
    "Pfizer": ("PFE", 12),
    "Ulta Beauty": ("ULTA", 1),
    "Verizon": ("VZ", 12),
    "Walmart": ("WMT", 1),
}
ALIASES: dict[str, list[str]] = {
    "MMM": ["3M Company", "Minnesota Mining"],
    "JNJ": ["J&J", "JNJ", "Johnson and Johnson"],
    "KO": ["Coca Cola", "Coke"],
    "PEP": ["Pepsi"],
    "JPM": ["JP Morgan", "J.P. Morgan", "JPMorgan Chase"],
    "AXP": ["Amex"],
    "SQ": ["Square", "Block Inc"],
    "MGM": ["MGM"],
    "BBY": ["BestBuy"],
    "ATVI": ["Activision"],
    "AMD": ["Advanced Micro Devices"],
    "AWK": ["American Water"],
    "CVS": ["CVS"],
    "LMT": ["Lockheed"],
    "KHC": ["Kraft", "Heinz"],
    "PYPL": ["PayPal"],
    "ULTA": ["Ulta"],
    "GIS": ["General Mills"],
    "FL": ["Foot Locker"],
    "WMT": ["Wal-Mart"],
}
_DOC_TYPES = {"10k": "10-K", "10q": "10-Q", "8k": "8-K", "earnings": "earnings_call"}


class Evidence(BaseModel):
    doc_id: str
    page: int  # 1-indexed
    text: str


class EvalQuestion(BaseModel):
    id: str
    question: str
    answer: str
    set: str = "financebench"
    tickers: list[str] = []
    doc_ids: list[str] = []
    evidence: list[Evidence] = []
    question_type: str = ""
    reasoning: str = ""
    answerable: bool = True


def _cache_dir() -> Path:
    d = get_settings().data_dir / "financebench"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fetch_jsonl(url: str, name: str) -> list[dict]:
    p = _cache_dir() / name
    if not p.exists():
        r = httpx.get(url, follow_redirects=True, timeout=60)
        r.raise_for_status()
        p.write_text(r.text)
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def load_questions() -> list[EvalQuestion]:
    out = []
    for r in _fetch_jsonl(QUESTIONS_URL, "financebench_open_source.jsonl"):
        ticker = COMPANIES.get(r["company"], (r["company"].upper(), 12))[0]
        ev = [
            Evidence(doc_id=e["doc_name"], page=int(e["evidence_page_num"]) + 1, text=e["evidence_text"]) for e in r["evidence"]
        ]
        out.append(
            EvalQuestion(
                id=r["financebench_id"],
                question=r["question"],
                answer=r["answer"],
                tickers=[ticker],
                doc_ids=sorted({r["doc_name"], *(e.doc_id for e in ev)}),
                evidence=ev,
                question_type=r.get("question_type") or "",
                reasoning=r.get("question_reasoning") or "",
            )
        )
    return out


def doc_metas(doc_names: set[str]) -> tuple[list[Company], list[DocMeta]]:
    info = {d["doc_name"]: d for d in _fetch_jsonl(DOCINFO_URL, "financebench_document_information.jsonl")}
    companies: dict[str, Company] = {}
    docs: list[DocMeta] = []
    for name in sorted(doc_names):
        d = info[name]
        ticker, fye = COMPANIES.get(d["company"], (d["company"].upper().replace(" ", ""), 12))
        companies[ticker] = Company(
            ticker=ticker, name=d["company"], country="US", fiscal_year_end_month=fye, aliases=ALIASES.get(ticker, [])
        )
        m = re.search(r"_(\d{4})(Q[1-4])?_", name + "_")
        period = m.group(2) if m and m.group(2) else "FY"
        docs.append(
            DocMeta(
                doc_id=name,
                ticker=ticker,
                company=d["company"],
                doc_type=_DOC_TYPES.get(d["doc_type"].lower(), "other"),
                fiscal_year=int(d["doc_period"]),
                period=period,
                fiscal_year_end_month=fye,
                url=f"{RAW}/pdfs/{name}.pdf",
                local_path=f"data/filings/financebench/{name}.pdf",
                track="financebench",
            )
        )
    return list(companies.values()), docs


def download(docs: list[DocMeta]) -> None:
    from ingest.manifest import local_path

    with httpx.Client(follow_redirects=True, timeout=120) as client:
        for n, meta in enumerate(docs, 1):
            path = local_path(meta)
            if path.exists() and path.stat().st_size > 0:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            r = client.get(meta.url)
            r.raise_for_status()
            path.write_bytes(r.content)
            log.info("[%d/%d] downloaded %s (%.1f MB)", n, len(docs), meta.doc_id, len(r.content) / 1e6)


def main() -> None:
    from ingest.manifest import upsert

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--docs", nargs="*", help="only these doc_names (default: all docs the questions use)")
    ap.add_argument("--no-download", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    qs = load_questions()
    names = {d for q in qs for d in q.doc_ids}
    if args.docs:
        names &= set(args.docs)
    companies, docs = doc_metas(names)
    upsert(get_settings().data_dir / "manifest.financebench.yaml", companies, docs)
    log.info("%d questions, %d documents, %d companies written to manifest.financebench.yaml", len(qs), len(docs), len(companies))
    if not args.no_download:
        download(docs)


if __name__ == "__main__":
    main()

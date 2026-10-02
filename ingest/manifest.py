"""Load and update the document manifest.

All `data/manifest*.yaml` files are merged: `manifest.yaml` is hand-curated (India demo, extra US
filings), while `manifest.edgar.yaml` and `manifest.financebench.yaml` are written by the fetch
scripts. Each file has `companies:` and `documents:` lists.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from app.config import get_settings
from app.schemas import Company, DocMeta


def _files(data_dir: Path) -> list[Path]:
    return sorted(data_dir.glob("manifest*.yaml"))


def load_companies(data_dir: Path | None = None) -> dict[str, Company]:
    data_dir = data_dir or get_settings().data_dir
    out: dict[str, Company] = {}
    for f in _files(data_dir):
        raw = yaml.safe_load(f.read_text()) or {}
        for c in raw.get("companies") or []:
            out[c["ticker"]] = Company(**c)
    return out


def load_documents(data_dir: Path | None = None) -> dict[str, DocMeta]:
    data_dir = data_dir or get_settings().data_dir
    companies = load_companies(data_dir)
    out: dict[str, DocMeta] = {}
    for f in _files(data_dir):
        raw = yaml.safe_load(f.read_text()) or {}
        for d in raw.get("documents") or []:
            co = companies.get(d["ticker"])
            d = {
                "company": co.name if co else d["ticker"],
                "fiscal_year_end_month": co.fiscal_year_end_month if co else 12,
                **d,
            }
            meta = DocMeta(**d)
            out[meta.doc_id] = meta
    return out


def local_path(meta: DocMeta) -> Path:
    s = get_settings()
    if meta.local_path:
        p = Path(meta.local_path)
        return p if p.is_absolute() else s.data_dir.parent / p
    return s.filings_dir / meta.ticker / f"{meta.doc_id}.pdf"


def upsert(path: Path, companies: list[Company], documents: list[DocMeta]) -> None:
    """Merge companies/documents into one manifest file, keyed by ticker / doc_id."""
    raw = yaml.safe_load(path.read_text()) if path.exists() else {}
    raw = raw or {}
    cos = {c["ticker"]: c for c in raw.get("companies") or []}
    docs = {d["doc_id"]: d for d in raw.get("documents") or []}
    for c in companies:
        cos[c.ticker] = c.model_dump()
    for d in documents:
        docs[d.doc_id] = d.model_dump(exclude={"company", "fiscal_year_end_month"}, exclude_none=True)
    path.write_text(
        yaml.safe_dump(
            {"companies": list(cos.values()), "documents": sorted(docs.values(), key=lambda x: x["doc_id"])},
            sort_keys=False,
            allow_unicode=True,
        )
    )

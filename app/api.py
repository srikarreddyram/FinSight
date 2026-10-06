"""FastAPI service.

    uv run uvicorn app.api:app --reload

POST /ask                              question -> cited answer
GET  /documents                        manifest + index status
GET  /documents/{doc_id}/pdf           the source PDF (open at #page=N)
GET  /documents/{doc_id}/page/{n}.png  rendered page, cited passage highlighted (?snippet=...)
POST /ingest                           upload a filing PDF and index it
GET  /recs/...                         the research dashboard's data (see recs/api.py)
GET  /moves/...                        what is moving a stock: market, sector, company, news (see news/api.py)
"""

from __future__ import annotations

import logging
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.config import get_settings
from app.pipeline import RUNS, get_pipeline
from app.schemas import Answer, Company, DocMeta
from news.api import router as moves_router
from recs.api import router as recs_router

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Load the embedding, BM25 and reranker models before the first question, not during it.
    try:
        pipe = get_pipeline()
        pipe.reranker.rerank("warm up", pipe.retriever.search("revenue", k=2), 1)
    except Exception as e:  # noqa: BLE001 - an empty index shouldn't stop the API from starting
        log.warning("warm-up skipped: %s", e)
    yield


app = FastAPI(title="FinSight", version="0.1.0", description="Citation-first RAG over company filings", lifespan=lifespan)
app.include_router(recs_router)
app.include_router(moves_router)
_ingest_lock = threading.Lock()


class AskRequest(BaseModel):
    question: str
    run: Literal["A", "B", "C", "D", "E"] = "E"


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=Answer)
def ask(req: AskRequest) -> Answer:
    q = req.question.strip()
    if not q:
        raise HTTPException(400, "empty question")
    from app.llm import QuotaExhausted

    pipe = get_pipeline()
    if req.run != "E":
        pipe = pipe.with_config(RUNS[req.run])
    try:
        return pipe.ask(q)
    except QuotaExhausted as e:
        raise HTTPException(429, str(e)) from e


@app.get("/documents")
def documents() -> list[dict]:
    from ingest.index import indexed_docs
    from ingest.manifest import load_documents, local_path

    indexed = indexed_docs()
    return [
        {
            **m.model_dump(),
            "fiscal_label": m.fiscal_label,
            "period_end": m.period_end.isoformat(),
            "indexed": doc_id in indexed,
            "downloaded": local_path(m).exists(),
        }
        for doc_id, m in sorted(load_documents().items())
    ]


def _pdf(doc_id: str) -> Path:
    from ingest.manifest import load_documents, local_path

    meta = load_documents().get(doc_id)
    if meta is None:
        raise HTTPException(404, f"unknown document {doc_id}")
    path = local_path(meta)
    if not path.exists():
        raise HTTPException(404, f"{doc_id} is not downloaded")
    return path


@app.get("/documents/{doc_id}/pdf")
def document_pdf(doc_id: str) -> FileResponse:
    return FileResponse(_pdf(doc_id), media_type="application/pdf", filename=f"{doc_id}.pdf")


@app.get("/documents/{doc_id}/page/{page}.png")
def document_page(doc_id: str, page: int, snippet: str = "", rows: bool = False) -> Response:
    """snippet: newline-separated passages to highlight; rows=true extends matches across table rows."""
    from app.viewer import render_page

    return Response(render_page(_pdf(doc_id), page, snippet, full_rows=rows), media_type="image/png")


@app.post("/ingest")
def ingest(
    file: UploadFile = File(...),
    ticker: str = Form(...),
    company: str = Form(...),
    doc_type: str = Form("annual_report"),
    fiscal_year: int = Form(...),
    period: str = Form("FY"),
    fiscal_year_end_month: int = Form(12),
    parser: Literal["pdfplumber", "docling"] = Form("pdfplumber"),
) -> dict:
    """Upload a filing and make it queryable. The pdfplumber parser indexes in well under a minute;
    choose docling for better tables at the cost of a few minutes."""
    from app.pipeline import available_years
    from ingest.index import ingest_doc
    from ingest.manifest import load_companies, upsert

    s = get_settings()
    ticker = re.sub(r"[^A-Z0-9.]", "", ticker.upper())
    if not ticker or not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(400, "need a ticker and a .pdf file")
    doc_id = f"{ticker}_FY{fiscal_year}_{doc_type.replace('-', '').upper()}" + ("" if period == "FY" else f"_{period}")
    dest = s.filings_dir / "uploads" / f"{doc_id}.pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(file.file.read())
    meta = DocMeta(
        doc_id=doc_id,
        ticker=ticker,
        company=company,
        doc_type=doc_type,
        fiscal_year=fiscal_year,
        period=period,
        fiscal_year_end_month=fiscal_year_end_month,
        local_path=str(dest.relative_to(s.data_dir.parent)),
        track="uploads",
    )
    co = load_companies().get(ticker) or Company(ticker=ticker, name=company, fiscal_year_end_month=fiscal_year_end_month)
    with _ingest_lock:
        upsert(s.data_dir / "manifest.uploads.yaml", [co], [meta])
        report = ingest_doc(meta, dest, parser=parser, force=True)
        pipe = get_pipeline()
        pipe.companies = load_companies()
        pipe.parser.__init__(pipe.companies, available_years(), llm=pipe.parser.llm)
    return report

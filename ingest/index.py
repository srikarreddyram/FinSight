"""Parse -> chunk -> embed -> upsert into Qdrant.

Documents are re-indexed only when their chunks change (tracked by a content hash per doc in
data/index_state.json), so re-running after editing the manifest is cheap.

    uv run python -m ingest.index --all                 # structured pipeline (runs B-E)
    uv run python -m ingest.index --all --naive         # PyPDF + fixed 1,000-token chunks (run A)
    uv run python -m ingest.index --doc 3M_2018_10K --no-llm-summaries
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from pathlib import Path

from qdrant_client import models

from app.config import get_settings
from app.schemas import Chunk, DocMeta
from app.store import DENSE, SPARSE, Embedders, ensure_collection, get_client, get_embedders, naive_collection, point_id
from ingest.chunk import TableSummarizer, chunk_naive, chunk_structured
from ingest.parse import parse

log = logging.getLogger(__name__)


def _state_path() -> Path:
    return get_settings().data_dir / "index_state.json"


def _load_state() -> dict[str, dict[str, str]]:
    p = _state_path()
    return json.loads(p.read_text()) if p.exists() else {}


def _save_state(state: dict) -> None:
    _state_path().write_text(json.dumps(state, indent=1, sort_keys=True))


def _hash(chunks: list[Chunk]) -> str:
    h = hashlib.sha1()
    for c in chunks:
        h.update(c.model_dump_json().encode())
    return h.hexdigest()


def upsert_chunks(collection: str, chunks: list[Chunk], emb: Embedders, batch: int = 64) -> None:
    client = get_client()
    ensure_collection(client, collection, emb.dim)
    for i in range(0, len(chunks), batch):
        part = chunks[i : i + batch]
        dense = emb.embed_docs([c.embed_text for c in part])
        sparse = emb.sparse_docs([c.sparse_text for c in part])
        client.upsert(
            collection,
            points=[
                models.PointStruct(id=point_id(c.chunk_id), vector={DENSE: d, SPARSE: sp}, payload=c.model_dump())
                for c, d, sp in zip(part, dense, sparse, strict=True)
            ],
        )


def delete_doc(collection: str, doc_id: str) -> None:
    client = get_client()
    if client.collection_exists(collection):
        client.delete(
            collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])
            ),
        )


def ingest_doc(
    meta: DocMeta,
    path: Path,
    *,
    naive: bool = False,
    use_llm: bool = True,
    force: bool = False,
    summarizer: TableSummarizer | None = None,
    parser: str = "docling",
) -> dict:
    """Parse, chunk and index one filing. Returns a small report."""
    s = get_settings()
    t0 = time.time()
    if naive:
        parsed = parse(meta, path, parser="pypdf", force=force)
        chunks = chunk_naive(parsed)
        collection = naive_collection(s)
    else:
        parsed = parse(meta, path, parser=parser, force=force)
        summarizer = summarizer or TableSummarizer(s, use_llm=use_llm)
        chunks = chunk_structured(parsed, s, summarizer)
        collection = s.collection
    t_parse = time.time() - t0

    state = _load_state()
    digest = _hash(chunks)
    if state.get(collection, {}).get(meta.doc_id) == digest and not force:
        return {"doc_id": meta.doc_id, "status": "unchanged", "chunks": len(chunks)}
    delete_doc(collection, meta.doc_id)
    upsert_chunks(collection, chunks, get_embedders())
    state = _load_state()  # re-read: another doc may have been written meanwhile
    state.setdefault(collection, {})[meta.doc_id] = digest
    _save_state(state)
    return {
        "doc_id": meta.doc_id,
        "status": "indexed",
        "parser": parsed.parser,
        "pages": parsed.page_count,
        "chunks": len(chunks),
        "tables": sum(c.chunk_type == "table" for c in chunks),
        "parse_s": round(t_parse, 1),
        "total_s": round(time.time() - t0, 1),
    }


def indexed_docs(collection: str | None = None) -> dict[str, str]:
    return _load_state().get(collection or get_settings().collection, {})


def main() -> None:
    from ingest.manifest import load_documents, local_path

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--doc", nargs="*", default=[])
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--track", help="only documents from this manifest track (financebench, edgar, india)")
    ap.add_argument("--naive", action="store_true", help="build the naive baseline collection for ablation run A")
    ap.add_argument("--no-llm-summaries", action="store_true", help="heuristic table summaries (no API calls)")
    ap.add_argument("--force", action="store_true", help="re-parse and re-index even if unchanged")
    ap.add_argument("--reverse", action="store_true", help="process documents in reverse order")
    ap.add_argument(
        "--summaries-only",
        action="store_true",
        help="only fill the table-summary cache (no Qdrant, so it can run alongside the indexer and double throughput)",
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    docs = load_documents()
    ids = [d for d, m in docs.items() if not args.track or m.track == args.track] if args.all else args.doc
    if args.reverse:
        ids = ids[::-1]
    summarizer = TableSummarizer(get_settings(), use_llm=not args.no_llm_summaries)
    for n, doc_id in enumerate(ids, 1):
        meta = docs[doc_id]
        path = local_path(meta)
        if not path.exists():
            log.warning("[%d/%d] %s: missing file %s", n, len(ids), doc_id, path)
            continue
        if args.summaries_only:
            # Tables already in the cache are skipped inside summarize(), so indexed filings cost nothing here.
            t0 = time.time()
            parsed = parse(meta, path)
            tables = [e for e in parsed.elements if e.kind == "table"]
            summarizer.summarize(meta.company, meta.fiscal_label, tables)
            log.info("[%d/%d] %s: summarised %d tables in %.0fs", n, len(ids), doc_id, len(tables), time.time() - t0)
            continue
        try:
            report = ingest_doc(meta, path, naive=args.naive, force=args.force, summarizer=summarizer)
            log.info("[%d/%d] %s", n, len(ids), report)
        except Exception:
            log.exception("[%d/%d] %s failed", n, len(ids), doc_id)


if __name__ == "__main__":
    main()

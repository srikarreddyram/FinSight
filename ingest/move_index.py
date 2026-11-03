"""Copy the embedded Qdrant store's collections to the Qdrant server, vectors and all, so nothing is re-embedded.

The FinanceBench filings are indexed in the embedded store (data/qdrant) by default; the 10-K sections of every
company need the server (ingest/sections.py), and one client serves both.

    docker compose up -d qdrant
    uv run python -m ingest.move_index        # finsight and finsight_naive -> http://localhost:6333
"""

from __future__ import annotations

import argparse
import logging

from qdrant_client import QdrantClient, models

from app.config import get_settings
from app.store import DENSE, ensure_collection, naive_collection

log = logging.getLogger(__name__)


def copy(src: QdrantClient, dst: QdrantClient, name: str, batch: int = 256) -> int:
    """Replace collection `name` on dst with src's copy. Returns the number of points copied."""
    dim = src.get_collection(name).config.params.vectors[DENSE].size
    if dst.collection_exists(name):
        dst.delete_collection(name)
    ensure_collection(dst, name, dim)
    n, offset = 0, None
    while True:
        points, offset = src.scroll(name, limit=batch, offset=offset, with_payload=True, with_vectors=True)
        if points:
            dst.upsert(name, points=[models.PointStruct(id=p.id, vector=p.vector, payload=p.payload) for p in points])
            n += len(points)
        if offset is None:
            return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:6333")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    s = get_settings()
    src, dst = QdrantClient(path=str(s.qdrant_path)), QdrantClient(url=args.url, timeout=120)
    for name in (s.collection, naive_collection(s)):
        if src.collection_exists(name):
            log.info("%s: copied %d points to %s", name, copy(src, dst, name), args.url)
    src.close()


if __name__ == "__main__":
    main()

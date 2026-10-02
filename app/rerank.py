"""Cross-encoder reranking (BAAI/bge-reranker-base) of the fused candidates."""

from __future__ import annotations

import math

from app.schemas import Hit
from app.store import Embedders, get_embedders


def _md_rows(md: str) -> list[list[str]]:
    rows = []
    for line in md.splitlines():
        if line.startswith("|") and not set(line) <= set("|-: "):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    return rows


def linearize_table(md: str, max_rows: int = 45) -> str:
    """'Purchases of PP&E: 2018 (1,577); 2017 (1,373)' per row. Cross-encoders are trained on prose and
    score linearized rows noticeably better than Markdown grids (3M capex table: rank 18 -> 11)."""
    rows = _md_rows(md)
    if not rows:
        return md
    head, out = rows[0], []
    for row in rows[1:max_rows]:
        vals = [f"{head[i]} {v}".strip() if i < len(head) and head[i] else v for i, v in enumerate(row[1:], 1) if v]
        if row[0] and vals:
            out.append(f"{row[0]}: " + "; ".join(vals))
        elif row[0]:
            out.append(f"{row[0]}:")
    return "\n".join(out)


def rerank_text(hit: Hit) -> str:
    """What the cross-encoder reads (it truncates at 512 tokens). Tables go in as linearized rows after
    the contextual header and the one-line summary."""
    c = hit.chunk
    if c.chunk_type != "table":
        return c.text
    header = c.embed_text.partition("\n")[0]
    return f"{header}\n{c.summary}\n{linearize_table(c.text)}"


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def order(hits: list[Hit], top_k: int, blend: float = 1.0, table_slots: int = 0) -> list[Hit]:
    """Final ordering of scored hits: optional blend with the fusion score, optional reserved table slots."""
    top_rrf = max((h.rrf_score for h in hits), default=0.0) or 1.0

    def final(h: Hit) -> float:
        return blend * (h.rerank_score or 0.0) + (1 - blend) * (h.rrf_score / top_rrf)

    ranked = sorted(hits, key=final, reverse=True)
    out = ranked[:top_k]
    if table_slots:
        have = sum(h.chunk.chunk_type == "table" for h in out)
        spare = [h for h in ranked[top_k:] if h.chunk.chunk_type == "table"][: max(0, table_slots - have)]
        if spare:
            keep = out[: top_k - len(spare)]
            dropped = [h for h in out[top_k - len(spare) :] if h.chunk.chunk_type == "table"]
            out = sorted(keep + dropped + spare, key=final, reverse=True)[:top_k]
    return out


class Reranker:
    def __init__(self, embedders: Embedders | None = None, blend: float = 1.0, table_slots: int = 0):
        self.emb = embedders or get_embedders()
        self.blend = blend
        self.table_slots = table_slots

    def score(self, query: str, hits: list[Hit]) -> list[Hit]:
        if hits:
            logits = self.emb.reranker.rerank(query, [rerank_text(h) for h in hits], batch_size=16)
            for h, logit in zip(hits, logits, strict=True):
                h.rerank_score = sigmoid(float(logit))
        return hits

    def rerank(self, query: str, hits: list[Hit], top_k: int) -> list[Hit]:
        return order(self.score(query, hits), top_k, self.blend, self.table_slots)

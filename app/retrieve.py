"""Hybrid retrieval: BM25 (Qdrant sparse vectors) + dense search, merged with reciprocal rank fusion."""

from __future__ import annotations

from qdrant_client import models

from app.config import Settings, get_settings
from app.schemas import Chunk, Hit, ParsedQuery
from app.store import DENSE, SPARSE, Embedders, get_client, get_embedders


def rrf(rankings: list[list[str]], k: int = 60) -> dict[str, float]:
    """Reciprocal rank fusion: score(d) = sum over rankings of 1 / (k + rank)."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return scores


def build_filter(pq: ParsedQuery | None, ticker: str | None = None) -> models.Filter | None:
    """Company + fiscal-year payload filter. With several companies, any (company AND its years) matches."""
    if pq is None:
        return None
    tickers = [ticker] if ticker else pq.tickers
    if not tickers:
        years = sorted({y for ys in pq.fiscal_years.values() for y in ys})
        return models.Filter(must=[models.FieldCondition(key="fiscal_year", match=models.MatchAny(any=years))]) if years else None
    clauses = []
    for t in tickers:
        must = [models.FieldCondition(key="ticker", match=models.MatchValue(value=t))]
        years = pq.fiscal_years.get(t)
        if years:
            must.append(models.FieldCondition(key="fiscal_year", match=models.MatchAny(any=years)))
        clauses.append(models.Filter(must=must))
    return clauses[0] if len(clauses) == 1 else models.Filter(should=clauses)


class Retriever:
    def __init__(self, settings: Settings | None = None, embedders: Embedders | None = None):
        self.s = settings or get_settings()
        self.emb = embedders or get_embedders()

    def search(
        self,
        query: str,
        *,
        collection: str | None = None,
        qfilter: models.Filter | None = None,
        k: int | None = None,
        hybrid: bool = True,
        boost_sections: list[str] | None = None,
        boost_doc_types: list[str] | None = None,
    ) -> list[Hit]:
        collection = collection or self.s.collection
        k = k or self.s.retrieve_k
        client = get_client()
        dense = client.query_points(
            collection, query=self.emb.embed_query(query), using=DENSE, query_filter=qfilter, limit=k, with_payload=True
        ).points
        payloads = {str(p.id): p.payload for p in dense}
        rankings = [[str(p.id) for p in dense]]
        if hybrid:
            sparse = client.query_points(
                collection, query=self.emb.sparse_query(query), using=SPARSE, query_filter=qfilter, limit=k, with_payload=True
            ).points
            payloads.update({str(p.id): p.payload for p in sparse})
            rankings.append([str(p.id) for p in sparse])

        scores = rrf(rankings, self.s.rrf_k)
        # Section / document-type hints from the question are soft boosts, not filters: section
        # tagging is heuristic and a hard filter would silently drop the right page.
        bonus = 0.5 / (self.s.rrf_k + 1)
        for pid, payload in payloads.items():
            if boost_sections and payload.get("section") in boost_sections:
                scores[pid] += bonus
            if boost_doc_types and payload.get("doc_type") in boost_doc_types:
                scores[pid] += bonus

        dense_rank = {pid: r for r, pid in enumerate(rankings[0], 1)}
        sparse_rank = {pid: r for r, pid in enumerate(rankings[1], 1)} if hybrid else {}
        ordered = sorted(scores, key=scores.get, reverse=True)[:k]
        return [
            Hit(
                chunk=Chunk(**payloads[pid]),
                rrf_score=scores[pid],
                dense_rank=dense_rank.get(pid),
                sparse_rank=sparse_rank.get(pid),
            )
            for pid in ordered
        ]

"""Query path: parse -> filter -> hybrid search -> rerank -> evidence gate -> answer.

The ablation runs A-E from the PRD are just PipelineConfig presets, so the benchmark exercises
exactly the code the API serves.
"""

from __future__ import annotations

import calendar
import logging
import math
import threading
import time
from dataclasses import dataclass

from app.answer import SCHEMA, SYSTEM, build_prompt, finalize, refusal, to_citation
from app.concepts import expand
from app.config import Settings, get_settings
from app.llm import LLM, LLMError, QuotaExhausted, get_llm
from app.query_parser import QueryParser
from app.rerank import Reranker
from app.retrieve import Retriever, build_filter
from app.schemas import Answer, Company, Hit, ParsedQuery
from app.store import naive_collection

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineConfig:
    name: str = "E"
    naive_index: bool = False  # PyPDF + fixed 1,000-token chunks
    hybrid: bool = True  # BM25 + dense with RRF (else dense only)
    rerank: bool = True  # cross-encoder over the top 30
    filters: bool = True  # metadata filters + comparison fan-out from the query parser
    evidence_gate: bool = True  # refuse when the best reranked passage is weak (needs rerank)
    llm_query_parser: bool = True
    expand_concepts: bool = True  # add the line items behind metrics like "quick ratio" to the search query


RUNS: dict[str, PipelineConfig] = {
    "A": PipelineConfig(
        "A", naive_index=True, hybrid=False, rerank=False, filters=False, evidence_gate=False, expand_concepts=False
    ),
    "B": PipelineConfig("B", hybrid=False, rerank=False, filters=False, evidence_gate=False, expand_concepts=False),
    "C": PipelineConfig("C", hybrid=True, rerank=False, filters=False, evidence_gate=False, expand_concepts=False),
    "D": PipelineConfig("D", hybrid=True, rerank=True, filters=False, expand_concepts=False),
    "E": PipelineConfig("E"),
}


def available_years() -> dict[str, list[int]]:
    """Fiscal years per ticker among documents that are actually indexed."""
    from ingest.index import indexed_docs
    from ingest.manifest import load_documents

    indexed = indexed_docs()
    out: dict[str, set[int]] = {}
    for doc_id, m in load_documents().items():
        if doc_id in indexed:
            out.setdefault(m.ticker, set()).add(m.fiscal_year)
    return {t: sorted(ys) for t, ys in out.items()}


class Pipeline:
    def __init__(self, config: PipelineConfig | None = None, settings: Settings | None = None, llm: LLM | None = None):
        from ingest.manifest import load_companies

        self.cfg = config or RUNS["E"]
        self.s = settings or get_settings()
        self.llm = llm or get_llm()
        self.retriever = Retriever(self.s)
        self.reranker = Reranker(blend=self.s.rerank_blend, table_slots=self.s.table_slots)
        self.companies: dict[str, Company] = load_companies()
        self.parser = QueryParser(self.companies, available_years(), llm=self.llm if self.cfg.llm_query_parser else None)
        self.collection = naive_collection(self.s) if self.cfg.naive_index else self.s.collection
        # The embedded Qdrant store isn't safe for concurrent use; LLM calls stay outside this lock.
        self._retrieve_lock = threading.Lock()

    def with_config(self, cfg: PipelineConfig) -> Pipeline:
        """Same models and clients, different ablation settings."""
        p = object.__new__(Pipeline)
        p.__dict__.update(self.__dict__)
        p.cfg = cfg
        p.collection = naive_collection(self.s) if cfg.naive_index else self.s.collection
        if not cfg.llm_query_parser:
            p.parser = replace_llm(self.parser, None)
        return p

    # ---------------------------------------------------------------- retrieval

    def _search(self, query: str, pq: ParsedQuery | None, ticker: str | None = None) -> list[Hit]:
        kw = dict(collection=self.collection, hybrid=self.cfg.hybrid)
        sections = list(pq.sections) if pq is not None else []
        if self.cfg.expand_concepts:
            query, from_statements = expand(query)
            if from_statements and "Financial Statements" not in sections:
                sections.append("Financial Statements")
        if pq is not None or sections:
            kw.update(boost_sections=sections or None, boost_doc_types=(pq.doc_types if pq else None) or None)
        hits = self.retriever.search(query, qfilter=build_filter(pq, ticker), **kw)
        if not hits and pq is not None:
            # The year filter can over-constrain (e.g. no filing for that year); fall back to company only.
            relaxed = pq.model_copy(update={"fiscal_years": {}})
            hits = self.retriever.search(query, qfilter=build_filter(relaxed, ticker), **kw)
        return hits

    def _rank(self, query: str, hits: list[Hit], k: int) -> list[Hit]:
        if self.cfg.rerank:
            return self.reranker.rerank(query, hits, k)
        return hits[:k]

    def retrieve(self, question: str) -> tuple[ParsedQuery | None, list[Hit], list[Hit]]:
        """Returns (parsed query, sources for the LLM, top-10 ranked list for recall@10)."""
        pq = self.parser.parse(question) if self.cfg.filters else None
        with self._retrieve_lock:
            return self._retrieve(question, pq)

    def _retrieve(self, question: str, pq: ParsedQuery | None) -> tuple[ParsedQuery | None, list[Hit], list[Hit]]:
        k = self.s.rerank_k
        if pq is not None and pq.is_comparison and pq.sub_queries:
            per = max(3, math.ceil(k * 1.5 / len(pq.sub_queries)))
            groups = []
            for ticker, sub in pq.sub_queries.items():
                groups.append(self._rank(sub, self._search(sub, pq, ticker), per))
            # interleave so every company is represented in the top of the list
            ranked = [h for tier in zip(*groups, strict=False) for h in tier]
            ranked += [h for g in groups for h in g if h not in ranked]
            return pq, ranked[: max(k, per * len(groups))], ranked[:10]
        ranked = self._rank(question, self._search(question, pq), max(k, 10))
        return pq, ranked[:k], ranked[:10]

    # ---------------------------------------------------------------- answering

    def fy_notes(self, hits: list[Hit]) -> list[str]:
        notes, seen = [], set()
        for h in hits:
            c = h.chunk
            co = self.companies.get(c.ticker)
            if not co or co.fiscal_year_end_month == 12 or c.ticker in seen:
                continue
            seen.add(c.ticker)
            month = calendar.month_name[co.fiscal_year_end_month]
            start = calendar.month_abbr[co.fiscal_year_end_month % 12 + 1]
            notes.append(
                f"{co.name}: fiscal years end in {month}; FY{c.fiscal_year % 100:02d} runs {start} {c.fiscal_year - 1} to "
                f"{calendar.month_abbr[co.fiscal_year_end_month]} {c.fiscal_year}."
            )
        return notes

    def ask(self, question: str) -> Answer:
        t0 = time.perf_counter()
        with self.llm.track() as usage:
            pq, sources, top10 = self.retrieve(question)
            t_retrieve = time.perf_counter() - t0
            ans = self.answer_from(question, pq, sources, top10)
        ans.timings = {"retrieve_s": round(t_retrieve, 3), "total_s": round(time.perf_counter() - t0, 3)}
        ans.usage = dict(usage)
        return ans

    def answer_from(self, question: str, pq: ParsedQuery | None, sources: list[Hit], top10: list[Hit]) -> Answer:
        """Evidence gate, then one structured LLM call, then Python verification (see app/answer.py)."""
        best = max((h.rerank_score or 0.0 for h in sources), default=0.0)
        if not sources or (self.cfg.rerank and self.cfg.evidence_gate and best < self.s.evidence_threshold):
            ans = refusal(question, sources, pq, note="No passage in the indexed filings is relevant enough to answer.")
        else:
            try:
                raw = self.llm.json(
                    system=SYSTEM,
                    user=build_prompt(question, sources, self.fy_notes(sources)),
                    schema=SCHEMA,
                    role="answer",
                    effort="medium",
                    max_tokens=8000,
                )
                ans = finalize(question, raw, sources, pq)
            except QuotaExhausted:
                raise  # not a real "not found": callers must see that the daily quota is spent
            except LLMError as e:
                log.error("answer generation failed: %s", e)
                ans = refusal(question, sources, pq, note="The answer model is unavailable right now.")
                ans.error = str(e)
        ans.retrieved = [to_citation(i, h) for i, h in enumerate(top10)]
        return ans


def replace_llm(parser: QueryParser, llm) -> QueryParser:
    p = object.__new__(QueryParser)
    p.__dict__.update(parser.__dict__)
    p.llm = llm
    return p


_pipeline: Pipeline | None = None


def get_pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = Pipeline()
    return _pipeline

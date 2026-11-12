"""Query path: parse -> filter -> hybrid search -> rerank -> evidence gate -> answer, then one retry
that looks further if the model can't answer.

The ablation runs A-G are just PipelineConfig presets, so the benchmark exercises exactly the code
the API serves. The one difference is the corpus: the benchmarks answer from the parsed filings alone
(Settings.sections off), the API also from every other company's latest 10-K.
"""

from __future__ import annotations

import calendar
import logging
import math
import threading
import time
from dataclasses import dataclass

from app.answer import SCHEMA, SYSTEM, build_prompt, finalize, refusal, retry_feedback, to_citation, which_company
from app.concepts import expand
from app.config import Settings, get_settings
from app.llm import LLM, LLMError, QuotaExhausted, get_llm
from app.query_parser import QueryParser
from app.rerank import Reranker, order
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
    rerank_k: int | None = None  # passages the LLM reads (None: the rerank_k setting)
    retry: bool = False  # when the model can't answer: look for what's missing and try once more
    facts: bool = False  # add the company's standard financials from XBRL as a source (app/facts.py)


RUNS: dict[str, PipelineConfig] = {
    "A": PipelineConfig(
        "A", naive_index=True, hybrid=False, rerank=False, filters=False, evidence_gate=False, expand_concepts=False
    ),
    "B": PipelineConfig("B", hybrid=False, rerank=False, filters=False, evidence_gate=False, expand_concepts=False),
    "C": PipelineConfig("C", hybrid=True, rerank=False, filters=False, evidence_gate=False, expand_concepts=False),
    "D": PipelineConfig("D", hybrid=True, rerank=True, filters=False, expand_concepts=False),
    "E": PipelineConfig("E", rerank_k=8),
    "F": PipelineConfig("F", retry=True),
    "G": PipelineConfig("G", retry=True, facts=True),
}


def tenk_docs() -> dict[tuple[str, int], str]:
    """(ticker, fiscal year) -> doc_id of each indexed 10-K."""
    from ingest.index import indexed_docs
    from ingest.manifest import load_documents

    indexed = indexed_docs()
    return {(m.ticker, m.fiscal_year): d for d, m in load_documents().items() if d in indexed and m.doc_type == "10-K"}


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

        self.cfg = config or RUNS["F"]
        self.s = settings or get_settings()
        self.llm = llm or get_llm()
        self.retriever = Retriever(self.s)
        self.reranker = Reranker(blend=self.s.rerank_blend, table_slots=self.s.table_slots)
        self.collection = naive_collection(self.s) if self.cfg.naive_index else self.s.collection
        # The embedded Qdrant store isn't safe for concurrent use; LLM calls stay outside this lock.
        self._retrieve_lock = threading.Lock()
        self.reload()

    def reload(self) -> None:
        """(Re)read what is indexed: the parsed filings (FinanceBench, EDGAR, uploads) and, on the Qdrant server,
        the latest 10-K sections of every other company (ingest/sections.py)."""
        from ingest import sections
        from ingest.manifest import load_companies

        filed = load_companies()
        years = available_years()
        self.tenk_docs = tenk_docs()
        self.pdf_tickers = set(years)
        vocab = sections.vocab()
        universe = sections.indexed() if self.s.qdrant_url and self.s.sections and vocab else {}
        # A company already filed under another ticker keeps that entry: Block's filings are under SQ, now XYZ.
        taken = {n.lower() for c in filed.values() for n in (c.name, *c.aliases)}
        self.sections = {t: f for t, f in universe.items() if t in filed or f["name"].lower() not in taken}
        others = {t: c for t, c in sections.companies().items() if t in self.sections and t not in filed}
        self.companies: dict[str, Company] = {**others, **filed}
        for t, f in self.sections.items():
            years[t] = sorted({*years.get(t, []), f["fiscal_year"]})
        # Each company's 10-Ks: where a question with no year looks, and what a facts source cites.
        self.annual_docs = {**{(t, f["fiscal_year"]): f["doc_id"] for t, f in self.sections.items()}, **self.tenk_docs}
        self.parser = QueryParser(
            self.companies, years, llm=self.llm if self.cfg.llm_query_parser else None, strict=set(others), vocab=vocab
        )

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

    def _collections(self, ticker: str | None) -> list[str]:
        """Parsed filings are in the main collection and every company's latest 10-K sections in their own. A
        company with both is searched in both, unless that 10-K is itself among the parsed filings: the year
        filter and the reranker choose between an old filing's pages and the latest one's text."""
        if self.cfg.naive_index or ticker not in self.sections:
            return [self.collection]
        if ticker not in self.pdf_tickers:
            return [self.s.sections_collection]
        if (ticker, self.sections[ticker]["fiscal_year"]) in self.tenk_docs:
            return [self.collection]
        return [self.collection, self.s.sections_collection]

    def _search(self, query: str, pq: ParsedQuery | None, ticker: str | None = None, k: int | None = None) -> list[Hit]:
        one = ticker or (pq.tickers[0] if pq is not None and len(pq.tickers) == 1 else None)
        collections = self._collections(one)
        kw = dict(hybrid=self.cfg.hybrid, k=k)
        sections = list(pq.sections) if pq is not None else []
        if self.cfg.expand_concepts:
            query, from_statements = expand(query)
            if from_statements and "Financial Statements" not in sections:
                sections.append("Financial Statements")
        if pq is not None or sections:
            kw.update(boost_sections=sections or None, boost_doc_types=(pq.doc_types if pq else None) or None)

        def search(parsed: ParsedQuery | None) -> list[Hit]:
            found = [
                h
                for c in collections
                for h in self.retriever.search(query, qfilter=build_filter(parsed, ticker), collection=c, **kw)
            ]
            return (
                sorted(found, key=lambda h: h.rrf_score, reverse=True)[: k or self.s.retrieve_k]
                if len(collections) > 1
                else found
            )

        hits = search(pq)
        if not hits and pq is not None:
            # The year filter can over-constrain (e.g. no filing for that year); fall back to company only.
            hits = search(pq.model_copy(update={"fiscal_years": {}}))
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

    def _facts(self, question: str, pq: ParsedQuery | None) -> list[Hit]:
        if not self.cfg.facts:
            return []
        from app.facts import sources

        return sources(pq, question, self.companies, self.annual_docs)

    def _retrieve(self, question: str, pq: ParsedQuery | None) -> tuple[ParsedQuery | None, list[Hit], list[Hit]]:
        if pq is not None and not pq.tickers:
            return pq, [], []  # no company named: answer_from asks which one
        k = self.cfg.rerank_k or self.s.rerank_k
        facts = self._facts(question, pq)
        if pq is not None and pq.is_comparison and pq.sub_queries:
            per = max(3, math.ceil(k * 1.5 / len(pq.sub_queries)))
            groups = []
            for ticker, sub in pq.sub_queries.items():
                groups.append(self._rank(sub, self._search(sub, pq, ticker), per))
            # interleave so every company is represented in the top of the list
            ranked = [h for tier in zip(*groups, strict=False) for h in tier]
            ranked += [h for g in groups for h in g if h not in ranked]
            return pq, ranked[: max(k, per * len(groups))] + facts, ranked[:10]
        ranked = self._rank(question, self._search(question, pq), max(k, 10))
        return pq, ranked[:k] + facts, ranked[:10]

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

    def _attempt(self, question: str, pq: ParsedQuery | None, sources: list[Hit], feedback: str = "") -> Answer:
        """Evidence gate, then one structured LLM call, then Python verification (see app/answer.py)."""
        best = max((h.rerank_score or 0.0 for h in sources), default=0.0)
        if not sources or (self.cfg.rerank and self.cfg.evidence_gate and best < self.s.evidence_threshold):
            return refusal(question, sources, pq, note="No passage in the indexed filings is relevant enough to answer.")
        try:
            raw = self.llm.json(
                system=SYSTEM,
                user=build_prompt(question, sources, self.fy_notes(sources), feedback),
                schema=SCHEMA,
                role="answer",
                effort="medium",
                max_tokens=8000,
            )
            return finalize(question, raw, sources, pq)
        except QuotaExhausted:
            raise  # not a real "not found": callers must see that the daily quota is spent
        except LLMError as e:
            log.error("answer generation failed: %s", e)
            ans = refusal(question, sources, pq, note="The answer model is unavailable right now.")
            ans.error = str(e)
            return ans

    def _look_further(self, question: str, pq: ParsedQuery | None, sources: list[Hit], missing: list[str]) -> list[Hit]:
        """Passages the first attempt didn't read: a search for each fact the model says it couldn't find, then a
        deeper search for the question itself, since the reranker normally sees only the top retrieve_k."""
        seen = {h.chunk.chunk_id for h in sources}
        more: list[Hit] = []

        def add(query: str, depth: int, top: int) -> None:
            hits = [h for h in self._search(query, pq, k=depth) if h.chunk.chunk_id not in seen]
            picked = order(self.reranker.score(query, hits), top, self.reranker.blend, table_slots=1)
            seen.update(h.chunk.chunk_id for h in picked)
            more.extend(picked)

        with self._retrieve_lock:
            for need in missing[:3]:
                add(need, self.s.retrieve_k, self.s.retry_need_k)
            add(question, self.s.retry_depth, self.s.retry_k)
        return more

    def answer_from(self, question: str, pq: ParsedQuery | None, sources: list[Hit], top10: list[Hit]) -> Answer:
        """Answer from the sources. If that fails and the pipeline retries, look further and try once more: the
        model refuses mostly when evidence is missing (6 of 103 FinanceBench questions with every gold page shown,
        24 of 47 without), and Python's rejections tell it what to fix. The second attempt passes the same checks."""
        if pq is not None and not pq.tickers:
            return which_company(question, pq)
        ans = self._attempt(question, pq, sources)
        read = sources
        if self.cfg.retry and ans.refused and not ans.error:
            more = self._look_further(question, pq, sources, ans.missing)
            if more or ans.stripped_sentences or any(not f.verified for f in ans.figures):
                first, read = ans, sources + more
                ans = self._attempt(question, pq, read, retry_feedback(first))
                ans.attempts = 2
                ans.missing = ans.missing or first.missing
        ans.retrieved = [to_citation(i, h) for i, h in enumerate(top10)]
        ans.shown = [to_citation(i, h) for i, h in enumerate(read)]
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

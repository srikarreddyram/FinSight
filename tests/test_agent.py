"""The pipeline's retry: when the model can't answer, look further and try once more."""

import threading

import pytest

from app.config import get_settings
from app.llm import LLMError, QuotaExhausted
from app.pipeline import RUNS, Pipeline
from app.schemas import Chunk, Hit

TABLE = "3M (MMM) 10-K FY18\n| (Millions) | 2018 |\n|---|---|\n| Purchases of PP&E | (1,577) |"
OTHER = "3M (MMM) 10-K FY18\nSpending went to new capacity."
BALANCE = "3M (MMM) 10-K FY18\n| (Millions) | 2018 |\n|---|---|\n| Total current liabilities | 7,244 |"


def _hit(name: str, text: str, page: int) -> Hit:
    c = Chunk(
        chunk_id=name,
        doc_id="3M_2018_10K",
        ticker="MMM",
        company="3M",
        doc_type="10-K",
        fiscal_year=2018,
        fiscal_label="FY18",
        period="FY",
        period_end="2018-12-31",
        section="Financial Statements",
        heading="",
        page=page,
        page_end=page,
        chunk_type="table",
        text=text,
        embed_text=text,
        sparse_text=text,
    )
    return Hit(chunk=c, rerank_score=0.9, rrf_score=0.01)


SOURCES = [_hit("cash", TABLE, 60), _hit("mdna", OTHER, 47)]


def _answer(text: str, *figures) -> dict:
    return {
        "answerable": True,
        "figures": list(figures),
        "calculations": [],
        "answer": text,
        "table": {"columns": [], "rows": []},
        "missing": [],
    }


def _fig(name: str, value: float, src: str) -> dict:
    return {
        "name": name,
        "value": value,
        "unit": "currency",
        "currency": "USD",
        "scale": "millions",
        "period": "FY2018",
        "source_id": src,
        "quote": name,
    }


def _refuse(*missing: str) -> dict:
    return {**_answer(""), "answerable": False, "missing": list(missing)}


class FakeLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts: list[str] = []

    def json(self, *, user: str, **_):
        self.prompts.append(user)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeRetriever:
    def __init__(self, hits: list[Hit]):
        self.hits = hits
        self.searches: list[tuple[str, int | None]] = []

    def search(self, query: str, *, k: int | None = None, **_) -> list[Hit]:
        self.searches.append((query, k))
        return [h.model_copy() for h in self.hits]


class FakeReranker:
    blend = 1.0

    def score(self, query: str, hits: list[Hit]) -> list[Hit]:
        return hits


def _pipeline(llm: FakeLLM, found: list[Hit] = (), run: str = "F") -> Pipeline:
    p = object.__new__(Pipeline)
    p.cfg, p.s, p.llm = RUNS[run], get_settings(), llm
    p.retriever, p.reranker = FakeRetriever(list(found)), FakeReranker()
    p.companies, p.parser, p.collection = {}, None, "c"
    p._retrieve_lock = threading.Lock()
    return p


def _ask(p: Pipeline, question: str = "What was the capex?"):
    return p.answer_from(question, None, list(SOURCES), list(SOURCES))


def test_an_answer_on_the_first_attempt_costs_nothing_extra():
    llm = FakeLLM(_answer("Capex was {fig:c} [S1].", _fig("c", 1577, "S1")))
    p = _pipeline(llm, [_hit("bs", BALANCE, 58)])
    ans = _ask(p)
    assert ans.attempts == 1 and not ans.refused
    assert len(llm.prompts) == 1 and not p.retriever.searches
    assert [c.page for c in ans.shown] == [60, 47]


def test_a_refusal_searches_for_what_is_missing_and_tries_again():
    llm = FakeLLM(_refuse("total current liabilities"), _answer("Liabilities were {fig:l} [S3].", _fig("l", 7244, "S3")))
    p = _pipeline(llm, [_hit("bs", BALANCE, 58)])
    ans = _ask(p, "What were current liabilities?")
    assert ans.attempts == 2 and not ans.refused
    assert ans.answer == "Liabilities were $7,244 million [3M FY18 p.58]."
    # one search for the missing fact, one deeper search for the question
    assert p.retriever.searches[0][0].startswith("total current liabilities")
    assert p.retriever.searches[0][1] == p.s.retrieve_k
    assert p.retriever.searches[1][0].startswith("What were current liabilities?")
    assert p.retriever.searches[1][1] == p.s.retry_depth
    # the second attempt reads everything, says what went wrong, and keeps the first attempt's source numbers
    assert "You could not find: total current liabilities" in llm.prompts[1]
    assert 'id="S1"' in llm.prompts[1] and 'id="S3"' in llm.prompts[1] and "Total current liabilities" in llm.prompts[1]
    assert [c.page for c in ans.shown] == [60, 47, 58]
    assert [c.page for c in ans.retrieved] == [60, 47]  # recall@10 still measures the first pass


def test_passages_already_read_are_not_added_twice():
    llm = FakeLLM(_refuse("capex"), _refuse())
    ans = _ask(_pipeline(llm, [*SOURCES, _hit("bs", BALANCE, 58)]))
    assert [c.page for c in ans.shown] == [60, 47, 58]


def test_a_second_refusal_stands_and_there_is_no_third_attempt():
    llm = FakeLLM(_refuse("capex by state"), _refuse())
    ans = _ask(_pipeline(llm, [_hit("bs", BALANCE, 58)]))
    assert ans.refused and ans.attempts == 2 and len(llm.prompts) == 2
    assert ans.missing == ["capex by state"]


def test_the_second_attempt_passes_the_same_checks():
    invented = _answer("Capex in Ohio was {fig:c} [S3].", _fig("c", 999, "S3"))
    ans = _ask(_pipeline(FakeLLM(_refuse("capex in Ohio"), invented), [_hit("bs", BALANCE, 58)]))
    assert ans.refused and ans.attempts == 2 and "999" not in ans.answer


def test_nothing_new_to_read_means_no_second_call():
    llm = FakeLLM(_refuse("capex"))
    ans = _ask(_pipeline(llm, SOURCES))
    assert ans.refused and ans.attempts == 1 and len(llm.prompts) == 1


def test_rejected_figures_get_a_second_try_even_with_nothing_new_to_read():
    wrong = _answer("Capex was {fig:c} [S1].", _fig("c", 1600, "S1"))
    right = _answer("Capex was {fig:c} [S1].", _fig("c", 1577, "S1"))
    llm = FakeLLM(wrong, right)
    ans = _ask(_pipeline(llm, SOURCES))
    assert not ans.refused and ans.attempts == 2
    assert "c = 1600 (S1)" in llm.prompts[1] and "not printed" in llm.prompts[1]


def test_a_model_failure_is_not_retried_and_a_spent_quota_surfaces():
    llm = FakeLLM(LLMError("503"))
    p = _pipeline(llm, [_hit("bs", BALANCE, 58)])
    ans = _ask(p)
    assert ans.error and ans.attempts == 1 and not p.retriever.searches
    with pytest.raises(QuotaExhausted):
        _ask(_pipeline(FakeLLM(QuotaExhausted("daily")), [_hit("bs", BALANCE, 58)]))


def test_run_e_does_not_retry():
    llm = FakeLLM(_refuse("capex"))
    ans = _ask(_pipeline(llm, [_hit("bs", BALANCE, 58)], run="E"))
    assert ans.refused and ans.attempts == 1 and len(llm.prompts) == 1
    assert RUNS["E"].rerank_k == 8 and RUNS["F"].rerank_k is None

"""Deterministic metrics: retrieval recall, numeric match, and failure tagging."""

from __future__ import annotations

import re
import statistics

from app.numbers import numbers_in
from app.schemas import Citation
from eval.financebench_loader import EvalQuestion, Evidence

_YEAR = re.compile(r"^(19|20)\d{2}$")
_SCALES = (1.0, 1e3, 1e6, 1e9, 1e-3, 1e-6, 1e-9)


def _on_page(c: Citation, e: Evidence) -> bool:
    return e.doc_id == c.doc_id and c.page <= e.page <= (c.page_end or c.page)


def hit_gold(c: Citation, q: EvalQuestion) -> bool:
    return any(_on_page(c, e) for e in q.evidence)


def recall_at_k(retrieved: list[Citation], q: EvalQuestion, k: int = 10) -> bool | None:
    """Does any gold evidence page appear in the top-k? None when the question has no gold pages."""
    if not q.evidence:
        return None
    return any(hit_gold(c, q) for c in retrieved[:k])


def evidence_complete(shown: list[Citation], q: EvalQuestion) -> bool | None:
    """Did the model read every gold evidence page? Recall counts one page as a hit, which flatters a ratio
    whose inputs sit on two different statements."""
    if not q.evidence:
        return None
    return all(any(_on_page(c, e) for c in shown) for e in q.evidence)


def gold_numbers(answer: str) -> list[float]:
    return [v for v in numbers_in(answer) if not _YEAR.match(f"{v:g}")]


def is_numeric_question(q: EvalQuestion) -> bool:
    """Short gold answers built around one or two numbers: the subset scored by numeric exact match."""
    nums = gold_numbers(q.answer)
    return 0 < len(nums) <= 2 and len(q.answer) <= 60


def numeric_match(answer: str, q: EvalQuestion, tol: float = 0.01) -> bool:
    """Every gold number is matched (within 1%) by some number in the answer, allowing unit rescaling
    (a gold "$1.58 billion" matches "$1,577 million")."""
    ours = numbers_in(answer)
    if not ours:
        return False
    for g in gold_numbers(q.answer):
        if g == 0:
            ok = 0.0 in ours
        else:
            ok = any(abs(o * s - g) <= tol * abs(g) for o in ours for s in _SCALES)
        if not ok:
            return False
    return True


def tag_failure(
    *,
    correct: bool | None,
    refused: bool,
    answerable: bool,
    recall10: bool | None,
    gold_page_parsed: bool | None,
    citations_ok: bool | None,
) -> str | None:
    """Assign one failure category (PRD: parsing / retrieval / reasoning / citation)."""
    if not answerable:
        return None if refused else "hallucinated (should refuse)"
    if correct is None:
        return "ungraded"  # the judge failed, so nothing is known about this answer
    if correct:
        return "citation" if citations_ok is False else None
    if recall10 is False:
        return "parsing" if gold_page_parsed is False else "retrieval"
    if refused:
        return "over-refusal" if recall10 else "retrieval"
    return "reasoning"


def median(xs: list[float]) -> float | None:
    return round(statistics.median(xs), 2) if xs else None


def rate(xs: list[bool | None]) -> float | None:
    vals = [x for x in xs if x is not None]
    return round(sum(vals) / len(vals), 3) if vals else None

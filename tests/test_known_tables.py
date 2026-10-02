"""Parsing guard: known financial-statement rows must come out of Docling intact, on the right page,
with values in the right columns. Table parsing bugs are silent and poison everything downstream.

Values are checked against the filings (FinanceBench gold evidence pages, 1-indexed).
Run after `python -m eval.financebench_loader` and `python -m ingest.parse --all`.
"""

import pytest

from app.numbers import appears_in
from eval.financebench_loader import load_questions
from eval.metrics import gold_numbers
from ingest.manifest import load_documents, local_path
from ingest.parse import cache_path, parse

pytestmark = pytest.mark.integration

KNOWN_ROWS = [
    # doc_id, page, row label prefix, expected leading values
    ("3M_2018_10K", 60, "Purchases of property, plant and equipment", ["(1,577)", "(1,373)", "(1,420)"]),
    ("ACTIVISIONBLIZZARD_2019_10K", 69, "Property and equipment, net", ["253", "282"]),
    ("ADOBE_2017_10K", 61, "Net income", ["1,693,954", "1,168,782", "629,551"]),  # cash flow statement, $ thousands
    ("WALMART_2020_10K", 51, "Operating income", ["20,568", "21,957", "20,437"]),
    ("3M_2018_10K", 58, "Cash and cash equivalents", ["2,853", "3,053"]),  # balance sheet
    ("3M_2018_10K", 57, "Net income including noncontrolling interest", ["5,363", "4,869", "5,058"]),
]


def _parsed(doc_id: str):
    if not cache_path(doc_id, "structured").exists():
        pytest.skip(f"{doc_id} not parsed yet")
    meta = load_documents()[doc_id]
    return parse(meta, local_path(meta))


@pytest.mark.parametrize(("doc_id", "page", "label", "values"), KNOWN_ROWS)
def test_known_rows(doc_id, page, label, values):
    p = _parsed(doc_id)
    rows = [r for el in p.elements if el.kind == "table" and el.page <= page <= (el.page_end or el.page) for r in el.rows or []]
    match = [r for r in rows if r and r[0].startswith(label)]
    assert match, f"no row starting with {label!r} on p.{page}"
    cells = [c.replace("$", "").strip() for c in match[0][1:] if c.replace("$", "").strip()]
    assert cells[: len(values)] == values


@pytest.mark.parametrize(
    "qid",
    ["financebench_id_03029", "financebench_id_02987", "financebench_id_03856", "financebench_id_06741", "financebench_id_07507"],
)
def test_gold_evidence_numbers_land_in_tables(qid):
    """Independent of our own labels: numbers in FinanceBench's gold evidence must appear in a parsed table on that page."""
    q = next(q for q in load_questions() if q.id == qid)
    for e in q.evidence:
        p = _parsed(e.doc_id)
        text = "\n".join(el.text for el in p.elements if el.kind == "table" and el.page <= e.page <= (el.page_end or el.page))
        nums = [n for n in gold_numbers(e.text) if n >= 100][:15]
        assert nums and sum(appears_in(n, text) for n in nums) / len(nums) >= 0.9

from app.schemas import Citation
from eval.financebench_loader import EvalQuestion, Evidence
from eval.metrics import evidence_complete, is_numeric_question, numeric_match, recall_at_k, tag_failure

Q = EvalQuestion(id="q", question="capex?", answer="$1577.00", evidence=[Evidence(doc_id="3M_2018_10K", page=60, text="")])


def _cite(doc_id: str, page: int, page_end: int | None = None) -> Citation:
    return Citation(
        id="S1",
        label="x",
        doc_id=doc_id,
        company="3M",
        fiscal_label="FY18",
        page=page,
        page_end=page_end,
        section="",
        chunk_type="text",
        snippet="",
    )


def test_recall_at_k_uses_gold_pages_and_table_spans():
    assert recall_at_k([_cite("3M_2018_10K", 59), _cite("3M_2018_10K", 60)], Q)
    assert recall_at_k([_cite("3M_2018_10K", 59, 61)], Q)
    assert not recall_at_k([_cite("3M_2022_10K", 60)], Q)
    assert not recall_at_k([_cite("x", 1)] * 10 + [_cite("3M_2018_10K", 60)], Q, k=10)


def test_numeric_match_allows_unit_rescaling():
    assert is_numeric_question(Q)
    assert numeric_match("Capex was $1,577 million [3M FY18 p.60].", Q)
    q2 = Q.model_copy(update={"answer": "$1.58 billion"})
    assert numeric_match("Capex was $1,577 million.", q2)
    assert not numeric_match("Capex was $1,650 million.", Q)
    assert not numeric_match("Not found in the filings.", Q)


def test_failure_tags():
    assert (
        tag_failure(correct=False, refused=False, answerable=True, recall10=False, gold_page_parsed=False, citations_ok=None)
        == "parsing"
    )
    assert (
        tag_failure(correct=False, refused=False, answerable=True, recall10=False, gold_page_parsed=True, citations_ok=None)
        == "retrieval"
    )
    assert (
        tag_failure(correct=False, refused=False, answerable=True, recall10=True, gold_page_parsed=None, citations_ok=True)
        == "reasoning"
    )
    assert (
        tag_failure(correct=True, refused=False, answerable=True, recall10=True, gold_page_parsed=None, citations_ok=False)
        == "citation"
    )
    assert (
        tag_failure(correct=True, refused=False, answerable=True, recall10=True, gold_page_parsed=None, citations_ok=True) is None
    )
    assert (
        tag_failure(correct=False, refused=True, answerable=False, recall10=None, gold_page_parsed=None, citations_ok=None)
        is None
    )


def test_evidence_complete_needs_every_gold_page():
    two_pages = Q.model_copy(
        update={"evidence": [Evidence(doc_id="3M_2018_10K", page=60, text=""), Evidence(doc_id="3M_2018_10K", page=58, text="")]}
    )
    assert recall_at_k([_cite("3M_2018_10K", 60)], two_pages)  # one page is a recall hit
    assert not evidence_complete([_cite("3M_2018_10K", 60)], two_pages)  # but half the evidence
    assert evidence_complete([_cite("3M_2018_10K", 60), _cite("3M_2018_10K", 58)], two_pages)
    assert evidence_complete([_cite("x", 1)], Q.model_copy(update={"evidence": []})) is None


def test_an_ungraded_answer_is_not_counted_as_a_system_failure():
    assert (
        tag_failure(correct=None, refused=False, answerable=True, recall10=True, gold_page_parsed=None, citations_ok=None)
        == "ungraded"
    )


def test_xbrl_answer_key_finds_the_value_on_a_matching_row_only():
    from eval.xbrl_set import pages_with_value

    tables = [
        {"page": 60, "rows": [["(Millions)", "2018"], ["Purchases of property, plant and equipment", "(1,577)"]]},
        {"page": 12, "rows": [["(Millions)", "2018"], ["Revenue from services", "1,577"]]},
        {"page": 58, "rows": [["(Dollars)", "2018"], ["Property and equipment, net", "1,577,000,000"]]},
    ]
    assert pages_with_value(tables, 1_577_000_000, r"property|plant") == [58, 60]
    assert pages_with_value(tables, -1_577_000_000, r"purchases") == [60]  # outflows are stored as either sign
    assert pages_with_value(tables, 9_000_000, r"property") == []

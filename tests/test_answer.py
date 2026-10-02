from app.answer import NOT_FOUND, finalize
from app.schemas import Chunk, Hit

CASH_FLOW = (
    "3M (MMM) 10-K FY18 | Financial Statements\nTable: Consolidated statement of cash flows, 2016-2018, $ millions\n"
    "| (Millions) | 2018 | 2017 |\n|---|---|---|\n| Purchases of property, plant and equipment (PP&E) | (1,577) | (1,373) |"
)
MDNA = "3M (MMM) 10-K FY18 | MD&A\nCapital spending was driven by investments in capacity and new products."


def _hit(text: str, page: int, kind: str = "text") -> Hit:
    c = Chunk(
        chunk_id=f"d:{page}",
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
        chunk_type=kind,
        text=text,
        embed_text=text,
        sparse_text=text,
    )
    return Hit(chunk=c, rerank_score=0.9)


HITS = [_hit(CASH_FLOW, 60, "table"), _hit(MDNA, 47)]


def _fig(name, value, src="S1", scale="millions"):
    return {
        "name": name,
        "value": value,
        "unit": "currency",
        "currency": "USD",
        "scale": scale,
        "period": "FY2018",
        "source_id": src,
        "quote": "Purchases of PP&E (1,577)",
    }


def _raw(answer, figures=(), calculations=(), table=None):
    return {
        "answerable": True,
        "figures": list(figures),
        "calculations": list(calculations),
        "answer": answer,
        "table": table or {"columns": [], "rows": []},
    }


def test_verified_figure_is_filled_and_citation_relabelled():
    ans = finalize("capex?", _raw("3M's FY2018 capital expenditure was {fig:capex18} [S1].", [_fig("capex18", 1577)]), HITS)
    assert ans.answer == "3M's FY2018 capital expenditure was $1,577 million [3M FY18 p.60]."
    assert [c.label for c in ans.citations] == ["3M FY18 p.60"]
    assert ans.figures[0].verified and not ans.stripped_sentences
    assert ans.citations[0].highlight == "Purchases of PP&E (1,577)"  # the viewer highlights the row used


def test_hallucinated_figure_removes_its_sentence():
    raw = _raw("Capex was {fig:capex18} [S1]. Spending went to new capacity [S2].", [_fig("capex18", 1650)])
    ans = finalize("capex?", raw, HITS)
    assert "1,650" not in ans.answer and "new capacity" in ans.answer
    assert not ans.figures[0].verified
    assert len(ans.stripped_sentences) == 1


def test_uncited_claims_and_unknown_sources_are_stripped():
    raw = _raw("Capex rose sharply. Spending went to new capacity [S2]. It was a record [S9].")
    ans = finalize("q", raw, HITS)
    assert ans.answer == "Spending went to new capacity [3M FY18 p.47]."
    assert len(ans.stripped_sentences) == 2


def test_typed_numbers_must_appear_in_the_cited_source():
    ans = finalize("q", _raw("Capex was $1,577 million [S1]. Capex was $1,900 million [S1]."), HITS)
    assert "1,577" in ans.answer and "1,900" not in ans.answer


def test_calculations_are_done_in_python():
    figs = [_fig("capex18", 1577), _fig("capex17", 1373)]
    calcs = [{"name": "capex_growth", "op": "growth", "inputs": ["capex17", "capex18"], "periods": 0}]
    ans = finalize("q", _raw("Capex grew {calc:capex_growth} to {fig:capex18} [S1].", figs, calcs), HITS)
    assert ans.answer == "Capex grew 14.86% to $1,577 million [3M FY18 p.60]."
    assert ans.calculations[0].value is not None


def test_calculation_on_unverified_input_is_dropped():
    figs = [_fig("capex18", 1577), _fig("capex17", 999)]
    calcs = [{"name": "g", "op": "growth", "inputs": ["capex17", "capex18"], "periods": 0}]
    ans = finalize("q", _raw("Capex grew {calc:g} [S1]. Spending went to new capacity [S2].", figs, calcs), HITS)
    assert "grew" not in ans.answer
    assert ans.calculations[0].error


def test_comparison_table_rendering():
    table = {"columns": ["Metric", "FY2018", "FY2017"], "rows": [["Capex", "{fig:c18}", "{fig:c17}"]]}
    raw = _raw("Capex figures are in the table [S1].", [_fig("c18", 1577), _fig("c17", 1373)], table=table)
    ans = finalize("q", raw, HITS)
    assert "| Capex | $1,577 million | $1,373 million |" in ans.table_markdown


def test_unanswerable_and_empty_answers_refuse():
    ans = finalize(
        "q", {"answerable": False, "figures": [], "calculations": [], "answer": "", "table": {"columns": [], "rows": []}}, HITS
    )
    assert ans.refused and ans.answer.startswith(NOT_FOUND) and len(ans.closest) == 2
    ans = finalize("q", _raw("Capex rose sharply."), HITS)
    assert ans.refused and ans.stripped_sentences


def test_tags_after_the_full_stop_stay_with_their_sentence():
    ans = finalize("q", _raw("Spending went to new capacity. [S2]"), HITS)
    assert not ans.refused and "[3M FY18 p.47]" in ans.answer


def test_abbreviations_do_not_split_sentences():
    ans = finalize("q", _raw("Spending went to new capacity in the U.S. Government segment [S2]."), HITS)
    assert not ans.stripped_sentences and "U.S. Government" in ans.answer


def test_units_written_around_placeholders_are_not_doubled():
    ans = finalize("q", _raw("Capex was ${fig:capex18} million [S1].", [_fig("capex18", 1577)]), HITS)
    assert ans.answer == "Capex was $1,577 million [3M FY18 p.60]."


def test_llm_json_tolerates_trailing_text():
    from app.llm import parse_json

    assert parse_json('{"a": 1}\n{"b": 2}') == {"a": 1}
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json('Here you go: {"a": [1, 2]} hope this helps') == {"a": [1, 2]}


def test_calculations_chain_and_multiply_by_a_constant():
    figs = [_fig("capex18", 1577), _fig("capex17", 1373)]
    calcs = [
        {"name": "avg_capex", "op": "average", "inputs": ["capex17", "capex18"], "periods": 0},
        {"name": "capex_ratio", "op": "ratio", "inputs": ["avg_capex", "capex18"], "periods": 0},
        {"name": "capex_days", "op": "multiply", "inputs": ["capex_ratio"], "periods": 0, "factor": 365},
    ]
    ans = finalize("q", _raw("The metric is {calc:capex_days} [S1].", figs, calcs), HITS)
    assert [c.error for c in ans.calculations] == [None, None, None]
    assert ans.answer == f"The metric is {(1577 + 1373) / 2 / 1577 * 365:,.2f} [3M FY18 p.60]."


def test_net_working_capital_style_subtraction_keeps_its_sign():
    figs = [_fig("capex18", 1577), _fig("capex17", 1373)]
    calcs = [{"name": "gap", "op": "subtract", "inputs": ["capex18", "capex17"], "periods": 0}]
    ans = finalize("q", _raw("The gap is {calc:gap} [S1].", figs, calcs), HITS)
    assert ans.answer == "The gap is $204 million [3M FY18 p.60]."

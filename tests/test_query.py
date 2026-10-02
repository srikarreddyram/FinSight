from app.query_parser import QueryParser, resolve_years
from app.retrieve import build_filter, rrf
from app.schemas import Company

COMPANIES = {
    "INFY": Company(ticker="INFY", name="Infosys", country="IN", fiscal_year_end_month=3, aliases=["Infosys Limited"]),
    "TCS": Company(ticker="TCS", name="TCS", country="IN", fiscal_year_end_month=3, aliases=["Tata Consultancy Services"]),
    "MMM": Company(ticker="MMM", name="3M", aliases=["3M Company"]),
    "FL": Company(ticker="FL", name="Foot Locker", fiscal_year_end_month=1),
}
AVAILABLE = {"INFY": [2023, 2024, 2025, 2026], "TCS": [2024, 2025, 2026], "MMM": [2018, 2022], "FL": [2022]}


def parser() -> QueryParser:
    return QueryParser(COMPANIES, AVAILABLE)


def test_rrf_rewards_agreement():
    scores = rrf([["a", "b", "c"], ["b", "a", "d"]], k=60)
    assert scores["a"] == scores["b"] == 1 / 61 + 1 / 62
    assert scores["c"] == scores["d"] == 1 / 63
    assert rrf([["x", "y"], ["y"]], k=60)["y"] > rrf([["x", "y"], ["y"]], k=60)["x"]


def test_company_matching_uses_names_aliases_and_capitalised_tickers():
    p = parser()
    assert p.heuristic("What was Infosys's operating margin?").tickers == ["INFY"]
    assert p.heuristic("Tata Consultancy Services revenue").tickers == ["TCS"]
    assert p.heuristic("3M capex in FY2018").tickers == ["MMM"]
    assert p.heuristic("Is the fl oor plan relevant?").tickers == []  # lowercase 'fl' is not a ticker
    assert p.heuristic("FL store count").tickers == ["FL"]


def test_explicit_years_become_per_company_filters():
    pq = parser().heuristic("What was Infosys's operating margin in FY24 and FY25?")
    assert pq.fiscal_years == {"INFY": [2024, 2025]}


def test_last_year_resolves_per_company():
    pq = parser().heuristic("Compare Infosys and 3M revenue growth last year")
    assert pq.fiscal_years == {"INFY": [2026], "MMM": [2022]}
    assert pq.is_comparison


def test_missing_year_falls_back_to_next_filing():
    # FY2021 figures appear as comparatives in the FY2022 10-K
    assert resolve_years([2021], [2018, 2022]) == [2022]
    assert resolve_years([2018], [2018, 2022]) == [2018]
    assert resolve_years([2010], [2018, 2022]) == []


def test_comparison_fans_out_into_single_company_queries():
    pq = parser().heuristic("Compare TCS and Infosys revenue growth over three years")
    assert pq.is_comparison and set(pq.sub_queries) == {"TCS", "INFY"}
    assert "Infosys" not in pq.sub_queries["TCS"].split("(")[0]
    assert pq.sub_queries["INFY"].endswith("(Infosys)")
    assert pq.fiscal_years["TCS"] == [2024, 2025, 2026]


def test_section_and_doc_type_hints():
    pq = parser().heuristic("What are the top risk factors 3M lists?")
    assert "Risk Factors" in pq.sections
    pq = parser().heuristic("What did management say drove Infosys's Q4 margin?")
    assert "MD&A" in pq.sections and "earnings_call" in pq.doc_types


def test_build_filter_shapes():
    pq = parser().heuristic("Compare Infosys and 3M revenue last year")
    f = build_filter(pq)
    assert f is not None and len(f.should) == 2
    single = build_filter(pq, "INFY")
    assert [c.key for c in single.must] == ["ticker", "fiscal_year"]
    assert build_filter(None) is None


def _scored(name: str, kind: str, rerank: float, fused: float):
    from app.schemas import Chunk, Hit

    c = Chunk(
        chunk_id=name,
        doc_id="d",
        ticker="T",
        company="T",
        doc_type="10-K",
        fiscal_year=2024,
        fiscal_label="FY24",
        period="FY",
        period_end="2024-12-31",
        section="",
        heading="",
        page=1,
        page_end=1,
        chunk_type=kind,
        text=name,
        embed_text=name,
        sparse_text=name,
    )
    return Hit(chunk=c, rrf_score=fused, rerank_score=rerank)


def test_final_ordering_blend_and_table_slots():
    from app.rerank import order

    hits = [_scored("t1", "text", 0.9, 0.01), _scored("t2", "text", 0.8, 0.02), _scored("tab", "table", 0.3, 0.03)]
    assert [h.chunk.chunk_id for h in order(hits, 2)] == ["t1", "t2"]
    assert [h.chunk.chunk_id for h in order(hits, 2, table_slots=1)] == ["t1", "tab"]
    assert order(hits, 1, blend=0.0)[0].chunk.chunk_id == "tab"  # pure fusion score


class _FakeLLM:
    def __init__(self, out):
        self.out = out

    def json(self, **_):
        return self.out


def test_llm_cannot_add_companies_the_question_never_names():
    out = {
        "tickers": ["MMM", "FL"],
        "fiscal_years": [2018],
        "relative": "none",
        "n_years": 0,
        "sections": [],
        "doc_types": [],
        "is_comparison": True,
        "sub_queries": [],
    }
    pq = QueryParser(COMPANIES, AVAILABLE, llm=_FakeLLM(out)).parse("By how much did 3M's net sales grow in 2018?")
    assert pq.tickers == ["MMM"] and not pq.is_comparison
    # but when no name matches, the LLM's resolution is used (only for companies with filings)
    out2 = {**out, "tickers": ["INFY", "ZZZZ"], "is_comparison": False}
    pq2 = QueryParser(COMPANIES, AVAILABLE, llm=_FakeLLM(out2)).parse("What did India's second-largest IT exporter earn?")
    assert pq2.tickers == ["INFY"]

"""Every company's latest 10-K sections, from the warehouse, as Copilot sources."""

from datetime import date

from app.answer import to_citation
from app.config import get_settings
from app.pipeline import RUNS, Pipeline
from app.query_parser import QueryParser
from app.schemas import Company, Hit
from ingest.chunk import text_chunks
from ingest.sections import clean_name, fiscal_year_of, latest_10ks, parsed
from warehouse import db


def test_names_lose_their_legal_suffixes_unless_too_generic():
    assert clean_name("Coca-Cola Company (The)") == "Coca-Cola"
    assert clean_name("Ichor Holdings, Ltd.") == "Ichor"
    assert clean_name("Target Corporation") == "Target"
    assert clean_name("Nvidia") == "Nvidia"
    assert clean_name("Southern Company (The)") == "Southern Company"  # "Southern" alone is a region


def test_fiscal_years_follow_the_period_end():
    assert fiscal_year_of(date(2026, 1, 25)) == (2026, 1)  # Nvidia's FY2026
    assert fiscal_year_of(date(2023, 1, 1)) == (2022, 12)  # a 52/53-week year: Johnson & Johnson's FY2022
    assert fiscal_year_of(date(2025, 9, 27)) == (2025, 9)  # Apple


def _warehouse():
    con = db.connect(":memory:")
    con.execute("insert into companies (cik, ticker, name) values (1045810, 'NVDA', 'Nvidia'), (1, 'OLD', 'Gone Inc.')")
    con.execute(
        "insert into filings (accn, cik, form, filed_at) values "
        "('A-26', 1045810, '10-K', '2026-02-25'), ('A-25', 1045810, '10-K', '2025-02-26'), ('B-19', 1, '10-K', '2019-03-01')"
    )
    con.execute(
        "insert into filing_text (accn, cik, item, section, text) values "
        "('A-26', 1045810, '7', 'MD&A', 'Item 7. Management''s Discussion\nData Center revenue rose on demand for Blackwell systems.\n12'), "
        "('A-26', 1045810, '1A', 'Risk Factors', 'Export controls could limit our sales to China and other regions.'), "
        "('A-25', 1045810, '7', 'MD&A', 'Last year''s discussion of results and the drivers behind them.'), "
        "('B-19', 1, '7', 'MD&A', 'A company that stopped filing years ago.')"
    )
    con.execute(
        "insert into facts (cik, taxonomy, concept, unit, value, period_start, period_end, filed_at, available_at, accn, form, fy, fp) "
        "values (1045810, 'us-gaap', 'Revenues', 'USD', 1, '2025-01-27', '2026-01-25', '2026-02-25', '2026-02-26', 'A-26', '10-K', 2026, 'FY')"
    )
    return con


def test_only_each_companys_latest_10k_and_only_companies_still_filing():
    [f] = latest_10ks(_warehouse())
    assert (f["ticker"], f["accn"], f["fiscal_year"], f["fye_month"]) == ("NVDA", "A-26", 2026, 1)
    assert f["doc_id"] == "edgar:1045810:A-26"


def test_sections_chunk_by_item_and_cite_the_item():
    con = _warehouse()
    doc = parsed(con, latest_10ks(con)[0])
    assert [e.section for e in doc.elements if e.kind == "heading"] == ["Risk Factors", "MD&A"]
    assert "12" not in [e.text for e in doc.elements]  # page furniture dropped
    chunks = text_chunks(doc, get_settings())
    assert {c.section for c in chunks} == {"Risk Factors", "MD&A"} and all(c.page == 0 for c in chunks)
    mdna = next(c for c in chunks if c.section == "MD&A")
    assert mdna.text.startswith("Nvidia (NVDA) 10-K FY26 | MD&A | Item 7. MD&A")
    cite = to_citation(0, Hit(chunk=mdna))
    assert cite.label == "Nvidia FY26 10-K Item 7" and "Blackwell" in cite.snippet


def test_universe_names_must_be_capitalised_but_filed_companies_need_not_be():
    companies = {
        "TGT": Company(ticker="TGT", name="Target"),
        "MMM": Company(ticker="MMM", name="3M"),
        "BBY": Company(ticker="BBY", name="Best Buy"),
    }
    p = QueryParser(companies, {}, strict={"TGT"})
    assert p.heuristic("What was Target's revenue?").tickers == ["TGT"]
    assert p.heuristic("Did 3M hit its target margin?").tickers == ["MMM"]
    assert p.heuristic("what was best buy's revenue?").tickers == ["BBY"]


def test_the_llm_only_sees_companies_sharing_a_word_with_the_question():
    many = {f"T{i}": Company(ticker=f"T{i}", name=f"Company {i}") for i in range(150)}
    many["NVDA"] = Company(ticker="NVDA", name="Nvidia", aliases=["NVIDIA Corporation"])
    p = QueryParser(many, {})
    assert set(p._candidates("how did the graphics chip maker nvidia do?")) == {"NVDA"}
    assert p._candidates("what drove the change in margins?") == {}


def _routing(run: str = "F") -> Pipeline:
    p = object.__new__(Pipeline)
    p.cfg, p.s, p.collection = RUNS[run], get_settings(), "finsight"
    p.pdf_tickers = {"MMM", "NKE"}
    p.sections = {"NVDA": {"fiscal_year": 2026}, "MMM": {"fiscal_year": 2025}, "NKE": {"fiscal_year": 2023}}
    p.tenk_docs = {("MMM", 2022): "3M_2022_10K", ("NKE", 2023): "NIKE_2023_10K"}
    return p


def test_questions_go_to_the_collections_that_hold_the_company():
    p = _routing()
    assert p._collections("NVDA") == [p.s.sections_collection]
    assert p._collections("MMM") == ["finsight", p.s.sections_collection]  # old filings' pages and the latest 10-K
    assert p._collections("NKE") == ["finsight"]  # that 10-K is already among the parsed filings
    assert p._collections(None) == ["finsight"] and p._collections("ZZZ") == ["finsight"]
    assert _routing("A")._collections("NVDA") == ["finsight"]


class _Search:
    def __init__(self):
        self.calls = []

    def search(self, query, *, collection, **_):
        self.calls.append(collection)
        return [Hit(chunk=_chunk(collection), rrf_score=0.03 if collection == "finsight" else 0.02)]


def _chunk(name: str):
    from app.schemas import Chunk

    return Chunk(
        chunk_id=name, doc_id="d", ticker="MMM", company="3M", doc_type="10-K", fiscal_year=2022, fiscal_label="FY22",
        period="FY", period_end="2022-12-31", section="", heading="", page=1, page_end=1, chunk_type="text", text=name,
        embed_text=name, sparse_text=name,
    )  # fmt: skip


def test_a_company_in_both_collections_is_searched_in_both_and_merged_by_score():
    from app.schemas import ParsedQuery

    p = _routing()
    p.retriever = _Search()
    hits = p._search("risks", ParsedQuery(question="q", tickers=["MMM"]))
    assert p.retriever.calls == ["finsight", p.s.sections_collection]
    assert [h.chunk.chunk_id for h in hits] == ["finsight", p.s.sections_collection]


def test_a_question_that_names_no_company_asks_which_one():
    from app.answer import WHICH_COMPANY
    from app.schemas import ParsedQuery

    p = _routing()
    pq = ParsedQuery(question="q")
    assert p._retrieve("What drove the reduction in SG&A?", pq) == (pq, [], [])
    ans = p.answer_from("What drove the reduction in SG&A?", pq, [], [])
    assert ans.clarify and ans.refused and ans.answer == WHICH_COMPANY and ans.attempts == 1


def test_a_name_inside_a_longer_name_belongs_to_the_longer():
    companies = {
        "FOXA": Company(ticker="FOXA", name="Fox"),
        "FOXF": Company(ticker="FOXF", name="Fox Factory"),
        "XYZ": Company(ticker="XYZ", name="Block"),
        "HRB": Company(ticker="HRB", name="H&R Block"),
    }
    p = QueryParser(companies, {}, strict=set(companies))
    assert p.heuristic("What was Fox Factory's revenue?").tickers == ["FOXF"]
    assert p.heuristic("Compare Fox and Fox Factory").tickers == ["FOXA", "FOXF"]
    assert p.heuristic("H&R Block's tax season").tickers == ["HRB"]


def test_acronym_names_need_their_capitals_and_any_ticker_works_after_a_dollar_sign():
    from app.query_parser import Vocab

    companies = {
        "DNOW": Company(ticker="DNOW", name="NOW"),
        "K": Company(ticker="K", name="Kellanova"),
        "QTWO": Company(ticker="QTWO", name="Q2", aliases=["Q2 Holdings"]),
        "NVDA": Company(ticker="NVDA", name="Nvidia"),
        "ALL": Company(ticker="ALL", name="Allstate"),
    }
    p = QueryParser(companies, {}, strict=set(companies), vocab=Vocab(plain=frozenset({"now", "all"})))
    assert p.heuristic("Now that rates fell, what does the 10-K say in Q2 for ALL segments?").tickers == []
    assert p.heuristic("How is NOW positioned?").tickers == ["DNOW"]
    assert p.heuristic("$K and $ALL margins").tickers == ["K", "ALL"]
    assert p.heuristic("NVIDIA's data center revenue").tickers == ["NVDA"]  # any capitalisation with a capital first
    assert p.heuristic("Q2 Holdings' revenue").tickers == ["QTWO"]


def test_universe_tickers_that_are_ordinary_words_cannot_name_a_company():
    from app.query_parser import Vocab

    companies = {t: Company(ticker=t, name=f"Name{i}x") for i, t in enumerate(["IT", "COST", "NVDA"])}
    p = QueryParser(companies, {}, strict=set(companies), vocab=Vocab(caps=frozenset({"COST"})))
    assert p.heuristic("IT spending and COST of sales").tickers == []
    assert p.heuristic("How did NVDA do?").tickers == ["NVDA"]


def test_names_that_are_ordinary_words_keep_their_suffix_unless_household():
    plain = frozenset({"post", "news", "target"})
    assert clean_name("Post Holdings, Inc.", plain) == "Post Holdings"
    assert clean_name("News Corporation", plain) == "News Corporation"
    assert clean_name("Target Corporation", plain) == "Target"
    assert clean_name("Nvidia Corporation", plain) == "Nvidia"


def test_lower_case_names_match_only_as_a_last_resort_and_never_ordinary_words():
    from app.query_parser import Vocab

    companies = {"NVDA": Company(ticker="NVDA", name="Nvidia"), "TGT": Company(ticker="TGT", name="Target")}
    p = QueryParser(companies, {}, strict=set(companies), vocab=Vocab(plain=frozenset({"target"})))
    assert p.heuristic("what was nvidia's revenue?").tickers == []
    assert p.parse("what was nvidia's revenue?").tickers == ["NVDA"]  # no model to ask
    assert p.parse("what is a good target margin?").tickers == []

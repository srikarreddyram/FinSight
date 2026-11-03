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


def test_questions_go_to_the_collection_that_holds_the_company():
    p = object.__new__(Pipeline)
    p.cfg, p.s, p.collection = RUNS["F"], get_settings(), "finsight"
    p.pdf_tickers, p.sections = {"MMM"}, {"NVDA": {}, "MMM": {}}
    assert p._collection("NVDA") == p.s.sections_collection
    assert p._collection("MMM") == "finsight"  # FinanceBench filings win: they have pages and tables
    assert p._collection(None) == "finsight" and p._collection("ZZZ") == "finsight"
    p.cfg = RUNS["A"]
    assert p._collection("NVDA") == "finsight"

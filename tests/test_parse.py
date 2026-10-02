from app.schemas import DocMeta, Element, ParsedDoc
from ingest.fetch_edgar import fye_month
from ingest.parse import _is_data_table, assign_sections, classify_heading, fix_kerning


def test_10k_items_map_to_sections():
    assert classify_heading("Item 1A. Risk Factors", "Business", "10-K") == "Risk Factors"
    assert classify_heading("Item 7. Management's Discussion and Analysis", "Other", "10-K") == "MD&A"
    assert (
        classify_heading("Item 7A. Quantitative and Qualitative Disclosures About Market Risk", "MD&A", "10-K") == "Market Risk"
    )
    assert (
        classify_heading("Item 8. Financial Statements and Supplementary Data", "Market Risk", "10-K") == "Financial Statements"
    )
    assert classify_heading("Item 1B. Unresolved Staff Comments", "Risk Factors", "10-K") == "Other"


def test_subheadings_inside_an_item_do_not_switch_section():
    # A "Legal Proceedings" note or a "Risk management" paragraph must stay in its parent section.
    assert classify_heading("Legal Proceedings", "Notes", "10-K") == "Notes"
    assert classify_heading("Risk Management", "MD&A", "10-K") == "MD&A"
    assert classify_heading("Consolidated Balance Sheet", "Notes", "10-K") == "Notes"


def test_statements_and_notes():
    assert classify_heading("Consolidated Statement of Cash Flows", "Auditor's Report", "10-K") == "Financial Statements"
    assert classify_heading("Notes to Consolidated Financial Statements", "Financial Statements", "10-K") == "Notes"
    assert (
        classify_heading("Report of Independent Registered Public Accounting Firm", "Market Risk", "10-K") == "Auditor's Report"
    )


def test_10q_and_20f_item_numbers():
    assert classify_heading("Item 2. Management's Discussion and Analysis", "Other", "10-Q") == "MD&A"
    assert classify_heading("Item 1. Financial Statements", "Other", "10-Q") == "Financial Statements"
    assert classify_heading("Item 5. Operating and Financial Review and Prospects", "Other", "20-F") == "MD&A"
    assert classify_heading("Item 3. Key Information", "Other", "20-F") == "Risk Factors"


def test_annual_report_keywords():
    assert classify_heading("Management Discussion and Analysis", "Other", "annual_report") == "MD&A"
    assert classify_heading("Board's Report", "MD&A", "annual_report") == "Governance"
    assert classify_heading("Standalone Balance Sheet", "Governance", "annual_report") == "Financial Statements"


def test_assign_sections_walks_headings():
    meta = DocMeta(doc_id="d", ticker="T", company="T", doc_type="10-K", fiscal_year=2024)
    els = [
        Element(kind="text", text="cover", page=1),
        Element(kind="heading", text="Item 1A. Risk Factors", page=2),
        Element(kind="text", text="risk text", page=2),
        Element(kind="heading", text="Legal Proceedings", page=3),
        Element(kind="text", text="still risk", page=3),
    ]
    p = assign_sections(ParsedDoc(meta=meta, parser="t", page_count=3, elements=els))
    assert [e.section for e in p.elements] == ["Other", "Risk Factors", "Risk Factors", "Risk Factors", "Risk Factors"]


def test_fix_kerning():
    assert fix_kerning("Consolidated Statement of Cash Flow s") == "Consolidated Statement of Cash Flows"
    assert fix_kerning("LIQUIDI TY AND CAPITAL RESOURCES") == "LIQUIDITY AND CAPITAL RESOURCES"
    assert fix_kerning("Registrant' s Common Equity") == "Registrant's Common Equity"
    assert fix_kerning("PART II") == "PART II"
    assert fix_kerning("value of a share in 2018") == "value of a share in 2018"


def test_prose_tables_are_not_data_tables():
    assert _is_data_table([["", "2024", "2023"], ["Revenue", "1,000", "900"], ["Cost", "(500)", "(450)"]])
    assert not _is_data_table([["Our strategy"], ["We aim to grow."]])


def test_sec_fiscal_year_end():
    assert fye_month("0331") == 3
    assert fye_month("0928") == 9
    assert fye_month("0101") == 12  # 52/53-week year ending a few days into January
    assert fye_month(None) == 12


def test_dropped_item_heading_is_recovered_from_page_text():
    from ingest.parse import recover_item_headings

    meta = DocMeta(doc_id="d", ticker="T", company="T", doc_type="10-K", fiscal_year=2022)
    els = [
        Element(kind="heading", text="Item 6. [Reserved]", page=20),
        Element(kind="heading", text="Overview", page=21),
        Element(kind="text", text="Verizon is a holding company that provides communications services.", page=21),
    ]
    p = ParsedDoc(meta=meta, parser="t", page_count=21, elements=els)
    pages = {21: "Item 7. Management's Discussion and Analysis of Financial Condition\nOverview\nVerizon is a holding company"}
    assert recover_item_headings(p, pages) == 1
    assert [e.text.split()[0] for e in p.elements] == ["Item", "Item", "Overview", "Verizon"]
    assert classify_heading(p.elements[1].text, "Selected Financial Data", "10-K") == "MD&A"
    # a table of contents (many Item lines on one page) is ignored
    toc = {21: "\n".join(f"Item {i}. Something" for i in range(1, 9))}
    assert recover_item_headings(ParsedDoc(meta=meta, parser="t", page_count=21, elements=list(els)), toc) == 0

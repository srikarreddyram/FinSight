from datetime import date

from warehouse.tenk import exhibit_13_urls, list_10ks, mda_from_exhibit


def _block(*rows):
    keys = ["accessionNumber", "form", "filingDate", "reportDate", "primaryDocument"]
    return {k: [r[i] for r in rows] for i, k in enumerate(keys)}


def test_lists_original_10ks_from_recent_and_older_pages():
    sub = {"filings": {"recent": _block(
        ("A-24", "10-K", "2024-02-07", "2023-12-31", "mmm-2023.htm"),
        ("A-23q", "10-Q", "2023-10-24", "2023-09-30", "q.htm"),
        ("A-23a", "10-K/A", "2023-03-01", "2022-12-31", "amend.htm"),
    )}}  # fmt: skip
    older = [_block(("A-10", "10-K", "2010-02-16", "2009-12-31", "k.htm"), ("A-08", "10-K", "2008-02-15", "2007-12-31", "k.htm"))]
    got = list_10ks(sub, older, since=date(2009, 1, 1))
    assert [f.accn for f in got] == ["A-24", "A-10"]  # no 10-Q, no amendment, nothing before 2009
    assert got[0].period_end == date(2023, 12, 31) and got[0].primary == "mmm-2023.htm"


def test_finds_exhibit_13_on_the_index_page():
    html = """<table>
    <tr><td>1</td><td><a href="/Archives/edgar/data/1/0001/k.htm">k.htm</a></td><td>10-K</td></tr>
    <tr><td>2</td><td><a href="/Archives/edgar/data/1/0001/ex13.htm">ex13.htm</a></td><td>EX-13</td></tr>
    <tr><td>3</td><td><a href="/ix?doc=/Archives/edgar/data/1/0001/ex13b.htm">ex13b.htm</a></td><td>EX-13.1</td></tr>
    <tr><td>4</td><td><a href="/Archives/edgar/data/1/0001/ex21.htm">ex21.htm</a></td><td>EX-21</td></tr>
    </table>"""
    assert exhibit_13_urls(html) == [  # the inline-XBRL viewer link is unwrapped to the document
        "https://www.sec.gov/Archives/edgar/data/1/0001/ex13.htm",
        "https://www.sec.gov/Archives/edgar/data/1/0001/ex13b.htm",
    ]


def test_mda_from_exhibit_skips_the_table_of_contents():
    body = "Revenue grew because customers bought more. " * 200
    text = (
        "Contents\nManagement's Discussion and Analysis 12\nConsolidated Statements of Income 40\n"
        "Letter to shareholders\n" + "We had a year. " * 50 + "\n"
        "Management’s Discussion and Analysis of Financial Condition\n" + body + "\n"
        "Report of Independent Registered Public Accounting Firm\nWe audited..."
    )
    s = mda_from_exhibit(text)
    assert s is not None and s.item == "7"
    assert s.text.startswith("Management’s Discussion") and s.text.endswith("customers bought more.")
    assert mda_from_exhibit("Management's Discussion and Analysis\nshort\nConsolidated Balance Sheets") is None


def test_mda_does_not_end_at_a_lowercase_mention_inside_a_table():
    text = (
        "Management's Discussion and Analysis\n"
        + "Sales rose. " * 400
        + "\nOther long-term liabilities reflected in our\nconsolidated balance sheet\n806\n"
        + "More discussion. " * 100
        + "\nConsolidated Statements of Income\nYear Ended December 31"
    )
    s = mda_from_exhibit(text)
    assert s is not None and s.text.endswith("More discussion.")


def test_mda_does_not_end_at_an_analysis_section_named_after_a_statement():
    text = (
        "Management's discussion and analysis\n"
        + "Rates rose. " * 300
        + "\nConsolidated Balance Sheets Analysis\n"
        + "Deposits grew. " * 300
        + "\nConsolidated balance sheets\nDecember 31"
    )
    s = mda_from_exhibit(text)
    assert s is not None and "Deposits grew." in s.text and s.text.startswith("Management's")


def test_a_heading_without_financial_statements_after_it_is_not_an_mda():
    index = "Management's Discussion and Analysis of Financial Condition and Results of\nOperations\n83\n" + "Other text. " * 900
    assert mda_from_exhibit(index) is None
    amex = "Financial Review\n" + "Billed business grew. " * 300 + "\nConsolidated Statements of Income\n"
    assert mda_from_exhibit(amex).text.startswith("Financial Review")


def test_a_table_of_contents_entry_spanning_other_items_is_not_an_mda():
    tenk = (
        "ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION\n41\nITEM 7A. MARKET RISK\n41\n"
        "ITEM 8. FINANCIAL STATEMENTS\n42\nITEM 9. CHANGES\n42\n"
        + "Business text. " * 900
        + "\nITEM 15. EXHIBITS\nincorporated by reference into Item 8:\nConsolidated Statements of Income\n"
    )
    assert mda_from_exhibit(tenk) is None

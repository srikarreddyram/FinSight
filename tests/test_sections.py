from warehouse import db, sections

FILLER = "The Company discusses its results in detail. " * 20  # ~900 characters of body text


def _filing():
    toc = "\n".join(
        [
            "TABLE OF CONTENTS",
            "ITEM 1 Business 4",
            "ITEM 1A Risk Factors 10",
            "ITEM 1B Unresolved Staff Comments 12",
            "ITEM 7 Management's Discussion and Analysis 15",
            "ITEM 7A Quantitative and Qualitative Disclosures 51",
            "ITEM 8 Financial Statements 52",
        ]
    )
    body = "\n".join(
        [
            "Item 1. Busines s.",  # kerning damage from PDF extraction
            "3M is a diversified technology company. " + FILLER,
            "Item 1A. Risk Factors",
            "Results are impacted by economic conditions. " + FILLER,
            "Item 1B. Unresolved Staff Comments.",
            "None.",
            "Item 7. Management's Discussion and Analysis",
            "Sales grew in all segments. " + FILLER,
            "Item 1A, Risk Factors, of this document describes the risks.",  # cross-reference, not a heading
            "More discussion of results. " + FILLER,
            "ITEM 7A: Quantitative and Qualitative Disclosures About Market Risk",
            "The Company is exposed to currency risk. " + FILLER,
            "Item 8 - Financial Statements and Supplementary Data",
            "Consolidated Statement of Income. " + FILLER,
        ]
    )
    return toc + "\n" + body


def test_body_items_are_found_and_table_of_contents_is_skipped():
    secs = sections.split_10k(_filing())
    assert list(secs) == ["1", "1A", "1B", "7", "7A", "8"]
    assert secs["1"].text.startswith("Item 1. Busines s.")
    assert secs["1A"].name == "Risk Factors" and "economic conditions" in secs["1A"].text
    assert "TABLE OF CONTENTS" not in secs["1"].text


def test_cross_reference_does_not_split_mdna():
    secs = sections.split_10k(_filing())
    mdna = secs["7"].text
    assert "Sales grew" in mdna and "More discussion of results" in mdna
    assert "currency risk" not in mdna
    assert secs["7A"].text.startswith("ITEM 7A:")


def test_missing_items_are_absent_not_invented():
    secs = sections.split_10k("Item 7. MD&A\n" + FILLER)
    assert list(secs) == ["7"]
    assert sections.split_10k("no items here") == {}


def test_html_to_text_drops_xbrl_header_and_keeps_blocks():
    html = (
        "<html><head><title>10-K</title></head><body>"
        "<ix:header><ix:hidden>dei:EntityCentralIndexKey 66740</ix:hidden></ix:header>"
        "<div>Item&#160;1A.&nbsp;Risk Factors</div><p>Results are <b>impacted</b> by conditions.</p>"
        "<table><tr><td>Net sales</td><td>32,765</td></tr></table>"
        "<script>var x = 1;</script></body></html>"
    )
    text = sections.html_to_text(html)
    assert text.splitlines() == ["Item 1A. Risk Factors", "Results are impacted by conditions.", "Net sales 32,765"]


def test_store_replaces_a_filing():
    con = db.connect(":memory:")
    secs = sections.split_10k(_filing())
    assert sections.store(con, "0000066740-19-000010", 66740, secs) == 6
    assert sections.store(con, "0000066740-19-000010", 66740, secs) == 6
    assert con.execute("select count(*) from filing_text").fetchone()[0] == 6

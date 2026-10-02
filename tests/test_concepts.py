from app.concepts import expand


def test_ratio_questions_expand_to_statement_line_items():
    q, statements = expand("Does 3M have a healthy liquidity profile based on its quick ratio for Q2 of FY2023?")
    assert q.startswith("Does 3M")
    assert "total current liabilities" in q and "balance sheet" in q
    assert statements

    q, statements = expand("Does Adobe have an improving Free cashflow conversion as of FY2022?")
    assert "purchases of property plant and equipment" in q and statements


def test_plain_questions_are_unchanged():
    assert expand("What industry does AMCOR primarily operate in?") == ("What industry does AMCOR primarily operate in?", False)


def test_cover_page_questions_do_not_force_statements():
    q, statements = expand("Which debt securities are registered to trade on a national securities exchange under 3M's name?")
    assert "trading symbol" in q and not statements


def test_ratio_across_two_statements_reaches_both():
    q, statements = expand(
        "What is the FY2017 operating cash flow ratio for Adobe? Operating cash flow ratio is defined as: cash from "
        "operations / total current liabilities."
    )
    assert "balance sheet" in q and "cash flow statement" in q and statements

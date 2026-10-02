from datetime import date

from app import fiscal
from app.schemas import DocMeta


def test_indian_fiscal_year_runs_april_to_march():
    assert fiscal.period_bounds(2026, "FY", 3) == (date(2025, 4, 1), date(2026, 3, 31))
    assert fiscal.label(2026) == "FY26"


def test_january_year_end_retailer():
    # Best Buy fiscal 2024 = Feb 2023 - Jan 2024
    assert fiscal.period_bounds(2024, "FY", 1) == (date(2023, 2, 1), date(2024, 1, 31))


def test_quarters_follow_fiscal_year():
    # Apple-style September year end: Q1 FY2024 = Oct-Dec 2023
    assert fiscal.period_bounds(2024, "Q1", 9) == (date(2023, 10, 1), date(2023, 12, 31))
    # Infosys Q4 FY25 = Jan-Mar 2025
    assert fiscal.period_bounds(2025, "Q4", 3) == (date(2025, 1, 1), date(2025, 3, 31))
    assert fiscal.label(2025, "Q4") == "Q4 FY25"


def test_fiscal_year_and_quarter_of_a_date():
    assert fiscal.fiscal_year_of(date(2025, 6, 30), 3) == 2026
    assert fiscal.fiscal_year_of(date(2025, 3, 31), 3) == 2025
    assert fiscal.fiscal_year_of(date(2024, 12, 31), 12) == 2024
    assert fiscal.quarter_of(date(2025, 6, 30), 3) == "Q1"
    assert fiscal.quarter_of(date(2023, 12, 30), 9) == "Q1"


def test_docmeta_exposes_calendar_period():
    m = DocMeta(doc_id="x", ticker="INFY", company="Infosys", doc_type="20-F", fiscal_year=2025, fiscal_year_end_month=3)
    assert (m.period_start, m.period_end) == (date(2024, 4, 1), date(2025, 3, 31))
    assert m.fiscal_label == "FY25"


def test_explicit_years():
    assert fiscal.explicit_years("operating margin in FY24 and FY25") == [2024, 2025]
    assert fiscal.explicit_years("What is the FY2018 capex") == [2018]
    assert fiscal.explicit_years("revenue in fiscal 2023") == [2023]
    assert fiscal.explicit_years("annual report 2024-25") == [2025]
    assert fiscal.explicit_years("as of 2024-03-31") == [2024]  # a date, not a year range
    assert fiscal.explicit_years("Q2 of FY 2024 vs FY'23") == [2023, 2024]


def test_relative_years_resolve_against_available_filings():
    assert fiscal.relative_years("What was revenue last year?", [2023, 2024, 2025]) == [2025]
    assert fiscal.relative_years("growth over the last three years", [2021, 2022, 2023, 2024]) == [2022, 2023, 2024]
    assert fiscal.relative_years("year-over-year change", [2023, 2024]) == [2023, 2024]
    assert fiscal.relative_years("What was revenue?", [2024]) is None

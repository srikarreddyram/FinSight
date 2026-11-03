import pytest

from app.numbers import CalcError, Quantity, appears_in, calculate, fmt_calc, fmt_quantity, numbers_in, requested_decimals


def test_numbers_in_handles_filing_formats():
    text = "Purchases of PP&E | (1,577) | (1,373) | margin 22.3 % | ₹ 1,23,456 crore"
    assert numbers_in(text) == [1577, 1373, 22.3, 123456]


@pytest.mark.parametrize(
    ("value", "found"),
    [(1577, True), (-1577, True), (1577.4, True), (1578, False), (22.3, True), (22.34, True), (123456, True), (9999, False)],
)
def test_appears_in_tolerates_printed_rounding_only(value, found):
    assert appears_in(value, "capex (1,577) and margin 22.3% and 1,23,456") is found


def test_formatting():
    assert fmt_quantity(Quantity(1577, "currency", "USD", "millions")) == "$1,577 million"
    assert fmt_quantity(Quantity(12345.6, "currency", "INR", "crore")) == "₹12,345.6 crore"
    assert fmt_quantity(Quantity(-42, "currency", "USD", "millions")) == "-$42 million"
    assert fmt_quantity(Quantity(21.25, "percent")) == "21.25%"
    assert fmt_quantity(Quantity(982, "count")) == "982"


def test_growth_rescales_units():
    q = calculate("growth", [Quantity(100, "currency", "USD", "millions"), Quantity(0.12, "currency", "USD", "billions")])
    assert q.value == pytest.approx(20.0)
    assert fmt_calc("growth", q) == "20%"


def test_margin_difference_ratio_cagr():
    margin = calculate("margin", [Quantity(7207, "currency", "USD", "millions"), Quantity(32765, "currency", "USD", "millions")])
    assert margin.value == pytest.approx(21.996, abs=1e-3)
    pp = calculate("change", [Quantity(21.0, "percent"), Quantity(24.1, "percent")])
    assert fmt_calc("change", pp) == "3.1 percentage points"
    ratio = calculate("ratio", [Quantity(300, "currency", "USD"), Quantity(150, "currency", "USD")])
    assert fmt_calc("ratio", ratio) == "2x"
    cagr = calculate("cagr", [Quantity(100, "currency", "INR", "crore"), Quantity(133.1, "currency", "INR", "crore")], periods=3)
    assert cagr.value == pytest.approx(10.0, abs=1e-6)
    total = calculate("sum", [Quantity(1.5, "currency", "USD", "billions"), Quantity(500, "currency", "USD", "millions")])
    assert fmt_quantity(total) == "$2 billion"


def test_calculation_guards():
    with pytest.raises(CalcError):
        calculate("growth", [Quantity(0, "currency", "USD"), Quantity(5, "currency", "USD")])
    with pytest.raises(CalcError):
        calculate("sum", [Quantity(1, "currency", "USD"), Quantity(1, "currency", "INR")])
    with pytest.raises(CalcError):
        calculate("cagr", [Quantity(1, "currency", "USD"), Quantity(2, "currency", "USD")], periods=0)
    with pytest.raises(CalcError):
        calculate("median", [Quantity(1)])


def test_subtract_is_a_minus_b_and_change_is_new_minus_old():
    assets = Quantity(19_815.0, "currency", "USD", "millions")
    liabilities = Quantity(13_997.0, "currency", "USD", "millions")
    assert calculate("subtract", [assets, liabilities]).value == 5_818.0  # "assets less liabilities"
    assert calculate("change", [liabilities, assets]).value == 5_818.0  # from old to new
    assert calculate("difference", [liabilities, assets]).value == 5_818.0  # legacy name = change


def test_multiplying_by_a_power_of_a_thousand_converts_the_unit():
    billions = calculate("multiply", [Quantity(8738, "currency", "USD", "millions")], factor=0.001)
    assert fmt_calc("multiply", billions) == "$8.74 billion"
    assert billions.base == pytest.approx(8738e6)  # later calculations see the same amount
    assert fmt_calc("multiply", calculate("multiply", [Quantity(302578, "currency", "USD", "thousands")], factor=0.001)) == (
        "$302.58 million"
    )
    # real arithmetic keeps its label, and a conversion with nowhere to go keeps the amount as printed
    assert fmt_calc("multiply", calculate("multiply", [Quantity(700, "currency", "USD", "millions")], factor=0.25)) == (
        "$175 million"
    )
    assert fmt_calc("multiply", calculate("multiply", [Quantity(5, "currency", "USD", "billions")], factor=0.001)) == "$5 billion"


def test_small_ratios_keep_a_third_decimal():
    assert fmt_quantity(Quantity(0.0142, "ratio")) == "0.014x"
    assert fmt_quantity(Quantity(0.8258, "ratio")) == "0.826x"
    assert fmt_quantity(Quantity(2.419, "ratio")) == "2.42x"


def test_results_follow_the_rounding_the_question_asks_for():
    assert requested_decimals("Round your answer to two decimal places.") == 2
    assert requested_decimals("Answer in units of percents and round to one decimal place") == 1
    assert requested_decimals("What was revenue?") is None
    assert fmt_calc("ratio", Quantity(0.8258, "ratio"), 2) == "0.83x"
    assert fmt_calc("cagr", Quantity(0.447, "percent"), 1) == "0.4%"
    assert fmt_calc("change", Quantity(3.14, "other"), 1) == "3.1 percentage points"

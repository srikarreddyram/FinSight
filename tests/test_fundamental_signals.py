import math

import pytest

from signals import fundamentals, valuation
from tests.test_accounting_signals import IMPROVING, Stub

CO = {**IMPROVING, "equity": [400, 350, 360], "capex": [30, 25, 20]}


def test_growth_margins_and_changes():
    f = fundamentals.compute(Stub(CO))
    assert f["revenue_growth"] == pytest.approx(1000 / 900 - 1)
    assert f["revenue_growth_chg"] == pytest.approx((1000 / 900 - 1) - (900 / 850 - 1))
    assert f["gross_margin"] == pytest.approx(0.45)
    assert f["gross_margin_chg"] == pytest.approx(0.45 - 0.40)
    assert f["operating_margin"] == pytest.approx(0.15)
    assert f["net_margin_chg"] == pytest.approx(0.08 - 50 / 900)


def test_returns_use_average_equity_and_beginning_assets():
    f = fundamentals.compute(Stub(CO))
    assert f["roe"] == pytest.approx(80 / 375)
    assert f["roe_chg"] == pytest.approx(80 / 375 - 50 / 355)
    assert f["roa"] == pytest.approx(80 / 1000)
    assert f["leverage"] == pytest.approx(700 / 1100)
    assert f["debt_to_equity"] == pytest.approx(250 / 400)


def test_negative_equity_gives_no_roe_rather_than_a_misleading_one():
    f = fundamentals.compute(Stub({**CO, "equity": [-50, -40, 10]}))
    assert math.isnan(f["roe"]) and math.isnan(f["debt_to_equity"])


def test_valuation_yields():
    v = valuation.compute(Stub(CO), mcap=2000.0)
    assert v == pytest.approx(
        {"earnings_yield": 80 / 2000, "book_to_market": 400 / 2000, "fcf_yield": (120 - 30) / 2000, "sales_to_price": 1000 / 2000}
    )
    assert all(math.isnan(x) for x in valuation.compute(Stub(CO), mcap=None).values())


def test_split_between_cover_date_and_as_of_is_carried_into_market_cap():
    from datetime import date

    from signals.base import split_factor
    from warehouse import db

    con = db.connect(":memory:")
    # 2,000 -> 100 on a 20-for-1 split day (+1% that day); a 1% dividend-like gap elsewhere is not a split.
    rows = [
        ("AMZN", date(2022, 6, 2), 2000.0, 0.0),
        ("AMZN", date(2022, 6, 3), 1960.0, -0.01),
        ("AMZN", date(2022, 6, 6), 1960.0 * 1.01 / 20, 0.01),
        ("AMZN", date(2022, 6, 7), 99.0, 0.0),
    ]
    con.executemany("insert into prices values (?, ?, ?, ?, 0, 'test')", rows)
    assert split_factor(con, "AMZN", date(2022, 4, 20), date(2022, 6, 30)) == pytest.approx(20, rel=0.02)
    assert split_factor(con, "AMZN", date(2022, 6, 6), date(2022, 6, 30)) == 1.0

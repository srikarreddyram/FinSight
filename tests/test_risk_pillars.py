import math
from datetime import date

import pytest

from risk.pillars import CAP_COVERAGE, CAP_LEVERAGE, disclosure_event_features, going_concern, health_quality, material_weakness
from tests.test_accounting_signals import IMPROVING, Stub
from warehouse import db

CO = {**IMPROVING, "cash": [100], "short_term_debt": [50], "depreciation": [40], "interest_expense": [15],
      "inventory": [120], "dividends": [25, 40], "net_income": [80, 50, 40, 30, 20],
      "assets": [1100, 1000, 1000, 900, 800]}  # fmt: skip


def test_health_measures_by_hand():
    h = health_quality(Stub(CO))
    assert h["net_debt_to_ebitda"] == pytest.approx((250 + 50 - 100) / (150 + 40))
    assert h["interest_coverage"] == pytest.approx(150 / 15)
    assert h["current_ratio"] == pytest.approx(500 / 300)
    assert h["quick_ratio"] == pytest.approx((500 - 120) / 300)
    assert h["cash_burn"] == 0.0  # operating cash flow is positive
    assert h["dividend_cut"] == 1.0  # 25 < 75% of 40
    assert h["earnings_vol"] == pytest.approx(
        __import__("statistics").stdev([80 / 1100, 50 / 1000, 40 / 1000, 30 / 900, 20 / 800])
    )


def test_loss_makers_get_the_worst_bucket_and_debt_free_firms_full_coverage():
    h = health_quality(Stub({**CO, "operating_income": [-50], "depreciation": [10], "cfo": [-40]}))
    assert h["net_debt_to_ebitda"] == CAP_LEVERAGE
    assert h["cash_burn"] == pytest.approx(40 / 100)
    free = health_quality(Stub({**CO, "long_term_debt": [0], "short_term_debt": [0], "interest_expense": [None]}))
    assert free["interest_coverage"] == CAP_COVERAGE


def test_going_concern_and_material_weakness_respect_hedges_and_negation():
    assert going_concern("These conditions raise substantial doubt about our ability to continue as a going concern.")
    assert not going_concern("A downturn could raise substantial doubt about our ability to continue as a going concern.")
    assert material_weakness("Management identified a material weakness in internal control related to revenue.")
    assert material_weakness("Management concluded that internal control over financial reporting was not effective.")
    assert not material_weakness("We did not identify any material weakness. Our controls were effective.")
    assert not material_weakness("The material weakness reported last year has been remediated.")


def test_event_counts_are_point_in_time():
    con = db.connect(":memory:")
    con.executemany("insert into filing_index values (5, ?, ?, ?, ?)", [
        ("e1", "8-K", date(2019, 5, 1), "4.01,9.01"), ("e2", "NT 10-K", date(2020, 3, 2), None),
        ("e3", "8-K", date(2020, 3, 10), "4.02"), ("e4", "10-K/A", date(2018, 1, 1), None)])  # fmt: skip
    f, _ = disclosure_event_features(con, 5, date(2020, 3, 10))  # e3 filed that day: public tomorrow
    assert (f["late_filings_12m"], f["auditor_change_24m"], f["non_reliance_24m"], f["amended_10k_12m"]) == (1, 1, 0, 0)
    assert math.isnan(f["going_concern"])  # no 10-K text
    f, _ = disclosure_event_features(con, 5, date(2020, 3, 11))
    assert f["non_reliance_24m"] == 1

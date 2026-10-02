import math
from datetime import date

import pytest

from signals import accounting
from warehouse import db, xbrl

# An improving company: every Piotroski test passes. Values in $ millions; year offset 0 = FY2019.
IMPROVING = {
    "assets": [1100, 1000, 1000],
    "net_income": [80, 50, 40],
    "cfo": [120, 60, 50],
    "long_term_debt": [250, 300, 300],
    "current_assets": [500, 400, 380],
    "current_liabilities": [300, 300, 300],
    "shares_diluted": [98, 100, 100],
    "revenue": [1000, 900, 850],
    "gross_profit": [450, 360, 340],
    "retained_earnings": [500, 430, 380],
    "operating_income": [150, 110, 100],
    "liabilities": [700, 650, 640],
}


class Stub(accounting.Inputs):
    def __init__(self, values):
        self.values, self.used = values, []

    def get(self, item, year):
        v = self.values.get(item)
        return None if v is None or year >= len(v) or v[year] is None else float(v[year])


def test_piotroski_all_nine_tests_pass():
    assert accounting.piotroski(Stub(IMPROVING)) == (9.0, 9)


def test_piotroski_dilution_costs_a_point_and_missing_inputs_give_nan():
    diluted = {**IMPROVING, "shares_diluted": [110, 100, 100]}
    assert accounting.piotroski(Stub(diluted)) == (8.0, 9)
    bank = {k: v for k, v in IMPROVING.items() if k not in ("current_assets", "current_liabilities")}
    score, n = accounting.piotroski(Stub(bank))
    assert math.isnan(score) and n == 8


def test_piotroski_uses_revenue_minus_cogs_when_gross_profit_is_not_tagged():
    no_gp = {k: v for k, v in IMPROVING.items() if k != "gross_profit"}
    no_gp["cogs"] = [550, 540, 510]
    assert accounting.piotroski(Stub(no_gp)) == (9.0, 9)


def test_accruals_ratio():
    assert accounting.accruals(Stub(IMPROVING)) == pytest.approx((80 - 120) / 1050)


def test_altman_z():
    z = accounting.altman_z(Stub(IMPROVING), market_cap=1960.0)
    want = 1.2 * 200 / 1100 + 1.4 * 500 / 1100 + 3.3 * 150 / 1100 + 0.6 * 1960 / 700 + 1.0 * 1000 / 1100
    assert z == pytest.approx(want)
    assert math.isnan(accounting.altman_z(Stub(IMPROVING), market_cap=None))


def test_beneish_constant_company_scores_the_intercept_plus_accruals():
    flat = {k: [v[0], v[0]] for k, v in IMPROVING.items()}
    flat.update(receivables=[100, 100], ppe_net=[300, 300], depreciation=[40, 40], sga=[200, 200])
    tata = (80 - 120) / 1100
    assert accounting.beneish_m(Stub(flat)) == pytest.approx(-2.48 + 4.679 * tata)


def test_end_to_end_from_the_warehouse_is_point_in_time():
    con = db.connect(":memory:")
    items = {
        "Assets": "assets", "NetIncomeLoss": "net_income", "NetCashProvidedByUsedInOperatingActivities": "cfo",
        "LongTermDebtNoncurrent": "long_term_debt", "AssetsCurrent": "current_assets",
        "LiabilitiesCurrent": "current_liabilities", "WeightedAverageNumberOfDilutedSharesOutstanding": "shares_diluted",
        "Revenues": "revenue", "GrossProfit": "gross_profit",
    }  # fmt: skip
    stocks = {"Assets", "LongTermDebtNoncurrent", "AssetsCurrent", "LiabilitiesCurrent"}
    facts = []
    for offset, fy in enumerate((2019, 2018, 2017)):
        for concept, item in items.items():
            unit = "shares" if concept.startswith("Weighted") else "USD"
            start = None if concept in stocks else date(fy, 1, 1)
            facts.append(
                xbrl.Fact(9, "us-gaap", concept, unit, float(IMPROVING[item][offset]), start, date(fy, 12, 31),
                          date(fy + 1, 2, 20), f"A{fy}", "10-K", fy, "FY")
            )  # fmt: skip
    xbrl.insert_facts(con, facts)
    feats, info = accounting.accounting_features(con, 9, date(2020, 3, 31))
    assert feats["f_score"] == 9.0 and info == date(2020, 2, 21)
    # Before the FY2019 10-K: the newest year is FY2018, and FY2016 assets were never filed.
    feats, info = accounting.accounting_features(con, 9, date(2019, 12, 31))
    assert math.isnan(feats["f_score"]) and info == date(2019, 2, 21)


def test_trailing_twelve_month_figures_in_10qs_do_not_create_fiscal_years():
    from warehouse.fundamentals import Snapshot

    con = db.connect(":memory:")
    facts = [
        xbrl.Fact(5, "us-gaap", "NetIncomeLoss", "USD", 10.0, date(2018, 1, 1), date(2018, 12, 31), date(2019, 2, 1), "K18", "10-K"),
        xbrl.Fact(5, "us-gaap", "NetIncomeLoss", "USD", 12.0, date(2018, 7, 1), date(2019, 6, 30), date(2019, 7, 25), "Q19", "10-Q"),
    ]  # fmt: skip
    xbrl.insert_facts(con, facts)
    assert Snapshot(con, 5, date(2019, 9, 30)).fiscal_year_ends == [date(2018, 12, 31)]


def test_ebit_falls_back_to_pretax_plus_interest():
    x = Stub({"pretax_income": [120], "interest_expense": [30]})
    assert x.ebit(0) == 150
    assert Stub({"operating_income": [140], "pretax_income": [120]}).ebit(0) == 140


def test_a_reorganised_company_keeps_its_predecessors_history():
    from warehouse.fundamentals import Snapshot

    con = db.connect(":memory:")
    ni = lambda cik, fy, v, filed, accn: xbrl.Fact(cik, "us-gaap", "NetIncomeLoss", "USD", v, date(fy, 1, 1),  # noqa: E731
                                                  date(fy, 12, 31), filed, accn, "10-K", fy, "FY")  # fmt: skip
    xbrl.insert_facts(con, [ni(1, 2016, 10.0, date(2017, 2, 1), "OLD16"), ni(1, 2017, 11.0, date(2018, 2, 1), "OLD17")])
    # The successor's first 10-K re-reports FY2017 (restated) alongside FY2018.
    xbrl.insert_facts(con, [ni(2, 2017, 11.5, date(2019, 2, 1), "NEW18"), ni(2, 2018, 13.0, date(2019, 2, 1), "NEW18")])
    con.execute("insert into cik_links values (2, 1, '2018-04-04')")
    snap = Snapshot(con, 2, date(2019, 3, 1))
    assert [v.value for v in snap.annual("net_income", 3)] == [13.0, 11.5, 10.0]
    assert [v.value for v in Snapshot(con, 2, date(2018, 3, 1)).annual("net_income", 2)] == [11.0, 10.0]


def test_zero_total_assets_gives_missing_tests_not_a_crash():
    zero = {**IMPROVING, "assets": [0, 1000, 1000]}
    score, n = accounting.piotroski(Stub(zero))
    assert math.isnan(score) and n < 9
    assert math.isnan(accounting.accruals(Stub({**IMPROVING, "assets": [0, 0, 0]})))

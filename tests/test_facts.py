"""The Copilot's facts source: a company's standard financials from XBRL, as the 10-K it asks about reported them."""

from datetime import date

from app.answer import finalize, to_citation
from app.facts import fiscal_year, sources, table
from app.schemas import Company, ParsedQuery
from warehouse import db, xbrl

CIK = 66740
MMM = Company(ticker="MMM", name="3M", fiscal_year_end_month=12)


def _fact(concept, value, end, filed, accn, start=None):
    return xbrl.Fact(
        cik=CIK, taxonomy="us-gaap", concept=concept, unit="USD", value=value, period_start=start, period_end=end,
        filed_at=filed, accn=accn, form="10-K", fy=end.year, fp="FY",
    )  # fmt: skip


def _warehouse():
    con = db.connect(":memory:")
    fy18, fy17 = (date(2018, 1, 1), date(2018, 12, 31)), (date(2017, 1, 1), date(2017, 12, 31))
    xbrl.insert_facts(
        con,
        [
            _fact("Revenues", 32_765e6, fy18[1], date(2019, 2, 7), "K18", fy18[0]),
            _fact("Revenues", 31_657e6, fy17[1], date(2019, 2, 7), "K18", fy17[0]),
            _fact("PaymentsToAcquirePropertyPlantAndEquipment", 1_577e6, fy18[1], date(2019, 2, 7), "K18", fy18[0]),
            _fact("AccountsPayableCurrent", 2_266e6, fy18[1], date(2019, 2, 7), "K18"),
            _fact("NetIncomeLoss", -5_349e6, fy18[1], date(2019, 2, 7), "K18", fy18[0]),
            # restated a year later: the FY2018 10-K printed the original
            _fact("Revenues", 32_700e6, fy18[1], date(2020, 2, 6), "K19", fy18[0]),
        ],
    )
    con.execute("insert into companies (cik, ticker, name) values (?, 'MMM', '3M')", [CIK])
    return con


def test_52_53_week_years_belong_to_the_year_they_nearly_end():
    assert fiscal_year(date(2023, 1, 1), 12) == 2022  # Johnson & Johnson's FY2022
    assert fiscal_year(date(2018, 1, 31), 1) == 2018  # Walmart's FY2018
    assert fiscal_year(date(2018, 5, 31), 5) == 2018


def test_the_table_shows_figures_as_that_10k_printed_them():
    text = table(_warehouse(), MMM, CIK, 2018)
    assert text.startswith("3M (MMM) standard financials from the XBRL data of its FY2018 10-K, filed Feb 7, 2019")
    assert "| Line item | FY2018 (Dec 31, 2018) | FY2017 (Dec 31, 2017) |" in text
    assert "| Total revenue / net sales | 32,765 | 31,657 |" in text  # not the later restatement
    assert "| Purchases of property, plant and equipment (capex) | 1,577 | – |" in text
    assert "| Accounts payable | 2,266 | – |" in text
    assert "-5,349" in text
    assert table(_warehouse(), MMM, CIK, 2016) is None  # no 10-K for that year


def test_sources_cover_named_companies_and_skip_quarterly_questions():
    pq = ParsedQuery(question="q", tickers=["MMM"], fiscal_years={"MMM": [2018]})
    [hit] = sources(pq, "What was 3M's FY2018 capex?", {"MMM": MMM}, {("MMM", 2018): "3M_2018_10K"}, _warehouse())
    assert hit.chunk.chunk_type == "facts" and hit.chunk.doc_id == "3M_2018_10K"
    assert sources(pq, "What was 3M's Q2 FY2018 capex?", {"MMM": MMM}, {}, _warehouse()) == []
    assert sources(ParsedQuery(question="q", tickers=["MMM"]), "capex?", {"MMM": MMM}, {}, _warehouse()) == []

    # a figure copied from the facts verifies like any table's, and cites the XBRL data
    raw = {
        "answerable": True,
        "figures": [
            {
                "name": "capex",
                "value": 1577,
                "unit": "currency",
                "currency": "USD",
                "scale": "millions",
                "period": "FY2018",
                "source_id": "S1",
                "quote": "capex",
            }  # fmt: skip
        ],
        "calculations": [],
        "answer": "3M's capex was {fig:capex} [S1].",
        "table": {"columns": [], "rows": []},
        "missing": [],
    }
    ans = finalize("q", raw, [hit])
    assert ans.answer == "3M's capex was $1,577 million [3M FY18 XBRL]." and ans.figures[0].verified
    assert to_citation(0, hit).snippet.startswith("3M (MMM) standard financials")

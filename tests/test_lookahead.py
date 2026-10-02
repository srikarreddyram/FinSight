"""Point-in-time guarantees for the warehouse (docs/phase-a-warehouse.md). Written before any feature code:
if one of these fails, every backtest built on the warehouse is suspect."""

import random
from datetime import date, timedelta

from warehouse import db, pit, xbrl

CIK = 66740  # 3M


def _fact(concept, value, end, filed, accn, start=None, form="10-K", fy=2018, fp="FY", unit="USD"):
    return xbrl.Fact(
        cik=CIK,
        taxonomy="us-gaap",
        concept=concept,
        unit=unit,
        value=value,
        period_start=start,
        period_end=end,
        filed_at=filed,
        accn=accn,
        form=form,
        fy=fy,
        fp=fp,
    )


def _warehouse(facts):
    con = db.connect(":memory:")
    xbrl.insert_facts(con, facts)
    return con


def test_facts_are_invisible_until_the_day_after_filing():
    con = _warehouse([_fact("Revenues", 32_765e6, date(2018, 12, 31), date(2019, 2, 7), "A1", start=date(2018, 1, 1))])
    assert pit.facts_asof(con, date(2019, 2, 6)) == []
    assert pit.facts_asof(con, date(2019, 2, 7)) == []  # filed after the close counts as not yet tradeable
    [row] = pit.facts_asof(con, date(2019, 2, 8))
    assert row["value"] == 32_765e6


def test_restatement_is_a_new_row_and_never_leaks_backwards():
    original = _fact("NetIncomeLoss", 5_349e6, date(2018, 12, 31), date(2019, 2, 7), "A1", start=date(2018, 1, 1))
    restated = _fact("NetIncomeLoss", 5_300e6, date(2018, 12, 31), date(2020, 2, 6), "A2", start=date(2018, 1, 1), fy=2019)
    con = _warehouse([original, restated])
    assert con.execute("select count(*) from facts").fetchone()[0] == 2  # nothing overwritten
    assert [r["value"] for r in pit.facts_asof(con, date(2019, 6, 30))] == [5_349e6]
    assert [r["value"] for r in pit.facts_asof(con, date(2020, 6, 30))] == [5_300e6]
    assert [r["value"] for r in pit.first_reported(con)] == [5_349e6]


def test_no_query_ever_returns_a_fact_before_it_was_available():
    rng = random.Random(7)
    facts = []
    for i in range(300):
        end = date(2010, 12, 31) + timedelta(days=rng.randrange(0, 12 * 365))
        filed = end + timedelta(days=rng.randrange(20, 400))
        facts.append(_fact(rng.choice(["Revenues", "Assets", "NetIncomeLoss"]), float(i), end, filed, f"A{i}"))
    con = _warehouse(facts)
    for _ in range(200):
        t = date(2010, 1, 1) + timedelta(days=rng.randrange(0, 15 * 365))
        for row in pit.facts_asof(con, t):
            assert row["filed_at"] < t, f"fact filed {row['filed_at']} used on {t}"


def test_one_value_per_period_as_of_any_date():
    con = _warehouse(
        [
            _fact("Assets", 36_500e6, date(2018, 12, 31), date(2019, 2, 7), "A1"),
            _fact("Assets", 36_500e6, date(2018, 12, 31), date(2020, 2, 6), "A2", fy=2019),  # repeated as a comparative
            _fact("Assets", 44_659e6, date(2019, 12, 31), date(2020, 2, 6), "A2", fy=2019),
        ]
    )
    rows = pit.facts_asof(con, date(2020, 3, 1), concepts=["Assets"])
    assert sorted((r["period_end"], r["value"]) for r in rows) == [
        (date(2018, 12, 31), 36_500e6),
        (date(2019, 12, 31), 44_659e6),
    ]


def test_latest_value_picks_the_newest_period_known_at_the_time():
    con = _warehouse(
        [
            _fact("Assets", 36_500e6, date(2018, 12, 31), date(2019, 2, 7), "A1"),
            _fact("Assets", 44_659e6, date(2019, 12, 31), date(2020, 2, 6), "A2", fy=2019),
        ]
    )
    assert pit.latest_value(con, CIK, "Assets", date(2019, 12, 31)) == 36_500e6  # FY19 not public yet
    assert pit.latest_value(con, CIK, "Assets", date(2020, 3, 1)) == 44_659e6
    assert pit.latest_value(con, CIK, "Assets", date(2019, 1, 1)) is None


def test_companyfacts_parser_keeps_every_filing_of_a_period():
    doc = {
        "cik": CIK,
        "entityName": "3M COMPANY",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            {
                                "start": "2018-01-01",
                                "end": "2018-12-31",
                                "val": 32765000000,
                                "accn": "0000066740-19-000010",
                                "fy": 2018,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2019-02-07",
                            },
                            {
                                "start": "2018-01-01",
                                "end": "2018-12-31",
                                "val": 32765000000,
                                "accn": "0000066740-20-000010",
                                "fy": 2019,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2020-02-06",
                            },
                        ]
                    }
                },
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "end": "2018-12-31",
                                "val": 36500000000,
                                "accn": "0000066740-19-000010",
                                "fy": 2018,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2019-02-07",
                            }
                        ]
                    }
                },
            }
        },
    }
    facts = xbrl.parse_companyfacts(doc)
    assert len(facts) == 3
    assets = next(f for f in facts if f.concept == "Assets")
    assert assets.period_start is None and assets.period_end == date(2018, 12, 31)  # balance-sheet instant
    assert {f.filed_at for f in facts if f.concept == "Revenues"} == {date(2019, 2, 7), date(2020, 2, 6)}

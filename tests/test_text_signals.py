import math
from datetime import date

import pytest

from signals import text
from warehouse import db

RF_OLD = "Competition may hurt our margins. Supply chains can fail. " * 60
RF_NEW = RF_OLD + "A cyberattack could disrupt operations and expose customer data. " * 60
MDA = "Revenue increased because customers bought more products. " * 30 + "\nTotal 1,234 5,678\n"


def _con():
    con = db.connect(":memory:")
    for accn, filed, rf in (("K1", date(2020, 2, 20), RF_OLD), ("K2", date(2021, 2, 18), RF_NEW)):
        con.execute("insert into filings (accn, cik, form, filed_at) values (?, 7, '10-K', ?)", [accn, filed])
        con.executemany(
            "insert into filing_text values (?, 7, ?, ?, ?, ?)",
            [(accn, "1A", "Risk Factors", rf, len(rf.split())), (accn, "7", "MD&A", MDA, len(MDA.split()))],
        )
    text._section.cache_clear()
    return con


def test_features_use_only_10ks_public_on_the_date():
    con = _con()
    f, info = text.text_features(con, 7, date(2021, 2, 18))  # K2 filed that day: public from the 19th
    assert info == date(2020, 2, 21) and math.isnan(f["sim_risk_factors"])  # no earlier 10-K to compare with
    f, info = text.text_features(con, 7, date(2021, 2, 19))
    assert info == date(2021, 2, 19)
    assert f["sim_mda"] == pytest.approx(1.0)
    assert 0.5 < f["sim_risk_factors"] < 0.9  # half the section is new
    assert f["risk_factors_words_chg"] == pytest.approx(math.log(len(text.words(RF_NEW)) / len(text.words(RF_OLD))))
    assert math.isnan(text.text_features(con, 7, date(2019, 12, 31))[0]["fog_mda"])


def test_fog_by_hand_ignores_table_rows():
    # 7 words per sentence; complex words (3+ syllables): "revenue", "customers" -> 2 of 7.
    assert text.fog(MDA) == pytest.approx(0.4 * (7 + 100 * 2 / 7))


def test_syllables():
    assert [text.syllables(w) for w in ("the", "make", "revenue", "operations", "table", "increased", "reported", "losses")] == [
        1,
        1,
        3,
        4,
        2,
        2,
        3,
        2,
    ]

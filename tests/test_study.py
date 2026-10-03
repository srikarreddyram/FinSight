import random
from datetime import date

import pandas as pd
import pytest

from models.ranks import add_ranks
from models.study import quantile_spread, study


def _panel():
    rng = random.Random(7)
    rows = []
    for year in range(2015, 2021):
        for month in range(1, 13):
            for i in range(50):
                good, noise = rng.random(), rng.random()
                rows.append(
                    {
                        "month": date(year, month, 28),
                        "sector": "A" if i % 2 else "B",
                        "good": good,
                        "noise": noise,
                        "excess_ret": 0.2 * good + rng.gauss(0, 0.1),
                    }
                )
    return add_ranks(pd.DataFrame(rows), ["good", "noise"])


def test_study_separates_a_real_signal_from_noise():
    res = study(_panel(), ["good", "noise"])
    assert res.index[0] == "good"
    assert res.loc["good", "ic_raw"] > 0.4 and res.loc["good", "years_pos_raw"] == "6/6"
    assert res.loc["good", "ic_sector"] > 0.4
    assert abs(res.loc["noise", "ic_raw"]) < 0.05 and abs(res.loc["noise", "t_raw"]) < 3
    # Top fifth by `good` averages ~0.18 excess return, bottom fifth ~0.02.
    assert res.loc["good", "spread_raw"] == pytest.approx(0.16, abs=0.02)


def test_quantile_spread_by_hand():
    p = pd.DataFrame({"month": [date(2020, 1, 31)] * 5, "s": [1, 2, 3, 4, 5], "excess_ret": [0.0, 0.1, 0.2, 0.3, 0.5]})
    assert quantile_spread(p, "s") == pytest.approx(0.5 - 0.0)
    assert quantile_spread(p, "s", q=0.4) == pytest.approx((0.3 + 0.5) / 2 - (0.0 + 0.1) / 2)


def test_tier_is_the_index_a_company_was_in_that_month():
    from models.study import _is_member, _stays, tier
    from warehouse import db

    con = db.connect(":memory:")
    rows = [
        (1, "UP", "Mover", date(2020, 1, 1), date(2022, 6, 20), "wikipedia", "sp600"),  # small cap, then promoted
        (1, "UP", "Mover", date(2022, 6, 20), None, "wikipedia", "sp400"),
        (2, "BIG", "Large", None, None, "wikipedia", "sp500"),
    ]
    con.executemany(
        "insert into universe (cik, ticker, name, start_date, end_date, source, index_name) values (?,?,?,?,?,?,?)", rows
    )
    stays = _stays(con, "sp1500")
    assert tier(stays, 1, date(2019, 12, 31)) is None  # before the 600's history: not a member
    assert tier(stays, 1, date(2021, 3, 31)) == "sp600"
    assert tier(stays, 1, date(2022, 6, 30)) == "sp400"
    assert tier(stays, 2, date(2011, 1, 31)) == "sp500"
    large_only = _stays(con, "sp500")
    assert not _is_member(large_only, 1, date(2023, 1, 31)) and _is_member(large_only, 2, date(2023, 1, 31))

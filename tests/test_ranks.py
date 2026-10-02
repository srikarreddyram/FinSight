from datetime import date

import numpy as np
import pandas as pd
import pytest

from models.ranks import add_ranks
from warehouse.sectors import sector


def test_ranks_are_within_month_centred_and_skip_missing():
    m1, m2 = date(2020, 1, 31), date(2020, 2, 29)
    p = pd.DataFrame(
        {
            "month": [m1, m1, m1, m1, m2, m2],
            "sector": ["Utilities", "Utilities", "Information Technology", "Information Technology", "Utilities", None],
            "lev": [0.9, 0.7, 0.2, np.nan, 5.0, 1.0],
        }
    )
    r = add_ranks(p, ["lev"])
    assert r["lev_rank"].tolist()[:3] == pytest.approx([2.5 / 3, 1.5 / 3, 0.5 / 3])
    assert np.isnan(r["lev_rank"][3])
    # Within sector: the high-leverage utility is top of its peers; the lone tech value sits at 0.5.
    assert r["lev_srank"].tolist()[:3] == pytest.approx([0.75, 0.25, 0.5])
    assert r["lev_rank"].tolist()[4:] == pytest.approx([0.75, 0.25])  # months never mix


def test_sic_to_sector_exceptions_come_before_broad_ranges():
    assert sector(2834) == "Health Care"  # pharma, inside the 2800s chemicals range
    assert sector(2860) == "Materials"
    assert sector(5331) == "Consumer Staples"  # Walmart, Costco; other retail is discretionary
    assert sector(5961) == "Consumer Discretionary"
    assert sector(7372) == "Information Technology"
    assert sector(6021) == "Financials" and sector(6798) == "Real Estate"
    assert sector(4941) == "Utilities" and sector(4953) == "Industrials"
    assert sector(3812) == "Industrials" and sector(3825) == "Information Technology"
    assert sector(None) is None and sector(9999) is None

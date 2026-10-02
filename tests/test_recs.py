import numpy as np
import pandas as pd

from recs.build import decile, drivers, ordinal
from recs.labels import base, fmt


def test_labels_and_formats():
    assert base("leverage_chg_srank") == ("leverage_chg", "sector")
    assert base("vol_12m_r") == ("vol_12m", "market") and base("vol_12m") == ("vol_12m", "market")
    assert fmt("leverage_chg", 0.042) == "+4.2 pts" and fmt("roe", 0.153) == "15.3%" and fmt("book_to_market", 0.5) == "0.50×"
    assert fmt("going_concern", 1.0) == "yes" and fmt("roe", float("nan")) is None
    assert [ordinal(n) for n in (1, 2, 3, 11, 12, 22, 87)] == ["1st", "2nd", "3rd", "11th", "12th", "22nd", "87th"]


def test_deciles_are_within_month():
    s = pd.Series(list(range(20)) + list(range(100, 110)))
    m = pd.Series([1] * 20 + [2] * 10)
    d = decile(s, m)
    assert d[:20].tolist() == [i // 2 for i in range(20)] and d[20:].tolist() == list(range(10))


def test_drivers_merge_variants_and_skip_events_that_did_not_happen():
    feats = ["roe_rank", "roe_srank", "leverage_chg_rank", "material_weakness_r", "late_filings_12m_r", "going_concern_r",
             "dividend_cut_r"]  # fmt: skip
    row = pd.Series({"roe": 0.25, "roe_rank": 0.9, "roe_srank": 0.8, "leverage_chg": 0.04, "leverage_chg_rank": 0.95,
                     "material_weakness": 0.0, "material_weakness_r": 0.4, "late_filings_12m": 0.0, "late_filings_12m_r": 0.4,
                     "going_concern": 1.0, "going_concern_r": 0.99, "dividend_cut": 0.0, "dividend_cut_r": 0.5})  # fmt: skip
    d = drivers(row, feats, np.array([0.2, 0.3, -0.4, 0.9, 0.8, 0.1, -0.7]), "raises", "lowers")
    assert [x["signal"] for x in d] == ["roe", "leverage_chg", "going_concern"]  # the three non-events are skipped
    assert d[0]["scope"] == "sector" and d[0]["effect"] == "raises"  # 0.2 + 0.3, led by the sector version
    assert d[0]["text"] == "Return on equity is 25.0%, 80th percentile of its sector"
    assert d[1]["effect"] == "lowers" and d[2]["text"] == "Going-concern doubt in the 10-K: yes"

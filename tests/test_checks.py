from datetime import date

import numpy as np
import pandas as pd

from models.checks import neutralise, unscored, yearly_t
from models.walkforward import rank_ic_by_month


def test_neutralising_removes_a_style_tilt_and_keeps_the_rest():
    rng = np.random.default_rng(3)
    rows = []
    for y in range(2016, 2020):
        for m in range(1, 13):
            size, skill, noise = rng.normal(size=200), rng.normal(size=200), rng.normal(size=200)
            ret = 0.5 * size + skill + rng.normal(size=200)  # bigger stocks did better that year: a style return
            for i in range(200):
                rows.append({"month": date(y, m, 28), "size": size[i], "pred": size[i] + 0.3 * noise[i], "pred2": skill[i],
                             "excess_ret": ret[i]})  # fmt: skip
    df = pd.DataFrame(rows)
    df["pred_n"] = neutralise(df, "pred", ["size"])
    df["pred2_n"] = neutralise(df, "pred2", ["size"])
    assert rank_ic_by_month(df, "pred", "excess_ret").mean() > 0.3  # looks skilful: it only bought big stocks
    assert abs(rank_ic_by_month(df, "pred_n", "excess_ret").mean()) < 0.05
    assert rank_ic_by_month(df, "pred2_n", "excess_ret").mean() > 0.5  # real skill survives


def test_yearly_t_and_unscored_share():
    ic = pd.Series([0.1, 0.0, 0.02, 0.06], index=[date(2016, 1, 31), date(2016, 2, 29), date(2017, 1, 31), date(2018, 1, 31)])
    mean, t, years = yearly_t(ic)  # monthly mean 0.045; t from the yearly means 0.05, 0.02, 0.06
    assert round(mean, 3) == 0.045 and years == 3 and round(t, 1) == 3.6
    panel = pd.DataFrame({"month": [date(2016, 1, 31)] * 4, "target_end": ["2017-02-28"] * 3 + ["2030-01-31"],
                          "excess_ret": [0.1, np.nan, 0.2, np.nan], "tier": "sp400"})  # fmt: skip
    assert unscored(panel, date(2026, 10, 1)).loc[2016, "sp400"] == 1 / 3  # the open window doesn't count

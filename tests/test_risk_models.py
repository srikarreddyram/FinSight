import random
from datetime import date

import numpy as np
import pandas as pd
import pytest

from models import panel as panel_mod
from risk import models
from risk.panel import MEASURES

pytest.importorskip("lightgbm")


def test_auc_by_hand():
    assert models.auc(np.array([0, 0, 1, 1.0]), np.array([0.1, 0.2, 0.3, 0.4])) == 1.0
    assert models.auc(np.array([0, 1, 0, 1.0]), np.array([0.1, 0.2, 0.3, 0.4])) == pytest.approx(0.75)
    assert np.isnan(models.auc(np.array([0, 0.0]), np.array([0.1, 0.2])))


def test_scorecard_follows_each_measures_risk_direction():
    p = pd.DataFrame({"month": [1, 1], **{m: [0.0, 0.0] for m in MEASURES}})
    p.loc[1, "vol_12m"], p.loc[1, "altman_z"] = 0.5, -3.0  # stock 1: more volatile, lower Z = riskier
    s = models.scorecard(p)
    assert s[1] > s[0]


def test_grades_are_monthly_quintiles_and_change_rate_counts_consecutive_months_only():
    months = [date(2020, 1, 31), date(2020, 2, 29), date(2020, 4, 30)]
    rows = [
        {"ticker": f"S{i}", "month": m, "pred_vol": i + 0.1 * k, "pred_downside": i}
        for k, m in enumerate(months)
        for i in range(10)
    ]
    r = pd.DataFrame(rows)
    r["grade"] = models.grades(r)
    assert r.groupby("month")["grade"].value_counts().unique().tolist() == [2]  # 2 stocks in each of 5 grades
    assert r.loc[(r["ticker"] == "S9"), "grade"].unique().tolist() == [5]
    r.loc[(r["ticker"] == "S0") & (r["month"] == months[2]), "grade"] = 3  # April follows a gap: not counted
    assert models.grade_change_rate(r) == 0.0


def test_walk_forward_learns_volatility_and_downside_without_peeking():
    rng = random.Random(3)
    rows = []
    for m in panel_mod.month_ends(date(2010, 1, 1), date(2018, 12, 31)):
        for i in range(80):
            risk = rng.random()
            row = {m_: rng.random() for m_ in MEASURES}
            row |= {"ticker": f"S{i}", "month": m, "sector": "A", "vol_12m": 0.1 + 0.4 * risk + rng.gauss(0, 0.05),
                    "altman_z": 3 - 2 * risk, "target_end": panel_mod.add_months(m, 12)}  # fmt: skip
            row["fwd_vol"] = max(0.05, 0.1 + 0.4 * risk + rng.gauss(0, 0.05))
            row["severe"] = float(rng.random() < 0.02 + 0.3 * risk**3)
            rows.append(row)
    r = models.walk_forward(pd.DataFrame(rows), first_test_year=2016, last_test_year=2018)
    assert set(r["year"]) == {2016, 2017, 2018}
    out = models.report(r)
    assert out["overall"].loc["vol_ic_model", "value"] > 0.5
    assert out["overall"].loc["auc_model", "value"] > 0.65
    cal = out["calibration"]
    assert cal["realised_vol"].is_monotonic_increasing and cal.loc["Severe", "severe_rate"] > cal.loc["Low", "severe_rate"]

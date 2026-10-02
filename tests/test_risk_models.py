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
    r["grade"] = models.grades(r, smooth=1)
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
    o = out["overall"]["value"]
    assert o["vol_ic_final"] > 0.5 and o["auc_final"] > 0.65
    # The blend is chosen with trailing volatility as a candidate, so what the grade uses is never far below it.
    assert o["vol_ic_final"] >= o["vol_ic_trailing"] - 0.02
    assert set(r["weight_vol"].unique()) <= set(models.WEIGHTS) | {models.DEFAULT_WEIGHT}
    assert out["stability"].loc[3, "grade_change_rate"] < out["stability"].loc[1, "grade_change_rate"]
    cal = out["calibration"]
    assert cal["realised_vol"].is_monotonic_increasing and cal.loc["Severe", "severe_rate"] > cal.loc["Low", "severe_rate"]


def test_blend_weights_run_from_the_model_alone_to_trailing_volatility_alone():
    df = pd.DataFrame({"month": [1, 1, 1, 1], "vol_12m": [0.4, 0.3, 0.2, np.nan]})
    pred = np.array([1.0, 2.0, 3.0, 4.0])  # the model ranks them the other way round
    assert models.blend(df, pred, 1.0).tolist() == [0.25, 0.5, 0.75, 1.0]
    b = models.blend(df, pred, 0.0)
    assert b[:3].tolist() == pytest.approx([1.0, 2 / 3, 1 / 3]) and b[3] == 1.0  # no price history: the model's rank
    assert models.blend(df, pred, 0.5)[1] == pytest.approx((0.5 + 2 / 3) / 2)


def test_smoothing_uses_only_past_months():
    months = [date(2020, m, 28) for m in (1, 2, 3)]
    rows = [{"ticker": f"S{i}", "month": m, "pred_vol": float(i), "pred_downside": float(i)} for m in months for i in range(10)]
    r = pd.DataFrame(rows)
    jump = (r["ticker"] == "S0") & (r["month"] == months[2])
    r.loc[jump, ["pred_vol", "pred_downside"]] = 99.0  # S0 turns riskiest in March
    unsmoothed, smoothed = models.grades(r, smooth=1), models.grades(r, smooth=3)
    assert unsmoothed[jump].item() == 5 and smoothed[jump].item() < 5  # the jump is damped
    feb = (r["ticker"] == "S0") & (r["month"] == months[1])
    assert smoothed[feb].item() == unsmoothed[feb].item() == 1  # February's grade doesn't know about March

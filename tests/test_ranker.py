import random
from datetime import date

import pandas as pd
import pytest

from models import panel as panel_mod
from models.ranker import ic_table, labels, walk_forward

pytest.importorskip("lightgbm")


def _panel(seed=1):
    """60 stocks a month, 2010-2019. The target depends on an interaction the linear model can't see."""
    rng = random.Random(seed)
    rows = []
    for m in panel_mod.month_ends(date(2010, 1, 1), date(2019, 12, 31)):
        start = panel_mod.add_months(m, 1)
        for i in range(60):
            a, b = rng.random(), rng.random()
            signal = a if b > 0.5 else 1 - a
            rows.append(
                {"month": m, "ticker": f"S{i}", "target_start": start, "target_end": panel_mod.add_months(start, 12),
                 "a_rank": a, "b_rank": b, "f_score_rank": rng.random(), "excess_ret": signal + rng.gauss(0, 0.3)}
            )  # fmt: skip
    return pd.DataFrame(rows)


def test_labels_are_within_month_quintiles():
    df = pd.DataFrame({"month": [1] * 10 + [2] * 5, "excess_ret": list(range(10)) + [5, 4, 3, 2, 1]})
    assert labels(df).tolist() == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 4, 3, 2, 1, 0]


def test_sector_labels_rank_within_each_sector():
    df = pd.DataFrame({"month": [1] * 4, "sector": ["A", "A", "B", "B"], "excess_ret": [0.1, 0.2, 0.5, 0.9]})
    assert labels(df, by="sector").tolist() == [0, 2, 0, 2]  # B's worst is still bottom of B
    assert labels(df).tolist() == [0, 1, 2, 3]


def test_feature_selection_uses_only_the_rows_it_is_given():
    from models.ranker import select

    p = _panel()
    p["noise_rank"] = p["f_score_rank"]
    p["leak_rank"] = p["excess_ret"].where(p["month"] >= date(2015, 1, 1))  # informative only in the future
    early = p[p["month"] < date(2014, 1, 1)]
    assert "leak_rank" not in select(early, ["a_rank", "b_rank", "noise_rank", "leak_rank"], 2)


def test_folds_train_only_on_labels_that_ended_before_the_test_year():
    preds, reports = walk_forward(_panel(), ["a_rank", "b_rank"], first_test_year=2015)
    assert [r.year for r in reports] == [2015, 2016, 2017, 2018, 2019]
    for r in reports:
        assert r.last_train_target_end < date(r.year, 1, 1)
    # Tuning needs 24 purged months before the validation years: early folds fall back to the default settings.
    assert [r.val_ic is not None for r in reports] == [False, False, True, True, True]
    assert set(preds["year"]) == {2015, 2016, 2017, 2018, 2019}
    assert all(m.year == y for m, y in zip(preds["month"], preds["year"], strict=True))


def test_lgbm_finds_the_interaction_and_baselines_behave():
    preds, _ = walk_forward(_panel(), ["a_rank", "b_rank"], first_test_year=2015)
    t = ic_table(preds)
    assert t.loc["lgbm", "mean"] > 0.3
    assert abs(t.loc["linear", "mean"]) < 0.1  # no linear signal by construction
    assert abs(t.loc["random", "mean"]) < 0.05 and abs(t.loc["fscore", "mean"]) < 0.05
    assert abs(t.loc["best_signal", "mean"]) < 0.1  # neither a nor b alone predicts: only their interaction does

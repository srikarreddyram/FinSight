"""Risk Engine models and grades (platform PRD, Module 7).

    uv run python -m risk.models          # needs data/study/sp500/risk_panel.parquet (uv run python -m risk.panel)

Two components, each walk-forward with the Signal Lab's purged folds (purged on the 12-month risk window) and
tuning inside each fold's training window only:

- Volatility: LightGBM regression on log realised 12-month volatility. Baselines: trailing volatility alone
  (strong, because volatility persists) and the scorecard. Metric: monthly rank IC with realised volatility.
- Downside: LightGBM classifier, class-weighted, for a drawdown of 40% or worse within 12 months. Baselines:
  the scorecard, Altman Z alone, trailing volatility. Metrics: AUC, and the severe-loss rate in the riskiest 10%.

Grade: each month, both predicted components are ranked within the universe, the ranks averaged and cut into
quintiles, 1 (Low) to 5 (Severe). Validated by the calibration table (realised volatility and severe-loss rate
by grade), by year, by sector, and by how often grades change month to month.
"""

from __future__ import annotations

import argparse
import logging
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from models import THREADS
from models.panel import add_months
from models.walkforward import folds, rank_ic_by_month
from risk.panel import DIRECTION, MEASURES, PILLARS, STUDY

log = logging.getLogger(__name__)

VAL_YEARS = 2
MIN_INNER_MONTHS = 24
BASE = {"subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8, "random_state": 0, "n_jobs": THREADS, "verbose": -1}
GRID = [
    {"num_leaves": 15, "min_child_samples": 50, "learning_rate": 0.05, "n_estimators": 200},
    {"num_leaves": 31, "min_child_samples": 100, "learning_rate": 0.05, "n_estimators": 300},
    {"num_leaves": 7, "min_child_samples": 200, "learning_rate": 0.03, "n_estimators": 400},
]
GRADES = {1: "Low", 2: "Moderate", 3: "Elevated", 4: "High", 5: "Severe"}
RANKED = [f"{m}_r" for m in MEASURES]
# Chosen per fold on validation, never on test years: the grade only ranks stocks within a month, so market-wide
# swings in level (calm 2017 vs 2020) may be noise for it. Iteration 2, added after the first test-year results
# (which used raw features and absolute targets only) had been seen.
FEATURE_SETS = {"raw": MEASURES, "rank": RANKED}
VOL_TARGETS = ("abs", "rel")  # log fwd_vol, or log fwd_vol minus that month's median


def scorecard(p: pd.DataFrame) -> pd.Series:
    """Each measure ranked within the month in its risk direction, averaged within its pillar, pillars averaged.
    Higher = riskier."""
    pillar_scores = []
    for measures in PILLARS.values():
        ranks = pd.concat([(p[m] * DIRECTION[m]).groupby(p["month"]).rank(pct=True) for m in measures], axis=1)
        pillar_scores.append(ranks.mean(axis=1))
    return pd.concat(pillar_scores, axis=1).mean(axis=1)


def auc(y: np.ndarray, score: np.ndarray) -> float:
    """Probability a random severe case scores above a random non-severe one (Mann-Whitney)."""
    ok = ~(np.isnan(y) | np.isnan(score))
    y, score = y[ok], score[ok]
    pos = y == 1
    n1, n0 = pos.sum(), (~pos).sum()
    if n1 == 0 or n0 == 0:
        return np.nan
    r = pd.Series(score).rank().to_numpy()
    return float((r[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def top_decile_rate(df: pd.DataFrame, score: str, target: str = "severe") -> float:
    """Severe-loss rate among each month's riskiest 10% by `score`, averaged over months."""

    def rate(g):
        g = g.dropna(subset=[score, target])
        k = max(1, len(g) // 10)
        return g.nlargest(k, score)[target].mean() if len(g) else np.nan

    return float(df.groupby("month")[[score, target]].apply(rate).mean())


def _vol_target(df: pd.DataFrame, variant: str) -> pd.Series:
    y = np.log(df["fwd_vol"])
    return y - y.groupby(df["month"]).transform("median") if variant == "rel" else y


def _fit(train: pd.DataFrame, target: str, params: dict, kind: str, features: list[str] = MEASURES, variant: str = "abs"):
    import lightgbm as lgb

    params = {**BASE, **params}
    rounds = params.pop("n_estimators")
    y = _vol_target(train, variant) if kind == "vol" else train[target]
    if kind == "vol":
        params |= {"objective": "regression"}
    else:
        pos = float(y.sum())
        params |= {"objective": "binary", "scale_pos_weight": (len(y) - pos) / max(pos, 1.0)}
    return lgb.train(params, lgb.Dataset(train[features], y), num_boost_round=rounds)


def monthly_auc(df: pd.DataFrame, score: str, target: str = "severe") -> float:
    """AUC within each month, averaged: how well the score sorts stocks against each other, which is all a
    within-month grade needs (pooled AUC also rewards guessing which years will be bad)."""
    per = df.groupby("month")[[score, target]].apply(lambda g: auc(g[target].to_numpy(), g[score].to_numpy()))
    return float(per.mean())


def _score(df: pd.DataFrame, pred: np.ndarray, kind: str) -> float:
    if kind == "vol":
        return float(rank_ic_by_month(df.assign(pred=pred), "pred", "fwd_vol").mean())
    return monthly_auc(df.assign(pred=pred), "pred")


def tune(train: pd.DataFrame, target: str, kind: str) -> tuple[tuple, float | None]:
    """(grid params, feature set, target variant) by validation score on the last VAL_YEARS, purged."""
    default = (GRID[0], "raw", "abs")
    val_start = date(max(m.year for m in train["month"]) - VAL_YEARS + 1, 1, 1)
    inner, val = train[train["target_end"] < val_start], train[train["month"] >= val_start]
    if inner["month"].nunique() < MIN_INNER_MONTHS or val.empty:
        return default, None
    options = [(g, f, v) for g in GRID for f in FEATURE_SETS for v in (VOL_TARGETS if kind == "vol" else ("abs",))]
    scores = [
        _score(val, _fit(inner, target, g, kind, FEATURE_SETS[f], v).predict(val[FEATURE_SETS[f]]), kind) for g, f, v in options
    ]
    best = int(np.nanargmax(scores))
    return options[best], scores[best]


def prepare(p: pd.DataFrame) -> pd.DataFrame:
    """Adds the scorecard and each measure's within-month rank (`<measure>_r`)."""
    p = p.reset_index(drop=True)
    p["scorecard"] = scorecard(p)
    for m in MEASURES:
        p[f"{m}_r"] = p.groupby("month")[m].rank(pct=True)
    return p


def walk_forward(p: pd.DataFrame, first_test_year: int, last_test_year: int) -> pd.DataFrame:
    p = prepare(p)
    out = []
    for fold in folds(p, first_test_year, last_test_year):
        train, test = p.loc[fold.train], p.loc[fold.test]
        if train["month"].nunique() < MIN_INNER_MONTHS:
            continue
        res = test[["ticker", "month", "sector", "fwd_vol", "severe", "vol_12m", "altman_z", "scorecard"]].copy()
        res["year"] = fold.year
        for kind, target in (("vol", "fwd_vol"), ("downside", "severe")):
            tr = train.dropna(subset=[target])
            (params, fset, variant), val = tune(tr, target, kind)
            feats = FEATURE_SETS[fset]
            pred = _fit(tr, target, params, kind, feats, variant).predict(test[feats])
            # A "rel" volatility prediction is relative to the month's median: fine for ranking within a month.
            res[f"pred_{kind}"] = np.exp(pred) if kind == "vol" else pred
            log.info("%d %s: %d rows, %s, %s features, %s target, validation %s",
                     fold.year, kind, len(tr), params, fset, variant, None if val is None else round(val, 3))  # fmt: skip
        out.append(res)
    return pd.concat(out, ignore_index=True)


def grades(r: pd.DataFrame) -> pd.Series:
    """Average of the two components' within-month ranks, cut into quintiles: 1 (Low) to 5 (Severe)."""
    v = r.groupby("month")["pred_vol"].rank(pct=True)
    d = r.groupby("month")["pred_downside"].rank(pct=True)
    combined = (v + d) / 2
    return combined.groupby(r["month"]).transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) + 1)


def grade_change_rate(r: pd.DataFrame) -> float:
    """Share of stock-months whose grade differs from the same stock's grade the month before (consecutive
    month-ends only: a company that leaves the index and returns isn't counted across the gap)."""
    s = r.sort_values(["ticker", "month"])
    prev_grade = s.groupby("ticker")["grade"].shift()
    prev_month = s.groupby("ticker")["month"].shift()
    consecutive = prev_month.notna() & (prev_month == s["month"].map(lambda m: add_months(m, -1)))
    return float((s["grade"] != prev_grade)[consecutive].mean())


def report(r: pd.DataFrame) -> dict[str, pd.DataFrame]:
    r = r.copy()
    r["grade"] = grades(r)
    r["neg_altman_z"] = -r["altman_z"]
    vol = r.dropna(subset=["fwd_vol"])
    down = r.dropna(subset=["severe"])
    by_year = pd.DataFrame({
        "vol_ic_model": vol.groupby("year").apply(lambda g: rank_ic_by_month(g, "pred_vol", "fwd_vol").mean()),
        "vol_ic_trailing": vol.groupby("year").apply(lambda g: rank_ic_by_month(g, "vol_12m", "fwd_vol").mean()),
        "vol_ic_scorecard": vol.groupby("year").apply(lambda g: rank_ic_by_month(g, "scorecard", "fwd_vol").mean()),
        "severe_rate": down.groupby("year")["severe"].mean(),
        "auc_model": down.groupby("year").apply(lambda g: auc(g["severe"].to_numpy(), g["pred_downside"].to_numpy())),
        "auc_scorecard": down.groupby("year").apply(lambda g: auc(g["severe"].to_numpy(), g["scorecard"].to_numpy())),
        "auc_altman_z": down.groupby("year").apply(lambda g: auc(g["severe"].to_numpy(), g["neg_altman_z"].to_numpy())),
        "auc_trailing_vol": down.groupby("year").apply(lambda g: auc(g["severe"].to_numpy(), g["vol_12m"].to_numpy())),
        "mauc_model": down.groupby("year").apply(lambda g: monthly_auc(g, "pred_downside")),
        "mauc_trailing_vol": down.groupby("year").apply(lambda g: monthly_auc(g, "vol_12m")),
    })  # fmt: skip
    overall = pd.Series({
        "vol_ic_model": rank_ic_by_month(vol, "pred_vol", "fwd_vol").mean(),
        "vol_ic_trailing": rank_ic_by_month(vol, "vol_12m", "fwd_vol").mean(),
        "vol_ic_scorecard": rank_ic_by_month(vol, "scorecard", "fwd_vol").mean(),
        "auc_model": auc(down["severe"].to_numpy(), down["pred_downside"].to_numpy()),
        "auc_scorecard": auc(down["severe"].to_numpy(), down["scorecard"].to_numpy()),
        "auc_altman_z": auc(down["severe"].to_numpy(), down["neg_altman_z"].to_numpy()),
        "auc_trailing_vol": auc(down["severe"].to_numpy(), down["vol_12m"].to_numpy()),
        "monthly_auc_model": monthly_auc(down, "pred_downside"),
        "monthly_auc_scorecard": monthly_auc(down, "scorecard"),
        "monthly_auc_altman_z": monthly_auc(down, "neg_altman_z"),
        "monthly_auc_trailing_vol": monthly_auc(down, "vol_12m"),
        "top10_severe_model": top_decile_rate(down, "pred_downside"),
        "top10_severe_trailing_vol": top_decile_rate(down, "vol_12m"),
        "top10_severe_scorecard": top_decile_rate(down, "scorecard"),
        "base_severe_rate": down["severe"].mean(),
    }, name="value").to_frame()  # fmt: skip
    calibration = (
        r.groupby("grade")
        .agg(n=("ticker", "size"), realised_vol=("fwd_vol", "mean"), severe_rate=("severe", "mean"))
        .rename(index=GRADES)
    )
    sector = down.assign(grade=r["grade"]).groupby("sector").apply(
        lambda g: pd.Series({"n": len(g), "severe_rate": g["severe"].mean(),
                             "auc_model": auc(g["severe"].to_numpy(), g["pred_downside"].to_numpy())})
    )  # fmt: skip
    stability = pd.Series({"monthly_grade_change_rate": grade_change_rate(r)}, name="value").to_frame()
    return {"overall": overall, "by_year": by_year, "calibration": calibration, "by_sector": sector, "stability": stability}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--panel", default=STUDY / "risk_panel.parquet", type=Path)
    ap.add_argument("--first-test-year", default=2015, type=int)
    ap.add_argument("--last-test-year", default=2024, type=int, help="2025 is the PRD's holdout")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = pd.read_parquet(args.panel)
    for c in ("month", "target_end"):
        p[c] = pd.to_datetime(p[c]).dt.date
    r = walk_forward(p, args.first_test_year, args.last_test_year)
    r.to_parquet(args.panel.parent / "risk_predictions.parquet")
    with pd.option_context("display.width", 220, "display.float_format", "{:.3f}".format, "display.max_columns", 20):
        for name, t in report(r).items():
            print(f"\n## {name}\n{t}")


if __name__ == "__main__":
    main()

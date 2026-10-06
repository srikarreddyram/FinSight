"""Risk Engine models and grades (platform PRD, Module 7).

    uv run python -m risk.models          # needs the study's risk_panel.parquet (uv run python -m risk.panel)

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
# Iteration 3, also added after test-year results had been seen: the model did not beat trailing volatility, so
# each fold now also chooses, on validation, how much weight the model gets in a blend of the two within-month
# ranks. 0 is trailing volatility alone, so the grade's inputs can never be chosen to do worse than the baseline.
WEIGHTS = (1.0, 0.75, 0.5, 0.25, 0.0)
DEFAULT_WEIGHT = 0.5  # folds too short to validate: an even blend
SMOOTH = 3  # months of the combined rank averaged before grading (past months only); 1 = no smoothing


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


def blend(df: pd.DataFrame, pred: np.ndarray, weight: float) -> pd.Series:
    """weight × the model's within-month rank + (1 − weight) × trailing volatility's. A stock without a year of
    price history has no trailing volatility and keeps the model's rank."""
    model = pd.Series(pred, index=df.index).groupby(df["month"]).rank(pct=True)
    base = df["vol_12m"].groupby(df["month"]).rank(pct=True).fillna(model)
    return weight * model + (1 - weight) * base


def tune(train: pd.DataFrame, target: str, kind: str) -> tuple[tuple, float | None]:
    """(grid params, feature set, target variant, blend weight) by validation score on the last VAL_YEARS,
    purged. The model's configuration is chosen first, then its weight against trailing volatility."""
    default = (GRID[0], "raw", "abs", DEFAULT_WEIGHT)
    val_start = date(max(m.year for m in train["month"]) - VAL_YEARS + 1, 1, 1)
    inner, val = train[train["target_end"] < val_start], train[train["month"] >= val_start]
    if inner["month"].nunique() < MIN_INNER_MONTHS or val.empty:
        return default, None
    options = [(g, f, v) for g in GRID for f in FEATURE_SETS for v in (VOL_TARGETS if kind == "vol" else ("abs",))]
    preds = [_fit(inner, target, g, kind, FEATURE_SETS[f], v).predict(val[FEATURE_SETS[f]]) for g, f, v in options]
    best = int(np.nanargmax([_score(val, p, kind) for p in preds]))
    by_weight = [_score(val, blend(val, preds[best], w).to_numpy(), kind) for w in WEIGHTS]
    w = int(np.nanargmax(by_weight))
    return (*options[best], WEIGHTS[w]), by_weight[w]


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
        keep = ("ticker", "month", "sector", "tier", "fwd_vol", "severe", "vol_12m", "altman_z", "scorecard")
        res = test[[c for c in keep if c in test]].copy()
        res["year"] = fold.year
        for kind, target in (("vol", "fwd_vol"), ("downside", "severe")):
            tr = train.dropna(subset=[target])
            (params, fset, variant, weight), val = tune(tr, target, kind)
            feats = FEATURE_SETS[fset]
            pred = _fit(tr, target, params, kind, feats, variant).predict(test[feats])
            res[f"model_{kind}"] = pred  # the model alone, for comparison against the baselines
            res[f"pred_{kind}"] = blend(test, pred, weight)  # what the grade uses: a within-month rank, 0 to 1
            res[f"weight_{kind}"] = weight
            log.info("%d %s: %d rows, %s, %s features, %s target, model weight %.2f, validation %s",
                     fold.year, kind, len(tr), params, fset, variant, weight, None if val is None else round(val, 3))  # fmt: skip
        out.append(res)
    return pd.concat(out, ignore_index=True)


def grades(r: pd.DataFrame, smooth: int = SMOOTH) -> pd.Series:
    """Average of the two components' within-month ranks, cut into quintiles: 1 (Low) to 5 (Severe). With
    smooth > 1 the combined rank is first averaged over the stock's latest `smooth` months (this one and
    earlier ones only), which steadies grades without using anything from the future."""
    v = r.groupby("month")["pred_vol"].rank(pct=True)
    d = r.groupby("month")["pred_downside"].rank(pct=True)
    combined = (v + d) / 2
    if smooth > 1:
        order = r.assign(combined=combined).sort_values(["ticker", "month"])
        combined = (
            order.groupby("ticker")["combined"].transform(lambda s: s.rolling(smooth, min_periods=1).mean()).reindex(r.index)
        )
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
    """Validation tables. "final" is what the grade uses (the model blended with trailing volatility at the
    weight each fold chose); "model" is the model alone; the rest are baselines."""
    r = r.copy()
    r["grade"] = grades(r)
    r["neg_altman_z"] = -r["altman_z"]
    vol = r.dropna(subset=["fwd_vol"])
    down = r.dropna(subset=["severe"])
    vol_scores = {"final": "pred_vol", "model": "model_vol", "trailing": "vol_12m", "scorecard": "scorecard"}
    down_scores = {"final": "pred_downside", "model": "model_downside", "trailing_vol": "vol_12m",
                   "scorecard": "scorecard", "altman_z": "neg_altman_z"}  # fmt: skip

    def ic(g, col):
        return rank_ic_by_month(g, col, "fwd_vol").mean()

    by_year = pd.DataFrame(
        {f"vol_ic_{k}": vol.groupby("year").apply(lambda g, c=c: ic(g, c)) for k, c in vol_scores.items()}
        | {"severe_rate": down.groupby("year")["severe"].mean()}
        | {f"mauc_{k}": down.groupby("year").apply(lambda g, c=c: monthly_auc(g, c)) for k, c in down_scores.items()}
        | {"weight_vol": r.groupby("year")["weight_vol"].first(), "weight_downside": r.groupby("year")["weight_downside"].first()}
    )
    overall = pd.Series(
        {f"vol_ic_{k}": ic(vol, c) for k, c in vol_scores.items()}
        | {f"monthly_auc_{k}": monthly_auc(down, c) for k, c in down_scores.items()}
        | {f"auc_{k}": auc(down["severe"].to_numpy(), down[c].to_numpy()) for k, c in down_scores.items()}
        | {f"top10_severe_{k}": top_decile_rate(down, c) for k, c in down_scores.items() if k != "altman_z"}
        | {"base_severe_rate": down["severe"].mean()},
        name="value",
    ).to_frame()
    calibration = (
        r.groupby("grade")
        .agg(n=("ticker", "size"), realised_vol=("fwd_vol", "mean"), severe_rate=("severe", "mean"))
        .rename(index=GRADES)
    )
    sector = down.groupby("sector").apply(
        lambda g: pd.Series({"n": len(g), "severe_rate": g["severe"].mean(),
                             "auc_final": auc(g["severe"].to_numpy(), g["pred_downside"].to_numpy()),
                             "auc_trailing_vol": auc(g["severe"].to_numpy(), g["vol_12m"].to_numpy())})
    )  # fmt: skip
    # Steadier grades against calibration: how often grades change, and how far apart the end grades' outcomes sit.
    rows = {}
    for months in (1, 3, 6):
        g = r.assign(grade=grades(r, smooth=months))
        by = g.groupby("grade").agg(vol=("fwd_vol", "mean"), severe=("severe", "mean"))
        rows[months] = {"grade_change_rate": grade_change_rate(g), "severe_rate_low": by.loc[1, "severe"],
                        "severe_rate_severe": by.loc[5, "severe"], "vol_low": by.loc[1, "vol"], "vol_severe": by.loc[5, "vol"]}  # fmt: skip
    stability = pd.DataFrame(rows).T.rename_axis("smoothing_months")
    out = {"overall": overall, "by_year": by_year, "calibration": calibration, "by_sector": sector, "stability": stability}
    if "tier" in r and r["tier"].nunique() > 1:  # the same scores judged inside one index at a time
        out["by_tier"] = pd.DataFrame({
            t: {"n": len(g), "severe_rate": g["severe"].mean(), "median_fwd_vol": g["fwd_vol"].median(),
                "vol_ic_final": ic(g.dropna(subset=["fwd_vol"]), "pred_vol"),
                "vol_ic_trailing": ic(g.dropna(subset=["fwd_vol"]), "vol_12m"),
                "monthly_auc_final": monthly_auc(g.dropna(subset=["severe"]), "pred_downside"),
                "monthly_auc_trailing_vol": monthly_auc(g.dropna(subset=["severe"]), "vol_12m"),
                "share_graded_severe": (g["grade"] == 5).mean()}
            for t, g in r.groupby("tier")
        }).T  # fmt: skip
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--panel", default=STUDY / "risk_panel.parquet", type=Path)
    ap.add_argument("--first-test-year", default=2015, type=int)
    ap.add_argument("--last-test-year", default=2024, type=int, help="2025 is the PRD's holdout")
    ap.add_argument(
        "--out", type=Path, help="where to write the predictions (default: risk_predictions.parquet beside the panel)"
    )
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = pd.read_parquet(args.panel)
    for c in ("month", "target_end"):
        p[c] = pd.to_datetime(p[c]).dt.date
    r = walk_forward(p, args.first_test_year, args.last_test_year)
    r.to_parquet(args.out or args.panel.parent / "risk_predictions.parquet")
    with pd.option_context("display.width", 220, "display.float_format", "{:.3f}".format, "display.max_columns", 20):
        for name, t in report(r).items():
            print(f"\n## {name}\n{t}")


if __name__ == "__main__":
    main()

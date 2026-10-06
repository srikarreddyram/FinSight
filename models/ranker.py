"""Return ranker (platform PRD, Module 5): LightGBM LambdaRank on the monthly signal ranks, walk-forward.

    uv run python -m models.ranker                    # on the study panel (build it with models.study)
    uv run python -m models.ranker --first-test-year 2015

Each month is one ranking query; the label is the stock's quintile of 12-month excess return, within the month
or within its sector that month. Every fold chooses its whole configuration inside its own training window: tree
settings, how many signals to keep (the top 5 or 10 by rank IC on the training rows, or all), and which label.
The last VAL_YEARS of training months are the validation set, and inner-training rows whose label window
reaches the validation period are purged, exactly as the outer folds purge against the test year; feature
selection on the inner rows only. The chosen configuration is refit on the whole training window (selection
redone there) and used once on the test year. The procedure was fixed before the test years were looked at
again, so the test years measure the procedure, not a choice made by looking at them.

Baselines, scored the same way: the best single signal on the training rows (sign included), the Piotroski
F-score alone, a ridge regression on all signals, and random ranks (which should score ~0).
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from models import STUDY_DIR, THREADS
from models.walkforward import folds, rank_ic_by_month

log = logging.getLogger(__name__)

LABELS = 5  # within-month quintiles
VAL_YEARS = 2
MIN_INNER_MONTHS = 24
BASE = {
    "objective": "lambdarank",
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "random_state": 0,
    "n_jobs": THREADS,
    "verbose": -1,
}
GRID = [
    {"num_leaves": 7, "min_child_samples": 20, "learning_rate": 0.05, "n_estimators": 150},
    {"num_leaves": 15, "min_child_samples": 40, "learning_rate": 0.05, "n_estimators": 150},
    {"num_leaves": 7, "min_child_samples": 80, "learning_rate": 0.03, "n_estimators": 300},
]
TOP_K = (5, 10, None)  # None = every signal
TARGETS = ("market", "sector")


@dataclass(frozen=True)
class Config:
    params: tuple  # GRID entry as sorted items (hashable)
    top_k: int | None
    target: str

    @property
    def grid(self) -> dict:
        return dict(self.params)


CONFIGS = [Config(tuple(sorted(g.items())), k, t) for g in GRID for k in TOP_K for t in TARGETS]
DEFAULT = Config(tuple(sorted(GRID[0].items())), None, "market")


@dataclass
class FoldReport:
    year: int
    train_rows: int
    last_train_target_end: date
    config: Config
    features: list[str]
    val_ic: float | None


def labels(df: pd.DataFrame, target: str = "excess_ret", by: str = "market") -> pd.Series:
    """Quintile of the target within the month ("market") or within the month and sector ("sector"),
    0 (worst) to LABELS - 1 (best)."""
    sector = df["sector"].fillna("Unknown") if "sector" in df else pd.Series("All", index=df.index)
    keys = ["month"] if by == "market" else ["month", sector]
    g = df.groupby(keys)[target]
    below = g.rank(method="first") - 1  # stocks ranked below this one
    return (below / g.transform("count") * LABELS).astype(int)


def feature_ics(df: pd.DataFrame, features: list[str], target: str = "excess_ret") -> pd.Series:
    """Mean monthly rank IC of each feature on these rows."""
    ranked = df.groupby("month")[[*features, target]].rank()
    ranked["month"] = df["month"].to_numpy()
    per_month = ranked.groupby("month").apply(lambda g: g[features].corrwith(g[target]))
    return per_month.mean()


def select(df: pd.DataFrame, features: list[str], k: int | None) -> list[str]:
    if k is None or k >= len(features):
        return features
    return list(feature_ics(df, features).abs().sort_values(ascending=False).index[:k])


def _fit_lgbm(train: pd.DataFrame, features: list[str], params: dict, by: str = "market"):
    import lightgbm as lgb

    train = train.sort_values("month")
    params = {**BASE, **params}
    rounds = params.pop("n_estimators")
    data = lgb.Dataset(train[features], labels(train, by=by), group=train.groupby("month", sort=True).size().to_numpy())
    return lgb.train(params, data, num_boost_round=rounds)


def _ic(df: pd.DataFrame, pred: np.ndarray) -> float:
    return float(rank_ic_by_month(df.assign(pred=pred), "pred", "excess_ret").mean())


def tune(train: pd.DataFrame, features: list[str]) -> tuple[Config, float | None]:
    """Pick the configuration by validation IC on the last VAL_YEARS of the training window, purged."""
    val_start = date(max(m.year for m in train["month"]) - VAL_YEARS + 1, 1, 1)
    inner = train[train["target_end"] < val_start]
    val = train[train["month"] >= val_start]
    if inner["month"].nunique() < MIN_INNER_MONTHS or val.empty:
        return DEFAULT, None
    chosen = {k: select(inner, features, k) for k in TOP_K}  # selection sees inner-training rows only
    scores = []
    for c in CONFIGS:
        f = chosen[c.top_k]
        scores.append(_ic(val, _fit_lgbm(inner, f, c.grid, c.target).predict(val[f])))
    best = int(np.nanargmax(scores))
    return CONFIGS[best], scores[best]


def ridge(train: pd.DataFrame, test: pd.DataFrame, features: list[str], alpha: float = 10.0) -> np.ndarray:
    """Linear baseline: ridge on the ranks (missing = 0.5, the middle) against the within-month target rank."""
    x = train[features].fillna(0.5).to_numpy() - 0.5
    y = train.groupby("month")["excess_ret"].rank(pct=True).to_numpy() - 0.5
    w = np.linalg.solve(x.T @ x + alpha * np.eye(x.shape[1]), x.T @ y)
    return (test[features].fillna(0.5).to_numpy() - 0.5) @ w


def walk_forward(
    panel: pd.DataFrame, features: list[str], first_test_year: int, seed: int = 0, last_test_year: int | None = None
) -> tuple[pd.DataFrame, list[FoldReport]]:
    """Out-of-sample predictions for every test year, plus what each fold trained on and chose."""
    rng = np.random.default_rng(seed)
    panel = panel.dropna(subset=["excess_ret"]).reset_index(drop=True)
    preds, reports = [], []
    for fold in folds(panel, first_test_year, last_test_year):
        train, test = panel.loc[fold.train], panel.loc[fold.test]
        if train["month"].nunique() < MIN_INNER_MONTHS:
            continue
        config, val_ic = tune(train, features)
        chosen = select(train, features, config.top_k)
        model = _fit_lgbm(train, chosen, config.grid, config.target)
        out = test[[c for c in ("month", "ticker", "sector", "tier", "excess_ret") if c in test]].copy()
        out["year"] = fold.year
        out["pred_lgbm"] = model.predict(test[chosen])
        ics = feature_ics(train, features)
        best = ics.abs().idxmax()
        out["pred_best_signal"] = np.sign(ics[best]) * test[best].fillna(0.5).to_numpy()
        out["pred_linear"] = ridge(train, test, features)
        if "f_score_rank" in test:
            out["pred_fscore"] = test["f_score_rank"].to_numpy()
        out["pred_random"] = rng.random(len(test))
        preds.append(out)
        reports.append(FoldReport(fold.year, len(train), train["target_end"].max(), config, chosen, val_ic))
        log.info(
            "%d: %d rows; %s, top %s (%s), %s labels; validation IC %s; best single signal %s (%+.3f)",
            fold.year, len(train), config.grid, config.top_k, ", ".join(chosen[:5]) + ("..." if len(chosen) > 5 else ""),
            config.target, None if val_ic is None else round(val_ic, 3), best, ics[best],
        )  # fmt: skip
    return pd.concat(preds, ignore_index=True), reports


def ic_table(preds: pd.DataFrame) -> pd.DataFrame:
    models = [c for c in preds.columns if c.startswith("pred_")]
    rows = {
        m[len("pred_") :]: {y: float(rank_ic_by_month(g, m, "excess_ret").mean()) for y, g in preds.groupby("year")}
        for m in models
    }
    t = pd.DataFrame(rows).T
    t["mean"] = t.mean(axis=1)
    return t


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--panel", default=STUDY_DIR / "panel.parquet", type=Path)
    ap.add_argument("--first-test-year", default=2015, type=int)
    ap.add_argument(
        "--last-test-year", default=2024, type=int,
        help="the PRD holds out the most recent full year (2025) for one final run; pass 2025 only for that run",
    )  # fmt: skip
    ap.add_argument("--out", type=Path, help="where to write the predictions (default: predictions.parquet beside the panel)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = pd.read_parquet(args.panel)
    for c in ("month", "target_end"):
        p[c] = pd.to_datetime(p[c]).dt.date
    features = [c for c in p.columns if c.endswith(("_rank", "_srank")) and not c.startswith("f_score_tests")]
    preds, _ = walk_forward(p, features, args.first_test_year, last_test_year=args.last_test_year)
    preds.to_parquet(args.out or args.panel.parent / "predictions.parquet")
    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        print(ic_table(preds))
        if "tier" in preds and preds["tier"].nunique() > 1:
            for t, g in preds.groupby("tier"):
                print(f"\nWithin {t}:")
                print(ic_table(g))


if __name__ == "__main__":
    main()

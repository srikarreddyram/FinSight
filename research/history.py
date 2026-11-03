"""The time machine: the watchlist as FinSight would have shown it in a past month, from the walk-forward run
(each month scored by models trained only on earlier data), next to what happened over the following year.

Months run over the test years (2015-2024). Ranks are the return model's percentile within the month; grades
use the risk engine's own rule (risk.models.grades); the outcome is the stock's 12-month return against the
S&P 500 and whether it fell 40% or more."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from models import STUDY_DIR
from risk.models import grades


@lru_cache(maxsize=1)
def _table(study: Path = STUDY_DIR) -> pd.DataFrame:
    p = pd.read_parquet(study / "predictions.parquet", columns=["month", "ticker", "sector", "tier", "excess_ret", "pred_lgbm"])
    r = pd.read_parquet(
        study / "risk_predictions.parquet", columns=["month", "ticker", "pred_vol", "pred_downside", "severe", "fwd_vol"]
    )
    for df in (p, r):
        df["month"] = pd.to_datetime(df["month"]).dt.strftime("%Y-%m")
    r["grade"] = grades(r)
    p["rank"] = p.groupby("month")["pred_lgbm"].rank(pct=True) * 100
    return p.merge(r[["month", "ticker", "grade", "severe", "fwd_vol"]], on=["month", "ticker"], how="outer")


def months() -> list[str]:
    return sorted(_table()["month"].unique().tolist())


def as_of(month: str) -> dict | None:
    t = _table()
    m = t[t["month"] == month]
    if m.empty:
        return None
    rows = [
        {
            "ticker": r.ticker, "sector": r.sector if isinstance(r.sector, str) else None, "tier": r.tier if isinstance(r.tier, str) else None,
            "rank": None if pd.isna(r.rank) else round(float(r.rank), 1), "grade": None if pd.isna(r.grade) else int(r.grade),
            "next_12m": None if pd.isna(r.excess_ret) else round(float(r.excess_ret), 4),
            "severe": None if pd.isna(r.severe) else bool(r.severe),
        }
        for r in m.itertuples()
    ]  # fmt: skip
    by_grade = (
        m.dropna(subset=["grade"])
        .groupby("grade")
        .agg(n=("ticker", "size"), next_12m=("excess_ret", "median"), severe=("severe", "mean"))
    )
    by_grade = [{"grade": int(g), "n": int(x.n), "next_12m": None if pd.isna(x.next_12m) else float(x.next_12m),
                 "severe": None if pd.isna(x.severe) else float(x.severe)} for g, x in by_grade.iterrows()]  # fmt: skip
    return {"month": month, "rows": rows, "by_grade": by_grade}

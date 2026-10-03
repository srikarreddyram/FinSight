"""Robustness checks for the return ranker's walk-forward predictions.

    uv run python -m models.checks                    # on the study's predictions and risk panel

A ranker can score a positive IC without knowing anything about the companies, by leaning on a known return
pattern: smaller, more volatile or recently rising stocks did better in some years. This asks how much of the
ranker's IC is left once that is taken out, and how much of the universe could not be scored at all.

- exposures: each month's rank correlation between the prediction and size (traded dollar volume, a proxy that
  needs no share count), past-year volatility, past-year return and beta
- neutral IC: the IC of what is left of the prediction after regressing its rank on those four ranks (and the
  index a stock belongs to) within each month
- t-statistics on yearly mean ICs, overall and inside each index
- unscored rows: stock-months whose 12-month outcome window has closed but that have no return, mostly
  companies that were later acquired or went bankrupt (Yahoo keeps no price history for them)
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

from models import STUDY_DIR
from models.walkforward import rank_ic_by_month

log = logging.getLogger(__name__)

STYLE = ["log_dollar_volume", "vol_12m", "ret_12m", "beta"]


def neutralise(df: pd.DataFrame, pred: str, controls: list[str]) -> pd.Series:
    """Residual of the prediction's within-month rank after an OLS fit on the controls' ranks (missing = middle)
    and index dummies, month by month."""
    out = pd.Series(np.nan, index=df.index)
    for _, g in df.groupby("month"):
        y = g[pred].rank(pct=True)
        ok = y.notna()
        if ok.sum() < 20:
            continue
        x = [g[c].rank(pct=True).fillna(0.5) for c in controls]
        if "tier" in g and g["tier"].nunique() > 1:
            x += [(g["tier"] == t).astype(float) for t in sorted(g["tier"].dropna().unique())[1:]]
        x = np.column_stack([np.ones(len(g)), *x])[ok.to_numpy()]
        beta, *_ = np.linalg.lstsq(x, y[ok].to_numpy(), rcond=None)
        out.loc[y[ok].index] = y[ok].to_numpy() - x @ beta
    return out


def yearly_t(ic: pd.Series) -> tuple[float, float, int]:
    """Mean monthly IC, t-statistic on yearly means (monthly ICs of a 12-month outcome overlap), years."""
    yearly = ic.groupby([m.year for m in ic.index]).mean()
    t = yearly.mean() / yearly.std(ddof=1) * math.sqrt(len(yearly)) if len(yearly) > 2 else np.nan
    return float(ic.mean()), float(t), len(yearly)


def exposures(df: pd.DataFrame, pred: str) -> dict[str, float]:
    return {c: float(rank_ic_by_month(df, pred, c).mean()) for c in STYLE if c in df}


def ic_rows(df: pd.DataFrame, preds: list[str]) -> list[dict]:
    rows = []
    groups = [("all", df)] + ([(t, g) for t, g in df.groupby("tier")] if "tier" in df and df["tier"].nunique() > 1 else [])
    for name, g in groups:
        for p in preds:
            for kind, col in (("raw", p), ("neutral", f"{p}_neutral")):
                mean, t, years = yearly_t(rank_ic_by_month(g, col, "excess_ret"))
                rows.append(
                    {"universe": name, "model": p.removeprefix("pred_"), "kind": kind, "ic": mean, "t": t, "years": years}
                )
    return rows


def unscored(panel: pd.DataFrame, last_price_day) -> pd.DataFrame:
    """Share of stock-months with a closed outcome window but no return, by index and year."""
    closed = panel[pd.to_datetime(panel["target_end"]) <= pd.Timestamp(last_price_day)]
    key = closed["tier"] if "tier" in closed else pd.Series("all", index=closed.index)
    return closed["excess_ret"].isna().groupby([key, closed["month"].map(lambda m: m.year)]).mean().unstack(0)


def run(study: Path, first_test_year: int = 2015) -> dict:
    preds = pd.read_parquet(study / "predictions.parquet")
    risk = pd.read_parquet(study / "risk_panel.parquet", columns=["ticker", "month", *STYLE])
    panel = pd.read_parquet(
        study / "panel.parquet", columns=["ticker", "month", "target_end", "excess_ret", *(["tier"] if "tier" in preds else [])]
    )
    for d in (preds, risk, panel):
        d["month"] = pd.to_datetime(d["month"]).dt.date
    df = preds.merge(risk, on=["ticker", "month"], how="left")
    models = [p for p in ("pred_lgbm", "pred_linear", "pred_fscore") if p in df]
    for p in models:
        df[f"{p}_neutral"] = neutralise(df, p, STYLE)
    import duckdb

    from warehouse import db

    con = duckdb.connect(str(db.default_path()), read_only=True)
    last_day = con.execute("select max(day) from prices where ticker = 'SPY'").fetchone()[0]
    con.close()
    gaps = unscored(panel[pd.to_datetime(panel["month"]).dt.year >= first_test_year], last_day)
    return {
        "ic": ic_rows(df, models),
        "exposures": {p.removeprefix("pred_"): exposures(df, p) for p in models},
        "unscored_by_year": json.loads(gaps.reset_index(names="year").to_json(orient="records")),
        "unscored": {str(k): float(v) for k, v in gaps.mean().items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--study", default=STUDY_DIR, type=Path)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    res = run(args.study)
    (args.study / "checks.json").write_text(json.dumps(res, indent=1))
    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        print(pd.DataFrame(res["ic"]).pivot_table(index=["universe", "model"], columns="kind", values=["ic", "t"]))
        print("\nRank correlation of each prediction with style measures (mean over months):")
        print(pd.DataFrame(res["exposures"]).T)
        print("\nShare of stock-months with a closed outcome window but no return:")
        print(pd.DataFrame(res["unscored_by_year"]).set_index("year"))


if __name__ == "__main__":
    main()

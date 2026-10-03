"""Dashboard endpoints (platform PRD, Module 6), served from the files `recs.build` writes.

GET /recs/meta               as-of month, model details, bands
GET /recs/watchlist          this month's ranked universe with risk grades and drivers
GET /recs/company/{ticker}   one card plus its history: signal percentiles, past ranks vs outcomes, past grades
GET /recs/signals            IC and spread per signal, per year
GET /recs/backtest           monthly long-short series, per-year table, before and after costs
GET /recs/risk               calibration table, grade distribution, model vs baselines
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException

from models import STUDY_DIR
from recs.labels import SIGNALS
from risk import models as risk_models

router = APIRouter(prefix="/recs", tags=["recommendations"])

RECS_DIR = Path("data/recs")
# Shown on the company page by default: one or two per family, the ones a reader recognises.
HISTORY_SIGNALS = ["revenue_growth", "operating_margin", "roe", "leverage", "leverage_chg", "earnings_yield",
                   "book_to_market", "f_score", "accruals", "sim_risk_factors"]  # fmt: skip
NOT_BUILT = "The dashboard data is not built yet. Run `uv run python -m recs.build`."


def _mtime(path: Path) -> float:
    if not path.exists():
        raise HTTPException(503, NOT_BUILT)
    return path.stat().st_mtime


@lru_cache(maxsize=16)
def _json(path: Path, mtime: float):
    return json.loads(path.read_text())


def load(name: str):
    path = RECS_DIR / name
    return _json(path, _mtime(path))


@lru_cache(maxsize=4)
def _history(study_dir: Path, mtime: float) -> dict[str, pd.DataFrame]:
    """Per-ticker history frames, built once per data refresh."""
    panel = pd.read_parquet(study_dir / "panel.parquet")
    cols = [s for s in HISTORY_SIGNALS if f"{s}_rank" in panel]
    signals = panel[["ticker", "month", *cols, *[f"{s}_rank" for s in cols]]].copy()
    preds = pd.read_parquet(study_dir / "predictions.parquet")
    preds["return_rank"] = preds.groupby("month")["pred_lgbm"].rank(pct=True) * 100
    risk = pd.read_parquet(study_dir / "risk_predictions.parquet")
    risk["grade"] = risk_models.grades(risk)
    for df in (signals, preds, risk):
        df["month"] = pd.to_datetime(df["month"]).dt.strftime("%Y-%m-%d")
    return {
        "signals": signals,
        "returns": preds[["ticker", "month", "return_rank", "excess_ret"]],
        "risk": risk[["ticker", "month", "grade", "fwd_vol", "severe", "vol_12m"]],
    }


def _records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records"))  # NaN -> null


@router.get("/meta")
def meta() -> dict:
    return load("meta.json")


@router.get("/watchlist")
def watchlist() -> list[dict]:
    return load("watchlist.json")


@router.get("/signals")
def signals() -> list[dict]:
    return load("signals.json")


@router.get("/backtest")
def backtest() -> dict:
    return load("backtest.json")


@router.get("/risk")
def risk() -> dict:
    return load("risk.json")


@router.get("/company/{ticker}")
def company(ticker: str) -> dict:
    ticker = ticker.upper()
    card = next((r for r in load("watchlist.json") if r["ticker"] == ticker), None)
    if card is None:
        raise HTTPException(404, f"{ticker} is not in this month's universe")
    h = _history(STUDY_DIR, _mtime(STUDY_DIR / "risk_predictions.parquet"))
    sig = h["signals"][h["signals"]["ticker"] == ticker].drop(columns="ticker").sort_values("month")
    names = [c for c in sig.columns if c in SIGNALS]
    return {
        "card": card,
        "signals": [{"signal": n, "label": SIGNALS[n][0], "family": SIGNALS[n][1], "format": SIGNALS[n][2]} for n in names],
        "signal_history": _records(sig),
        "return_history": _records(h["returns"][h["returns"]["ticker"] == ticker].drop(columns="ticker").sort_values("month")),
        "risk_history": _records(h["risk"][h["risk"]["ticker"] == ticker].drop(columns="ticker").sort_values("month")),
    }

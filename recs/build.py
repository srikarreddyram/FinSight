"""Recommendation Layer (platform PRD, Module 6): this month's watchlist and the dashboard's summaries.

    uv run python -m recs.build        # needs the study, ranker, risk panel and risk model outputs

For the newest month in the panel, the return ranker and the two risk models are refit on every stock-month
whose 12-month outcome is known (same tuning and feature selection as each walk-forward fold) and used to score
it. Every score comes with its reasons:

- Drivers: the three largest SHAP contributions (exact for trees, from LightGBM itself) in plain words.
- Confidence band: what stocks in the same predicted decile actually returned in the walk-forward test years.
- Risk components: the realised volatility and severe-loss rate of the same predicted decile in those test
  years. The classifier's raw scores are class-weighted, so they are not probabilities and are never shown.

Nothing here says "buy": the output is a ranked research watchlist.
"""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from models import backtest as bt
from models import ranker
from models.walkforward import rank_ic_by_month
from recs.labels import PILLAR_LABELS, SIGNALS, base, fmt, label
from risk import models as risk_models
from risk.panel import PILLARS
from signals.base import Inputs, market_cap, snapshot
from warehouse import db

log = logging.getLogger(__name__)

STUDY = Path("data/study/sp500")
OUT = Path("data/recs")
PILLAR_OF = {m: p for p, ms in PILLARS.items() for m in ms}


def _dates(df: pd.DataFrame, cols=("month", "target_end")) -> pd.DataFrame:
    for c in cols:
        if c in df:
            df[c] = pd.to_datetime(df[c]).dt.date
    return df


def decile(score: pd.Series, month: pd.Series) -> pd.Series:
    """Within-month decile of a score, 0 (lowest) to 9 (highest)."""
    g = score.groupby(month)
    return np.floor((g.rank(method="first") - 1) / g.transform("count") * 10).astype("Int64")


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def drivers(row: pd.Series, features: list[str], contrib: np.ndarray, up: str, down: str, n: int = 3) -> list[dict]:
    """The n signals that moved one stock's score most, in plain words. contrib excludes the model's bias term.
    A signal's market-wide and within-sector versions count as one driver; an event that didn't happen (no
    material weakness, no dividend cut, zero late filings) is never listed as a reason."""
    total: dict[str, float] = {}
    lead: dict[str, int] = {}
    for i, f in enumerate(features):
        name = base(f)[0]
        total[name] = total.get(name, 0.0) + float(contrib[i])
        if name not in lead or abs(contrib[i]) > abs(contrib[lead[name]]):
            lead[name] = i
    out = []
    for name in sorted(total, key=lambda k: -abs(total[k])):
        raw = row.get(name)
        _, family, kind = SIGNALS.get(name, ("", "", ""))
        # Something that didn't happen is not a reason: a flag that is "no", or an event count of zero.
        non_event = (kind == "flag" or (family == "Event risk" and kind == "num")) and (pd.isna(raw) or raw == 0)
        if total[name] == 0 or non_event:
            continue
        feature = features[lead[name]]
        scope = base(feature)[1]
        value = fmt(name, raw)
        rank = row.get(feature) if feature != name else row.get(f"{name}_r", row.get(f"{name}_rank"))
        where = "its sector" if scope == "sector" else "the universe"
        if value is None:
            text = f"{label(name)} is not reported"
        elif SIGNALS.get(name, ("", "", ""))[2] == "flag" or rank is None or pd.isna(rank):
            text = f"{label(name)}: {value}"
        else:
            text = f"{label(name)} is {value}, {ordinal(max(1, round(float(rank) * 100)))} percentile of {where}"
        out.append({"signal": name, "label": label(name), "scope": scope, "value": value,
                    "effect": up if total[name] > 0 else down, "text": text})  # fmt: skip
        if len(out) == n:
            break
    return out


def score_returns(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    features = [c for c in panel.columns if c.endswith(("_rank", "_srank")) and not c.startswith("f_score_tests")]
    train = panel.dropna(subset=["excess_ret"]).reset_index(drop=True)
    config, val_ic = ranker.tune(train, features)
    chosen = ranker.select(train, features, config.top_k)
    model = ranker._fit_lgbm(train, chosen, config.grid, config.target)
    latest = panel[panel["month"] == panel["month"].max()].reset_index(drop=True)
    contrib = model.predict(latest[chosen], pred_contrib=True)[:, :-1]
    out = latest[["ticker", "cik", "month", "sector"]].copy()
    out["return_score"] = model.predict(latest[chosen])
    out["return_rank"] = (out["return_score"].rank(pct=True) * 100).round(1)
    out["return_decile"] = decile(out["return_score"], out["month"])
    out["return_drivers"] = [
        drivers(latest.iloc[i], chosen, contrib[i], "lifts the rank", "lowers the rank") for i in range(len(latest))
    ]
    info = {"trained_through": str(train["month"].max()), "rows": len(train), "features": len(chosen),
            "labels": config.target, "validation_ic": val_ic}  # fmt: skip
    return out, info


def return_bands(preds: pd.DataFrame) -> dict[int, dict]:
    """12-month excess return actually earned by each predicted decile in the walk-forward test years."""
    d = decile(preds["pred_lgbm"], preds["month"])
    q = preds.groupby(d)["excess_ret"].quantile([0.25, 0.5, 0.75]).unstack()
    n = preds.groupby(d)["excess_ret"].size()
    return {int(k): {"p25": float(q.loc[k, 0.25]), "p50": float(q.loc[k, 0.5]), "p75": float(q.loc[k, 0.75]), "n": int(n[k])}
            for k in q.index}  # fmt: skip


def score_risk(risk_panel: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Grades for the newest months: enough of them to smooth the latest grade and to show last month's.
    Each component is the model blended with trailing volatility at the weight validation chose, exactly as in
    the walk-forward folds."""
    p = risk_models.prepare(risk_panel)
    recent = sorted(p["month"].unique())[-(risk_models.SMOOTH + 1) :]
    score = p[p["month"].isin(recent)].reset_index(drop=True)
    out = score[["ticker", "month"]].copy()
    info, contribs = {}, {}
    for kind, target in (("vol", "fwd_vol"), ("downside", "severe")):
        train = p.dropna(subset=[target])
        (params, fset, variant, weight), val = risk_models.tune(train, target, kind)
        feats = risk_models.FEATURE_SETS[fset]
        model = risk_models._fit(train, target, params, kind, feats, variant)
        out[f"pred_{kind}"] = risk_models.blend(score, model.predict(score[feats]), weight).to_numpy()
        contribs[kind] = (feats, model.predict(score[feats], pred_contrib=True)[:, :-1])
        info[kind] = {"trained_through": str(train["month"].max()), "rows": len(train), "features": fset,
                      "target": variant, "model_weight": weight, "validation": val}  # fmt: skip
    out["grade"] = risk_models.grades(out).astype(int)
    out["vol_decile"] = decile(out["pred_vol"], out["month"])
    out["downside_decile"] = decile(out["pred_downside"], out["month"])
    feats, c = contribs["downside"]
    names = [base(f)[0] for f in feats]
    pillar_of = np.array([PILLAR_OF[n] for n in names])
    by_pillar = pd.DataFrame({pl: c[:, pillar_of == pl].sum(axis=1) for pl in PILLARS})
    # The pillar that moves the score most, up or down: for a low-risk company every pillar may push risk down,
    # and "the one that pushes least" would be a meaningless answer.
    out["risk_pillar"] = by_pillar.abs().idxmax(axis=1).map(PILLAR_LABELS).to_numpy()
    lead = by_pillar.to_numpy()[np.arange(len(by_pillar)), by_pillar.abs().to_numpy().argmax(axis=1)]
    out["risk_pillar_effect"] = np.where(lead > 0, "raises risk", "lowers risk")
    out["risk_drivers"] = [drivers(score.iloc[i], feats, c[i], "raises risk", "lowers risk") for i in range(len(score))]
    if info["downside"]["model_weight"] == 0:
        # Validation gave the model no weight: the downside component is trailing volatility alone, so that is
        # the only honest driver to show.
        above = (score["vol_12m_r"] >= 0.5).to_numpy()
        effect = np.where(above, "raises risk", "lowers risk")
        out["risk_pillar"], out["risk_pillar_effect"] = PILLAR_LABELS["market"], effect
        one = np.array([1.0])
        out["risk_drivers"] = [
            drivers(score.iloc[i], ["vol_12m_r"], one if above[i] else -one, "raises risk", "lowers risk")
            for i in range(len(score))
        ]
    for m in ("vol_12m", "beta"):
        out[m] = score[m].to_numpy()
    return out, info


def risk_components(risk_preds: pd.DataFrame) -> dict[str, dict[int, float]]:
    """Realised volatility by predicted-volatility decile, and severe-loss rate by predicted-downside decile,
    in the walk-forward test years: the honest reading of a predicted decile."""
    v = risk_preds.groupby(decile(risk_preds["pred_vol"], risk_preds["month"]))["fwd_vol"].mean()
    s = risk_preds.groupby(decile(risk_preds["pred_downside"], risk_preds["month"]))["severe"].mean()
    return {"vol": {int(k): float(x) for k, x in v.items()}, "severe": {int(k): float(x) for k, x in s.items()}}


def signal_summary(panel: pd.DataFrame) -> list[dict]:
    overall = pd.read_csv(STUDY / "signals.csv", index_col="signal")
    done = panel.dropna(subset=["excess_ret"])
    out = []
    for name, row in overall.iterrows():
        ic = rank_ic_by_month(done, f"{name}_rank", "excess_ret")
        sic = rank_ic_by_month(done, f"{name}_srank", "excess_ret")
        years = sorted({m.year for m in ic.index})
        out.append({
            "signal": name, "label": label(name), "family": SIGNALS.get(name, ("", "Other", ""))[1],
            **{k: (None if pd.isna(v) else v) for k, v in row.items()},
            "by_year": [{"year": y, "ic": float(ic[[m.year == y for m in ic.index]].mean()),
                         "ic_sector": float(sic[[m.year == y for m in sic.index]].mean())} for y in years],
        })  # fmt: skip
    return out


def backtest_summary(con: duckdb.DuckDBPyConnection, preds: pd.DataFrame, q: float = 0.1, cost_bps: float = 10.0) -> dict:
    rows = bt.forward_1m(con, preds)
    ics = ranker.ic_table(preds)
    models = {}
    for col in [c for c in preds.columns if c.startswith("pred_")]:
        run = bt.backtest(rows, col, q, cost_bps)
        name = col[len("pred_") :]
        by_year = run.groupby([m.year for m in run.index]).agg(
            long_short=("long_short", lambda r: float((1 + r).prod() - 1)),
            long_short_net=("long_short_net", lambda r: float((1 + r).prod() - 1)),
            bench=("bench", lambda r: float((1 + r).prod() - 1)),
        )
        by_year["ic"] = [float(ics.loc[name, y]) for y in by_year.index]
        models[name] = {
            "stats": json.loads(bt.report(run).to_json(orient="index")),
            "monthly": json.loads(run.reset_index().assign(month=lambda d: d["month"].astype(str)).to_json(orient="records")),
            "by_year": json.loads(by_year.reset_index(names="year").to_json(orient="records")),
            "mean_ic": float(ics.loc[name, "mean"]),
        }
    return {"q": q, "cost_bps": cost_bps, "models": models}


def risk_summary(risk_preds: pd.DataFrame, latest: pd.DataFrame) -> dict:
    rep = risk_models.report(risk_preds)
    return {
        "overall": {k: (None if pd.isna(v) else float(v)) for k, v in rep["overall"]["value"].items()},
        "by_year": json.loads(rep["by_year"].reset_index().to_json(orient="records")),
        "calibration": json.loads(rep["calibration"].reset_index().to_json(orient="records")),
        "by_sector": json.loads(rep["by_sector"].reset_index().to_json(orient="records")),
        "grade_change_rate": float(rep["stability"].loc[risk_models.SMOOTH, "grade_change_rate"]),
        "smoothing_months": risk_models.SMOOTH,
        "stability": json.loads(rep["stability"].reset_index().to_json(orient="records")),
        "distribution": json.loads(
            latest.groupby(["sector", "risk_grade"]).size().rename("n").reset_index().to_json(orient="records")
        ),
        "pillars": latest["risk_pillar"].value_counts().to_dict(),
    }


def build(con: duckdb.DuckDBPyConnection) -> dict:
    panel = _dates(pd.read_parquet(STUDY / "panel.parquet"))
    risk_panel = _dates(pd.read_parquet(STUDY / "risk_panel.parquet"))
    preds = _dates(pd.read_parquet(STUDY / "predictions.parquet"))
    risk_preds = _dates(pd.read_parquet(STUDY / "risk_predictions.parquet"))

    returns, return_info = score_returns(panel)
    bands = return_bands(preds)
    risk, risk_info = score_risk(risk_panel)
    comps = risk_components(risk_preds)
    as_of = returns["month"].max()
    prev_month = sorted(risk["month"].unique())[-2]
    prev = risk[risk["month"] == prev_month].set_index("ticker")["grade"]
    now = risk[risk["month"] == as_of].drop(columns="month")

    w = returns.merge(now, on="ticker", how="left").rename(columns={"grade": "risk_grade"})
    w["risk_label"] = w["risk_grade"].map(risk_models.GRADES)
    w["previous_grade"] = w["ticker"].map(prev)
    w["band"] = w["return_decile"].map(lambda d: bands.get(int(d)))
    w["expected_vol"] = w["vol_decile"].map(lambda d: comps["vol"].get(int(d)) if pd.notna(d) else None)
    w["severe_loss_rate"] = w["downside_decile"].map(lambda d: comps["severe"].get(int(d)) if pd.notna(d) else None)
    names = dict(con.execute("select cik, name from companies").fetchall())
    w["name"] = w["cik"].map(names)
    caps = {}
    for cik in w["cik"]:
        snap = snapshot(con, int(cik), as_of)
        caps[cik] = market_cap(con, snap, int(cik), Inputs(snap))
    w["market_cap"] = w["cik"].map(caps)
    # The risk-adjusted view: rank on expected return within each risk grade.
    w["rank_in_grade"] = w.groupby("risk_grade")["return_score"].rank(ascending=False, method="first")
    w = w.sort_values("return_rank", ascending=False).reset_index(drop=True)

    OUT.mkdir(parents=True, exist_ok=True)
    w.to_json(OUT / "watchlist.json", orient="records", date_format="iso", default_handler=str)
    meta = {
        "as_of": str(as_of), "built": str(date.today()), "companies": len(w), "universe": "S&P 500 members",
        "returns_model": return_info, "risk_models": risk_info, "return_bands": bands, "risk_components": comps,
        "holdout_note": "Development test years end at 2024; 2025 is held out for one final evaluation.",
    }  # fmt: skip
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1, default=str))
    (OUT / "signals.json").write_text(json.dumps(signal_summary(panel), default=str))
    (OUT / "backtest.json").write_text(json.dumps(backtest_summary(con, preds), default=str))
    (OUT / "risk.json").write_text(json.dumps(risk_summary(risk_preds, w), default=str))
    return meta


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    con = duckdb.connect(str(db.default_path()), read_only=True)
    meta = build(con)
    log.info("watchlist as of %s: %d companies -> %s", meta["as_of"], meta["companies"], OUT)
    log.info("returns model: %s", meta["returns_model"])
    log.info("risk models: %s", meta["risk_models"])


if __name__ == "__main__":
    main()

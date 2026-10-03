"""Vectorised monthly backtest (platform PRD, Module 5): long the top fraction of each month's ranking, short the
bottom, equal-weight, rebalanced monthly, one-month hold.

    uv run python -m models.backtest                  # on the study's predictions.parquet (from models.ranker)
    uv run python -m models.backtest --q 0.1 --cost-bps 10

Positions are formed at the close of month-end t, when every feature was already public (info_date <= t),
and held over the trading days in (t, end of month t+1]. Turnover is the sum of absolute weight changes at
each rebalance, with weights reset to equal (drift within the month is ignored); costs are turnover × bps.
Results are reported before and after costs.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from models import STUDY_DIR
from models.panel import Returns, add_months
from warehouse import db


def forward_1m(con: duckdb.DuckDBPyConnection, rows: pd.DataFrame, benchmark: str = "SPY") -> pd.DataFrame:
    """Adds `ret_1m` (each stock's return over the month after `month`) and `bench_1m`."""
    rets = Returns(con, [*rows["ticker"].unique(), benchmark])
    nxt = {m: add_months(m, 1) for m in rows["month"].unique()}
    out = rows.copy()
    out["ret_1m"] = [rets.window(t, m, nxt[m]) for t, m in zip(out["ticker"], out["month"], strict=True)]
    out["bench_1m"] = out["month"].map({m: rets.window(benchmark, m, n) for m, n in nxt.items()})
    return out


def weights(month: pd.DataFrame, pred: str, q: float) -> pd.Series:
    g = month.dropna(subset=[pred, "ret_1m"])
    k = max(1, int(len(g) * q))
    order = g.sort_values(pred)
    w = pd.Series(0.0, index=g["ticker"].to_numpy())
    w[order["ticker"].iloc[-k:].to_numpy()] = 1.0 / k
    w[order["ticker"].iloc[:k].to_numpy()] = -1.0 / k
    return w


def backtest(rows: pd.DataFrame, pred: str, q: float = 0.1, cost_bps: float = 10.0) -> pd.DataFrame:
    """One row per month: long, short and long-short returns, turnover, and the net long-short return."""
    out, prev = [], pd.Series(dtype=float)
    for m, g in rows.groupby("month", sort=True):
        w = weights(g, pred, q)
        r = g.set_index("ticker")["ret_1m"].reindex(w.index)
        turnover = float(w.sub(prev, fill_value=0.0).abs().sum())
        long_, short = float((w.clip(lower=0) * r).sum()), float((-w.clip(upper=0) * r).sum())
        out.append({"month": m, "long": long_, "short": short, "long_short": long_ - short,
                    "bench": float(g["bench_1m"].iloc[0]), "turnover": turnover,
                    "long_short_net": long_ - short - turnover * cost_bps / 1e4})  # fmt: skip
        prev = w
    return pd.DataFrame(out).set_index("month")


def stats(r: pd.Series) -> dict[str, float]:
    """Annualised mean, volatility and Sharpe (no risk-free rate: long-short is self-financing), max drawdown."""
    r = r.dropna()
    wealth = (1 + r).cumprod()
    return {
        "ann_return": float((1 + r).prod() ** (12 / len(r)) - 1) if len(r) else np.nan,
        "ann_vol": float(r.std(ddof=1) * math.sqrt(12)),
        "sharpe": float(r.mean() / r.std(ddof=1) * math.sqrt(12)) if r.std(ddof=1) > 0 else np.nan,
        "max_drawdown": float((wealth / wealth.cummax() - 1).min()),
        "months": len(r),
    }


def report(bt: pd.DataFrame) -> pd.DataFrame:
    t = pd.DataFrame({c: stats(bt[c]) for c in ("long", "short", "bench", "long_short", "long_short_net")}).T
    t["avg_turnover"] = bt["turnover"].mean()
    return t


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--predictions", default=STUDY_DIR / "predictions.parquet", type=Path)
    ap.add_argument("--q", default=0.1, type=float, help="fraction of names in each leg")
    ap.add_argument("--cost-bps", default=10.0, type=float)
    args = ap.parse_args()
    p = pd.read_parquet(args.predictions)
    p["month"] = pd.to_datetime(p["month"]).dt.date
    con = duckdb.connect(str(db.default_path()), read_only=True)
    rows = forward_1m(con, p)
    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        for pred in [c for c in p.columns if c.startswith("pred_")]:
            print(f"\n{pred}  (q={args.q}, {args.cost_bps:g} bps)")
            print(report(backtest(rows, pred, args.q, args.cost_bps)))
        if "tier" in rows and rows["tier"].nunique() > 1:  # the same portfolios formed inside one index at a time
            for t, g in rows.groupby("tier"):
                for pred in ("pred_lgbm", "pred_linear"):
                    print(f"\n{pred} within {t}  (q={args.q}, {args.cost_bps:g} bps)")
                    print(report(backtest(g, pred, args.q, args.cost_bps)))


if __name__ == "__main__":
    main()

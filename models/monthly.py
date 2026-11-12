"""The return ranker at a one-month horizon (docs/phase-j-monthly-ranker.md).

    uv run python -m models.monthly build      # panel_1m.parquet from the study panel (models.study builds that)
    uv run python -m models.monthly signals    # each signal's rank IC against next month's return
    uv run python -m models.ranker --panel data/study/sp1500/panel_1m.parquet --out data/study/sp1500/predictions_1m.parquet
    uv run python -m models.monthly report     # the ranker: ICs, style-neutral ICs, long-short backtest

The 12-month study samples a 12-month return every month, so its ten test years are about ten independent
observations, and its backtest trades monthly on a signal fitted to yearly returns. Here the target is the next
month's excess return: 120 test months that don't overlap, so a t-statistic on monthly ICs means what it says,
and the model is fitted to the return the backtest earns.

The panel keeps every feature of the study panel (they are point-in-time at each month-end already) and adds two
price families with evidence at this horizon: the reaction to the latest earnings report (signals/earnings.py) and
low risk (signals/lowrisk.py). Positions are entered at the close of the first trading day after the month-end,
not at the month-end close the features were computed from, and held to the next month-end.

`signals` and `report` stop at --last-month (default December 2024): later months are the confirmatory test,
scored once (see the doc).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
from datetime import date, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from models import STUDY_DIR
from models.backtest import backtest, stats
from models.checks import STYLE, neutralise
from models.panel import Returns, add_months
from models.ranks import add_ranks
from models.walkforward import rank_ic_by_month
from signals.earnings import earnings_features
from signals.lowrisk import lowrisk_features
from warehouse import db

log = logging.getLogger(__name__)

NEW_FAMILIES = [earnings_features, lowrisk_features]
NEW_SIGNALS = ["ear", "vol_1y", "beta_1y", "ivol_1m"]
BENCHMARK = "SPY"
LAST_DEV_MONTH = date(2024, 12, 31)
_TARGET = ["target_start", "target_end", "fwd_ret", "bench_ret", "excess_ret"]


def one_month_targets(rets: Returns, rows: pd.DataFrame, benchmark: str = BENCHMARK) -> pd.DataFrame:
    """For each (ticker, month): the return from the close of the first trading day after the month-end to the
    close of the next month-end, the market's over the same days, and the difference. Missing unless the market
    has traded through that whole month and the stock has prices on both sides."""
    days = rets.series[benchmark][0]
    out = rows[["ticker", "month"]].copy()
    spans: dict[date, tuple[date | None, date]] = {}
    for m in out["month"].unique():
        i = int(np.searchsorted(days, m, side="right"))  # first trading day after the month-end
        end = add_months(m, 1)
        last = end
        while last.weekday() >= 5:
            last -= timedelta(days=1)
        spans[m] = (days[i] if i < len(days) and days[-1] >= last else None, end)
    out["target_start"] = out["month"].map(lambda m: spans[m][0])
    out["target_end"] = out["month"].map(lambda m: spans[m][1])
    bench = {m: rets.window(benchmark, s, e) if s else np.nan for m, (s, e) in spans.items()}
    out["fwd_ret"] = [
        rets.window(t, spans[m][0], spans[m][1]) if spans[m][0] else np.nan
        for t, m in zip(out["ticker"], out["month"], strict=True)
    ]
    out["bench_ret"] = out["month"].map(bench)
    out["excess_ret"] = out["fwd_ret"] - out["bench_ret"]
    return out


def new_features(con: duckdb.DuckDBPyConnection, rows: pd.DataFrame) -> pd.DataFrame:
    """The new families for each (cik, month) of the study panel, with the latest date of anything they used."""
    out = []
    for cik, months in rows.groupby("cik")["month"]:
        for m in months:
            row: dict = {"cik": cik, "month": m}
            infos = []
            for fn in NEW_FAMILIES:
                values, info = fn(con, int(cik), m)
                row.update(values)
                if info is not None:
                    infos.append(info)
            row["new_info_date"] = max(infos) if infos else None
            out.append(row)
    return pd.DataFrame(out)


def build(study: Path, con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    p = pd.read_parquet(study / "panel.parquet")
    p["month"] = pd.to_datetime(p["month"]).dt.date
    p = p.drop(columns=_TARGET).merge(new_features(con, p[["cik", "month"]]), on=["cik", "month"], how="left")
    info = pd.concat([pd.to_datetime(p["info_date"]), pd.to_datetime(p.pop("new_info_date"))], axis=1).max(axis=1)
    p["info_date"] = info.dt.date.where(info.notna(), None)
    p = add_ranks(p, NEW_SIGNALS)
    rets = Returns(con, [*p["ticker"].unique(), BENCHMARK])
    return p.merge(one_month_targets(rets, p), on=["ticker", "month"], how="left")


def monthly_t(ic: pd.Series) -> tuple[float, float, int]:
    """Mean monthly IC, its t-statistic (the months don't overlap, so they count as separate observations) and
    the number of months."""
    n = len(ic)
    sd = ic.std(ddof=1) if n > 2 else np.nan
    return float(ic.mean()), float(ic.mean() / sd * math.sqrt(n)) if sd and sd > 0 else np.nan, n


def signal_table(p: pd.DataFrame, signals: list[str]) -> pd.DataFrame:
    rows = []
    for s in signals:
        row: dict = {"signal": s, "coverage": float(p[s].notna().mean())}
        for kind, col in (("raw", f"{s}_rank"), ("sector", f"{s}_srank")):
            ic = rank_ic_by_month(p, col, "excess_ret")
            mean, t, n = monthly_t(ic)
            row |= {f"ic_{kind}": mean, f"t_{kind}": t, f"months_pos_{kind}": f"{int((ic > 0).sum())}/{n}"}
        rows.append(row)
    return pd.DataFrame(rows).set_index("signal").sort_values("t_raw", key=abs, ascending=False)


def ic_rows(df: pd.DataFrame, models: list[str]) -> list[dict]:
    rows = []
    groups = [("all", df)] + ([(t, g) for t, g in df.groupby("tier")] if "tier" in df and df["tier"].nunique() > 1 else [])
    for name, g in groups:
        for m in models:
            for kind, col in (("raw", m), ("neutral", f"{m}_neutral")):
                ic = rank_ic_by_month(g, col, "excess_ret")
                mean, t, n = monthly_t(ic)
                rows.append({"universe": name, "model": m.removeprefix("pred_"), "kind": kind, "ic": mean, "t": t,
                             "months": n, "positive": float((ic > 0).mean())})  # fmt: skip
    return rows


def report(study: Path, predictions: Path, first: date, last: date, q: float = 0.1, cost_bps: float = 10.0) -> dict:
    preds = pd.read_parquet(predictions)
    panel = pd.read_parquet(study / "panel_1m.parquet", columns=["ticker", "month", "fwd_ret", "bench_ret"])
    risk = pd.read_parquet(study / "risk_panel.parquet", columns=["ticker", "month", *STYLE])
    for d in (preds, panel, risk):
        d["month"] = pd.to_datetime(d["month"]).dt.date
    preds = preds[(preds["month"] >= first) & (preds["month"] <= last)]
    df = preds.merge(risk, on=["ticker", "month"], how="left").merge(panel, on=["ticker", "month"], how="left")
    df = df.rename(columns={"fwd_ret": "ret_1m", "bench_ret": "bench_1m"})
    models = [c for c in preds.columns if c.startswith("pred_")]
    for m in models:
        df[f"{m}_neutral"] = neutralise(df, m, STYLE)
    out: dict = {"first": str(first), "last": str(last), "ic": ic_rows(df, models), "backtest": {}, "by_year": {}}
    for m in models:
        bt = backtest(df, m, q, cost_bps)
        net = bt["long_short_net"]
        best = net.groupby([d.year for d in net.index]).apply(lambda r: (1 + r).prod() - 1)
        out["backtest"][m.removeprefix("pred_")] = {
            **{f"gross_{k}": v for k, v in stats(bt["long_short"]).items() if k in ("ann_return", "sharpe")},
            **stats(net),
            "turnover": float(bt["turnover"].mean()),
            "by_year": {int(y): float(v) for y, v in best.items()},
        }
        ic = rank_ic_by_month(df, m, "excess_ret")
        out["by_year"][m.removeprefix("pred_")] = {
            int(y): float(v) for y, v in ic.groupby([d.year for d in ic.index]).mean().items()
        }
    out["exposures"] = {
        m.removeprefix("pred_"): {c: float(rank_ic_by_month(df, m, c).mean()) for c in STYLE if c in df} for m in models
    }
    return out


def _show(res: dict) -> None:
    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        print(f"\nfeature months {res['first']} to {res['last']}")
        print(pd.DataFrame(res["ic"]).pivot_table(index=["universe", "model"], columns="kind", values=["ic", "t"]))
        print("\nMean rank IC by year:")
        print(pd.DataFrame(res["by_year"]).T)
        print("\nLong-short deciles after costs:")
        print(pd.DataFrame({k: {x: y for x, y in v.items() if x != "by_year"} for k, v in res["backtest"].items()}).T)
        print("\nRank correlation with style measures:")
        print(pd.DataFrame(res["exposures"]).T)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["build", "signals", "report"])
    ap.add_argument("--study", default=STUDY_DIR, type=Path)
    ap.add_argument("--predictions", type=Path, help="default: predictions_1m.parquet in the study folder")
    ap.add_argument("--first-month", default=date(2015, 1, 1), type=date.fromisoformat)
    ap.add_argument(
        "--last-month", default=LAST_DEV_MONTH, type=date.fromisoformat,
        help="later months are the confirmatory test: pass a later date only for that one run",
    )  # fmt: skip
    ap.add_argument("--out", type=Path, help="where `report` writes its JSON (default: monthly.json in the study folder)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.command == "build":
        con = duckdb.connect(str(db.default_path()), read_only=True)
        p = build(args.study, con)
        p.to_parquet(args.study / "panel_1m.parquet")
        dev = p[p["month"] <= LAST_DEV_MONTH]
        log.info("%d stock-months, %.1f%% with a one-month return up to %s; new signals' coverage: %s",
                 len(p), 100 * dev["excess_ret"].notna().mean(), LAST_DEV_MONTH,
                 {s: round(float(dev[s].notna().mean()), 3) for s in NEW_SIGNALS})  # fmt: skip
    elif args.command == "signals":
        p = pd.read_parquet(args.study / "panel_1m.parquet")
        p["month"] = pd.to_datetime(p["month"]).dt.date
        p = p[(p["month"] <= args.last_month)].dropna(subset=["excess_ret"])
        signals = [c[: -len("_rank")] for c in p.columns if c.endswith("_rank") and not c.startswith("f_score_tests")]
        res = signal_table(p, signals)
        res.to_csv(args.study / "signals_1m.csv")
        with pd.option_context("display.width", 200, "display.max_rows", 100, "display.float_format", "{:.3f}".format):
            print(res)
    else:
        res = report(args.study, args.predictions or args.study / "predictions_1m.parquet", args.first_month, args.last_month)
        (args.out or args.study / "monthly.json").write_text(json.dumps(res, indent=1))
        _show(res)


if __name__ == "__main__":
    main()

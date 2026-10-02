"""Single-signal study (platform PRD, Signal Lab): does each signal, on its own, rank next year's excess returns?

    uv run python -m models.study                      # build the panel, then study every signal
    uv run python -m models.study --cached             # reuse data/study/panel.parquet

For each signal, raw and sector-neutral: monthly rank IC, its yearly averages, and the top-minus-bottom quintile
spread in 12-month excess return. The target is a 12-month return sampled monthly, so consecutive months'
ICs share 11 of 12 months and are not independent; the t-statistic is therefore computed on yearly mean ICs,
which is conservative. Signs are reported as measured: accruals or leverage are expected to come out negative.

Until the universe is decided this runs on the FinanceBench companies only, which checks the machinery; with
~29 names per month the numbers are noise and must not be reported.
"""

from __future__ import annotations

import argparse
import logging
import math
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from models import THREADS
from models import panel as panel_mod
from models.ranks import add_ranks
from models.walkforward import rank_ic_by_month
from signals.accounting import accounting_features
from signals.fundamentals import fundamental_features
from signals.text import text_features
from signals.valuation import valuation_features
from warehouse import db

log = logging.getLogger(__name__)

FAMILIES = [accounting_features, fundamental_features, valuation_features, text_features]
NOT_SIGNALS = {"f_score_tests"}  # bookkeeping columns families return alongside their signals
OUT_DIR = Path("data/study")


def _stays(con: duckdb.DuckDBPyConnection) -> dict[int, list[tuple[date | None, date | None]]]:
    out: dict[int, list] = {}
    for cik, start, end in con.execute("select cik, start_date, end_date from universe").fetchall():
        out.setdefault(cik, []).append((start, end))
    return out


def _is_member(stays: dict, cik: int, month: date) -> bool:
    return any((s is None or s <= month) and (e is None or month < e) for s, e in stays.get(cik, ()))


def _build_chunk(args) -> pd.DataFrame:
    path, chunk, months, stays, *families = args
    con = duckdb.connect(path, read_only=True)
    active = (lambda cik, m: _is_member(stays, cik, m)) if stays else None
    return panel_mod.build_panel(con, chunk, months, families[0] if families else FAMILIES, active=active)


def build(
    con: duckdb.DuckDBPyConnection, start: date, end: date, universe: str = "sp500", workers: int = 6
) -> tuple[pd.DataFrame, list[str]]:
    """The panel for `universe`: "sp500" (index members in the months they were members, from the universe
    table) or "financebench" (the Copilot's companies, every month). Built in parallel over company chunks,
    each worker with its own read-only connection."""
    if universe == "sp500":
        stays = _stays(con)
        names = dict(con.execute("select ticker, cik from companies where cik in (select cik from universe)").fetchall())
    else:
        from ingest.manifest import load_documents

        stays = {}
        tickers = sorted({m.ticker for m in load_documents().values() if m.track == "financebench"})
        names = dict(con.execute(
            f"select ticker, cik from companies where ticker in ({', '.join('?' * len(tickers))})", tickers
        ).fetchall())  # fmt: skip
    months = panel_mod.month_ends(start, end)
    log.info("panel (%s): %d companies x %d months, %d workers", universe, len(names), len(months), workers)
    path = str(db.default_path())
    items = sorted(names.items())
    chunks = [dict(items[i::workers]) for i in range(workers)]
    with ProcessPoolExecutor(workers) as pool:
        parts = list(pool.map(_build_chunk, [(path, c, months, stays) for c in chunks if c]))
    p = pd.concat(parts, ignore_index=True).sort_values(["month", "ticker"], ignore_index=True)
    sectors = dict(con.execute("select ticker, sector from companies").fetchall())
    p["sector"] = p["ticker"].map(sectors)
    fixed = {"ticker", "cik", "month", "target_start", "target_end", "info_date", "fwd_ret", "bench_ret", "excess_ret", "sector"}
    signals = [c for c in p.columns if c not in fixed and c not in NOT_SIGNALS]
    return add_ranks(p, signals), signals


def quantile_spread(df: pd.DataFrame, col: str, target: str = "excess_ret", q: float = 0.2) -> float:
    """Mean over months of (average target of the top q by `col`) minus (that of the bottom q)."""

    def spread(g: pd.DataFrame) -> float:
        g = g[[col, target]].dropna()
        k = int(len(g) * q)
        if k < 1:
            return np.nan
        g = g.sort_values(col)
        return g[target].iloc[-k:].mean() - g[target].iloc[:k].mean()

    return float(df.groupby("month")[[col, target]].apply(spread).mean())


def study(p: pd.DataFrame, signals: list[str], target: str = "excess_ret") -> pd.DataFrame:
    rows = []
    for s in signals:
        row: dict = {"signal": s, "coverage": float(p[s].notna().mean())}
        for kind, col in (("raw", f"{s}_rank"), ("sector", f"{s}_srank")):
            ic = rank_ic_by_month(p, col, target)
            yearly = ic.groupby([m.year for m in ic.index]).mean()
            t = yearly.mean() / yearly.std(ddof=1) * math.sqrt(len(yearly)) if len(yearly) > 2 else np.nan
            row |= {
                f"ic_{kind}": ic.mean(),
                f"t_{kind}": t,
                f"years_pos_{kind}": f"{int((yearly > 0).sum())}/{len(yearly)}",
                f"spread_{kind}": quantile_spread(p, col, target),
            }
        rows.append(row)
    return pd.DataFrame(rows).set_index("signal").sort_values("ic_raw", key=abs, ascending=False)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2011-01-01", type=date.fromisoformat)
    ap.add_argument("--end", default=None, type=date.fromisoformat, help="last feature month (default: today)")
    ap.add_argument("--cached", action="store_true", help="reuse the saved panel")
    ap.add_argument("--universe", choices=["sp500", "financebench"], default="sp500")
    ap.add_argument("--workers", default=THREADS, type=int)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    out_dir = OUT_DIR / args.universe
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = out_dir / "panel.parquet"
    if args.cached and cache.exists():
        p = pd.read_parquet(cache)
        p["month"] = pd.to_datetime(p["month"]).dt.date
        signals = [c[: -len("_rank")] for c in p.columns if c.endswith("_rank")]
    else:
        con = duckdb.connect(str(db.default_path()), read_only=True)
        p, signals = build(con, args.start, args.end or date.today(), args.universe, args.workers)
        p.to_parquet(cache)
    res = study(p.dropna(subset=["excess_ret"]), signals)
    res.to_csv(out_dir / "signals.csv")
    with pd.option_context("display.width", 200, "display.max_columns", 20, "display.float_format", "{:.3f}".format):
        print(res)


if __name__ == "__main__":
    main()

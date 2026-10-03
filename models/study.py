"""Single-signal study (platform PRD, Signal Lab): does each signal, on its own, rank next year's excess returns?

    uv run python -m models.study                      # build the panel, then study every signal
    uv run python -m models.study --cached             # reuse the saved panel
    uv run python -m models.study --universe sp500     # large caps only

For each signal, raw and sector-neutral: monthly rank IC, its yearly averages, and the top-minus-bottom quintile
spread in 12-month excess return. The target is a 12-month return sampled monthly, so consecutive months'
ICs share 11 of 12 months and are not independent; the t-statistic is therefore computed on yearly mean ICs,
which is conservative. Signs are reported as measured: accruals or leverage are expected to come out negative.

The "sp1500" universe is the S&P 500, 400 and 600 together; each row carries the index the company was in
that month (`tier`), and the study is repeated within each index. The 400's members only count from 2016 and the
600's from 2020 (see warehouse.universe), so the smaller indexes have fewer years behind their numbers.
"financebench" (the Copilot's ~29 companies) only checks the machinery; its numbers are noise.
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

from models import INDEXES, THREADS, UNIVERSE
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


def _stays(con: duckdb.DuckDBPyConnection, universe: str = UNIVERSE) -> dict[int, list[tuple[date | None, date | None, str]]]:
    """CIK -> its membership stays (start, end, index) in the indexes that make up `universe`, largest index first."""
    indexes = INDEXES[universe]
    out: dict[int, list] = {}
    for cik, start, end, index in con.execute("select cik, start_date, end_date, index_name from universe").fetchall():
        if index in indexes:
            out.setdefault(cik, []).append((start, end, index))
    for spans in out.values():
        spans.sort(key=lambda x: indexes.index(x[2]))
    return out


def tier(stays: dict, cik: int, month: date) -> str | None:
    """The index the company was a member of at that month-end, or None if it was in none."""
    return next((i for s, e, i in stays.get(cik, ()) if (s is None or s <= month) and (e is None or month < e)), None)


def _is_member(stays: dict, cik: int, month: date) -> bool:
    return tier(stays, cik, month) is not None


def _build_chunk(args) -> pd.DataFrame:
    path, chunk, months, stays, *families = args
    con = duckdb.connect(path, read_only=True)
    active = (lambda cik, m: _is_member(stays, cik, m)) if stays else None
    return panel_mod.build_panel(con, chunk, months, families[0] if families else FAMILIES, active=active)


def build(
    con: duckdb.DuckDBPyConnection, start: date, end: date, universe: str = "sp500", workers: int = 6
) -> tuple[pd.DataFrame, list[str]]:
    """The panel for `universe`: "sp1500" or "sp500" (index members in the months they were members, from the
    universe table) or "financebench" (the Copilot's companies, every month). Built in parallel over company
    chunks, each worker with its own read-only connection."""
    if universe in INDEXES:
        stays = _stays(con, universe)
        names = {
            t: c for t, c in con.execute("select ticker, cik from companies where ticker is not null").fetchall() if c in stays
        }
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
    p["tier"] = [tier(stays, c, m) for c, m in zip(p["cik"], p["month"], strict=True)] if stays else None
    fixed = {"ticker", "cik", "month", "target_start", "target_end", "info_date", "fwd_ret", "bench_ret", "excess_ret",
             "sector", "tier"}  # fmt: skip
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
    ap.add_argument("--universe", choices=[*INDEXES, "financebench"], default=UNIVERSE)
    ap.add_argument("--workers", default=THREADS, type=int)
    ap.add_argument("--out", type=Path, help="output folder (default: data/study/<universe>)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    out_dir = args.out or OUT_DIR / args.universe
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
    labelled = p.dropna(subset=["excess_ret"])
    res = study(labelled, signals)
    res.to_csv(out_dir / "signals.csv")
    with pd.option_context("display.width", 200, "display.max_columns", 20, "display.float_format", "{:.3f}".format):
        print(res)
        tiers = [t for t in INDEXES.get(args.universe, ()) if "tier" in p and (labelled["tier"] == t).any()]
        if len(tiers) > 1:
            by_tier = {t: study(labelled[labelled["tier"] == t], signals) for t in tiers}
            for t, r in by_tier.items():
                r.to_csv(out_dir / f"signals_{t}.csv")
            cols = ["ic_raw", "t_raw", "ic_sector", "t_sector"]
            print("\nWithin each index (rank IC against 12-month excess return):")
            print(pd.concat({t: r[cols] for t, r in by_tier.items()}, axis=1).reindex(res.index))


if __name__ == "__main__":
    main()

"""Daily prices: yfinance → Parquet cache (data/prices/<TICKER>.parquet) → DuckDB `prices`.

    uv run python -m warehouse.prices MMM NKE PEP
    uv run python -m warehouse.prices --track financebench

Yahoo re-scales its whole adjusted-price history after every dividend and split, so adjusted closes cached
on different days sit on different bases, and gluing them together turns a 2-for-1 split into a fake -50%
day. The cache therefore stores only values that never change after the fact:

- `ret`: the daily total return (dividends included), computed inside a single download
- `raw_close` / `raw_volume`: the prices as actually traded that day, with later splits undone, which is
  what shares-outstanding from a filing must be multiplied by to get market cap

The cache is append-only: a re-run downloads from the last cached day (one day of overlap, so the first new
return is on the same basis as its predecessor) and adds the days after it.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from app.config import get_settings
from warehouse import db

log = logging.getLogger(__name__)

START = date(2009, 1, 1)  # a year of history before the 2010 universe start, for trailing features
COLUMNS = ["ticker", "day", "raw_close", "ret", "raw_volume", "source"]

History = Callable[[str, date], pd.DataFrame]


def cache_dir() -> Path:
    return get_settings().data_dir / "prices"


def yahoo_history(ticker: str, start: date) -> pd.DataFrame:
    import yfinance as yf

    return yf.Ticker(ticker).history(start=start.isoformat(), auto_adjust=False, actions=True)


def normalise(hist: pd.DataFrame, ticker: str, source: str = "yfinance") -> pd.DataFrame:
    """Yahoo frame (Close = split-adjusted, Adj Close = split+dividend-adjusted) → basis-free rows."""
    if hist.empty:
        return pd.DataFrame(columns=COLUMNS)
    h = hist.sort_index()
    splits = h.get("Stock Splits", pd.Series(0.0, index=h.index)).replace(0, 1.0).fillna(1.0)
    # Product of split ratios strictly after each day: multiplying Yahoo's split-adjusted close by it gives
    # the close as traded. The reversed cumulative product runs from each day to the end of the download.
    after = splits[::-1].cumprod()[::-1].shift(-1, fill_value=1.0)
    out = pd.DataFrame(
        {
            "ticker": ticker.upper(),
            "day": [ts.date() for ts in h.index],
            "raw_close": (h["Close"] * after).to_numpy(),
            "ret": h["Adj Close"].pct_change().to_numpy(),
            "raw_volume": (h["Volume"] / after).to_numpy(),
            "source": source,
        }
    )
    return out[out["raw_close"].notna()].reset_index(drop=True)


def _read(path: Path) -> pd.DataFrame:
    return duckdb.sql(f"select * from read_parquet('{path}') order by day").df() if path.exists() else pd.DataFrame()


def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.parquet")
    duckdb.from_df(df[COLUMNS]).write_parquet(str(tmp))
    tmp.replace(path)  # never leave a half-written cache


def update(ticker: str, history: History = yahoo_history, root: Path | None = None) -> int:
    """Bring one ticker's cache up to date; returns the number of new days (0 if none or unknown ticker)."""
    path = (root or cache_dir()) / f"{ticker.upper()}.parquet"
    cached = _read(path)
    last = cached["day"].max() if not cached.empty else None
    if hasattr(last, "date"):
        last = last.date()
    fresh = normalise(history(ticker, last or START), ticker)
    if last is not None:
        fresh = fresh[fresh["day"] > last]  # the overlap day only served as the base for the first return
    if fresh.empty:
        return 0
    combined = pd.concat([cached, fresh], ignore_index=True) if not cached.empty else fresh
    _write(combined, path)
    return len(fresh)


def load(con: duckdb.DuckDBPyConnection, root: Path | None = None) -> int:
    """Replace the `prices` table's contents with every cached ticker."""
    files = sorted((root or cache_dir()).glob("*.parquet"))
    files = [f for f in files if not f.name.endswith(".tmp.parquet")]
    con.execute("delete from prices")
    if not files:
        return 0
    paths = ", ".join(f"'{f}'" for f in files)
    con.execute(f"insert into prices select {', '.join(COLUMNS)} from read_parquet([{paths}])")
    return con.execute("select count(*) from prices").fetchone()[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tickers", nargs="*")
    ap.add_argument("--track", help="all companies from this manifest track (e.g. financebench)")
    ap.add_argument("--universe", action="store_true", help="every company in the universe table")
    ap.add_argument("--missing-only", action="store_true", help="skip tickers that already have a cache file")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    tickers = list(args.tickers)
    if args.track:
        from ingest.manifest import load_documents

        tickers += sorted({m.ticker for m in load_documents().values() if m.track == args.track})
    if args.universe:
        con = db.connect()
        tickers += [r[0] for r in con.execute(
            "select ticker from companies where cik in (select cik from universe) and ticker is not null "
            "and ticker not like '%~%' order by 1"  # a "~" marks a delisted company: no history to fetch
        ).fetchall()]  # fmt: skip
        con.close()
    missing = []
    for t in dict.fromkeys(t.upper() for t in tickers):
        if args.missing_only and (cache_dir() / f"{t}.parquet").exists():
            continue
        try:
            n = update(t)
        except Exception as e:  # one bad ticker shouldn't stop the batch
            log.warning("%s: %s", t, e)
            n = 0
        if n == 0 and not (cache_dir() / f"{t}.parquet").exists():
            missing.append(t)
        log.info("%s: %d new days", t, n)
    con = db.connect()
    log.info("prices table: %d rows", load(con))
    con.close()
    if missing:
        log.warning("no price history for %d tickers (delisted, renamed or unknown): %s", len(missing), ", ".join(missing))


if __name__ == "__main__":
    main()

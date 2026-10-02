"""The modelling panel: one row per (stock, month-end t) with features known at t and a forward return.

Timeline for a row at month-end t (platform PRD, backtest protocol):

    t ── embargo (1 month) ──► target_start ─────── horizon (12 months) ──────► target_end
    features: facts with available_at <= t      return: trading days in (target_start, target_end]

Feature functions take (con, cik, as_of) and return ({name: value}, info_date), where info_date is the
latest `available_at` among the facts they used; the panel keeps it so tests can prove nothing leaked.
"""

from __future__ import annotations

import calendar
import logging
from collections import Counter
from collections.abc import Callable
from datetime import date

import duckdb
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

Feature = Callable[[duckdb.DuckDBPyConnection, int, date], tuple[dict[str, float], date | None]]


def month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + d.month - 1 + n, 12)
    return month_end(y, m + 1)


def month_ends(start: date, end: date) -> list[date]:
    out, d = [], month_end(start.year, start.month)
    while d <= end:
        out.append(d)
        d = add_months(d, 1)
    return out


class Returns:
    """Compound returns over date windows from the warehouse's daily total returns."""

    def __init__(self, con: duckdb.DuckDBPyConnection, tickers: list[str]):
        df = con.execute(
            f"select ticker, day, ret from prices where ticker in ({', '.join('?' * len(tickers))}) order by ticker, day",
            tickers,
        ).df()
        self.series: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        for tk, g in df.groupby("ticker"):
            days = pd.to_datetime(g["day"]).dt.date.to_numpy()
            cum = np.cumsum(np.log1p(g["ret"].fillna(0.0).to_numpy()))
            self.series[tk] = (days, cum)

    def window(self, ticker: str, start: date, end: date) -> float:
        """Total return over trading days in (start, end]; NaN unless prices cover the whole window."""
        if ticker not in self.series:
            return np.nan
        days, cum = self.series[ticker]
        if days[0] > start or days[-1] < end:
            return np.nan
        i = np.searchsorted(days, start, side="right") - 1  # last day <= start
        j = np.searchsorted(days, end, side="right") - 1  # last day <= end
        return float(np.expm1(cum[j] - cum[i]))


def build_panel(
    con: duckdb.DuckDBPyConnection,
    universe: dict[str, int],
    months: list[date],
    features: list[Feature],
    benchmark: str = "SPY",
    horizon: int = 12,
    embargo: int = 1,
    active: Callable[[int, date], bool] | None = None,
) -> pd.DataFrame:
    """active(cik, month): whether the stock belongs in that month's cross-section (index membership);
    rows outside it are never built."""
    rets = Returns(con, [*universe, benchmark])
    rows = []
    errors: Counter[str] = Counter()
    for t in months:
        target_start, target_end = add_months(t, embargo), add_months(t, embargo + horizon)
        bench = rets.window(benchmark, target_start, target_end)
        for tk, cik in universe.items():
            if active is not None and not active(cik, t):
                continue
            row: dict = {"ticker": tk, "cik": cik, "month": t, "target_start": target_start, "target_end": target_end}
            info_dates = []
            for fn in features:
                try:
                    values, info = fn(con, cik, t)
                except Exception as e:  # one company-month's bad data shouldn't sink the panel; counted and logged
                    errors[fn.__name__] += 1
                    if errors[fn.__name__] == 1:
                        log.warning("%s failed for CIK %d at %s (%s: %s); its features are left missing",
                                    fn.__name__, cik, t, type(e).__name__, e)  # fmt: skip
                    continue
                row.update(values)
                if info is not None:
                    info_dates.append(info)
            row["info_date"] = max(info_dates) if info_dates else None
            fwd = rets.window(tk, target_start, target_end)
            row["fwd_ret"], row["bench_ret"], row["excess_ret"] = fwd, bench, fwd - bench
            rows.append(row)
    for name, n in errors.items():
        log.warning("%s failed on %d company-months", name, n)
    return pd.DataFrame(rows)

"""Earnings reaction (Signal Lab family 7): how the stock moved against the market when it last reported.

Post-earnings-announcement drift is one of the oldest return patterns: prices keep moving for weeks in the
direction of an earnings surprise. There are no analyst estimates here, so the surprise is read from the market's
own reaction, as in news/earnings.py: an earnings date is the day the company filed an 8-K with item 2.02, and
because the filing date doesn't say whether results came before the open or after the close, the reaction runs
from the close before that date to the close of the trading day after it.

- ear: the stock's return minus SPY's over that window, for the latest report whose window had closed by the
  month-end; missing when that report is more than 100 days old (the drift literature measures a quarter)
"""

from __future__ import annotations

from datetime import date, timedelta

import duckdb
import numpy as np

from signals.base import NAN
from signals.momentum import _series, benchmark

MAX_AGE = timedelta(days=100)
_DATES: dict[tuple, list[date]] = {}


def _earnings_dates(con: duckdb.DuckDBPyConnection, cik: int) -> list[date]:
    key = (con, cik)
    if key not in _DATES:
        if len(_DATES) > 4000:
            _DATES.clear()
        rows = con.execute(
            "select distinct filed_at from filing_index where cik = ? and form like '8-K%' and items like '%2.02%' "
            "order by filed_at",
            [cik],
        ).fetchall()
        _DATES[key] = [r[0] for r in rows]
    return _DATES[key]


def compute(
    days: np.ndarray, cum: np.ndarray, market_days: np.ndarray, market_cum: np.ndarray, reports: list[date], as_of: date
) -> tuple[dict[str, float], date | None]:
    """The reaction to the latest report in `reports` (sorted) that is public history on `as_of`."""
    for d in reversed(reports):
        if d > as_of:
            continue
        if d < as_of - MAX_AGE:
            break
        on = int(np.searchsorted(days, d, side="left"))  # the filing date, or the next trading day
        before, after = on - 1, on + 1
        if before < 0 or after >= len(days) or days[after] > as_of:
            continue  # the reaction window hadn't closed by the month-end (or there are no prices around it)
        m0 = int(np.searchsorted(market_days, days[before], side="right")) - 1
        m1 = int(np.searchsorted(market_days, days[after], side="right")) - 1
        if m0 < 0:
            continue
        stock = float(np.expm1(cum[after] - cum[before]))
        market = float(np.expm1(market_cum[m1] - market_cum[m0]))
        return {"ear": stock - market}, days[after]
    return {"ear": NAN}, None


def earnings_features(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> tuple[dict[str, float], date | None]:
    s, m = _series(con, cik), benchmark(con)
    if s is None or m is None:
        return {"ear": NAN}, None
    return compute(s[0], s[1], m[0], m[1], _earnings_dates(con, cik), as_of)

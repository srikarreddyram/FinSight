"""Price momentum (Signal Lab family 5): the best-documented return pattern outside the filings, here both as a
signal in its own right and as a control for the filing signals.

From the stock's daily total returns up to the month-end (everything is public the day it trades):
- mom_12_1: return over the past twelve months, skipping the most recent one (the classic 12-1 momentum)
- rev_1m: return over the most recent month (short-term reversal: expected to come out negative)
- high_52w: price relative to its 52-week high (1 = at the high)
A month is 21 trading days and a year 252.
"""

from __future__ import annotations

from datetime import date

import duckdb
import numpy as np

from signals.base import NAN

MONTH, YEAR = 21, 252
_SERIES: dict[tuple, tuple[np.ndarray, np.ndarray] | None] = {}


def _series(con: duckdb.DuckDBPyConnection, cik: int) -> tuple[np.ndarray, np.ndarray] | None:
    """(trading days, cumulative log total return) for the company's priced ticker, cached per connection."""
    key = (con, cik)  # the connection itself, not id(): a closed one's id can be reused
    if key not in _SERIES:
        if len(_SERIES) > 4000:
            _SERIES.clear()
        df = con.execute(
            "select p.day, p.ret from prices p join companies c on c.ticker = p.ticker where c.cik = ? order by p.day", [cik]
        ).df()
        if df.empty:
            _SERIES[key] = None
        else:
            days = np.array([d.date() if hasattr(d, "date") else d for d in df["day"]])
            _SERIES[key] = (days, np.cumsum(np.log1p(df["ret"].fillna(0.0).to_numpy())))
    return _SERIES[key]


def compute(cum: np.ndarray, i: int) -> dict[str, float]:
    """Momentum measures at index i of a cumulative log-return series (NaN without a year of history)."""
    if i < YEAR:
        return {"mom_12_1": NAN, "rev_1m": NAN, "high_52w": NAN}
    return {
        "mom_12_1": float(np.expm1(cum[i - MONTH] - cum[i - YEAR])),
        "rev_1m": float(np.expm1(cum[i] - cum[i - MONTH])),
        "high_52w": float(np.exp(cum[i] - cum[i - YEAR + 1 : i + 1].max())),
    }


def momentum_features(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> tuple[dict[str, float], date | None]:
    s = _series(con, cik)
    if s is None:
        return compute(np.array([]), -1), None
    days, cum = s
    i = int(np.searchsorted(days, as_of, side="right")) - 1
    if i < 0:
        return compute(cum, -1), None
    return compute(cum, i), days[i]

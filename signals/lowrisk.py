"""Low risk (Signal Lab family 8): volatility, beta and idiosyncratic volatility as return signals.

The low-risk anomaly: volatile, high-beta stocks have earned no more, and often less, than calm ones, and stocks
with high idiosyncratic volatility over the past month have done worst in the month after. The Risk Engine
already predicts risk from these measures; here they are tested for what they say about returns, so each is
expected to come out with a negative IC.

From daily total returns up to the month-end (log returns; a month is 21 trading days and a year 252):
- vol_1y: annualised volatility over the past year
- beta_1y: slope against SPY over the same days
- ivol_1m: annualised volatility over the past month of what beta_1y × SPY doesn't explain
"""

from __future__ import annotations

from datetime import date

import duckdb
import numpy as np

from signals.base import NAN
from signals.momentum import MONTH, YEAR, _series, benchmark

MIN_YEAR, MIN_MONTH = 200, 15
_EMPTY = {"vol_1y": NAN, "beta_1y": NAN, "ivol_1m": NAN}


def compute(r: np.ndarray, m: np.ndarray) -> dict[str, float]:
    """r, m: the stock's and the market's daily log returns over the same days, oldest first, ending at the
    month-end (NaN in m where the market has no price that day)."""
    r, m = r[-YEAR:], m[-YEAR:]
    ok = ~np.isnan(m)
    if ok.sum() < MIN_YEAR:
        return dict(_EMPTY)
    var = float(np.var(m[ok], ddof=1))
    beta = float(np.cov(r[ok], m[ok])[0, 1] / var) if var > 0 else NAN
    out = {"vol_1y": float(r[ok].std(ddof=1) * np.sqrt(YEAR)), "beta_1y": beta, "ivol_1m": NAN}
    last = ok[-MONTH:]
    if last.sum() >= MIN_MONTH and not np.isnan(beta):
        resid = r[-MONTH:][last] - beta * m[-MONTH:][last]
        out["ivol_1m"] = float(resid.std(ddof=1) * np.sqrt(YEAR))
    return out


def aligned(days: np.ndarray, market_days: np.ndarray, market_cum: np.ndarray) -> np.ndarray:
    """The market's daily log return on each of the stock's trading days (NaN where it has none)."""
    idx = np.searchsorted(market_days, days)
    hit = (idx < len(market_days)) & (market_days[np.minimum(idx, len(market_days) - 1)] == days)
    level = np.where(hit, market_cum[np.minimum(idx, len(market_cum) - 1)], np.nan)
    return np.diff(level, prepend=np.nan)


_ALIGNED: dict[tuple, np.ndarray] = {}


def lowrisk_features(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> tuple[dict[str, float], date | None]:
    s, mk = _series(con, cik), benchmark(con)
    if s is None or mk is None:
        return dict(_EMPTY), None
    days, cum = s
    i = int(np.searchsorted(days, as_of, side="right")) - 1
    if i < MIN_YEAR:
        return dict(_EMPTY), None
    key = (con, cik)
    if key not in _ALIGNED:
        if len(_ALIGNED) > 4000:
            _ALIGNED.clear()
        _ALIGNED[key] = aligned(days, mk[0], mk[1])
    lo = max(1, i - YEAR + 1)
    r = np.diff(cum[lo - 1 : i + 1])
    return compute(r, _ALIGNED[key][lo : i + 1]), days[i]

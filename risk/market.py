"""Market-risk pillar and the Risk Engine's targets, from daily prices (platform PRD, Module 7).

Features at month-end t use trading days up to and including t (the close at t is known at t):
trailing 12-month volatility, beta to SPY, maximum drawdown, downside deviation, 3-month dollar volume and the
12-month return. Targets cover trading days in (t, end of month t+12]:

- fwd_vol: realised annualised volatility, needing at least MIN_DAYS of the window
- fwd_mdd: worst fall from a running peak, starting from the close at t
- severe: fwd_mdd of -40% or worse. If prices stop inside the window (delisted), the outcome counts as severe
  only if the stock had already fallen 40%; otherwise it is unknown, never quietly truncated.

Delisting for cause can't be told apart from takeovers yet: Yahoo drops delisted names entirely (see the
survivorship note in docs/phase-b-signals.md).
"""

from __future__ import annotations

from datetime import date

import duckdb
import numpy as np
import pandas as pd

from models.panel import add_months

DAYS = 252
MIN_DAYS = 200
SEVERE = -0.40


def _mdd(rets: np.ndarray) -> float:
    if len(rets) == 0:
        return np.nan
    wealth = np.concatenate([[1.0], np.cumprod(1 + rets)])
    return float((wealth / np.maximum.accumulate(wealth) - 1).min())


def series(con: duckdb.DuckDBPyConnection, tickers: list[str]) -> dict[str, pd.DataFrame]:
    df = con.execute(
        f"select ticker, day, ret, raw_close, raw_volume from prices where ticker in ({', '.join('?' * len(tickers))}) "
        "order by ticker, day",
        tickers,
    ).df()
    df["day"] = pd.to_datetime(df["day"]).dt.date
    return {tk: g.reset_index(drop=True) for tk, g in df.groupby("ticker")}


def measures(s: pd.DataFrame, spy: pd.DataFrame, months: list[date], last_day: date) -> pd.DataFrame:
    """Market features and forward targets for one stock at each month-end."""
    days = s["day"].to_numpy()
    r = s["ret"].fillna(0.0).to_numpy()
    dollar = (s["raw_close"] * s["raw_volume"]).to_numpy()
    spy_r = pd.Series(spy["ret"].to_numpy(), index=spy["day"].to_numpy())
    rows = []
    for t in months:
        i = np.searchsorted(days, t, side="right")  # days[:i] are <= t
        row: dict = {"month": t}
        past = r[max(0, i - DAYS) : i]
        if i >= MIN_DAYS and len(past) >= MIN_DAYS:
            row["vol_12m"] = float(past.std(ddof=1) * np.sqrt(DAYS))
            m = spy_r.reindex(days[max(0, i - DAYS) : i]).to_numpy()
            ok = ~np.isnan(m)
            var = np.var(m[ok], ddof=1) if ok.sum() > MIN_DAYS else 0.0
            row["beta"] = float(np.cov(past[ok], m[ok])[0, 1] / var) if var > 0 else np.nan
            row["mdd_12m"] = _mdd(past)
            row["downside_dev"] = float(np.sqrt(np.mean(np.minimum(past, 0) ** 2)) * np.sqrt(DAYS))
            row["ret_12m"] = float(np.prod(1 + past) - 1)
            dv = dollar[max(0, i - 63) : i]
            row["log_dollar_volume"] = float(np.log(np.nanmean(dv))) if np.nanmean(dv) > 0 else np.nan
        end = add_months(t, 12)
        j = np.searchsorted(days, end, side="right")
        fwd = r[i:j]
        row["risk_target_end"] = end
        if end <= last_day:  # the window has closed in the data
            complete = len(days) > 0 and days[-1] >= end - pd.Timedelta(days=7).to_pytimedelta()
            mdd = _mdd(fwd)
            row["fwd_mdd"] = mdd
            if complete:
                row["fwd_vol"] = float(fwd.std(ddof=1) * np.sqrt(DAYS)) if len(fwd) >= MIN_DAYS else np.nan
                row["severe"] = float(mdd <= SEVERE) if not np.isnan(mdd) else np.nan
            else:  # prices stop inside the window
                row["severe"] = 1.0 if mdd <= SEVERE else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def market_panel(con: duckdb.DuckDBPyConnection, tickers: list[str], months: list[date], benchmark: str = "SPY") -> pd.DataFrame:
    data = series(con, [*tickers, benchmark])
    spy = data[benchmark]
    last_day = spy["day"].iloc[-1]
    parts = []
    for tk in tickers:
        if tk in data and len(data[tk]):
            m = measures(data[tk], spy, months, last_day)
            m["ticker"] = tk
            parts.append(m)
    return pd.concat(parts, ignore_index=True)

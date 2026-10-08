"""Insider buying (Signal Lab family 6): open-market trades by a company's directors and officers (Form 4).

Insiders sell for many reasons (diversification, taxes, planned sales) but buy with their own money for one,
which is why purchases carry most of the information in the literature. Over the six months before the
month-end, counting only trades public by then (filed the day before or earlier):
- insider_buyers_6m: how many directors and officers bought
- insider_net_6m: (buyers - sellers) / (buyers + sellers), from -1 (only selling) to 1 (only buying); missing when
  nobody traded
"""

from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pandas as pd

from signals.base import NAN

WINDOW = timedelta(days=182)
_TRADES: dict[tuple, pd.DataFrame] = {}


def _trades(con: duckdb.DuckDBPyConnection, cik: int) -> pd.DataFrame:
    key = (con, cik)
    if key not in _TRADES:
        if len(_TRADES) > 4000:
            _TRADES.clear()
        df = con.execute("select owner_cik, filed_at, code from insider_trades where issuer_cik = ?", [cik]).df()
        df["filed_at"] = pd.to_datetime(df["filed_at"]).dt.date
        _TRADES[key] = df
    return _TRADES[key]


def compute(trades: pd.DataFrame, as_of: date) -> tuple[dict[str, float], date | None]:
    public = trades[(trades["filed_at"] < as_of) & (trades["filed_at"] >= as_of - WINDOW)]
    buyers = public.loc[public["code"] == "P", "owner_cik"].nunique()
    sellers = public.loc[public["code"] == "S", "owner_cik"].nunique()
    net = (buyers - sellers) / (buyers + sellers) if buyers + sellers else NAN
    info = public["filed_at"].max() + timedelta(days=1) if len(public) else None
    return {"insider_buyers_6m": float(buyers), "insider_net_6m": net}, info


def insider_features(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> tuple[dict[str, float], date | None]:
    return compute(_trades(con, cik), as_of)

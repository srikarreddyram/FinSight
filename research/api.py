"""Endpoints for company research beyond the dashboard:

GET /research/{ticker}/changes      what changed in the Risk Factors since the previous 10-K
GET /research/{ticker}/timeline     filings, 8-K events with earnings reactions, and insider trades (3 years)
GET /research/{ticker}/financials   four years of financial lines, each with the filing that reported it
GET /research/asof?month=YYYY-MM    the watchlist as it stood that month, with what happened next
GET /research/asof/months           the months the time machine covers

Each request reads the warehouse read-only.
"""

from __future__ import annotations

from datetime import date, timedelta

import duckdb
from fastapi import APIRouter, HTTPException, Query

from research import history
from research.changes import risk_changes
from research.financials import financials
from research.timeline import timeline
from warehouse import db

router = APIRouter(prefix="/research", tags=["research"])


def _con() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(db.default_path()), read_only=True)


def _row(ticker: str) -> dict:
    from news.api import _company

    row = _company(ticker)
    if not row.get("cik"):
        raise HTTPException(404, f"No filings on record for {ticker}")
    return row


@router.get("/asof/months")
def asof_months() -> list[str]:
    return history.months()


@router.get("/asof")
def asof(month: str = Query(..., pattern=r"^\d{4}-\d{2}$")) -> dict:
    from news.api import _watchlist

    out = history.as_of(month)
    if out is None:
        raise HTTPException(404, f"No scores for {month}")
    names = {t: r.get("name") for t, r in _watchlist().items()}
    for r in out["rows"]:
        r["name"] = names.get(r["ticker"]) or r["ticker"].split("~")[0]
        r["listed"] = "~" not in r["ticker"]  # a company since delisted keeps its CIK suffix
    return out


@router.get("/{ticker}/changes")
def changes(ticker: str) -> dict:
    row = _row(ticker)
    con = _con()
    try:
        out = risk_changes(con, row["cik"], date.today())
    finally:
        con.close()
    if out is None:
        raise HTTPException(404, f"Fewer than two 10-Ks with Risk Factors on record for {row['ticker']}")
    return {"ticker": row["ticker"], **out}


@router.get("/{ticker}/timeline")
def company_timeline(ticker: str, years: int = Query(3, ge=1, le=10)) -> dict:
    row = _row(ticker)
    con = _con()
    try:
        events = timeline(con, row["cik"], row["ticker"], date.today() - timedelta(days=365 * years))
    finally:
        con.close()
    return {"ticker": row["ticker"], "events": events}


@router.get("/{ticker}/financials")
def company_financials(ticker: str) -> dict:
    row = _row(ticker)
    con = _con()
    try:
        out = financials(con, row["cik"], date.today())
    finally:
        con.close()
    if out is None:
        raise HTTPException(404, f"No annual financials on record for {row['ticker']}")
    return {"ticker": row["ticker"], **out}

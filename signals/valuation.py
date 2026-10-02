"""Valuation factors (Signal Lab family 3): cheap versus expensive, as a control. Fundamentals from the latest
annual report public on as_of; market cap from that report's cover-page share count and the price on as_of."""

from __future__ import annotations

from datetime import date

import duckdb

from signals.base import NAN, Inputs, div, market_cap, snapshot


def compute(x: Inputs, mcap: float | None) -> dict[str, float]:
    if not mcap or mcap <= 0:
        return {"earnings_yield": NAN, "book_to_market": NAN, "fcf_yield": NAN, "sales_to_price": NAN}
    g = x.get
    cfo, capex = g("cfo", 0), g("capex", 0)
    fcf = cfo - capex if cfo is not None and capex is not None else None
    vals = {
        "earnings_yield": div(g("net_income", 0), mcap),
        "book_to_market": div(g("equity", 0), mcap),
        "fcf_yield": div(fcf, mcap),
        "sales_to_price": div(g("revenue", 0), mcap),
    }
    return {k: NAN if v is None else v for k, v in vals.items()}


def valuation_features(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> tuple[dict[str, float], date | None]:
    snap = snapshot(con, cik, as_of)
    x = Inputs(snap)
    feats = compute(x, market_cap(con, snap, cik, x))
    return feats, (max(x.used) if x.used else None)

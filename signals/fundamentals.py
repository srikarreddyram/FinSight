"""Fundamental factors (Signal Lab family 2): growth, margins, returns and leverage, plus their year-over-year
changes. Levels say what kind of business it is; changes say which way it is heading."""

from __future__ import annotations

from datetime import date

import duckdb

from signals.base import NAN, Inputs, div, snapshot


def _nan(v: float | None) -> float:
    return NAN if v is None else v


def _chg(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def compute(x: Inputs) -> dict[str, float]:
    g = x.get
    rev = [g("revenue", y) for y in range(3)]
    ni = [g("net_income", y) for y in range(2)]
    assets = [g("assets", y) for y in range(3)]
    equity = [g("equity", y) for y in range(3)]

    def margin(num, y):
        return div(num, rev[y])

    gm = [margin(x.gross_profit(y), y) for y in range(2)]
    om = [margin(x.ebit(y), y) for y in range(2)]
    nm = [margin(ni[y], y) for y in range(2)]

    def roe(y):
        if ni[y] is None or equity[y] is None or equity[y + 1] is None:
            return None
        avg = (equity[y] + equity[y + 1]) / 2
        return ni[y] / avg if avg > 0 else None  # negative book equity makes ROE meaningless

    def roa(y):
        return div(ni[y], assets[y + 1])  # on beginning-of-year assets

    lev = [div(x.total_liabilities(y), assets[y]) for y in range(2)]
    feats = {
        "revenue_growth": _chg(div(rev[0], rev[1]), 1.0),
        "revenue_growth_chg": _chg(_chg(div(rev[0], rev[1]), 1.0), _chg(div(rev[1], rev[2]), 1.0)),
        "asset_growth": _chg(div(assets[0], assets[1]), 1.0),
        "gross_margin": gm[0],
        "gross_margin_chg": _chg(gm[0], gm[1]),
        "operating_margin": om[0],
        "operating_margin_chg": _chg(om[0], om[1]),
        "net_margin": nm[0],
        "net_margin_chg": _chg(nm[0], nm[1]),
        "roe": roe(0),
        "roe_chg": _chg(roe(0), roe(1)),
        "roa": roa(0),
        "roa_chg": _chg(roa(0), roa(1)),
        "leverage": lev[0],
        "leverage_chg": _chg(lev[0], lev[1]),
        "debt_to_equity": div(g("long_term_debt", 0) or 0.0, equity[0]) if equity[0] and equity[0] > 0 else None,
    }
    return {k: _nan(v) for k, v in feats.items()}


def fundamental_features(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> tuple[dict[str, float], date | None]:
    x = Inputs(snapshot(con, cik, as_of))
    feats = compute(x)
    return feats, (max(x.used) if x.used else None)

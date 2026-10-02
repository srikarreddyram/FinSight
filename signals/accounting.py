"""Accounting-quality signals (Signal Lab family 1): Piotroski F-score, Altman Z-score, Beneish M-score,
accruals ratio. Standard textbook definitions; every input comes from a point-in-time Snapshot, and the
panel records the latest filing date used (info_date) so leakage tests can check it.

A score is NaN when any of its inputs is missing (banks have no current assets or cost of sales, for
instance) rather than silently computed from a subset; the PRD's sector-neutral ranks handle the gaps.
"""

from __future__ import annotations

import math
from datetime import date

import duckdb

from signals.base import NAN, Inputs, div, market_cap, snapshot


def piotroski(x: Inputs) -> tuple[float, int]:
    """(F-score 0-9 or NaN, number of the 9 tests that could be computed)."""
    ni0, ni1 = x.get("net_income", 0), x.get("net_income", 1)
    a0, a1, a2 = x.get("assets", 0), x.get("assets", 1), x.get("assets", 2)
    cfo0 = x.get("cfo", 0)
    roa0, roa1 = div(ni0, a1), div(ni1, a2)
    ltd0, ltd1 = x.get("long_term_debt", 0) or 0.0, x.get("long_term_debt", 1) or 0.0  # no debt tag = no debt
    cr0 = div(x.get("current_assets", 0), x.get("current_liabilities", 0))
    cr1 = div(x.get("current_assets", 1), x.get("current_liabilities", 1))
    sh0, sh1 = x.get("shares_diluted", 0), x.get("shares_diluted", 1)
    gm0 = div(x.gross_profit(0), x.get("revenue", 0))
    gm1 = div(x.gross_profit(1), x.get("revenue", 1))
    at0, at1 = div(x.get("revenue", 0), a1), div(x.get("revenue", 1), a2)

    def test(cond, *inputs):
        if any(v is None for v in inputs):
            return None
        try:
            return int(cond())
        except ZeroDivisionError:  # a zero denominator (some filers tag total assets as 0 in a year)
            return None

    tests = [
        test(lambda: roa0 > 0, roa0),
        test(lambda: cfo0 > 0, cfo0),
        test(lambda: roa0 > roa1, roa0, roa1),
        test(lambda: cfo0 / a1 > roa0, cfo0, a1, roa0),
        test(lambda: ltd0 / a0 <= ltd1 / a1, a0, a1),
        test(lambda: cr0 > cr1, cr0, cr1),
        test(lambda: sh0 <= sh1, sh0, sh1),
        test(lambda: gm0 > gm1, gm0, gm1),
        test(lambda: at0 > at1, at0, at1),
    ]
    known = [t for t in tests if t is not None]
    return (float(sum(known)) if len(known) == 9 else NAN), len(known)


def accruals(x: Inputs) -> float:
    """(Net income − operating cash flow) / average total assets. High = earnings not backed by cash."""
    ni, cfo, a0, a1 = x.get("net_income", 0), x.get("cfo", 0), x.get("assets", 0), x.get("assets", 1)
    if None in (ni, cfo, a0, a1) or a0 + a1 <= 0:
        return NAN
    return (ni - cfo) / ((a0 + a1) / 2)


def altman_z(x: Inputs, market_cap: float | None) -> float:
    """Original Altman (1968) Z-score. Below ~1.8 is the distress zone."""
    ta, ca, cl = x.get("assets", 0), x.get("current_assets", 0), x.get("current_liabilities", 0)
    re_, ebit, sales, tl = x.get("retained_earnings", 0), x.ebit(0), x.get("revenue", 0), x.total_liabilities(0)
    if None in (ta, ca, cl, re_, ebit, sales, tl, market_cap) or not ta or not tl:
        return NAN
    return 1.2 * (ca - cl) / ta + 1.4 * re_ / ta + 3.3 * ebit / ta + 0.6 * market_cap / tl + 1.0 * sales / ta


def beneish_m(x: Inputs) -> float:
    """Beneish (1999) 8-variable M-score. Above ~-1.78 flags likely earnings manipulation."""
    g = x.get
    need = {
        k: (g(k, 0), g(k, 1))
        for k in (
            "receivables",
            "revenue",
            "current_assets",
            "ppe_net",
            "assets",
            "depreciation",
            "sga",
            "current_liabilities",
            "net_income",
            "cfo",
        )
    }
    gp0, gp1 = x.gross_profit(0), x.gross_profit(1)
    ltd0, ltd1 = g("long_term_debt", 0) or 0.0, g("long_term_debt", 1) or 0.0
    if gp0 is None or gp1 is None or any(v is None for pair in need.values() for v in pair):
        return NAN
    (rec0, rec1), (s0, s1) = need["receivables"], need["revenue"]
    (ca0, ca1), (ppe0, ppe1), (ta0, ta1) = need["current_assets"], need["ppe_net"], need["assets"]
    (dep0, dep1), (sga0, sga1), (cl0, cl1) = need["depreciation"], need["sga"], need["current_liabilities"]
    ni0, cfo0 = need["net_income"][0], need["cfo"][0]
    try:
        dsri = (rec0 / s0) / (rec1 / s1)
        gmi = (gp1 / s1) / (gp0 / s0)
        aqi = (1 - (ca0 + ppe0) / ta0) / (1 - (ca1 + ppe1) / ta1)
        sgi = s0 / s1
        depi = (dep1 / (dep1 + ppe1)) / (dep0 / (dep0 + ppe0))
        sgai = (sga0 / s0) / (sga1 / s1)
        lvgi = ((cl0 + ltd0) / ta0) / ((cl1 + ltd1) / ta1)
        tata = (ni0 - cfo0) / ta0
    except ZeroDivisionError:
        return NAN
    return (
        -4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi + 0.115 * depi - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi
    )


def accounting_features(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> tuple[dict[str, float], date | None]:
    snap = snapshot(con, cik, as_of)
    x = Inputs(snap)
    f, f_n = piotroski(x)
    feats = {
        "f_score": f,
        "f_score_tests": float(f_n),
        "accruals": accruals(x),
        "altman_z": altman_z(x, market_cap(con, snap, cik, x)),
        "beneish_m": beneish_m(x),
    }
    feats = {k: (NAN if v is None or (isinstance(v, float) and math.isinf(v)) else v) for k, v in feats.items()}
    return feats, (max(x.used) if x.used else None)

"""Risk Engine pillar measures from filings (platform PRD, Module 7), point-in-time like every Signal Lab family.

Financial health and earnings quality come from XBRL; disclosure and event risk from 10-K text and EDGAR's
filing index. The market pillar is computed from prices for the whole panel at once (risk/market.py), and
some measures already exist as signals (Altman Z, accruals, Beneish M, leverage, 10-K similarity).
Higher values mean more risk for every measure here except the ratios named "coverage" and "ratio".
"""

from __future__ import annotations

import math
import re
import statistics
from datetime import date, timedelta

import duckdb

from signals.base import NAN, Inputs, div, snapshot
from warehouse.fundamentals import lineage

CAP_LEVERAGE = 20.0  # net debt / EBITDA when EBITDA is negative but there is net debt: the worst bucket
CAP_COVERAGE = 100.0  # interest coverage when there is no interest to pay


def _nan(v):
    return NAN if v is None or (isinstance(v, float) and math.isinf(v)) else v


def health_quality(x: Inputs) -> dict[str, float]:
    g = x.get
    ebit, dep = x.ebit(0), g("depreciation", 0)
    ebitda = ebit + dep if ebit is not None and dep is not None else ebit
    cash = g("cash", 0)
    debt = (g("long_term_debt", 0) or 0.0) + (g("short_term_debt", 0) or 0.0)
    net_debt = debt - cash if cash is not None else None
    if net_debt is None or ebitda is None:
        nd_ebitda = None
    elif ebitda > 0:
        nd_ebitda = max(-5.0, min(CAP_LEVERAGE, net_debt / ebitda))
    else:
        nd_ebitda = CAP_LEVERAGE if net_debt > 0 else None
    interest = g("interest_expense", 0)
    if ebit is None:
        coverage = None
    elif interest and interest > 0:
        coverage = max(-10.0, min(CAP_COVERAGE, ebit / interest))
    else:
        coverage = CAP_COVERAGE if debt == 0 else None  # no debt: nothing to cover; debt but no tag: unknown
    ca, cl, inv = g("current_assets", 0), g("current_liabilities", 0), g("inventory", 0)
    cfo = g("cfo", 0)
    burn = None if cfo is None or cash is None else (div(-cfo, cash) if cfo < 0 else 0.0)
    roa = [div(g("net_income", y), g("assets", y)) for y in range(5)]
    roa = [r for r in roa if r is not None]
    d0, d1 = g("dividends", 0), g("dividends", 1)
    if d1 and d1 > 0:
        cut = float((d0 or 0.0) < 0.75 * d1)
    else:
        cut = 0.0 if d1 is not None or d0 is not None or x.snap.fiscal_year_ends else None  # no dividend: no cut
    return {k: _nan(v) for k, v in {
        "net_debt_to_ebitda": nd_ebitda,
        "interest_coverage": coverage,
        "current_ratio": div(ca, cl),
        "quick_ratio": div(ca - (inv or 0.0), cl) if ca is not None else None,
        "cash_burn": burn,
        "earnings_vol": statistics.stdev(roa) if len(roa) >= 3 else None,
        "dividend_cut": cut,
    }.items()}  # fmt: skip


def health_quality_features(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> tuple[dict[str, float], date | None]:
    x = Inputs(snapshot(con, cik, as_of), years=5)
    feats = health_quality(x)
    return feats, (max(x.used) if x.used else None)


_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_GOING_CONCERN = re.compile(
    r"substantial doubt (?:about|as to|regarding) (?:the company['’]?s|our|its) ability to continue as a going concern", re.I
)
_GC_HEDGE = re.compile(r"\b(?:no|not|could|may|might|would|alleviat\w*)\b", re.I)
_MW = re.compile(r"material weakness", re.I)
_MW_NEGATED = re.compile(r"\b(?:no|not|did not|has not|have not|were no|was no|absence of|remediat\w*)\b", re.I)
_NOT_EFFECTIVE = re.compile(r"internal control over financial reporting (?:was|were|is) not effective", re.I)


def going_concern(text: str) -> bool:
    """A going-concern doubt stated as fact; "could raise substantial doubt" in a risk factor is not one."""
    for s in _SENTENCE.split(text):
        m = _GOING_CONCERN.search(s)
        if m and not _GC_HEDGE.search(s[: m.start()]):
            return True
    return False


def material_weakness(item_9a: str) -> bool:
    """Item 9A reports a material weakness (or concludes internal control was not effective), as opposed to
    the routine "we did not identify any material weakness" or a weakness remediated in an earlier year."""
    if _NOT_EFFECTIVE.search(item_9a):
        return True
    return any(_MW.search(s) and not _MW_NEGATED.search(s) for s in _SENTENCE.split(item_9a))


def disclosure_event_features(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> tuple[dict[str, float], date | None]:
    ciks = lineage(con, cik)
    ph = ", ".join("?" * len(ciks))
    feats: dict[str, float] = dict.fromkeys(("going_concern", "material_weakness"), NAN)
    info: list[date] = []
    latest = con.execute(
        f"select accn, filed_at from filings where cik in ({ph}) and form like '10-K%' and filed_at + interval 1 day <= ? "
        "and accn in (select accn from filing_text) order by filed_at desc limit 1",
        [*ciks, as_of],
    ).fetchone()
    if latest:
        texts = dict(con.execute("select item, text from filing_text where accn = ?", [latest[0]]).fetchall())
        feats["going_concern"] = float(any(going_concern(texts.get(i) or "") for i in ("1A", "7", "9A")))
        if texts.get("9A"):
            feats["material_weakness"] = float(material_weakness(texts["9A"]))
        info.append(latest[1] + timedelta(days=1))

    def count(cond: str, days: int) -> float:
        return float(con.execute(
            f"select count(*) from filing_index where cik in ({ph}) and {cond} "
            "and filed_at + interval 1 day <= ? and filed_at > ?",
            [*ciks, as_of, as_of - timedelta(days=days)],
        ).fetchone()[0])  # fmt: skip

    has_index = con.execute(f"select count(*) from filing_index where cik in ({ph})", ciks).fetchone()[0] > 0
    feats |= (
        {
            "late_filings_12m": count("form like 'NT 10-%'", 365),
            "amended_10k_12m": count("form = '10-K/A'", 365),
            "auditor_change_24m": count("form like '8-K%' and items like '%4.01%'", 730),
            "non_reliance_24m": count("form like '8-K%' and items like '%4.02%'", 730),
        }
        if has_index
        else dict.fromkeys(("late_filings_12m", "amended_10k_12m", "auditor_change_24m", "non_reliance_24m"), NAN)
    )
    return feats, (max(info) if info else None)

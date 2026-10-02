"""Fiscal-year conventions.

Convention used everywhere: fiscal year N is the one that *ends* in calendar year N, in the company's
fiscal-year-end month. So Infosys FY26 = Apr 2025-Mar 2026, Apple FY2024 = Oct 2023-Sep 2024, and
Best Buy FY2024 = Feb 2023-Jan 2024. Fiscal labels and calendar periods are stored separately so
"last year" can be resolved per company.
"""

from __future__ import annotations

import calendar
import re
from datetime import date


def label(fiscal_year: int, period: str = "FY") -> str:
    fy = f"FY{fiscal_year % 100:02d}"
    return fy if period == "FY" else f"{period} {fy}"


def _add_months(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def period_bounds(fiscal_year: int, period: str, fye_month: int) -> tuple[date, date]:
    """Calendar start/end dates of a fiscal year or quarter."""
    fy_end_y, fy_end_m = fiscal_year, fye_month
    start_y, start_m = _add_months(fy_end_y, fy_end_m, -11)
    if period == "FY":
        return date(start_y, start_m, 1), _month_end(fy_end_y, fy_end_m)
    q = int(period[1])
    q_start = _add_months(start_y, start_m, 3 * (q - 1))
    q_end = _add_months(start_y, start_m, 3 * q - 1)
    return date(q_start[0], q_start[1], 1), _month_end(*q_end)


def fiscal_year_of(d: date, fye_month: int) -> int:
    """The fiscal year a calendar date falls in."""
    return d.year if d.month <= fye_month else d.year + 1


def quarter_of(d: date, fye_month: int) -> str:
    fy = fiscal_year_of(d, fye_month)
    start = period_bounds(fy, "FY", fye_month)[0]
    months = (d.year - start.year) * 12 + d.month - start.month
    return f"Q{months // 3 + 1}"


_RANGE = re.compile(r"\b((?:19|20)\d{2})\s*[-–/]\s*(\d{4}|\d{2})\b(?!\s*[-/]\s*\d)")  # 2024-25 -> 2025
_FY_PATTERNS = [
    re.compile(r"\bFY\s?'?(\d{4})\b", re.I),  # FY2024, FY 2024
    re.compile(r"\bFY\s?'?(\d{2})\b", re.I),  # FY24, FY'24
    re.compile(r"\bfiscal(?:\s+year)?\s+(\d{4})\b", re.I),  # fiscal 2024, fiscal year 2024
    re.compile(r"\b((?:19|20)\d{2})\b"),  # bare years
]


def explicit_years(text: str) -> list[int]:
    """Fiscal years written explicitly in a question, e.g. 'FY24', 'fiscal 2023', '2024-25'."""
    found: set[int] = set()
    consumed: list[tuple[int, int]] = []
    for m in _RANGE.finditer(text):
        start, end = int(m.group(1)), int(m.group(2))
        end = end if end > 100 else start // 100 * 100 + end
        if end == start + 1:  # Indian-style "2024-25" names the year ending in 2025
            found.add(end)
            consumed.append(m.span())
    for pat in _FY_PATTERNS:
        for m in pat.finditer(text):
            if any(s <= m.start() < e for s, e in consumed):
                continue
            consumed.append(m.span())
            y = int(m.group(1))
            if y < 100:
                y += 2000
            if 1990 <= y <= 2100:
                found.add(y)
    return sorted(found)


_RELATIVE = [
    (re.compile(r"\blast\s+(\d+|two|three|four|five)\s+(?:fiscal\s+)?years\b", re.I), "last_n"),
    (re.compile(r"\bpast\s+(\d+|two|three|four|five)\s+(?:fiscal\s+)?years\b", re.I), "last_n"),
    (re.compile(r"\bover\s+(\d+|two|three|four|five)\s+years\b", re.I), "last_n"),
    (re.compile(r"\b(?:last|previous|prior)\s+(?:fiscal\s+)?year\b", re.I), "last"),
    (re.compile(r"\b(?:latest|most recent|this|current)\s+(?:fiscal\s+)?year\b", re.I), "latest"),
    (re.compile(r"\byear[- ]over[- ]year\b|\byoy\b", re.I), "latest_two"),
]
_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5}


def relative_years(text: str, available: list[int]) -> list[int] | None:
    """Resolve phrases like 'last year' or 'last three years' against the fiscal years we hold for a company.

    'last year' means the most recent *completed* fiscal year we have filings for, which differs by
    company: for Infosys in Sep 2026 that is FY26 (ended Mar 2026), for a December filer it is FY2025.
    """
    if not available:
        return None
    avail = sorted(set(available))
    for pat, kind in _RELATIVE:
        m = pat.search(text)
        if not m:
            continue
        if kind == "last_n":
            n = m.group(1)
            n = _WORDS.get(n.lower()) if not n.isdigit() else int(n)
            return avail[-n:] if n else None
        if kind in ("last", "latest"):
            return avail[-1:]
        if kind == "latest_two":
            return avail[-2:]
    return None

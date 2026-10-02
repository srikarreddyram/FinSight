"""Shared plumbing for Signal Lab families: annual inputs from a point-in-time Snapshot (tracking the newest
filing used, for the panel's info_date audit) and market capitalisation."""

from __future__ import annotations

from collections import OrderedDict
from datetime import date

import duckdb

from warehouse.fundamentals import Snapshot, Value

NAN = float("nan")

_SNAPSHOTS: OrderedDict[tuple, Snapshot] = OrderedDict()


def snapshot(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> Snapshot:
    """One Snapshot per (company, date) shared by every family: the panel asks for the same one several times
    in a row, once per family."""
    key = (con, cik, as_of)  # the connection itself, not id(): a closed one's id can be reused
    if key in _SNAPSHOTS:
        _SNAPSHOTS.move_to_end(key)
    else:
        _SNAPSHOTS[key] = Snapshot(con, cik, as_of)
        if len(_SNAPSHOTS) > 16:
            _SNAPSHOTS.popitem(last=False)
    return _SNAPSHOTS[key]


class Inputs:
    """Annual values by item and year offset (0 = latest fiscal year), tracking the newest filing used."""

    def __init__(self, snap: Snapshot, years: int = 3):
        self.snap = snap
        self.years = years
        self._cache: dict[str, list[Value | None]] = {}
        self.used: list[date] = []

    def get(self, item: str, year: int) -> float | None:
        if item not in self._cache:
            self._cache[item] = self.snap.annual(item, self.years)
        vals = self._cache[item]
        v = vals[year] if year < len(vals) else None
        if v is None:
            return None
        self.used.append(v.available_at)
        return v.value

    def gross_profit(self, year: int) -> float | None:
        gp = self.get("gross_profit", year)
        if gp is not None:
            return gp
        rev, cogs = self.get("revenue", year), self.get("cogs", year)
        return rev - cogs if rev is not None and cogs is not None else None

    def ebit(self, year: int) -> float | None:
        """Operating income; where it isn't tagged, pre-tax income plus interest expense (pre-tax income
        alone if no interest line is tagged either, e.g. Nike: a small understatement)."""
        oi = self.get("operating_income", year)
        if oi is not None:
            return oi
        pretax = self.get("pretax_income", year)
        return None if pretax is None else pretax + (self.get("interest_expense", year) or 0.0)

    def total_liabilities(self, year: int) -> float | None:
        tl = self.get("liabilities", year)
        if tl is not None:
            return tl
        ta, eq = self.get("assets", year), self.get("equity_total", year)
        return ta - eq if ta is not None and eq is not None else None


def div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


SPLIT_TOLERANCE = 0.2  # a day whose raw close is >20% off what its total return implies is a split, not a dividend


def split_factor(con: duckdb.DuckDBPyConnection, ticker: str, after: date, through: date) -> float:
    """Shares multiply by this between `after` and `through` (20 for a 20-for-1 split, 0.1 for a 1-for-10
    reverse). Split days are found from the stored basis-free data: on an ordinary day yesterday's raw close
    × (1 + total return) is today's raw close; on a split day it is off by the split ratio."""
    rows = con.execute(
        "select raw_close, ret from prices where ticker = ? and day <= ? "
        "and day >= coalesce((select max(day) from prices where ticker = ? and day <= ?), ?) order by day",
        [ticker, through, ticker, after, after],
    ).fetchall()
    factor = 1.0
    for (prev, _), (close, ret) in zip(rows, rows[1:], strict=False):
        if prev and close and ret is not None:
            r = prev * (1 + ret) / close
            if abs(r - 1) > SPLIT_TOLERANCE:
                factor *= r
    return factor


def market_cap(con: duckdb.DuckDBPyConnection, snap: Snapshot, cik: int, x: Inputs) -> float | None:
    """Cover-page shares outstanding × the raw close on the last trading day on or before as_of, with the
    share count carried through any split between the cover date and as_of (Amazon's April 2022 10-Q
    counts pre-split shares; its June 30 price is post-split)."""
    shares = snap.latest_shares_outstanding(con, cik)
    row = con.execute(
        "select p.ticker, p.raw_close from prices p join companies c on c.ticker = p.ticker "
        "where c.cik = ? and p.day <= ? order by p.day desc limit 1",
        [cik, snap.as_of],
    ).fetchone()
    if shares is None or row is None or row[1] is None:
        return None
    x.used.append(shares.available_at)
    return shares.value * split_factor(con, row[0], shares.period_end, snap.as_of) * row[1]

"""Point-in-time reads. Every feature in the Signal Lab reads the warehouse through these functions, never
through raw SQL on `facts`, so the look-ahead rule lives in one place (tests/test_lookahead.py).

Rule: as of date t, only rows with available_at <= t exist. For each reported period, the value is the
latest version already public at t: the first-reported value unless a restatement was already out.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import duckdb

_PERIOD_KEY = "cik, taxonomy, concept, unit, period_start, period_end"
_COLUMNS = "cik, taxonomy, concept, unit, value, period_start, period_end, filed_at, available_at, accn, form, fy, fp"


def _rows(cur: duckdb.DuckDBPyConnection) -> list[dict]:
    names = [d[0] for d in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def _filters(ciks: Iterable[int] | None, concepts: Iterable[str] | None) -> tuple[str, list]:
    sql, params = "", []
    if ciks is not None:
        ciks = list(ciks)
        sql += f" and cik in ({', '.join('?' * len(ciks))})"
        params += ciks
    if concepts is not None:
        concepts = list(concepts)
        sql += f" and concept in ({', '.join('?' * len(concepts))})"
        params += concepts
    return sql, params


def facts_asof(
    con: duckdb.DuckDBPyConnection,
    as_of: date,
    ciks: Iterable[int] | None = None,
    concepts: Iterable[str] | None = None,
) -> list[dict]:
    """One row per reported period: the latest version public on `as_of`."""
    where, params = _filters(ciks, concepts)
    cur = con.execute(
        f"""
        select {_COLUMNS} from facts
        where available_at <= ? {where}
        qualify row_number() over (partition by {_PERIOD_KEY} order by filed_at desc, accn desc) = 1
        order by cik, concept, period_end
        """,
        [as_of, *params],
    )
    return _rows(cur)


def first_reported(
    con: duckdb.DuckDBPyConnection, ciks: Iterable[int] | None = None, concepts: Iterable[str] | None = None
) -> list[dict]:
    """One row per reported period: the value as originally filed (for the restatement study)."""
    where, params = _filters(ciks, concepts)
    cur = con.execute(
        f"""
        select {_COLUMNS} from facts where true {where}
        qualify row_number() over (partition by {_PERIOD_KEY} order by filed_at, accn) = 1
        order by cik, concept, period_end
        """,
        params,
    )
    return _rows(cur)


def latest_value(con: duckdb.DuckDBPyConnection, cik: int, concept: str, as_of: date, unit: str = "USD") -> float | None:
    """The most recent period's value known on `as_of`. For duration concepts, ties on period end go to the
    longest period (the annual figure over a quarter ending the same day)."""
    cur = con.execute(
        f"""
        with known as (
            select {_COLUMNS} from facts
            where available_at <= ? and cik = ? and concept = ? and unit = ?
            qualify row_number() over (partition by {_PERIOD_KEY} order by filed_at desc, accn desc) = 1
        )
        select value from known
        order by period_end desc, coalesce(period_end - period_start, 0) desc
        limit 1
        """,
        [as_of, cik, concept, unit],
    )
    row = cur.fetchone()
    return row[0] if row else None

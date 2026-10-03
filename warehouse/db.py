"""DuckDB schema for the warehouse. Every fact keeps the date it became public; nothing is ever overwritten."""

from __future__ import annotations

from pathlib import Path

import duckdb

from app.config import get_settings

SCHEMA = """
create table if not exists companies (
    cik              integer primary key,
    ticker           varchar,
    name             varchar,
    sector           varchar,
    listed_from      date,
    delisted_on      date,
    in_universe_from date,
    in_universe_to   date
);

create table if not exists filings (
    accn       varchar primary key,
    cik        integer not null,
    form       varchar,
    period_end date,
    filed_at   date not null,
    fy         integer,
    fp         varchar
);

-- One row per reported value. A restatement arrives as a new accession, so it is a new row.
create table if not exists facts (
    cik          integer not null,
    taxonomy     varchar not null,
    concept      varchar not null,
    unit         varchar not null,
    value        double  not null,
    period_start date,             -- null for balance-sheet instants
    period_end   date    not null,
    filed_at     date    not null,
    available_at date    not null, -- filed_at + 1 day: the first day the value is tradeable
    accn         varchar not null,
    form         varchar,
    fy           integer,
    fp           varchar
);
create index if not exists facts_lookup on facts (cik, concept, available_at);

-- Basis-free price history (see warehouse/prices.py): values here never change after the fact.
create table if not exists prices (
    ticker     varchar not null,
    day        date    not null,
    raw_close  double,           -- as traded that day (later splits undone)
    ret        double,           -- daily total return, dividends included
    raw_volume double,
    source     varchar,
    primary key (ticker, day)
);

create table if not exists filing_text (
    accn       varchar not null,
    cik        integer not null,
    item       varchar not null,  -- 10-K Item code, e.g. 1A
    section    varchar not null,  -- canonical name, e.g. Risk Factors
    text       varchar,
    word_count integer,
    primary key (accn, item)
);

alter table companies add column if not exists sic integer;

-- Index membership spans: one row per continuous stay (a company can leave and rejoin). end_date is the first
-- day it was no longer a member (null = still a member); start_date null = a member before the history begins.
create table if not exists universe (
    cik        integer not null,
    ticker     varchar,
    name       varchar,
    start_date date,
    end_date   date,
    source     varchar
);
alter table universe add column if not exists index_name varchar default 'sp500';  -- sp500, sp400 or sp600

-- EDGAR's filing index for risk events: late-filing notices, amendments, and 8-K items (4.01 auditor change,
-- 4.02 non-reliance on past financials). Public from filed_at + 1 day, like everything else.
create table if not exists filing_index (
    cik       integer not null,
    accn      varchar not null,
    form      varchar not null,
    filed_at  date not null,
    items     varchar,
    primary key (accn, cik)
);

-- A company that reorganised under a new CIK: the successor's history continues the predecessor's.
create table if not exists cik_links (
    successor   integer not null,
    predecessor integer not null,
    day         date
);
"""


def default_path() -> Path:
    return get_settings().data_dir / "warehouse.duckdb"


def connect(path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open (and create if needed) the warehouse. Pass ":memory:" for tests."""
    target = str(path or default_path())
    if target != ":memory:":
        Path(target).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(target)
    con.execute(SCHEMA)
    return con

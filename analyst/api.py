"""Endpoints for the Analyst's research notes.

GET  /analyst                     the latest notes across companies, newest first
GET  /analyst/{ticker}            the latest note on the company, or null if none was written
POST /analyst/{ticker}/context    step one of writing a note: read the 10-K, facts, news and data; returns counts
POST /analyst/{ticker}            write today's note (or, with refresh=true, rewrite it): one LLM call

A note is cached per company per day in data/analyst. Building its context reads the warehouse (read-only, for the
length of the request), the live price and news feeds, and the dashboard's data; the context step keeps it for ten
minutes for the note that follows.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
from fastapi import APIRouter, HTTPException

from analyst.context import Item, as_json, facts, tenk_items
from analyst.note import write_note
from warehouse import db

log = logging.getLogger(__name__)
router = APIRouter(prefix="/analyst", tags=["analyst"])

CACHE = Path("data/analyst")
CONTEXT_TTL = 600
_locks: dict[str, threading.Lock] = {}
_context: dict[str, tuple[float, list[dict]]] = {}


def _path(ticker: str) -> Path:
    return CACHE / f"{ticker}_{date.today()}.json"


def _pct(v: float | None, signed: bool = True) -> str:
    if v is None:
        return "–"
    return f"{'−' if v < 0 else ('+' if signed else '')}{abs(v) * 100:.1f}%"


def finsight_items(row: dict, start: int) -> list[Item]:
    """FinSight's own view of the company: model outputs and price behaviour, as citable items."""
    from news import api as moves_api

    out: list[Item] = []

    def add(title: str, text: str, value: bool = False) -> None:
        out.append(Item(f"D{start + len(out)}", "data", title, text, meta={"value": value}))

    if row.get("risk_grade"):
        add("FinSight risk grade", f"{row.get('risk_label') or 'grade'} ({row['risk_grade']} of 5)", value=True)
    if row.get("expected_vol") is not None:
        add("Expected 12-month volatility for stocks graded like it", _pct(row["expected_vol"], signed=False), value=True)
    if row.get("severe_loss_rate") is not None:
        add(
            "Share of similarly graded stocks that fell 40% or more within a year",
            _pct(row["severe_loss_rate"], signed=False),
            value=True,
        )
    for d in [d for d in row.get("risk_drivers") or [] if d.get("value")][:3]:  # a bank has no quick ratio
        add(f"{d['label']} ({d['effect']})", d["value"].replace("-", "−"), value=True)
    try:
        m = moves_api._move(row, "1m")
        add("Price change over the past month", _pct(m.change), value=True)
        add("Market's part of that change (S&P 500)", _pct(m.market), value=True)
        add("Sector's part of that change", _pct(m.sector), value=True)
        add("Company-specific part of that change", _pct(m.company), value=True)
    except Exception as e:  # noqa: BLE001 - the note works without live prices
        log.warning("move for %s: %s", row["ticker"], e)
    try:
        e = moves_api.earnings_reactions(row["ticker"])["summary"]
        if e.get("count"):
            add("Typical two-day move around earnings, vs S&P 500 (median absolute)", f"±{e['typical'] * 100:.1f}%", value=True)
            add("Earnings reports after which the stock beat the market", f"{e['up']} of {e['count']}", value=True)
            last = e["last"]
            add(f"Reaction to the latest earnings report ({last['date']}), vs S&P 500", _pct(last["vs_market"]), value=True)
    except Exception as e:  # noqa: BLE001
        log.warning("earnings for %s: %s", row["ticker"], e)
    return out


def news_items(row: dict) -> list[Item]:
    from news import sources

    found = sources.evidence(row.get("name") or row["ticker"], row.get("cik"), date.today() - timedelta(days=30))
    return [
        Item(
            f"N{i + 1}",
            "news",
            e.title,
            url=e.url,
            meta={"date": e.published.date().isoformat(), "source": e.source, "kind": e.kind},
        )
        for i, e in enumerate(found[:14])
    ]


def filing_items(row: dict) -> list[Item]:
    from app.store import get_embedders

    emb = get_embedders()
    con = duckdb.connect(str(db.default_path()), read_only=True)
    try:
        return [
            *tenk_items(con, row["cik"], date.today(), emb.embed_docs, emb.embed_query),
            *facts(con, row["cik"], date.today()),
        ]
    finally:
        con.close()


def build_items(row: dict) -> list[dict]:
    """The note's numbered context; the filings, the news and the price data are fetched at the same time."""
    with ThreadPoolExecutor(3) as pool:
        filed, news, data = (pool.submit(f, row) for f in (filing_items, news_items, lambda r: finsight_items(r, 1)))
        return as_json([*filed.result(), *news.result(), *data.result()])


def summarise(items: list[dict]) -> dict:
    n = Counter(i["kind"] for i in items)
    filed = next((i["meta"].get("filed") for i in items if i["kind"] == "tenk"), None)
    return {"tenk": n["tenk"], "facts": n["fact"], "news": n["news"], "data": n["data"], "filed": filed}


@router.get("")
def list_notes(limit: int = 8) -> list[dict]:
    """The latest note on each company that has one, newest first."""
    from news.api import _watchlist

    latest: dict[str, Path] = {}
    for f in sorted(CACHE.glob("*_*.json")):  # dated names sort by day, so the last one per company is its latest
        latest[f.stem.rsplit("_", 1)[0]] = f
    rows = _watchlist()
    out = []
    for t, f in latest.items():
        n = json.loads(f.read_text())
        r = rows.get(t, {})
        out.append({"ticker": t, "name": r.get("name") or t, "sector": r.get("sector"), "headline": n["headline"],
                    "generated": n["generated"], "bull": len(n["bull"]), "bear": len(n["bear"]), "watch": len(n["watch"])})  # fmt: skip
    return sorted(out, key=lambda n: n["generated"], reverse=True)[:limit]


@router.get("/{ticker}")
def get_note(ticker: str) -> dict | None:
    found = sorted(CACHE.glob(f"{ticker.upper()}_*.json"))
    return json.loads(found[-1].read_text()) if found else None


@router.post("/{ticker}/context")
def gather(ticker: str) -> dict:
    from news.api import _company

    row = _company(ticker)
    items = build_items(row)
    _context[row["ticker"]] = (time.time(), items)
    return summarise(items)


@router.post("/{ticker}")
def make_note(ticker: str, refresh: bool = False) -> dict:
    from app.llm import LLMError, QuotaExhausted, get_llm
    from news.api import _company

    row = _company(ticker)
    t = row["ticker"]
    path = _path(t)
    lock = _locks.setdefault(t, threading.Lock())
    with lock:  # two clicks on the same company write one note
        if path.exists() and not refresh:
            return json.loads(path.read_text())
        hit = _context.pop(t, None)
        items = hit[1] if hit and time.time() - hit[0] < CONTEXT_TTL else build_items(row)
        if not any(i["kind"] in ("tenk", "fact") for i in items):
            raise HTTPException(422, f"No filings on record for {t}")
        try:
            note = write_note(row.get("name") or t, t, row.get("sector"), items, get_llm())
        except QuotaExhausted as e:
            raise HTTPException(429, "The daily analysis limit has been reached; try again tomorrow.") from e
        except LLMError as e:
            raise HTTPException(502, f"The note didn't finish: {e}") from e
        note["built"] = datetime.now(UTC).isoformat()
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(note))
        return note

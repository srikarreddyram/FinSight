"""A company's events on one track: its 10-K and 10-Q filings, 8-Ks named by what they announce (earnings with
the two-session price reaction against the S&P 500), and insider purchases and sales by name and title."""

from __future__ import annotations

from datetime import date, timedelta

import duckdb
import numpy as np
import pandas as pd

from news.earnings import reactions
from news.sources import ITEMS, collapse_reports
from research.changes import filing_url
from warehouse.fundamentals import lineage

FORMS = ("10-K", "10-K/A", "10-Q", "8-K", "8-K/A", "NT 10-K", "NT 10-Q")
KIND = {"2.02": "earnings", "5.02": "leadership", "2.01": "deal", "1.01": "deal", "1.02": "deal", "8.01": "other"}


def _closes(con: duckdb.DuckDBPyConnection, ticker: str, since: date) -> pd.DataFrame:
    """Total-return levels for the stock and SPY from the warehouse's daily returns."""
    df = con.execute(
        "select day, ticker, ret from prices where ticker in (?, 'SPY') and day >= ? order by day",
        [ticker, since - timedelta(days=10)],
    ).df()
    if df.empty:
        return pd.DataFrame()
    wide = df.pivot(index="day", columns="ticker", values="ret").fillna(0.0)
    wide.index = pd.to_datetime(wide.index).date
    return (1 + wide).cumprod()


def _kind(form: str, items: list[str]) -> str:
    if form.startswith("NT"):
        return "late"
    if form.startswith(("10-K", "10-Q")):
        return "report"
    for i in items:
        if i in KIND and KIND[i] != "other":
            return KIND[i]
    return "event"


def timeline(con: duckdb.DuckDBPyConnection, cik: int, ticker: str, since: date) -> list[dict]:
    ciks = lineage(con, cik)
    marks = ", ".join("?" * len(ciks))
    events: list[dict] = []
    rows = con.execute(
        f"select cik, accn, form, filed_at, items from filing_index where cik in ({marks}) and filed_at >= ? "
        f"and form in ({', '.join('?' * len(FORMS))}) order by filed_at desc",
        [*ciks, since, *FORMS],
    ).fetchall()
    earnings: list[date] = []
    for filer, accn, form, filed, items in rows:
        codes = [i for i in (items or "").split(",") if i]
        labels = [ITEMS[i] for i in codes if i in ITEMS and i != "9.01"]
        kind = _kind(form, codes)
        title = {"10-K": "Annual report (10-K)", "10-Q": "Quarterly report (10-Q)", "10-K/A": "Annual report amended", "NT 10-K": "Late annual report notice",
                 "NT 10-Q": "Late quarterly report notice"}.get(form) or (", ".join(labels) if labels else "Current report (8-K)")  # fmt: skip
        events.append({"date": str(filed), "kind": kind, "title": title, "form": form, "url": filing_url(filer, accn)})
        if "2.02" in codes:
            earnings.append(filed)

    # The price reaction to each earnings report, against the S&P 500.
    closes = _closes(con, ticker, since)
    if not closes.empty and ticker in closes:
        days = set(collapse_reports(sorted(earnings)))
        moved = {r["date"]: r for r in reactions(closes, ticker, sorted(days))}
        for e in events:
            if e["kind"] != "earnings":
                continue
            if date.fromisoformat(e["date"]) not in days:  # a second results filing for the same report
                e["kind"] = "event"
                continue
            r = moved.get(e["date"])
            e["reaction"] = None if r is None else {"change": r["change"], "vs_market": r["vs_market"]}

    # Insider purchases and sales, one event per Form 4.
    trades = con.execute(
        f"select accession, filed_at, trans_date, code, shares, price, owner_name, owner_title, director, officer "
        f"from insider_trades where issuer_cik in ({marks}) and filed_at >= ? order by filed_at desc",
        [*ciks, since],
    ).df()
    for accn, g in trades.groupby("accession", sort=False):
        first = g.iloc[0]
        shares = float(g["shares"].sum())
        value = float((g["shares"] * g["price"]).sum())
        role = first["owner_title"] or ("Director" if first["director"] else "Officer")
        events.append({
            "date": str(pd.Timestamp(first["filed_at"]).date()), "kind": "insider", "form": "4",
            "title": f"{'Bought' if first['code'] == 'P' else 'Sold'} {shares:,.0f} shares",
            "insider": {"name": _name(first["owner_name"]), "role": _title(str(role)),
                        "side": "buy" if first["code"] == "P" else "sell", "shares": shares,
                        "price": float(value / shares) if shares else None, "value": value if np.isfinite(value) else None},
            "url": filing_url(cik, str(accn)),
        })  # fmt: skip
    return sorted(events, key=lambda e: e["date"], reverse=True)


def _name(raw: str | None) -> str:
    """SEC lists owners as 'Last First Middle'; show 'First Middle Last'."""
    if not raw:
        return "Insider"
    parts = str(raw).split()
    return " ".join([*parts[1:], parts[0]]).title() if len(parts) > 1 else str(raw).title()


_KEEP = {"CEO", "CFO", "COO", "CTO", "CIO", "CMO", "EVP", "SVP", "VP", "GC", "US", "II", "III", "IV", "NA", "AI"}


def _title(role: str) -> str:
    """Officer titles arrive in capitals ('EVP: CHIEF LEGAL OFFICER'): title-case them, keeping abbreviations."""
    if not role.isupper():
        return role
    return " ".join(w if w.strip(":,.&()") in _KEEP else w.capitalize() for w in role.split())

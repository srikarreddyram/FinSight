"""Four fiscal years of a company's main financial lines, each figure with the filing it was reported in (the
latest filing to report that period), and the ratios computed from them."""

from __future__ import annotations

from datetime import date, timedelta

import duckdb

from analyst.context import FACT_ITEMS
from research.changes import filing_url
from warehouse.fundamentals import Snapshot

YEARS = 4
RATIOS = [
    ("Gross margin", "gross_profit", "revenue"),
    ("Operating margin", "operating_income", "revenue"),
    ("Net margin", "net_income", "revenue"),
]


def financials(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> dict | None:
    snap = Snapshot(con, cik, as_of)
    ends = snap.fiscal_year_ends[:YEARS]
    if not ends:
        return None
    vals = {item: snap.annual(item, YEARS) for item, _ in FACT_ITEMS}
    rows = []
    for item, label in FACT_ITEMS:
        cells = []
        for v in vals[item]:
            if v is None:
                cells.append(None)
                continue
            filer = v.cik or cik
            cells.append({
                "value": v.value, "form": v.form, "accn": v.accn, "filed": str(v.available_at - timedelta(days=1)),
                "url": filing_url(filer, v.accn) if v.accn else None,
            })  # fmt: skip
        if any(cells):
            rows.append({"item": item, "label": label, "values": cells})
    ratios = []
    for label, num, den in RATIOS:
        values = [(n.value / d.value) if n and d and d.value else None for n, d in zip(vals[num], vals[den], strict=False)]
        if any(v is not None for v in values):
            ratios.append({"label": label, "values": values, "formula": f"{dict(FACT_ITEMS)[num]} ÷ {dict(FACT_ITEMS)[den]}"})
    return {"years": [str(e) for e in ends], "rows": rows, "ratios": ratios}

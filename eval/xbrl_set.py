"""A test set with an answer key nobody had to write: what each 10-K's own XBRL data says, e.g. "What was 3M's
capital expenditure in FY2018?" -> 1,577,000,000.

The answers come from the warehouse; the gold pages are those where that value sits on a matching table row of
the parsed filing. Grading is a numeric match, so no LLM judge is involved. These are plain lookups on the
FinanceBench filings: they check parsing and retrieval on questions the system was never tuned on, not reasoning.

    uv run python -m eval.xbrl_set              # writes eval/xbrl_set.yaml
    uv run python -m eval.run --runs F --sets xbrl
"""

from __future__ import annotations

import json
import logging
import random
import re
from pathlib import Path

import duckdb
import yaml

from app.config import get_settings
from app.numbers import appears_in
from ingest.manifest import load_documents
from ingest.parse import cache_path

log = logging.getLogger(__name__)
PER_METRIC = 7

# metric -> (XBRL concepts, row label pattern, question wording)
METRICS: dict[str, tuple[list[str], str, str]] = {
    "revenue": (
        ["Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueGoodsNet"],
        r"revenue|net sales|^sales|total sales",
        "What was {co}'s total revenue in FY{y}?",
    ),
    "cost_of_sales": (
        ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold"],
        r"cost of|costs of",
        "What was {co}'s cost of sales in FY{y}?",
    ),
    "operating_income": (
        ["OperatingIncomeLoss"],
        r"operating (income|profit|loss|earnings)|income from operations|earnings from operations",
        "What was {co}'s operating income in FY{y}?",
    ),
    # NetIncomeLoss excludes minority interests, so the question has to say so (MGM reports both lines).
    "net_income": (
        ["NetIncomeLoss"],
        r"net (income|earnings|loss|\(loss\))",
        "What was the net income attributable to {co}'s shareholders in FY{y}?",
    ),
    "total_assets": (["Assets"], r"total assets", "What were {co}'s total assets at the end of FY{y}?"),
    "current_assets": (["AssetsCurrent"], r"total current assets", "What were {co}'s total current assets at the end of FY{y}?"),
    "current_liabilities": (
        ["LiabilitiesCurrent"],
        r"total current liabilities",
        "What were {co}'s total current liabilities at the end of FY{y}?",
    ),
    "inventory": (["InventoryNet"], r"inventor", "What was {co}'s inventory at the end of FY{y}?"),
    "accounts_payable": (["AccountsPayableCurrent"], r"payable", "What were {co}'s accounts payable at the end of FY{y}?"),
    "net_ppe": (
        ["PropertyPlantAndEquipmentNet"],
        r"property|plant|equipment",
        "What was {co}'s net property, plant and equipment at the end of FY{y}?",
    ),
    "operating_cash_flow": (
        ["NetCashProvidedByUsedInOperatingActivities"],
        r"operating activities|operations",
        "What was {co}'s net cash from operating activities in FY{y}?",
    ),
    "capex": (
        ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
        r"property|plant|equipment|capital expenditure|purchases of|additions to",
        "What was {co}'s capital expenditure in FY{y}?",
    ),
    "cash": (
        ["CashAndCashEquivalentsAtCarryingValue"],
        r"cash and",
        "What were {co}'s cash and cash equivalents at the end of FY{y}?",
    ),
    "depreciation": (
        ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet", "DepreciationAndAmortization"],
        r"depreciation",
        "What was {co}'s depreciation and amortization in FY{y}?",
    ),
}


def pages_with_value(tables: list[dict], value: float, label: str) -> list[int]:
    """Pages where `value` (in dollars, thousands or millions) sits on a table row whose label matches."""
    targets = [x for x in (abs(value), abs(value) / 1e3, abs(value) / 1e6) if x >= 10]
    pages = set()
    for t in tables:
        for row in t.get("rows") or []:
            if row and re.search(label, str(row[0]), re.I) and any(appears_in(x, " ".join(map(str, row[1:]))) for x in targets):
                pages.add(t["page"])
    return sorted(pages)


def build() -> list[dict]:
    s = get_settings()
    con = duckdb.connect(str(s.data_dir / "warehouse.duckdb"), read_only=True)
    ciks = dict(con.sql("select ticker, cik from companies where ticker is not null").fetchall())
    docs = [m for m in load_documents().values() if m.track == "financebench" and m.doc_type == "10-K"]
    by_metric: dict[str, list[dict]] = {m: [] for m in METRICS}
    for d in docs:
        path, cik = cache_path(d.doc_id, "structured"), ciks.get(d.ticker)
        if cik is None or not path.exists():
            log.info("skipping %s: no CIK or parse", d.doc_id)
            continue
        tables = [e for e in json.loads(path.read_text())["elements"] if e["kind"] == "table"]
        for metric, (concepts, label, wording) in METRICS.items():
            listed = ", ".join(f"'{c}'" for c in concepts)
            # Periods end within days of the fiscal year end, not in its calendar year: Johnson & Johnson's FY2022
            # ended on 1 January 2023, and matching on the year picked up FY2021's balances.
            rows = con.sql(
                f"""select distinct value from facts where cik = {cik} and concept in ({listed}) and form = '10-K' and unit = 'USD'
                and abs(date_diff('day', period_end, DATE '{d.period_end.isoformat()}')) <= 10
                and (period_start is null or date_diff('day', period_start, period_end) between 340 and 380)"""
            ).fetchall()
            found = {v: p for (v,) in rows if v and (p := pages_with_value(tables, v, label))}
            if len(found) != 1:  # none on the page, or several values that can't be told apart
                continue
            value, pages = next(iter(found.items()))
            by_metric[metric].append(
                {
                    "question": wording.format(co=d.company, y=d.fiscal_year),
                    "answer": str(int(abs(value))),
                    "tickers": [d.ticker],
                    "evidence": [{"doc_id": d.doc_id, "page": p} for p in pages],
                }
            )
    rng = random.Random(7)
    picked = [q for metric in METRICS for q in rng.sample(by_metric[metric], min(PER_METRIC, len(by_metric[metric])))]
    log.info("%d possible questions, %d picked", sum(map(len, by_metric.values())), len(picked))
    return [{"id": f"xbrl_{i:03d}", **q} for i, q in enumerate(picked, 1)]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    out = Path(__file__).resolve().parent / "xbrl_set.yaml"
    header = "# Generated by eval/xbrl_set.py: plain lookups whose answers and gold pages come from each filing's XBRL data.\n"
    out.write_text(header + yaml.safe_dump({"questions": build()}, sort_keys=False, allow_unicode=True))


if __name__ == "__main__":
    main()

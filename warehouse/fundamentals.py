"""Standard annual line items from XBRL, point-in-time.

Companies tag the same line item with different concepts, and switch concepts over time (revenue moved to
RevenueFromContractWithCustomer... with ASC 606 in 2018), so each item lists concepts in priority order and
the choice is made per fiscal year. Coverage across the FinanceBench companies was measured before choosing
the lists (see docs/phase-b-signals.md).

    snap = Snapshot(con, cik, as_of)       # everything public on as_of, one query
    snap.annual("revenue", n=3)            # [(fiscal_year_end, value), ...] newest first
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date

import duckdb

from warehouse import pit

# item -> (concepts in priority order, "flow" = income/cash-flow duration, "stock" = balance-sheet instant)
ITEMS: dict[str, tuple[tuple[str, ...], str]] = {
    "revenue": (
        (
            "Revenues",
            "RegulatedAndUnregulatedOperatingRevenue",  # utilities (American Water)
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueNet",
            "SalesRevenueGoodsNet",
            "RevenuesNetOfInterestExpense",
        ),
        "flow",
    ),
    "cogs": (
        (
            "CostOfGoodsAndServicesSold",
            "CostOfRevenue",
            "CostOfGoodsSold",
            "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
        ),
        "flow",
    ),
    "gross_profit": (("GrossProfit",), "flow"),
    "operating_income": (("OperatingIncomeLoss",), "flow"),
    "pretax_income": (
        (
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        ),
        "flow",
    ),
    "interest_expense": (("InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"), "flow"),
    "net_income": (("NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"), "flow"),
    "cfo": (
        ("NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
        "flow",
    ),
    "capex": (("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"), "flow"),
    "depreciation": (
        (
            "DepreciationDepletionAndAmortization",
            "DepreciationAndAmortization",
            "DepreciationAmortizationAndAccretionNet",
            "Depreciation",
        ),
        "flow",
    ),
    "sga": (("SellingGeneralAndAdministrativeExpense",), "flow"),
    "shares_diluted": (("WeightedAverageNumberOfDilutedSharesOutstanding",), "flow"),
    "assets": (("Assets",), "stock"),
    "current_assets": (("AssetsCurrent",), "stock"),
    "current_liabilities": (("LiabilitiesCurrent",), "stock"),
    "liabilities": (("Liabilities",), "stock"),
    "equity": (("StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"), "stock"),
    "equity_total": (
        ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "StockholdersEquity"),
        "stock",
    ),
    "long_term_debt": (
        ("LongTermDebtNoncurrent", "LongTermDebt", "LongTermDebtAndCapitalLeaseObligations"),
        "stock",
    ),
    "retained_earnings": (("RetainedEarningsAccumulatedDeficit",), "stock"),
    "receivables": (("AccountsReceivableNetCurrent", "ReceivablesNetCurrent"), "stock"),
    "ppe_net": (("PropertyPlantAndEquipmentNet",), "stock"),
    # Risk Engine (financial health): liquidity, net debt, payouts.
    "cash": (
        (
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            "CashAndDueFromBanks",
            "Cash",
        ),
        "stock",
    ),
    "inventory": (("InventoryNet", "InventoryFinishedGoodsNetOfReserves"), "stock"),
    "short_term_debt": (("LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings", "CommercialPaper"), "stock"),
    "dividends": (("PaymentsOfDividendsCommonStock", "PaymentsOfDividends"), "flow"),
}
ANNUAL_DAYS = (340, 380)  # a fiscal year, allowing 52/53-week years
ANNUAL_FORMS = ("10-K", "20-F", "40-F")


@dataclass(frozen=True)
class Value:
    period_end: date
    value: float
    available_at: date


def lineage(con: duckdb.DuckDBPyConnection, cik: int) -> list[int]:
    """The company and every predecessor it reorganised from (warehouse.universe's cik_links), newest first."""
    out, frontier = [cik], [cik]
    while frontier:
        preds = [r[0] for r in con.execute(
            f"select predecessor from cik_links where successor in ({', '.join('?' * len(frontier))})", frontier
        ).fetchall()]  # fmt: skip
        frontier = [p for p in preds if p not in out]
        out += frontier
    return out


def _latest_per_period(rows: list[dict]) -> list[dict]:
    """Across a company's lineage the same period can be reported under two CIKs (a successor's comparatives):
    keep the version filed last, the same rule pit.facts_asof applies within one CIK."""
    best: dict[tuple, dict] = {}
    for r in rows:
        key = (r["concept"], r["unit"], r["period_start"], r["period_end"])
        if key not in best or (r["filed_at"], r["accn"]) > (best[key]["filed_at"], best[key]["accn"]):
            best[key] = r
    return list(best.values())


class Snapshot:
    """Every core fact about one company (and its predecessors) public on `as_of`, with annual accessors."""

    def __init__(self, con: duckdb.DuckDBPyConnection, cik: int, as_of: date):
        self.as_of = as_of
        self.ciks = lineage(con, cik)
        concepts = {c for cs, _ in ITEMS.values() for c in cs}
        self._by_concept: dict[str, list[dict]] = defaultdict(list)
        for r in _latest_per_period(pit.facts_asof(con, as_of, ciks=self.ciks, concepts=concepts)):
            if r["unit"] in ("USD", "shares"):
                self._by_concept[r["concept"]].append(r)
        self.fiscal_year_ends = self._fiscal_year_ends()

    def _fiscal_year_ends(self) -> list[date]:
        # Only annual reports define fiscal years: some 10-Qs tag trailing-twelve-month figures (Amazon does),
        # which look annual but end at a quarter.
        ends = set()
        for concept in ("NetIncomeLoss", "ProfitLoss", *ITEMS["revenue"][0]):
            for r in self._by_concept.get(concept, []):
                if not (r["form"] or "").startswith(ANNUAL_FORMS):
                    continue
                if r["period_start"] and ANNUAL_DAYS[0] <= (r["period_end"] - r["period_start"]).days <= ANNUAL_DAYS[1]:
                    ends.add(r["period_end"])
        return sorted(ends, reverse=True)

    def _value(self, item: str, fy_end: date) -> Value | None:
        concepts, kind = ITEMS[item]
        for concept in concepts:  # priority order, decided per fiscal year
            for r in self._by_concept.get(concept, []):
                if r["period_end"] != fy_end:
                    continue
                if kind == "flow":
                    if not r["period_start"] or not ANNUAL_DAYS[0] <= (fy_end - r["period_start"]).days <= ANNUAL_DAYS[1]:
                        continue
                elif r["period_start"] is not None:
                    continue
                return Value(fy_end, r["value"], r["available_at"])
        return None

    def annual(self, item: str, n: int = 2) -> list[Value | None]:
        """The item for the newest n fiscal years known on as_of (None where not reported), newest first."""
        return [self._value(item, end) for end in self.fiscal_year_ends[:n]]

    def latest_shares_outstanding(self, con: duckdb.DuckDBPyConnection, cik: int) -> Value | None:
        """Shares outstanding from the most recent cover page (dei), used for market cap."""
        rows = pit.facts_asof(con, self.as_of, ciks=self.ciks, concepts=["EntityCommonStockSharesOutstanding"])
        rows = [r for r in rows if r["unit"] == "shares"]
        if not rows:
            return None
        latest = max(r["period_end"] for r in rows)
        # Some filers report each share class as its own row on the cover date: add them up.
        same = [r for r in rows if r["period_end"] == latest]
        return Value(latest, sum(r["value"] for r in same), max(r["available_at"] for r in same))

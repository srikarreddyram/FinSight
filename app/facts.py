"""Standard financials from the warehouse's XBRL facts, as a source the Copilot can quote.

For each company the question names, one source lists the standard line items for the latest fiscal year asked
about (or, with no year in the question, its latest 10-K's), and the years before it for averages and growth.
They are read point-in-time on the day after that 10-K was filed, so a later restatement can't replace a figure. Values are in $ millions, as
most statements print them, so the model copies a figure like any table's and Python verifies it the same way.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta

import duckdb

from app import fiscal
from app.schemas import Chunk, Company, Hit, ParsedQuery
from warehouse import db
from warehouse.fundamentals import Snapshot, lineage

log = logging.getLogger(__name__)

# (warehouse.fundamentals item, label as financial statements word it)
LINES: list[tuple[str, str]] = [
    ("revenue", "Total revenue / net sales"),
    ("cogs", "Cost of sales"),
    ("gross_profit", "Gross profit"),
    ("sga", "Selling, general and administrative expense"),
    ("operating_income", "Operating income"),
    ("interest_expense", "Interest expense"),
    ("pretax_income", "Income before income taxes"),
    ("net_income", "Net income attributable to the company"),
    ("depreciation", "Depreciation and amortization"),
    ("cfo", "Net cash provided by operating activities"),
    ("capex", "Purchases of property, plant and equipment (capex)"),
    ("dividends", "Dividends paid"),
    ("cash", "Cash and cash equivalents"),
    ("short_term_investments", "Short-term investments / marketable securities"),
    ("receivables", "Accounts receivable, net"),
    ("inventory", "Inventories"),
    ("current_assets", "Total current assets"),
    ("ppe_net", "Property, plant and equipment, net"),
    ("assets", "Total assets"),
    ("accounts_payable", "Accounts payable"),
    ("current_liabilities", "Total current liabilities"),
    ("short_term_debt", "Short-term debt and current portion of long-term debt"),
    ("long_term_debt", "Long-term debt"),
    ("liabilities", "Total liabilities"),
    ("equity", "Shareholders' equity"),
    ("shares_diluted", "Diluted weighted-average shares (millions)"),
]
MAX_YEARS = 5
# Annual facts would answer a quarterly question with the wrong period.
_QUARTERLY = re.compile(r"\bQ[1-4]\b|quarter", re.I)


def fiscal_year(end: date, fye_month: int) -> int:
    """The fiscal year a period ending on `end` closes, allowing 52/53-week years that end a few days into the
    next month (Johnson & Johnson's FY2022 ended on 1 January 2023)."""
    return min(
        (end.year - 1, end.year, end.year + 1),
        key=lambda y: abs((fiscal.period_bounds(y, "FY", fye_month)[1] - end).days),
    )


def filed_on(con: duckdb.DuckDBPyConnection, ciks: list[int], year: int, fye_month: int) -> date | None:
    """When the 10-K for `year` was filed: the first annual report of a period ending at that fiscal year's end."""
    end = fiscal.period_bounds(year, "FY", fye_month)[1]
    row = con.execute(
        f"select min(filed_at) from facts where cik in ({', '.join('?' * len(ciks))}) and form like '10-K%' "
        "and period_start is not null and abs(date_diff('day', period_end, ?)) <= 10",
        [*ciks, end],
    ).fetchone()
    return row[0] if row else None


def _millions(v: float) -> str:
    s = f"{abs(v) / 1e6:,.3f}".rstrip("0").rstrip(".")
    return f"-{s}" if v < 0 else s


def table(con: duckdb.DuckDBPyConnection, company: Company, cik: int, year: int, n: int = 3) -> str | None:
    """The standard line items for fiscal `year` and the n - 1 years before, as that year's 10-K reported them."""
    fye = company.fiscal_year_end_month
    when = filed_on(con, lineage(con, cik), year, fye)
    if when is None:
        return None
    snap = Snapshot(con, cik, when + timedelta(days=1))
    ends = snap.fiscal_year_ends[:n]
    if not ends or fiscal_year(ends[0], fye) != year:
        return None
    rows = []
    for item, label in LINES:
        vals = snap.annual(item, len(ends))
        if any(vals):
            rows.append(f"| {label} | " + " | ".join(_millions(v.value) if v else "–" for v in vals) + " |")
    if not rows:
        return None
    head = " | ".join(f"FY{fiscal_year(e, fye)} ({e:%b} {e.day}, {e.year})" for e in ends)
    return (
        f"{company.name} ({company.ticker}) standard financials from its XBRL filings, as of the FY{year} 10-K "
        f"filed {when:%b} {when.day}, {when.year}; $ millions\n"
        f"| Line item | {head} |\n|---|{'---|' * len(ends)}\n" + "\n".join(rows)
    )


def sources(
    pq: ParsedQuery | None,
    question: str,
    companies: dict[str, Company],
    tenk_docs: dict[tuple[str, int], str],
    con: duckdb.DuckDBPyConnection | None = None,
) -> list[Hit]:
    """One facts source per company the question names, for the latest fiscal year it asks about, or with no
    year in the question, the latest 10-K indexed for it.
    tenk_docs: (ticker, fiscal year) -> doc_id of the indexed 10-K, so the citation names the filing."""
    if pq is None or not pq.tickers or _QUARTERLY.search(question):
        return []
    own = con is None
    try:
        con = con or duckdb.connect(str(db.default_path()), read_only=True)
    except duckdb.Error as e:
        log.warning("no warehouse for facts: %s", e)
        return []
    try:
        ciks = dict(con.execute("select ticker, cik from companies where ticker is not null").fetchall())
        explicit = fiscal.explicit_years(question)
        out = []
        for t in pq.tickers:
            # The parser resolves years against filings with text; facts go back further than the text does.
            held = [y for tk, y in tenk_docs if tk == t]
            years, co = pq.fiscal_years.get(t) or explicit or ([max(held)] if held else []), companies.get(t)
            if not years or co is None or t not in ciks:
                continue
            year = max(years)
            first = min([*years, *(y for y in explicit if y <= year)])
            text = table(con, co, ciks[t], year, min(MAX_YEARS, max(3, year - first + 1)))
            if text is None:
                continue
            end = fiscal.period_bounds(year, "FY", co.fiscal_year_end_month)[1]
            chunk = Chunk(
                chunk_id=f"facts:{t}:{year}",
                doc_id=tenk_docs.get((t, year), ""),
                ticker=t,
                company=co.name,
                doc_type="10-K",
                fiscal_year=year,
                fiscal_label=fiscal.label(year),
                period="FY",
                period_end=end.isoformat(),
                section="Financial Statements",
                heading="XBRL",
                page=0,
                page_end=0,
                chunk_type="facts",
                text=text,
                embed_text="",
                sparse_text="",
                summary="Standard financials from XBRL",
            )
            out.append(Hit(chunk=chunk))
        return out
    finally:
        if own:
            con.close()

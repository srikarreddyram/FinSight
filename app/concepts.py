"""Financial-concept expansion for retrieval.

Analyst questions name derived metrics ("quick ratio", "operating margin", "FCF conversion") while the
evidence lives in statement line items ("Total current liabilities", "Operating income", "Purchases of
property, plant and equipment"). In the FinanceBench ablation, 48 of 51 recall misses in the full
system found the right filing but not the right page, mostly on such ratio questions. Expanding the
retrieval query with the inputs of the metric, and steering it toward the primary statements, closes
that vocabulary gap. The expansion only feeds search; the reranker and the LLM still see the question.
"""

from __future__ import annotations

import re

# pattern -> (line items / synonyms that carry the inputs, statements where they live)
CONCEPTS: list[tuple[re.Pattern, str, list[str]]] = [
    (
        re.compile(r"quick ratio|acid[- ]test", re.I),
        "cash and cash equivalents marketable securities accounts receivable total current liabilities",
        ["balance sheet"],
    ),
    (
        re.compile(r"current ratio|working capital|liquidity", re.I),
        "total current assets total current liabilities cash and cash equivalents",
        ["balance sheet"],
    ),
    (
        re.compile(r"operating margin|operating profit margin|operating income margin", re.I),
        "operating income net sales total revenue",
        ["income statement"],
    ),
    (
        re.compile(r"gross margin|gross profit", re.I),
        "gross profit net sales revenue cost of sales cost of goods sold",
        ["income statement"],
    ),
    (re.compile(r"net (profit )?margin|net income margin", re.I), "net income net sales total revenue", ["income statement"]),
    (
        re.compile(r"ebitda", re.I),
        "operating income depreciation and amortization net sales",
        ["income statement", "cash flow statement"],
    ),
    (
        re.compile(r"free cash ?flow|fcf|cash ?flow conversion|cash conversion", re.I),
        "net cash provided by operating activities purchases of property plant and equipment capital expenditures net income",
        ["cash flow statement"],
    ),
    (
        re.compile(r"capex|capital expenditure|capital[- ]intensive|capital intensity", re.I),
        "purchases of property plant and equipment capital expenditures total assets revenue",
        ["cash flow statement", "balance sheet"],
    ),
    (
        re.compile(r"inventory turnover|inventory days|days inventory|dio\b", re.I),
        "cost of sales cost of goods sold inventories",
        ["income statement", "balance sheet"],
    ),
    (
        re.compile(r"(receivable|dso|days sales outstanding)", re.I),
        "accounts receivable net revenue net sales",
        ["balance sheet"],
    ),
    (re.compile(r"payable|dpo\b|days payable", re.I), "accounts payable cost of sales", ["balance sheet"]),
    (
        re.compile(r"asset turnover|fixed asset turnover", re.I),
        "net sales revenue property plant and equipment net total assets",
        ["income statement", "balance sheet"],
    ),
    (
        re.compile(r"return on (assets|equity|invested capital)|\broa\b|\broe\b|\broic\b", re.I),
        "net income total assets total shareholders equity",
        ["income statement", "balance sheet"],
    ),
    (
        re.compile(r"debt[- ]to[- ]equity|leverage|debt ratio|solvency", re.I),
        "long-term debt short-term borrowings total debt total shareholders equity",
        ["balance sheet"],
    ),
    (re.compile(r"interest coverage|times interest", re.I), "operating income interest expense", ["income statement"]),
    (re.compile(r"dividend|payout ratio", re.I), "dividends paid cash dividends per share", ["cash flow statement"]),
    (
        re.compile(r"effective tax rate|tax rate", re.I),
        "provision for income taxes income before income taxes",
        ["income statement"],
    ),
    (re.compile(r"\beps\b|earnings per share", re.I), "earnings per share diluted basic net income", ["income statement"]),
    (re.compile(r"revenue growth|sales growth|top line", re.I), "net sales total revenue", ["income statement"]),
    (
        re.compile(r"(operating )?cash flow ratio", re.I),
        "net cash provided by operating activities total current liabilities",
        ["cash flow statement", "balance sheet"],
    ),
    # Balance-sheet line items named outright in the question ("divided by total current liabilities").
    (
        re.compile(
            r"current (assets|liabilities)|total assets|total liabilities|shareholders.? equity|"
            r"stockholders.? equity|accounts payable|inventor(y|ies)\b|property,? plant",
            re.I,
        ),
        "total current assets total current liabilities",
        ["balance sheet"],
    ),
    (
        re.compile(r"cash from operations|operating cash flow|cfo\b", re.I),
        "net cash provided by operating activities",
        ["cash flow statement"],
    ),
    (
        re.compile(r"securities registered|registered to trade|trading symbol", re.I),
        "title of each class trading symbol name of each exchange on which registered section 12(b)",
        ["cover page"],
    ),
]


def expand(question: str) -> tuple[str, bool]:
    """Return (search query, is_statement_question). The search query appends the line items behind any
    metric the question names; is_statement_question is True when the answer should come from the
    primary financial statements."""
    extra: list[str] = []
    statements: list[str] = []
    for pat, items, where in CONCEPTS:
        if pat.search(question):
            extra.append(items)
            statements += where
    if not extra:
        return question, False
    terms = " ".join(dict.fromkeys(extra + list(dict.fromkeys(statements))))
    return f"{question}\n{terms}", any(s != "cover page" for s in statements)

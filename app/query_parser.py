"""Turn a question into metadata filters (companies, fiscal years, section / document-type hints).

A deterministic pass (company names, aliases, tickers, "FY24", "2024-25", "last three years") always
runs. When an LLM is available, a small model adds what regexes miss (implicit comparisons, section
intent, per-company sub-queries). Relative years are always resolved in Python, per company, against
the fiscal years actually in the index, so "last year" means FY26 for Infosys and FY2025 for a
December filer.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass

from app import fiscal
from app.schemas import Company, ParsedQuery

log = logging.getLogger(__name__)

SECTIONS = [
    "MD&A",
    "Risk Factors",
    "Financial Statements",
    "Notes",
    "Business",
    "Market Risk",
    "Governance",
    "Legal Proceedings",
    "Q&A",
    "Prepared Remarks",
    "Auditor's Report",
    "Sustainability",
]
DOC_TYPES = ["10-K", "10-Q", "20-F", "8-K", "annual_report", "earnings_call"]

_SECTION_HINTS = [
    (re.compile(r"\brisk", re.I), ["Risk Factors"]),
    (
        re.compile(
            r"\bmanagement (said|say|attribut|explain|comment|discuss)|\bdrove\b|\bdriv(er|ers|en|ing)\b|\bwhy\b|\breason", re.I
        ),
        ["MD&A", "Prepared Remarks", "Q&A"],
    ),
    (
        re.compile(
            r"cash flow statement|balance sheet|income statement|statement of (cash|income|operations|financial)|P&L", re.I
        ),
        ["Financial Statements"],
    ),
    (re.compile(r"\bnote[s]?\b|accounting polic|contingenc|lease|debt maturit|segment", re.I), ["Notes"]),
    (re.compile(r"\blitigation|lawsuit|legal proceeding", re.I), ["Legal Proceedings", "Notes"]),
    (re.compile(r"\bguidance|outlook|analyst|call\b", re.I), ["Prepared Remarks", "Q&A"]),
]
_DOC_HINTS = [
    (re.compile(r"\b10-?Q\b|\bQ[1-4]\b|\bquarter", re.I), ["10-Q", "earnings_call"]),
    (re.compile(r"earnings call|transcript|conference call", re.I), ["earnings_call"]),
    (re.compile(r"\b8-?K\b", re.I), ["8-K"]),
    (re.compile(r"\b10-?K\b|\b20-?F\b|annual report", re.I), ["10-K", "20-F", "annual_report"]),
]


_FORWARD = re.compile(r"\b(expect(s|ed|ing)?|guidance|outlook|forecasts?|anticipat\w+|project(s|ed|ions?))\b", re.I)


@dataclass(frozen=True)
class Vocab:
    """Words filings use as ordinary words, measured by ingest.sections: lower-case words (`plain`) and all-capital
    tokens (`caps`). A ticker in `caps` ("IT", "ARR", "COST") can't name a company bare."""

    plain: frozenset[str] = frozenset()
    caps: frozenset[str] = frozenset()


class CompanyMatcher:
    """strict: companies whose names must be written with a capital, because there are too many of them to vet
    one by one (the whole universe): 'Target' the company, not a target margin. Their tickers must also be
    three letters or more and not an ordinary acronym (vocab.caps): "IT" and "ALL" are not Gartner and Allstate."""

    def __init__(self, companies: Iterable[Company], strict: Iterable[str] = (), vocab: Vocab | None = None):
        strict = set(strict)
        vocab = vocab or Vocab()
        self.patterns: list[tuple[re.Pattern, str, bool]] = []
        for c in companies:
            names = {c.name, *c.aliases}
            for n in sorted(names, key=len, reverse=True):
                if len(n) >= 3 or not n.isalpha():
                    pat = re.compile(rf"(?<![\w&]){re.escape(n)}(?![\w&])", re.I)
                    self.patterns.append((pat, c.ticker, c.ticker in strict))
            # Tickers must be written in capitals so 'FL' or 'KO' don't fire on ordinary words.
            if c.ticker not in strict or (len(c.ticker) >= 3 and c.ticker not in vocab.caps):
                self.patterns.append((re.compile(rf"(?<![\w$]){re.escape(c.ticker)}(?![\w])"), c.ticker, False))

    def find(self, text: str) -> list[str]:
        hits: list[tuple[int, str]] = []
        for pat, ticker, strict in self.patterns:
            m = next((m for m in pat.finditer(text) if not (strict and m.group(0)[0].islower())), None)
            if m:
                hits.append((m.start(), ticker))
        out: list[str] = []
        for _, t in sorted(hits):
            if t not in out:
                out.append(t)
        return out


def resolve_years(requested: list[int], available: list[int]) -> list[int]:
    """Map requested fiscal years onto the filings we hold.

    A year's figures appear in that year's filing and as comparatives in the next one or two, so if
    FY2023 itself isn't indexed we fall back to FY2024/FY2025 filings rather than returning nothing.
    """
    if not requested or not available:
        return requested
    avail = set(available)
    exact = sorted(y for y in requested if y in avail)
    missing = [y for y in requested if y not in avail]
    extra = []
    for y in missing:
        later = [a for a in (y + 1, y + 2) if a in avail]
        if later:
            extra.append(later[0])
    out = sorted(set(exact + extra))
    return out or []


class QueryParser:
    SYSTEM = (
        "You turn an analyst's question about company filings into search filters. "
        "Only use tickers from the provided company list; leave lists empty when the question doesn't say. "
        "mentions: for each company the question refers to, its ticker and the exact words of the question that refer "
        "to it. If no words in the question refer to a company, leave it empty: never guess one. "
        "fiscal_years: only years written explicitly (FY24 -> 2024; Indian-style '2024-25' -> 2025). "
        "relative: 'last_year' / 'last_n_years' (set n_years) / 'latest' when the question uses relative time, else 'none'. "
        "sub_queries: for questions about several companies, one self-contained question per company."
    )

    def __init__(
        self,
        companies: dict[str, Company],
        available_years: dict[str, list[int]],
        llm=None,
        strict=(),
        vocab: Vocab | None = None,
    ):
        self.companies = companies
        self.available = available_years
        self.matcher = CompanyMatcher(companies.values(), strict, vocab)
        self.llm = llm

    def _candidates(self, question: str) -> dict[str, Company]:
        """The companies the LLM may pick from: all of a small corpus, but with the whole universe indexed only
        those sharing a word with the question, so the prompt stays small."""
        if len(self.companies) <= 100:
            return self.companies
        words = set(re.findall(r"[a-z0-9&]{4,}", question.lower()))
        return {
            t: c
            for t, c in self.companies.items()
            if words & set(re.findall(r"[a-z0-9&]{4,}", " ".join([c.name, *c.aliases]).lower()))
        }

    def _schema(self, tickers: Iterable[str]) -> dict:
        return {
            "type": "object",
            "properties": {
                "mentions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ticker": {"type": "string", "enum": sorted(tickers)},
                            "words": {"type": "string"},
                        },
                        "required": ["ticker", "words"],
                        "additionalProperties": False,
                    },
                },
                "fiscal_years": {"type": "array", "items": {"type": "integer"}},
                "relative": {"type": "string", "enum": ["none", "last_year", "last_n_years", "latest"]},
                "n_years": {"type": "integer"},
                "sections": {"type": "array", "items": {"type": "string", "enum": SECTIONS}},
                "doc_types": {"type": "array", "items": {"type": "string", "enum": DOC_TYPES}},
                "is_comparison": {"type": "boolean"},
                "sub_queries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"ticker": {"type": "string"}, "query": {"type": "string"}},
                        "required": ["ticker", "query"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": [
                "mentions",
                "fiscal_years",
                "relative",
                "n_years",
                "sections",
                "doc_types",
                "is_comparison",
                "sub_queries",
            ],
            "additionalProperties": False,
        }

    def heuristic(self, question: str) -> ParsedQuery:
        tickers = self.matcher.find(question)
        years = fiscal.explicit_years(question)
        sections = [s for pat, secs in _SECTION_HINTS if pat.search(question) for s in secs]
        doc_types = [d for pat, ds in _DOC_HINTS if pat.search(question) for d in ds]
        pq = ParsedQuery(
            question=question,
            tickers=tickers,
            sections=list(dict.fromkeys(sections)),
            doc_types=list(dict.fromkeys(doc_types)),
            is_comparison=len(tickers) > 1,
        )
        self._resolve(pq, years, relative_text=question)
        if pq.is_comparison:
            pq.sub_queries = {t: self._single_company_query(question, t, tickers) for t in tickers}
        return pq

    def _single_company_query(self, question: str, ticker: str, all_tickers: list[str]) -> str:
        """Drop the other companies' names so each sub-query retrieves one company's evidence."""
        q = question
        for other in all_tickers:
            if other == ticker:
                continue
            c = self.companies[other]
            for n in sorted({c.name, *c.aliases, c.ticker}, key=len, reverse=True):
                q = re.sub(rf"(?<![\w&]){re.escape(n)}(?![\w&])", "", q, flags=re.I)
        q = re.sub(r"\b(and|vs\.?|versus|with)\s+(?=\W|$)", " ", q)
        q = re.sub(r"\s{2,}", " ", q).strip()
        return f"{q} ({self.companies[ticker].name})"

    def _resolve(
        self, pq: ParsedQuery, explicit: list[int], relative_text: str | None = None, relative: str = "none", n_years: int = 0
    ) -> None:
        for t in pq.tickers or []:
            avail = self.available.get(t, [])
            years: list[int] | None = None
            if explicit:
                years = resolve_years(explicit, avail)
            elif relative_text is not None:
                years = fiscal.relative_years(relative_text, avail)
            if not years and relative != "none" and avail:
                a = sorted(avail)
                years = a[-(n_years or 1) :] if relative == "last_n_years" else a[-1:]
            if years and relative_text and _FORWARD.search(relative_text):
                # Guidance for a year is published the year before: the FY2023 outlook is in the FY2022 results.
                years = sorted({*years, *(y - 1 for y in years if y - 1 in avail)})
            if years:
                pq.fiscal_years[t] = years
        if not pq.tickers and explicit:
            pq.fiscal_years["*"] = explicit

    def parse(self, question: str) -> ParsedQuery:
        pq = self.heuristic(question)
        # A name in the question settles the company, and the regex pass handles years, sections and comparisons.
        # On FinanceBench it retrieved as well as the LLM parser, for no call (all gold pages in the top 8: 71.3% vs
        # 68.7%), so the LLM only runs when the question names no company outright.
        if self.llm is None or pq.tickers:
            return pq
        candidates = self._candidates(question)
        if not candidates:
            return pq
        try:
            out = self.llm.json(
                system=self.SYSTEM,
                user=self._prompt(question, candidates),
                schema=self._schema(candidates),
                role="fast",
                max_tokens=1500,
            )
        except Exception as e:  # noqa: BLE001 - the heuristic parse is a complete fallback
            log.warning("LLM query parse failed, using heuristics: %s", e)
            return pq
        # Small models name companies that were never mentioned (Gemma filtered two company-less FinanceBench
        # questions to Adobe, the first ticker in the list). So the model must quote the words that refer to the
        # company, Python checks they are in the question, and only companies with indexed filings count.
        merged = list(
            dict.fromkeys(
                m["ticker"]
                for m in out.get("mentions", [])
                if len(m.get("words", "").strip()) >= 3
                and m["words"].strip().lower() in question.lower()
                and m["ticker"] in self.companies
                and self.available.get(m["ticker"])
            )
        )
        llm_pq = ParsedQuery(
            question=question,
            tickers=merged,
            sections=list(dict.fromkeys(out.get("sections", []) + pq.sections)),
            doc_types=list(dict.fromkeys(out.get("doc_types", []) + pq.doc_types)),
            is_comparison=len(merged) > 1,
        )
        explicit = sorted(set(fiscal.explicit_years(question)) | set(out.get("fiscal_years", [])))
        self._resolve(
            llm_pq, explicit, relative_text=question, relative=out.get("relative", "none"), n_years=out.get("n_years", 0)
        )
        if llm_pq.is_comparison:
            subs = {s["ticker"]: s["query"] for s in out.get("sub_queries", []) if s.get("ticker") in merged}
            llm_pq.sub_queries = {t: subs.get(t) or self._single_company_query(question, t, merged) for t in merged}
        return llm_pq

    def _prompt(self, question: str, companies: dict[str, Company]) -> str:
        lines = []
        for t, c in sorted(companies.items()):
            years = self.available.get(t, [])
            span = f"FY{min(years)}-FY{max(years)}" if years else "none indexed"
            aka = f" (aka {', '.join(c.aliases)})" if c.aliases else ""
            lines.append(f"- {t}: {c.name}{aka}; fiscal year ends month {c.fiscal_year_end_month}; filings {span}")
        return "Companies:\n" + "\n".join(lines) + f"\n\nQuestion: {question}"

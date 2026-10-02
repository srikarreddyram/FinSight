"""Split 10-K text into its Items (Risk Factors, MD&A, ...) for the Signal Lab's text features.

Works on plain text: EDGAR's HTML filings go through `html_to_text` first; the Copilot's parsed PDFs can be
used directly. Every Item heading appears at least twice (table of contents, body, sometimes a running page
header), and running text mentions Items all the time ("see Item 1A, Risk Factors"). Three rules pick the
body headings:

1. A candidate is "Item <code>" followed by that Item's own title (compared with spaces removed, so PDF
   kerning damage like "RIS K FACTORS" still matches) and not preceded by "see", "in", "Part I," or a quote.
2. Consecutive candidates for the same Item (running page headers) form one run that starts at the first.
3. Among all sequences of candidates in canonical Item order, choose the one with the highest total of
   log(characters covered): table-of-contents entries cover a few characters each, and one long stretch
   can't outvote a run of real sections, so the body headings win.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from html.parser import HTMLParser

import duckdb

# 10-K Items in filing order, with the canonical section names used across FinSight.
ITEMS_10K: list[tuple[str, str]] = [
    ("1", "Business"),
    ("1A", "Risk Factors"),
    ("1B", "Unresolved Staff Comments"),
    ("1C", "Cybersecurity"),
    ("2", "Properties"),
    ("3", "Legal Proceedings"),
    ("4", "Mine Safety Disclosures"),
    ("5", "Market for Common Equity"),
    ("6", "Selected Financial Data"),
    ("7", "MD&A"),
    ("7A", "Market Risk"),
    ("8", "Financial Statements"),
    ("9", "Changes in Accountants"),
    ("9A", "Controls and Procedures"),
    ("9B", "Other Information"),
    ("9C", "Foreign Jurisdiction Disclosure"),
    ("10", "Directors and Officers"),
    ("11", "Executive Compensation"),
    ("12", "Security Ownership"),
    ("13", "Related Transactions"),
    ("14", "Accountant Fees"),
    ("15", "Exhibits"),
    ("16", "Form 10-K Summary"),
]
_ORDER = {code: i for i, (code, _) in enumerate(ITEMS_10K)}
_TITLE = dict(ITEMS_10K)

# How each Item's heading title starts, lower-cased with spaces removed. Older filings use other titles for
# Items 4 and 6 ("Submission of Matters...", "(Removed and Reserved)", "[Reserved]").
_TITLE_START: dict[str, tuple[str, ...]] = {
    "1": ("business",),
    "1A": ("riskfactors",),
    "1B": ("unresolved",),
    "1C": ("cybersecurity",),
    "2": ("properties",),
    "3": ("legalproceedings",),
    "4": ("minesafety", "submission", "(removed", "removed", "[reserved", "reserved"),
    "5": ("market",),
    "6": ("selected", "[reserved", "reserved", "(reserved"),
    "7": ("management", "md&a"),
    "7A": ("quantitative",),
    "8": ("financialstatements", "consolidatedfinancial"),
    "9": ("changesin", "changesand"),
    "9A": ("controls",),
    "9B": ("otherinformation",),
    "9C": ("disclosure",),
    "10": ("directors",),
    "11": ("executivecompensation",),
    "12": ("securityownership",),
    "13": ("certainrelationships",),
    "14": ("principalaccount",),
    "15": ("exhibit",),
    "16": ("form10-k", "form10k"),
}

_ITEM = re.compile(r"(?i)\bitem[\s\xa0]*(\d{1,2}[A-C]?)(?![0-9A-Za-z])")
_PUNCT = re.compile(r"^[\s\xa0.:\-\u2013\u2014]*")
_XREF_BEFORE = re.compile(r"(?i)(?:part\s+i{1,3}v?\s*,|\bsee|\bin|\bunder|\band|\bto|\bof|\bwithin|[\u201c\"'\u2018(,])\s*$")


def _candidates(text: str) -> list[tuple[int, str]]:
    out = []
    for m in _ITEM.finditer(text):
        code = m.group(1).upper()
        if code not in _ORDER or _XREF_BEFORE.search(text[max(0, m.start() - 20) : m.start()]):
            continue
        after = text[m.end() : m.end() + 80]
        after = after[_PUNCT.match(after).end() :]
        squashed = re.sub(r"[\s\xa0]+", "", after).lower().replace("\u2019", "'")
        if squashed.startswith(_TITLE_START[code]):
            out.append((m.start(), code))
    return out


@dataclass(frozen=True)
class Section:
    item: str
    name: str
    start: int
    end: int
    text: str

    @property
    def word_count(self) -> int:
        return len(self.text.split())


def split_10k(text: str) -> dict[str, Section]:
    """Map Item code (e.g. "1A") → Section. Items that can't be found are simply absent."""
    cands = _candidates(text)
    # Collapse runs of the same Item (running page headers) into their first occurrence.
    runs = [c for i, c in enumerate(cands) if i == 0 or cands[i - 1][1] != c[1]]
    if not runs:
        return {}
    ends = [runs[i + 1][0] if i + 1 < len(runs) else len(text) for i in range(len(runs))]
    # Log of the text a run covers: many substantial sections outweigh one long stretch, so a stray
    # cross-reference can't knock out a run of real Items, and table-of-contents entries score ~nothing.
    weight = [math.log1p(end - pos) for (pos, _), end in zip(runs, ends, strict=True)]

    # Heaviest chain of runs whose Items are in strictly increasing canonical order.
    best = weight[:]
    prev = [-1] * len(runs)
    for i, (_, code) in enumerate(runs):
        for j in range(i):
            if _ORDER[runs[j][1]] < _ORDER[code] and best[j] + weight[i] > best[i]:
                best[i], prev[i] = best[j] + weight[i], j
    chain, i = [], max(range(len(runs)), key=best.__getitem__)
    while i != -1:
        chain.append(runs[i])
        i = prev[i]
    chain.reverse()

    out: dict[str, Section] = {}
    for k, (pos, code) in enumerate(chain):
        end = chain[k + 1][0] if k + 1 < len(chain) else len(text)
        out[code] = Section(item=code, name=_TITLE[code], start=pos, end=end, text=text[pos:end].strip())
    return out


class _Text(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}
    SKIP = {"script", "style", "head", "title", "ix:header"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """EDGAR filing HTML → text with one block per line (inline-XBRL header and scripts dropped)."""
    p = _Text()
    p.feed(html)
    text = "".join(p.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def store(con: duckdb.DuckDBPyConnection, accn: str, cik: int, sections: dict[str, Section]) -> int:
    con.execute("delete from filing_text where accn = ?", [accn])
    rows = [(accn, cik, s.item, s.name, s.text, s.word_count) for s in sections.values()]
    if not rows:  # none of the requested Items were found
        return 0
    con.executemany("insert into filing_text (accn, cik, item, section, text, word_count) values (?, ?, ?, ?, ?, ?)", rows)
    return len(rows)

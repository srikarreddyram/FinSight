"""Everything the Analyst may cite, each item with an ID: K (10-K passages), X (financial facts), N (news),
D (FinSight's own data). The note can only use what is listed here.

- 10-K: the latest annual report's risk-factor titles (Item 1A states each risk as a one-sentence heading) and the
  MD&A passages closest, by embedding similarity, to four questions an analyst asks (results, drivers, outlook,
  capital).
- Facts: standard annual line items from XBRL for the last three fiscal years, plus growth, margins and free cash
  flow computed here. Each has a display string; the note refers to them by ID and never types a number.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date

import duckdb
import numpy as np

from warehouse.fundamentals import Snapshot, lineage

FACT_ITEMS = [
    ("revenue", "Revenue"),
    ("gross_profit", "Gross profit"),
    ("operating_income", "Operating income"),
    ("net_income", "Net income"),
    ("cfo", "Operating cash flow"),
    ("capex", "Capital expenditure"),
    ("cash", "Cash"),
    ("long_term_debt", "Long-term debt"),
    ("equity", "Shareholders' equity"),
    ("dividends", "Dividends paid"),
]
MDA_QUESTIONS = [
    "overview of the year's results: revenue, profit and earnings performance compared with the prior year",
    "the main factors that increased or decreased revenue and gross margin",
    "outlook, guidance and expectations for the coming fiscal year",
    "liquidity, cash flow, debt, share repurchases and dividends",
]
PASSAGE_WORDS = 170
MAX_TITLES = 10


@dataclass
class Item:
    id: str
    kind: str  # tenk | fact | news | data
    title: str
    text: str = ""
    url: str | None = None
    meta: dict = field(default_factory=dict)


def money(v: float) -> str:
    sign = "−" if v < 0 else ""
    a = abs(v)
    if a >= 1e12:
        return f"{sign}${a / 1e12:.2f}T"
    if a >= 1e9:
        return f"{sign}${a / 1e9:.2f}B"
    if a >= 1e6:
        return f"{sign}${a / 1e6:.0f}M"
    return f"{sign}${a:,.0f}"


def pct(v: float) -> str:
    return f"{'−' if v < 0 else '+'}{abs(v) * 100:.1f}%"


def fy(end: date) -> str:
    return f"FY{end.year} (year to {end.strftime('%b %-d, %Y')})"


def facts(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> list[Item]:
    """Annual line items for the newest three fiscal years, then derived growth, margins and free cash flow."""
    snap = Snapshot(con, cik, as_of)
    ends = snap.fiscal_year_ends[:3]
    if not ends:
        return []
    vals = {item: snap.annual(item, 3) for item, _ in FACT_ITEMS}
    out: list[Item] = []

    def add(title: str, value: str, **meta) -> None:
        out.append(Item(f"X{len(out) + 1}", "fact", title, value, meta=meta))

    for item, label in FACT_ITEMS:
        for v in vals[item]:
            if v is not None:
                add(f"{label}, {fy(v.period_end)}", money(v.value), item=item, fy_end=str(v.period_end))
    rev, op, ni, cfo, capex = (vals[k] for k in ("revenue", "operating_income", "net_income", "cfo", "capex"))
    if len(rev) > 1 and rev[0] and rev[1] and rev[1].value:
        add(f"Revenue growth, {fy(rev[0].period_end)}", pct(rev[0].value / rev[1].value - 1), derived=True)
    for i in range(min(2, len(rev))):
        if rev[i] and rev[i].value and op[i]:
            add(f"Operating margin, {fy(rev[i].period_end)}", f"{op[i].value / rev[i].value * 100:.1f}%", derived=True)
    if rev and rev[0] and rev[0].value and ni[0]:
        add(f"Net margin, {fy(rev[0].period_end)}", f"{ni[0].value / rev[0].value * 100:.1f}%", derived=True)
    if cfo and cfo[0] and capex and capex[0]:
        add(f"Free cash flow, {fy(cfo[0].period_end)}", money(cfo[0].value - capex[0].value), derived=True)
    return out


def latest_10k(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> tuple[str, date, int, dict[str, str]] | None:
    """(accession, filing date, filer CIK, {item: text}) of the newest 10-K in the company's lineage filed by as_of."""
    ciks = lineage(con, cik)
    row = con.execute(
        f"select f.accn, f.filed_at, f.cik from filings f where f.cik in ({', '.join('?' * len(ciks))}) and f.form like '10-K%' "
        "and f.filed_at <= ? and exists (select 1 from filing_text t where t.accn = f.accn) order by f.filed_at desc limit 1",
        [*ciks, as_of],
    ).fetchone()
    if not row:
        return None
    items = dict(con.execute("select item, text from filing_text where accn = ? and item in ('1A', '7')", [row[0]]).fetchall())
    return row[0], row[1], row[2], items


_PAGE = re.compile(r"^(table of contents|.*form 10-k \d+|\d+)$", re.I)


def risk_titles(text: str, n: int = MAX_TITLES) -> list[str]:
    """Item 1A states each risk as a one-sentence heading followed by its explanation: one-sentence lines of
    8 to 50 words, in order, skipping bullets and the forward-looking boilerplate."""
    out = []
    for line in (ln.strip() for ln in text.splitlines()):
        words = line.split()
        if not 8 <= len(words) <= 50 or not line.endswith(".") or line.startswith(("•", "-", "(")) or _PAGE.match(line):
            continue
        if line.count(". ") > 0:  # more than one sentence: body text, not a heading
            continue
        low = line.lower()
        if "forward-looking" in low or low.startswith(("the risks included", "investors should", "certain written")):
            continue
        out.append(line)
        if len(out) == n:
            break
    return out


_BULLET = re.compile(r"^[•▪●◦·]\s*")


def passages(text: str, words: int = PASSAGE_WORDS) -> list[str]:
    """MD&A split into passages of about `words` words, along line boundaries; tables and page furniture dropped."""
    out, cur = [], []
    for line in (_BULLET.sub("", ln.strip()) for ln in text.splitlines()):
        if not line or _PAGE.match(line) or line.count("|") > 2:
            continue
        cur.append(line)
        if sum(len(c.split()) for c in cur) >= words:
            out.append(" ".join(cur))
            cur = []
    if sum(len(c.split()) for c in cur) > 40:
        out.append(" ".join(cur))
    return out


def passage_title(p: str, words: int = 14) -> str:
    """The passage's first words, starting at the first word: a passage that begins mid-table starts with figures."""
    text = re.sub(r"^[^A-Za-z]+(?=[A-Za-z])", "", p)
    return " ".join(text.split()[:words]) + "…"


def best_passages(chunks: list[str], embed_docs, embed_query, per_question: int = 3) -> list[str]:
    """The passages closest to each analyst question (cosine similarity of embeddings), first-seen order kept."""
    if not chunks:
        return []
    docs = np.array(embed_docs(chunks), dtype=float)
    docs /= np.linalg.norm(docs, axis=1, keepdims=True) + 1e-9
    picked: list[int] = []
    for q in MDA_QUESTIONS:
        qv = np.array(embed_query(q), dtype=float)
        qv /= np.linalg.norm(qv) + 1e-9
        for i in np.argsort(-(docs @ qv))[:per_question]:
            if int(i) not in picked:
                picked.append(int(i))
    return [chunks[i] for i in sorted(picked)]


def tenk_items(con: duckdb.DuckDBPyConnection, cik: int, as_of: date, embed_docs, embed_query) -> list[Item]:
    found = latest_10k(con, cik, as_of)
    if not found:
        return []
    accn, filed, filer, items = found
    url = f"https://www.sec.gov/Archives/edgar/data/{filer}/{accn.replace('-', '')}/{accn}-index.htm"
    out: list[Item] = []
    for t in risk_titles(items.get("1A", "")):
        out.append(Item(f"K{len(out) + 1}", "tenk", t, url=url, meta={"item": "1A", "filed": str(filed)}))
    for p in best_passages(passages(items.get("7", "")), embed_docs, embed_query):
        out.append(Item(f"K{len(out) + 1}", "tenk", passage_title(p), p, url=url, meta={"item": "7", "filed": str(filed)}))
    return out


def as_json(items: list[Item]) -> list[dict]:
    return [asdict(i) for i in items]

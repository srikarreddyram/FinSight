"""Filing-text signals (Signal Lab family 4) from the latest 10-K public at as_of and the one before it.

- Similarity of Risk Factors and MD&A to last year's (cosine of word counts). Cohen, Malloy and Nguyen's
  "Lazy Prices" finds that firms whose 10-Ks change a lot underperform: changes tend to carry news.
- Risk Factors length (log words) and its change: a growing section is new risks being disclosed.
- MD&A readability: Gunning Fog index (years of schooling to follow it); Li (2008) links hard-to-read
  reports to weaker, less persistent earnings.

A 10-K's text counts from the day after it was filed, like XBRL facts. Loughran-McDonald tone is left out
until its dictionary's licence is settled (free for academic use; commercial use needs permission).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date, timedelta
from functools import lru_cache

import duckdb

from signals.base import NAN
from warehouse.fundamentals import lineage

_WORD = re.compile(r"[a-z][a-z'-]*[a-z]|[a-z]")
_SENTENCE_END = re.compile(r"[.!?]+(?:\s|$)")
_VOWELS = re.compile(r"[aeiouy]+")
FEATURES = ("sim_risk_factors", "sim_mda", "risk_factors_words", "risk_factors_words_chg", "fog_mda")


def words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def cosine(a: Counter, b: Counter) -> float | None:
    if not a or not b:
        return None
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


def syllables(word: str) -> int:
    n = len(_VOWELS.findall(word))
    if n > 1 and (
        (word.endswith("e") and not word.endswith(("le", "ee", "ue")))  # silent e: "make"; not "table", "value"
        or (word.endswith("ed") and not word.endswith(("ted", "ded")))  # "increased"; not "reported"
        or (word.endswith("es") and not word.endswith(("ses", "zes", "ces", "ges")))  # "makes"; not "losses"
    ):
        n -= 1
    return max(1, n)


def fog(text: str) -> float | None:
    """Gunning Fog: 0.4 × (words per sentence + 100 × share of words with 3+ syllables). Lines without a
    sentence ending (table rows, headings) are dropped first so tables don't read as one endless sentence."""
    prose = "\n".join(line for line in text.splitlines() if _SENTENCE_END.search(line))
    w = words(prose)
    sentences = len(_SENTENCE_END.findall(prose))
    if len(w) < 100 or not sentences:
        return None
    complex_share = sum(syllables(x) >= 3 for x in w) / len(w)
    return 0.4 * (len(w) / sentences + 100 * complex_share)


def _latest_two(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> list[tuple[str, date]]:
    ciks = lineage(con, cik)
    return con.execute(
        f"select accn, filed_at from filings where cik in ({', '.join('?' * len(ciks))}) and form like '10-K%' "
        "and filed_at + interval 1 day <= ? and accn in (select accn from filing_text) order by filed_at desc limit 2",
        [*ciks, as_of],
    ).fetchall()


@lru_cache(maxsize=4096)
def _section(con: duckdb.DuckDBPyConnection, accn: str, item: str) -> tuple[Counter, int, float | None]:
    row = con.execute("select text from filing_text where accn = ? and item = ?", [accn, item]).fetchone()
    text = row[0] if row and row[0] else ""
    w = words(text)
    return Counter(w), len(w), (fog(text) if item == "7" else None)


def text_features(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> tuple[dict[str, float], date | None]:
    feats = dict.fromkeys(FEATURES, NAN)
    filings = _latest_two(con, cik, as_of)
    if not filings:
        return feats, None
    (cur, filed), prev = filings[0], (filings[1][0] if len(filings) > 1 else None)
    rf, rf_n, _ = _section(con, cur, "1A")
    mda, _, fog_mda = _section(con, cur, "7")
    if rf_n:
        feats["risk_factors_words"] = math.log(rf_n)
    if fog_mda is not None:
        feats["fog_mda"] = fog_mda
    if prev:
        rf0, rf0_n, _ = _section(con, prev, "1A")
        mda0, _, _ = _section(con, prev, "7")
        feats["sim_risk_factors"] = cosine(rf, rf0) if rf_n and rf0_n else NAN
        feats["sim_mda"] = cosine(mda, mda0) if mda and mda0 else NAN
        if rf_n and rf0_n:
            feats["risk_factors_words_chg"] = math.log(rf_n / rf0_n)
    return {k: NAN if v is None else v for k, v in feats.items()}, filed + timedelta(days=1)

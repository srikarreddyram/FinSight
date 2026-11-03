"""What changed in a company's Risk Factors (10-K Item 1A) since the year before.

Both years' text is split into paragraphs. Each paragraph of the new 10-K is matched to its closest paragraph in
the old one by word overlap (Jaccard similarity of their word sets):

- same      overlap of 0.92 or more: unchanged apart from a word or two
- changed   between 0.5 and 0.92: the same risk, reworded; the words added and removed are marked
- new       below 0.5: nothing like it last year
- removed   an old paragraph that no new paragraph matches at 0.5 or more

A paragraph is a heading when it is one sentence of 8-50 words, the way Item 1A states each risk.
"""

from __future__ import annotations

import difflib
import re
from datetime import date

import duckdb

from warehouse.fundamentals import lineage

SAME, CHANGED = 0.92, 0.5
_WORD = re.compile(r"[a-z0-9][a-z0-9'’-]*")
_PAGE = re.compile(r"^(table of contents|.*form 10-k\s*\d*|\d+|page \d+)$", re.I)
_BULLET = re.compile(r"^[•▪●◦·]\s*")


def paragraphs(text: str) -> list[str]:
    """Item 1A as paragraphs: one per line, page furniture and fragments of under six words dropped."""
    out = []
    for line in (_BULLET.sub("", ln.strip()) for ln in (text or "").splitlines()):
        if line and not _PAGE.match(line) and len(line.split()) >= 6:
            out.append(line)
    return out


def is_heading(p: str) -> bool:
    words = p.split()
    return 8 <= len(words) <= 50 and p.rstrip().endswith((".", ":")) and ". " not in p.rstrip(". ")


def _words(p: str) -> set[str]:
    return set(_WORD.findall(p.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a or b else 1.0


def word_diff(old: str, new: str) -> list[list[str]]:
    """[op, text] runs turning old into new, op one of '=', '+', '-'; adjacent runs of one kind merged."""
    a, b = old.split(), new.split()
    out: list[list[str]] = []

    def push(op: str, words: list[str]) -> None:
        if not words:
            return
        if out and out[-1][0] == op:
            out[-1][1] += " " + " ".join(words)
        else:
            out.append([op, " ".join(words)])

    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            push("=", a[i1:i2])
        else:
            push("-", a[i1:i2])
            push("+", b[j1:j2])
    return out


def compare(old: list[str], new: list[str]) -> dict:
    old_w, new_w = [_words(p) for p in old], [_words(p) for p in new]
    blocks, used = [], set()
    for i, p in enumerate(new):
        best, score = None, 0.0
        for j, w in enumerate(old_w):
            s = _jaccard(new_w[i], w)
            if s > score:
                best, score = j, s
        block = {"heading": is_heading(p), "score": round(score, 3)}
        if best is not None and score >= SAME:
            block |= {"status": "same", "text": p}
            used.add(best)
        elif best is not None and score >= CHANGED:
            block |= {"status": "changed", "segments": word_diff(old[best], p)}
            used.add(best)
        else:
            block |= {"status": "new", "text": p}
        blocks.append(block)
    removed = []
    for j, p in enumerate(old):
        if j in used:
            continue
        if max((_jaccard(old_w[j], w) for w in new_w), default=0.0) < CHANGED:
            removed.append({"status": "removed", "heading": is_heading(p), "text": p})
    count = {k: sum(b["status"] == k for b in blocks) for k in ("same", "changed", "new")}
    return {"summary": {**count, "removed": len(removed)}, "blocks": blocks, "removed": removed}


def filing_url(cik: int, accn: str) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/{accn}-index.htm"


def last_two_10ks(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> list[tuple[str, date, int, str]]:
    """(accession, filed, filer CIK, Item 1A text) of the company's two newest 10-Ks with a Risk Factors section."""
    ciks = lineage(con, cik)
    return con.execute(
        f"select f.accn, f.filed_at, f.cik, t.text from filings f join filing_text t on t.accn = f.accn and t.item = '1A' "
        f"where f.cik in ({', '.join('?' * len(ciks))}) and f.form = '10-K' and f.filed_at <= ? and t.word_count > 200 "
        "order by f.filed_at desc limit 2",
        [*ciks, as_of],
    ).fetchall()


def risk_changes(con: duckdb.DuckDBPyConnection, cik: int, as_of: date) -> dict | None:
    pair = last_two_10ks(con, cik, as_of)
    if len(pair) < 2:
        return None
    (n_accn, n_filed, n_cik, n_text), (o_accn, o_filed, o_cik, o_text) = pair
    new, old = paragraphs(n_text), paragraphs(o_text)
    out = compare(old, new)

    def meta(accn: str, filed: date, filer: int, text: str) -> dict:
        return {"accn": accn, "filed": str(filed), "url": filing_url(filer, accn), "words": len(text.split())}

    return {"current": meta(n_accn, n_filed, n_cik, n_text), "previous": meta(o_accn, o_filed, o_cik, o_text), **out}

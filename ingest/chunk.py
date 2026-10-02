"""Turn parsed filings into retrieval chunks with full metadata.

Text: grouped by section, ~500 tokens with 15% overlap. A chunk never spans a page boundary, so
every chunk cites exactly one page. Tables: one chunk per table (row groups for very large ones),
stored as Markdown for the LLM plus a one-line summary that is what gets embedded.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.config import Settings, get_settings
from app.schemas import Chunk, Element, ParsedDoc

log = logging.getLogger(__name__)

_TOKEN = re.compile(r"\w+|[^\w\s]")
_SENT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z(\"'])")


def n_tokens(text: str) -> int:
    """Cheap, deterministic token estimate (close to wordpiece counts for English filings)."""
    return len(_TOKEN.findall(text))


def _header(p: ParsedDoc, section: str, heading: str) -> str:
    m = p.meta
    h = f"{m.company} ({m.ticker}) {m.doc_type} {m.fiscal_label} | {section}"
    if heading and heading.lower() != section.lower():
        h += f" | {heading[:120]}"
    return h


def _make_chunk(
    p: ParsedDoc,
    *,
    kind: str,
    idx: int,
    page: int,
    page_end: int,
    section: str,
    heading: str,
    body: str,
    embed_body: str,
    sparse_body: str,
    summary: str = "",
    contextual: bool = True,
) -> Chunk:
    m = p.meta
    header = _header(p, section, heading) if contextual else ""
    return Chunk(
        chunk_id=f"{m.doc_id}:{kind}:{page}:{idx}",
        doc_id=m.doc_id,
        ticker=m.ticker,
        company=m.company,
        doc_type=m.doc_type,
        fiscal_year=m.fiscal_year,
        fiscal_label=m.fiscal_label,
        period=m.period,
        period_end=m.period_end.isoformat(),
        section=section,
        heading=heading,
        page=page,
        page_end=page_end,
        chunk_type="table" if kind == "table" else "text",
        text=f"{header}\n{body}".strip(),
        embed_text=f"{header}\n{embed_body}".strip(),
        sparse_text=f"{header}\n{sparse_body}".strip(),
        summary=summary,
    )


# --------------------------------------------------------------------------------------------
# Text chunks
# --------------------------------------------------------------------------------------------


def _split_long(text: str, limit: int) -> list[str]:
    """Split an oversized paragraph on sentence boundaries (hard-wrap as a last resort)."""
    parts, cur = [], ""
    for sent in _SENT.split(text):
        if cur and n_tokens(cur) + n_tokens(sent) > limit:
            parts.append(cur)
            cur = ""
        cur = f"{cur} {sent}".strip()
    if cur:
        parts.append(cur)
    out = []
    for part in parts:
        words = part.split()
        while n_tokens(" ".join(words)) > limit * 1.5:
            cut = max(1, len(words) // 2)
            out.append(" ".join(words[:cut]))
            words = words[cut:]
        out.append(" ".join(words))
    return out


def _tail(paras: list[str], overlap: int) -> list[str]:
    """The last ~`overlap` tokens of a chunk, cut at paragraph, then sentence, then word boundaries."""
    tail: list[str] = []
    total = 0
    for para in reversed(paras):
        if total + n_tokens(para) > overlap:
            break
        tail.insert(0, para)
        total += n_tokens(para)
    if tail:
        return tail
    sents = _SENT.split(paras[-1])
    picked: list[str] = []
    for sent in reversed(sents):
        if n_tokens(" ".join([sent, *picked])) > overlap:
            break
        picked.insert(0, sent)
    if picked:
        return [" ".join(picked)]
    words = paras[-1].split()
    picked_words: list[str] = []
    for w in reversed(words):
        if n_tokens(" ".join([w, *picked_words])) > overlap:
            break
        picked_words.insert(0, w)
    return [" ".join(picked_words)] if picked_words else []


def text_chunks(p: ParsedDoc, s: Settings) -> list[Chunk]:
    limit = s.chunk_tokens
    overlap = int(limit * s.chunk_overlap)
    chunks: list[Chunk] = []
    buf: list[str] = []
    key: tuple[str, int] | None = None  # (section, page)
    heading = ""

    def flush(carry: bool) -> list[str]:
        if not buf or key is None:
            return []
        body = "\n".join(buf)
        if n_tokens(body) >= 12:  # drop crumbs like lone page numbers
            chunks.append(
                _make_chunk(
                    p,
                    kind="text",
                    idx=len(chunks),
                    page=key[1],
                    page_end=key[1],
                    section=key[0],
                    heading=heading,
                    body=body,
                    embed_body=body,
                    sparse_body=body,
                )
            )
        if not carry:
            return []
        return _tail(buf, overlap)

    for el in p.elements:
        if el.kind == "table":
            continue
        new_key = (el.section, el.page)
        if new_key != key:
            flush(carry=False)
            buf = []
            key = new_key
        if el.kind == "heading":
            heading = el.heading
        text = f"## {el.text}" if el.kind == "heading" else el.text
        for piece in _split_long(text, limit) if n_tokens(text) > limit else [text]:
            if buf and n_tokens("\n".join(buf)) + n_tokens(piece) > limit:
                buf = flush(carry=True)
            buf.append(piece)
    flush(carry=False)
    return chunks


# --------------------------------------------------------------------------------------------
# Table chunks
# --------------------------------------------------------------------------------------------


def _rows_md(rows: list[list[str]]) -> str:
    from ingest.parse import _rows_to_markdown

    return _rows_to_markdown(rows)


def compact_md(md: str) -> str:
    """Docling pads Markdown cells for alignment; the padding costs tokens and carries no information."""
    md = re.sub(r" {2,}", " ", md)
    return re.sub(r"-{3,}", "---", md)


def _row_labels(rows: list[list[str]]) -> str:
    labels = [r[0] for r in rows[1:] if r and r[0] and not re.fullmatch(r"[\d,.$()% \-–]+", r[0])]
    return "; ".join(dict.fromkeys(labels))[:1200] if labels else ""


def heuristic_summary(el: Element) -> str:
    title = el.context or el.heading or "Table"
    cols = [c for c in (el.rows[0] if el.rows else []) if c and not c.startswith("Unnamed")][:6]
    return f"{title[:160]} (columns: {', '.join(cols)[:160]})" if cols else title[:200]


class TableSummarizer:
    """One-line LLM summaries of tables, batched and cached on disk by content hash."""

    SYSTEM = (
        "You label financial tables extracted from company filings. For each table write ONE line (max 45 words) "
        "saying what it is, which periods it covers, and its units/currency, e.g. "
        "'Consolidated income statement, FY23-FY25, ₹ crore' or 'Segment revenue by geography, 2022-2024, $ millions'. "
        "Then add the common analyst names for its key line items when they differ from the table's wording, e.g. "
        "'capex' for purchases of property, plant and equipment, 'revenue' for net sales, 'D&A', 'free cash flow inputs', "
        "'COGS', 'EBIT' for operating income. Use only what is visible in the table and its context line."
    )
    SCHEMA = {
        "type": "object",
        "properties": {
            "summaries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "summary": {"type": "string"}},
                    "required": ["id", "summary"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["summaries"],
        "additionalProperties": False,
    }

    def __init__(self, s: Settings, use_llm: bool = True, batch_tokens: int | None = None, workers: int = 4):
        self.s = s
        self.use_llm = use_llm
        # Batches are sized by tokens, not table count, to fit free-tier tokens-per-minute limits.
        self.batch_tokens = batch_tokens or s.summary_batch_tokens
        self.workers = workers
        self.path: Path = s.cache_dir / "table_summaries.jsonl"
        self.cache: dict[str, str] = {}
        self._offset = 0
        self._refresh()

    def _refresh(self) -> None:
        """Pick up summaries appended by other processes (`ingest.index --summaries-only` runs alongside)."""
        if not self.path.exists():
            return
        with self.path.open("rb") as f:
            f.seek(self._offset)
            data = f.read()
        end = data.rfind(b"\n") + 1  # ignore a line another process is still writing
        for line in data[:end].decode().splitlines():
            if line.strip():
                row = json.loads(line)
                self.cache[row["key"]] = row["summary"]
        self._offset += end

    @staticmethod
    def _key(company: str, el: Element) -> str:
        return hashlib.sha1(f"{company}|{el.context}|{el.text[:4000]}".encode()).hexdigest()

    def summarize(self, company: str, fiscal_label: str, tables: list[Element]) -> list[str]:
        self._refresh()
        keys = [self._key(company, t) for t in tables]
        todo = [i for i, k in enumerate(keys) if k not in self.cache]
        if todo and self.use_llm:
            new: dict[str, str] = {}
            # Second pass: models sometimes skip entries in a long list, so re-ask for those in small batches.
            for max_tables in (20, 5):
                todo = [i for i in todo if keys[i] not in new]
                if not todo or not self.use_llm:
                    break
                batches = self._batches(tables, todo, max_tables)
                with ThreadPoolExecutor(self.workers) as pool:
                    results = list(pool.map(lambda b: self._call(company, fiscal_label, tables, b), batches))
                for b, res in zip(batches, results, strict=True):
                    for i in b:
                        if res.get(i):
                            new[keys[i]] = res[i]
            self.cache.update(new)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # One write per line with O_APPEND, so concurrent processes don't interleave partial lines.
            with self.path.open("a") as f:
                for k, v in new.items():
                    f.write(json.dumps({"key": k, "summary": v}, ensure_ascii=False) + "\n")
                    f.flush()
        return [self.cache.get(k) or heuristic_summary(t) for k, t in zip(keys, tables, strict=True)]

    def _batches(self, tables: list[Element], idxs: list[int], max_tables: int) -> list[list[int]]:
        batches: list[list[int]] = [[]]
        size = 0
        for i in idxs:
            cost = n_tokens(self._preview(tables[i]))
            if batches[-1] and (size + cost > self.batch_tokens or len(batches[-1]) >= max_tables):
                batches.append([])
                size = 0
            batches[-1].append(i)
            size += cost
        return batches

    @staticmethod
    def _preview(t: Element) -> str:
        rows = t.rows or []
        body = compact_md(_rows_md(rows[:20])) if rows else t.text[:2000]
        return f"Context: {t.context or t.heading}\n{body[:2500]}"

    def _call(self, company: str, fiscal_label: str, tables: list[Element], idxs: list[int]) -> dict[int, str]:
        from app.llm import QuotaExhausted, get_llm

        if not self.use_llm:
            return {}
        parts = [f"<table id={i}>\n{self._preview(tables[i])}\n</table>" for i in idxs]
        user = f"Company: {company}. Filing: {fiscal_label}.\n\n" + "\n\n".join(parts)
        try:
            out = get_llm().json(system=self.SYSTEM, user=user, schema=self.SCHEMA, role="summary", effort="low", max_tokens=6000)
            return {int(x["id"]): x["summary"].strip() for x in out.get("summaries", []) if x.get("summary")}
        except QuotaExhausted as e:
            log.warning("%s; remaining tables keep heuristic summaries (re-run later to fill them in)", e)
            self.use_llm = False
            return {}
        except Exception as e:  # noqa: BLE001 - summaries are nice-to-have; fall back to heuristics
            log.warning("table summary batch failed for %s: %s", company, e)
            return {}


def table_chunks(p: ParsedDoc, s: Settings, summarizer: TableSummarizer | None) -> list[Chunk]:
    tables = [e for e in p.elements if e.kind == "table"]
    if summarizer:
        summaries = summarizer.summarize(p.meta.company, p.meta.fiscal_label, tables)
    else:
        summaries = [heuristic_summary(t) for t in tables]
    chunks: list[Chunk] = []
    for t, summary in zip(tables, summaries, strict=True):
        rows = t.rows or []
        page_end = t.page_end or t.page
        groups: list[str]
        if rows and n_tokens(t.text) > s.table_max_tokens:
            header, body = rows[0], rows[1:]
            per = max(5, int(len(body) * s.table_max_tokens / max(n_tokens(t.text), 1)))
            groups = [_rows_md([header, *body[i : i + per]]) for i in range(0, len(body), per)]
        else:
            groups = [compact_md(t.text)]
        for gi, md in enumerate(groups):
            part = f" (part {gi + 1}/{len(groups)})" if len(groups) > 1 else ""
            labels = _row_labels(rows)
            chunks.append(
                _make_chunk(
                    p,
                    kind="table",
                    idx=len(chunks) * 100 + gi,
                    page=t.page,
                    page_end=page_end,
                    section=t.section,
                    heading=t.heading,
                    summary=summary + part,
                    body=f"Table: {summary}{part}\n{md}",
                    embed_body=f"Table: {summary}{part}\nLine items: {labels}",
                    sparse_body=f"Table: {summary}{part}\n{md}",
                )
            )
    return chunks


def chunk_structured(p: ParsedDoc, s: Settings | None = None, summarizer: TableSummarizer | None = None) -> list[Chunk]:
    s = s or get_settings()
    return text_chunks(p, s) + table_chunks(p, s, summarizer)


# --------------------------------------------------------------------------------------------
# Naive baseline (ablation run A): fixed 1,000-token windows over raw page text
# --------------------------------------------------------------------------------------------


def chunk_naive(p: ParsedDoc, size: int = 1000) -> list[Chunk]:
    """No section awareness, no table handling and no contextual header: the "chat with your PDF" baseline."""
    words: list[tuple[str, int]] = []
    for el in p.elements:
        words += [(w, el.page) for w in el.text.split()]
    chunks = []
    i = 0
    while i < len(words):
        j, count = i, 0
        while j < len(words) and count < size:
            count += n_tokens(words[j][0])
            j += 1
        window = words[i:j]
        body = " ".join(w for w, _ in window)
        c = _make_chunk(
            p,
            kind="naive",
            idx=len(chunks),
            page=window[0][1],
            page_end=window[-1][1],
            section="Other",
            heading="",
            body=body,
            embed_body=body,
            sparse_body=body,
            contextual=False,
        )
        chunks.append(c)
        i = j
    return chunks

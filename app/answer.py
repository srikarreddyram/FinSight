"""Evidence-grounded answer generation.

One structured LLM call returns (a) the raw figures it read, each tied to a source and quote,
(b) the calculations it wants, by name only, and (c) prose/table templates that reference those
with {fig:name} / {calc:name} placeholders and cite sources as [S#]. Python then:

  1. verifies every figure is actually printed in its cited source,
  2. does all arithmetic (growth, margins, ratios, CAGR),
  3. fills the placeholders, so every number in the answer came from a source or from Python,
  4. strips sentences that are uncited, cite unknown sources, depend on an unverified figure, or
     contain a hard-coded number that doesn't appear in the sources they cite,
  5. rewrites [S#] tags as [Company FY p.N] citations.
"""

from __future__ import annotations

import re

from app.numbers import CalcError, Quantity, appears_in, calculate, fmt_calc, fmt_quantity, numbers_in
from app.schemas import Answer, Calculation, Citation, Figure, Hit, ParsedQuery

NOT_FOUND = "Not found in the filings."

SYSTEM = """You are FinSight, an analyst's assistant that answers questions strictly from excerpts of company filings (10-Ks, 10-Qs, annual reports, earnings-call transcripts).

Rules:
- Use only the numbered sources. If they don't contain what the question needs, set answerable=false and leave the rest empty. Never use outside knowledge, never guess.
- Numbers: never type a number from a source directly into the answer and never do arithmetic yourself. Instead:
  * list each number you use under `figures`, transcribed exactly as printed (without rescaling; report outflows and expenses shown in parentheses, such as capex (1,577), as positive amounts, and keep a minus sign only for losses, declines or negative balances), with its unit, currency, scale (e.g. "millions" when the table header says "(Millions)", "crore" for "₹ crore"), the period it refers to, the source id, and as `quote` the row label or phrase the number appears with (at most 12 words, e.g. "Purchases of property, plant and equipment (PP&E)");
  * list every derived number under `calculations` by operation and input figure names: growth [old, new] (percent change), subtract [a, b] (a minus b, e.g. "assets less liabilities" is subtract [assets, liabilities]), change [old, new] (new minus old), margin or share [part, whole], ratio [numerator, denominator], sum, average, cagr [start, end] with periods = years between them, multiply [x] with factor = a constant from the question (e.g. 365 for days); a calculation may use earlier calculations as inputs, so build multi-step metrics as a chain and never state a computed number in the answer text;
  * write {fig:name} or {calc:name} wherever that number belongs in the answer. The placeholder already includes the currency symbol and scale (it renders as e.g. "$1,577 million" or "14.9%"), so don't add them around it.
- Citations: end every sentence that states a fact with the tag(s) of the sources supporting it, e.g. "Revenue rose to {fig:rev_fy25} [S2]." Put tags before the full stop. Sentences without a tag will be deleted.
- Watch fiscal years: each source says which company, fiscal year and page it is from. A filing for one year also contains prior-year comparatives; pick the column for the period the question asks about.
- Never copy long passages from the sources; state facts in your own words.
- Be concise: lead with the direct answer, then at most a few sentences of support. Plain prose or short bullets, no headings.
- For comparisons across companies or years, also fill `table` (columns and rows of cells that may contain placeholders); otherwise leave table columns and rows empty.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "answerable": {"type": "boolean"},
        "figures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "number"},
                    "unit": {"type": "string", "enum": ["currency", "percent", "count", "ratio", "per_share", "other"]},
                    "currency": {"type": "string"},
                    "scale": {"type": "string", "enum": ["units", "thousands", "lakh", "millions", "crore", "billions"]},
                    "period": {"type": "string"},
                    "source_id": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["name", "value", "unit", "currency", "scale", "period", "source_id", "quote"],
                "additionalProperties": False,
            },
        },
        "calculations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "op": {
                        "type": "string",
                        "enum": [
                            "growth",
                            "subtract",
                            "change",
                            "margin",
                            "share",
                            "ratio",
                            "sum",
                            "average",
                            "cagr",
                            "multiply",
                        ],
                    },
                    "inputs": {"type": "array", "items": {"type": "string"}},
                    "periods": {"type": "integer"},
                    "factor": {"type": "number"},
                },
                "required": ["name", "op", "inputs", "periods"],
                "additionalProperties": False,
            },
        },
        "answer": {"type": "string"},
        "table": {
            "type": "object",
            "properties": {
                "columns": {"type": "array", "items": {"type": "string"}},
                "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
            },
            "required": ["columns", "rows"],
            "additionalProperties": False,
        },
    },
    "required": ["answerable", "figures", "calculations", "answer", "table"],
    "additionalProperties": False,
}


def source_id(i: int) -> str:
    return f"S{i + 1}"


def to_citation(i: int, h: Hit) -> Citation:
    c = h.chunk
    body = c.text.split("\n", 1)[-1]
    return Citation(
        id=source_id(i),
        label=f"{c.company} {c.fiscal_label} p.{c.page}",
        doc_id=c.doc_id,
        company=c.company,
        fiscal_label=c.fiscal_label,
        page=c.page,
        page_end=c.page_end,
        section=c.section,
        chunk_type=c.chunk_type,
        snippet=body[:600],
        score=h.rerank_score,
    )


def build_prompt(question: str, hits: list[Hit], fy_notes: list[str]) -> str:
    parts = []
    for i, h in enumerate(hits):
        c = h.chunk
        parts.append(
            f'<source id="{source_id(i)}" company="{c.company}" filing="{c.doc_type} {c.fiscal_label}" '
            f'period_end="{c.period_end}" page="{c.page}" section="{c.section}" type="{c.chunk_type}">\n'
            f"{c.text}\n</source>"
        )
    notes = ("\nFiscal-year conventions:\n" + "\n".join(f"- {n}" for n in fy_notes)) if fy_notes else ""
    return "Sources:\n" + "\n\n".join(parts) + f"\n{notes}\n\nQuestion: {question}"


# --------------------------------------------------------------------------------------------
# Post-processing
# --------------------------------------------------------------------------------------------

_TAG = re.compile(r"\[\s*(S\d+(?:\s*[,;]\s*S\d+)*)\s*\]")
_PLACEHOLDER = re.compile(r"\{(fig|calc):([A-Za-z0-9_\-.]+)\}")
_YEARISH = re.compile(r"^(19|20)\d{2}$")


_ABBREV = re.compile(
    r"\b(U\.S|U\.K|Inc|Co|Corp|Ltd|Bros|No|vs|e\.g|i\.e|etc|Dr|Mr|Ms|Mrs|St|approx|Rs|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\.$"
)


def _split_sentences(text: str) -> list[str]:
    """Split markdown prose into sentences, keeping line structure (bullets) and attaching orphan tags."""
    out: list[str] = []
    for line in text.split("\n"):
        if not line.strip():
            out.append("\n")
            continue
        pieces = re.split(r"(?<=[.!?])\s+(?=[A-Z\[*\-(\"'{])", line)
        merged: list[str] = []
        for p in pieces:  # "the U.S. Government" is one sentence, not two
            if merged and _ABBREV.search(merged[-1]):
                merged[-1] = f"{merged[-1]} {p}"
            else:
                merged.append(p)
        for p in merged:
            if out and out[-1] != "\n" and _TAG.fullmatch(p.strip().rstrip(".")):
                out[-1] = out[-1] + " " + p  # "... revenue. [S2]" -> keep the tag with its sentence
            else:
                out.append(p)
        out.append("\n")
    return out


def _cited_ids(sentence: str) -> list[str]:
    ids = []
    for m in _TAG.finditer(sentence):
        ids += [x.strip() for x in re.split(r"[,;]", m.group(1))]
    return ids


def _stray_numbers(sentence: str) -> list[float]:
    """Numbers typed directly into a sentence (placeholders, tags, years and list markers excluded)."""
    s = _TAG.sub("", _PLACEHOLDER.sub("", sentence))
    s = re.sub(r"\b(FY|Q)\s?'?\d{1,4}\b", "", s, flags=re.I)
    s = re.sub(r"^\s*(\d+[.)]|[-*])\s+", "", s)
    out = []
    for tok in re.findall(r"\d[\d,]*(?:\.\d+)?", s):
        if _YEARISH.match(tok):
            continue
        v = float(tok.replace(",", ""))
        if v <= 10 and float(v).is_integer():  # "two segments", "3 factors": too common to police
            continue
        out.append(v)
    return out


def _is_prose(sentence: str) -> bool:
    """Claims need citations; intro lines ("Key drivers:") and one- or two-word fragments don't."""
    bare = _TAG.sub("", sentence).strip()
    return len(re.findall(r"[A-Za-z]{2,}", bare)) >= 3 and not bare.endswith(":")


def finalize(question: str, raw: dict, hits: list[Hit], pq: ParsedQuery | None = None) -> Answer:
    cits = [to_citation(i, h) for i, h in enumerate(hits)]
    by_id = {c.id: c for c in cits}
    texts = {source_id(i): h.chunk.text for i, h in enumerate(hits)}

    if not raw.get("answerable", False):
        return refusal(question, hits, pq)

    # 1. verify figures against their cited source
    figures: dict[str, Figure] = {}
    quantities: dict[str, Quantity] = {}
    for f in raw.get("figures", []):
        q = Quantity(value=float(f["value"]), unit=f["unit"], currency=f.get("currency", ""), scale=f.get("scale", "units"))
        src = texts.get(f["source_id"], "")
        verified = bool(src) and appears_in(q.value, src)
        figures[f["name"]] = Figure(
            name=f["name"], value=q.value, display=fmt_quantity(q), source_id=f["source_id"], verified=verified
        )
        if verified:
            quantities[f["name"]] = q

    # 2. arithmetic in Python
    calcs: dict[str, Calculation] = {}
    for c in raw.get("calculations", []):
        try:
            missing = [n for n in c["inputs"] if n not in quantities]
            if missing:
                raise CalcError(f"unverified or unknown inputs: {missing}")
            result = calculate(c["op"], [quantities[n] for n in c["inputs"]], c.get("periods", 0), c.get("factor"))
            calcs[c["name"]] = Calculation(
                name=c["name"], op=c["op"], inputs=c["inputs"], value=result.value, display=fmt_calc(c["op"], result)
            )
            quantities[c["name"]] = result  # later calculations may build on this one
        except CalcError as e:
            calcs[c["name"]] = Calculation(
                name=c["name"], op=c["op"], inputs=c["inputs"], value=None, display="n/a", error=str(e)
            )

    def resolve(m: re.Match) -> str | None:
        kind, name = m.group(1), m.group(2)
        if kind == "fig":
            f = figures.get(name)
            return f.display if f and f.verified else None
        c = calcs.get(name)
        return c.display if c and c.value is not None else None

    # 3-4. sentence-level checks, then fill placeholders
    kept, stripped, used = [], [], []
    for sent in _split_sentences(raw.get("answer", "")):
        if sent == "\n":
            kept.append(sent)
            continue
        ids = _cited_ids(sent)
        problems = []
        if _is_prose(sent) and not ids:
            problems.append("uncited")
        if any(i not in by_id for i in ids):
            problems.append("unknown source")
        cited_text = " ".join(texts.get(i, "") for i in ids)
        if any(not appears_in(v, cited_text) for v in _stray_numbers(sent)):
            problems.append("number not in cited source")
        filled = sent
        for m in list(_PLACEHOLDER.finditer(sent)):
            val = resolve(m)
            if val is None:
                problems.append(f"unresolved {m.group(0)}")
            else:
                filled = filled.replace(m.group(0), val)
        if problems:
            stripped.append(f"{sent.strip()}  <- {', '.join(problems)}")
            continue
        used += [i for i in ids if i not in used]
        kept.append(filled)

    body = _tidy_units(re.sub(r"[ \t]+\n", "\n", " ".join(kept).replace(" \n ", "\n").replace("\n ", "\n")))
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if not body:
        return refusal(
            question, hits, pq, note="The model's answer could not be supported by the retrieved passages.", stripped=stripped
        )

    # 5. [S#] -> [Company FY p.N]
    def relabel(m: re.Match) -> str:
        ids = [x.strip() for x in re.split(r"[,;]", m.group(1))]
        return "[" + "; ".join(by_id[i].label for i in ids if i in by_id) + "]"

    body = _TAG.sub(relabel, body)
    for f in raw.get("figures", []):
        if f["source_id"] in by_id and figures[f["name"]].verified and f.get("quote"):
            c = by_id[f["source_id"]]
            c.highlight = f"{c.highlight}\n{f['quote']}".strip()
    table_md = _render_table(raw.get("table") or {}, resolve)
    if table_md:
        table_md = _TAG.sub(relabel, table_md)

    return Answer(
        question=question,
        answer=body,
        citations=[by_id[i] for i in used],
        figures=list(figures.values()),
        calculations=list(calcs.values()),
        table_markdown=table_md,
        retrieved=cits,
        parsed_query=pq,
        stripped_sentences=stripped,
    )


def _render_table(table: dict, resolve) -> str | None:
    cols, rows = table.get("columns") or [], table.get("rows") or []
    if not cols or not rows:
        return None

    def cell(x: str) -> str:
        return _PLACEHOLDER.sub(lambda m: resolve(m) or "n/a", x).replace("|", "/")

    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        r = (list(r) + [""] * len(cols))[: len(cols)]
        lines.append("| " + " | ".join(cell(x) for x in r) + " |")
    return "\n".join(lines)


_SCALE_WORDS = r"(thousand|million|billion|trillion|crore|lakh)"


def _tidy_units(text: str) -> str:
    """Remove units the model wrote around a filled placeholder that already carries them
    ("$$1,577 million million" -> "$1,577 million", "14.9%%" -> "14.9%")."""
    text = re.sub(r"([$₹€£¥])\s*(-?)\s*\1", r"\2\1", text)  # "$-$1" -> "-$1", "$$1" -> "$1"
    text = re.sub(rf"\b{_SCALE_WORDS}s?\s+\1s?\b", r"\1", text)
    return re.sub(r"%\s*%", "%", text)


def refusal(
    question: str, hits: list[Hit], pq: ParsedQuery | None = None, note: str = "", stripped: list[str] | None = None
) -> Answer:
    cits = [to_citation(i, h) for i, h in enumerate(hits)]
    text = NOT_FOUND + (f" {note}" if note else "") + (" The closest passages are listed below." if cits else "")
    return Answer(
        question=question,
        answer=text,
        refused=True,
        closest=cits[:3],
        retrieved=cits,
        parsed_query=pq,
        stripped_sentences=stripped or [],
    )


def numbers_supported(text: str, sources: str) -> bool:
    """Helper for eval: are all non-year numbers in `text` present in `sources`?"""
    return all(appears_in(v, sources) for v in numbers_in(text) if not _YEARISH.match(str(int(v))))

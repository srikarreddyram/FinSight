"""The research note: one structured LLM call over the numbered context, then Python checks.

The model writes a headline, a short summary, a bull case, a bear case and what to watch, citing the IDs of the
items it uses ([K3], [X7], [N2], [D1]). A figure from the filings' facts or FinSight's data appears as its item's
placeholder, {X7} or {D3}, and Python fills in the value and cites the item. Python then
- keeps only citations to items that were given, and drops any point left without one;
- drops any sentence with a number that isn't a filled placeholder and doesn't appear, with the same unit, in an
  item the sentence cites (years, "10-K", "Item 1A" and the like are allowed), so every figure on the page is in a
  source the reader can open;
- picks the key numbers shown above the note from the facts the model chose, by ID.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

SYSTEM = """You are an equity research analyst writing a short, balanced research note on one company for a
professional reader. Use ONLY the numbered items you are given:
K = passages and risk headings from the company's latest 10-K, X = financial facts from its filings,
N = recent news headlines, D = FinSight's own data (its risk grade, price moves, earnings reactions).

Rules:
- Cite the items behind every statement in square brackets, e.g. "Revenue was flat [X28] as wholesale demand
  slowed [K12]." Never use outside knowledge.
- Figures: to state an X figure or a D figure marked "value", write its placeholder, e.g. {X7} or {D3}. It is
  replaced with the value exactly as shown, sign included, so write "the stock returned {D5}", not "a negative
  {D5}". K and N items have no placeholder: to use a figure from a 10-K passage or a headline, copy it exactly as
  written there and cite that item, e.g. "wholesale revenues were $27.5 billion [K11]". Any other number is
  removed. Words like "flat", "fell", "doubled" are fine.
- Bull case: 2 to 4 points that support a better outcome. Bear case: 2 to 4 points against. What to watch: 2 or 3
  upcoming things the evidence points to (results, guidance, a risk that is building). Each point one or two
  sentences.
- Be balanced and specific to this company; skip generic risks every company lists. Draw on the 10-K passages
  for segment, channel, regional and margin detail, quoting their figures exactly, and use each fact in one point
  only: the summary says what matters most, the points add to it.
- Write the headline and titles in sentence case, keeping names capitalised ("JPMorgan Chase").
- key_facts: the IDs of the 4 to 6 facts (X) that matter most for this company now.
- No recommendation to buy or sell, no price targets."""

_POINT = {
    "type": "object",
    "properties": {"title": {"type": "string", "description": "Under 8 words, sentence case"}, "text": {"type": "string"}},
    "required": ["title", "text"],
}
SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "The note's main point in under 14 words, sentence case"},
        "summary": {"type": "string", "description": "Two or three sentences with [ID] citations"},
        "bull": {"type": "array", "items": _POINT},
        "bear": {"type": "array", "items": _POINT},
        "watch": {"type": "array", "items": _POINT},
        "key_facts": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "summary", "bull", "bear", "watch", "key_facts"],
}

_CITE = re.compile(r"\[([A-Z]\d+(?:\s*,\s*[A-Z]\d+)*)\]")
_HOLE = re.compile(r"\{([A-Z]\d+)\}")
# Digits that are not figures: years, filing names, items, quarters, the index names.
_ALLOWED = re.compile(
    r"\b(19|20)\d{2}s?\b|\b10-[KQ]\b|\b8-K\b|\bItem \d+[A-C]?\b|\bQ[1-4]\b|\bFY\d{2,4}\b|S&P \d{3}|\bH[12]\b|\[[A-Z]\d+(?:\s*,\s*[A-Z]\d+)*\]"
)
_FIGURE = re.compile(
    r"(\d[\d,]*(?:\.\d+)?)\s*(%|percent\b|per cent\b|basis points?\b|bps\b|trillion\b|billion\b|bn\b|million\b|mn\b|thousand\b|[TBMK]\b)?",
    re.I,
)
_UNIT = {"%": "%", "percent": "%", "per cent": "%", "basis point": "bp", "basis points": "bp", "bps": "bp"}
_UNIT |= {"trillion": "t", "t": "t", "billion": "b", "bn": "b", "b": "b", "million": "m", "mn": "m", "m": "m"}
_UNIT |= {"thousand": "k", "k": "k"}
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def figures(text: str) -> set[tuple[Decimal, str]]:
    """The numbers in a text with their units: "$27.5 billion" and "$27.50B" are both (27.5, "b")."""
    out = set()
    for num, unit in _FIGURE.findall(text):
        try:
            out.add((Decimal(num.replace(",", "")), _UNIT.get(unit.lower(), "") if unit else ""))
        except InvalidOperation:
            continue
    return out


def grounded(typed: set[tuple[Decimal, str]], sources: str) -> bool:
    """Every typed figure appears in the sources: with the same unit if it has one, else as a bare number."""
    have = figures(sources)
    numbers = {n for n, _ in have}
    return all((n, u) in have if u else n in numbers for n, u in typed)


def flatten(raw: dict) -> dict:
    """The schema's points come back as {"title", "text"}; some models nest or rename them, so normalise."""
    out = dict(raw)
    for side in ("bull", "bear", "watch"):
        pts = []
        for p in raw.get(side) or []:
            if isinstance(p, str):
                p = {"title": "", "text": p}
            pts.append({"title": str(p.get("title", "")).strip(), "text": str(p.get("text") or p.get("point") or "").strip()})
        out[side] = pts
    return out


def check(text: str, ids: set[str], facts: dict[str, str], texts: dict[str, str]) -> tuple[str, list[str]]:
    """Fill placeholders, keep valid citations, and drop sentences with a figure that isn't in a cited source.
    Returns the cleaned text and the IDs it cites."""
    kept, cited = [], []
    for sentence in _SENTENCE.split(text.strip()):
        holes = list(dict.fromkeys(_HOLE.findall(sentence)))
        if any(h not in facts for h in holes):
            continue  # a placeholder for an item that wasn't given or holds no single figure
        refs = list(dict.fromkeys(i.strip() for m in _CITE.finditer(sentence) for i in m.group(1).split(",")))
        refs = [r for r in refs if r in ids]
        typed = figures(_ALLOWED.sub("", _HOLE.sub("", sentence)))
        if typed and not grounded(typed, " ".join(texts[r] for r in refs + holes)):
            continue  # a figure that isn't in anything the sentence cites

        def cite(m: re.Match) -> str:
            valid = [i.strip() for i in m.group(1).split(",") if i.strip() in ids]
            return f"[{', '.join(valid)}]" if valid else ""

        s = _CITE.sub(cite, sentence)
        extra = [h for h in holes if h not in refs]
        if extra:  # a filled figure cites the item it came from
            s = re.sub(r"\s*([.!?]?)\s*$", f" [{', '.join(extra)}]\\1", s, count=1)
        s = _HOLE.sub(lambda m: facts[m.group(1)], s)
        kept.append(re.sub(r"\s+([.,;:])", r"\1", re.sub(r"\s{2,}", " ", s)).strip())
        cited.extend(refs + extra)
    return " ".join(kept).strip(), list(dict.fromkeys(cited))


def _title(text: str) -> str:
    """A point the model left untitled is titled with its first sentence, without citations, shortened."""
    first = re.sub(r"\s+", " ", _CITE.sub("", _SENTENCE.split(text)[0])).strip().rstrip(".").strip()
    return first if len(first) <= 60 else first[:60].rsplit(" ", 1)[0] + "…"


def clean(raw: dict, items: list[dict]) -> dict:
    ids = {i["id"] for i in items}
    facts = {i["id"]: i["text"] for i in items if i["kind"] == "fact" or i["meta"].get("value")}
    texts = {i["id"]: f"{i['title']} {i['text']}" for i in items}
    raw = flatten(raw)
    summary, _ = check(raw.get("summary", ""), ids, facts, texts)
    headline, _ = check(raw.get("headline", ""), ids, facts, texts)
    out = {"headline": _CITE.sub("", headline).strip(), "summary": summary}
    for side in ("bull", "bear", "watch"):
        pts = []
        for p in raw[side]:
            text, cited = check(p["text"], ids, facts, texts)
            if text and cited:  # every point must rest on something given
                title, _ = check(p["title"], ids, facts, texts)
                pts.append({"title": _CITE.sub("", title).strip() or _title(text), "text": text, "evidence": cited})
        out[side] = pts[:4]
    out["key_facts"] = [i for i in dict.fromkeys(raw.get("key_facts") or []) if i in facts and i.startswith("X")][:6]
    return out


def prompt(company: str, ticker: str, sector: str | None, items: list[dict]) -> str:
    lines = []
    for i in items:
        value = i["kind"] == "fact" or i["meta"].get("value")
        body = f": {i['text']}" if value else (f" — {i['text']}" if i["text"] else "")
        tag = {"tenk": f"10-K Item {i['meta'].get('item', '')}", "fact": "fact", "news": f"news {i['meta'].get('date', '')}",
               "data": "FinSight, value" if value else "FinSight"}[i["kind"]]  # fmt: skip
        lines.append(f"{i['id']} ({tag}) {i['title']}{body}")
    return f"Company: {company} ({ticker}), sector: {sector or 'unknown'}\nToday: {datetime.now(UTC).date()}\n\n" + "\n".join(
        lines
    )


def write_note(company: str, ticker: str, sector: str | None, items: list[dict], llm) -> dict:
    raw = llm.json(
        system=SYSTEM,
        user=prompt(company, ticker, sector, items),
        schema=SCHEMA,
        role="answer",
        effort="medium",
        max_tokens=12000,
    )
    return {**clean(raw, items), "items": items, "generated": datetime.now(UTC).isoformat(), "ticker": ticker}

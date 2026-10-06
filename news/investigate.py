"""What drove a move: one structured LLM call over the dated evidence, every driver cited.

The model sees the move's numbers (total, market, sector, company-specific, the key days) and a numbered list of
headlines and filings, and returns a short summary and up to four drivers, each naming the evidence it rests on.
Python then keeps only citations to evidence that was actually given, and drops any driver left without one, so
nothing in the output is unsourced. When the move was mostly the market or the sector, the summary says so.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from news.moves import Move
from news.sources import Evidence

MAX_LISTED = 60  # evidence numbered and shown
MAX_EVIDENCE = 30  # of which the model reads at most this many
SYSTEM = """You explain what moved a stock's price, using only the numbered evidence you are given (news
headlines and SEC filings, each with a date). Rules:
- Every driver must cite the evidence IDs it rests on, e.g. ["N3", "F1"]. Never use outside knowledge.
- Prefer events dated on or just before the key days. Ignore evidence about other companies.
- If most of the move is the market or the sector rather than the company, say that first.
- If the evidence does not explain the company-specific part, say so plainly instead of guessing.
- Up to 4 drivers, most important first. No predictions, no recommendations.
- In the summary, cite IDs in square brackets, e.g. "Shares fell after weak guidance [N2]."
"""
SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "Two or three sentences with [ID] citations"},
        "drivers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "headline": {"type": "string", "description": "The driver in under ten words"},
                    "detail": {"type": "string", "description": "One or two sentences"},
                    "effect": {"type": "string", "enum": ["pushed up", "pushed down", "mixed"]},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["headline", "detail", "effect", "evidence"],
            },
        },
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["summary", "drivers", "confidence"],
}


def number(items: list[Evidence]) -> list[dict]:
    """Evidence with IDs: N1, N2... for news and F1, F2... for filings, newest first within each. The IDs are
    the ones shown on the page, so an analysis's citations point at the same list."""
    out, counts = [], {"news": 0, "filing": 0}
    for e in items[:MAX_LISTED]:
        counts[e.kind] += 1
        out.append(e.as_json(f"{'N' if e.kind == 'news' else 'F'}{counts[e.kind]}"))
    return out


def select(evidence: list[dict], move: Move, k: int = MAX_EVIDENCE) -> list[dict]:
    """The evidence the model reads: every filing, then the news closest in time to the move's key days (the
    newest headlines are often commentary written after the fact). Original IDs and date order are kept."""
    if len(evidence) <= k:
        return evidence
    days = [datetime.combine(kd.day, datetime.min.time(), UTC) for kd in move.key_days] or [datetime.now(UTC)]

    def distance(e: dict) -> float:
        when = datetime.fromisoformat(e["published"])
        return min(abs((when - d).total_seconds()) for d in days)

    filings = [e for e in evidence if e["kind"] == "filing"]
    news = sorted((e for e in evidence if e["kind"] == "news"), key=distance)
    chosen = {e["id"] for e in [*filings, *news][:k]}
    return [e for e in evidence if e["id"] in chosen]


def prompt(company: str, ticker: str, sector: str | None, move: Move, evidence: list[dict]) -> str:
    pct = lambda v: f"{v * 100:+.1f}%"  # noqa: E731
    days = "; ".join(f"{k.day}: {pct(k.change)} (company-specific {pct(k.company)})" for k in move.key_days)
    lines = "\n".join(f"{e['id']} | {e['published'][:10]} | {e['source']} | {e['title']}" for e in evidence)
    return (
        f"Company: {company} ({ticker}), sector: {sector or 'unknown'}\n"
        f"Window: {move.start} to {move.end} ({move.days} trading days)\n"
        f"Price change: {pct(move.change)} = market {pct(move.market)} + sector {pct(move.sector)} "
        f"+ company-specific {pct(move.company)}\n"
        f"Largest company-specific days: {days}\n\n"
        f"Evidence (ID | date | source | title):\n{lines or '(none found)'}\n"
    )


_REFS = re.compile(r"\s*\[([A-Z]\d+(?:\s*,\s*[A-Z]\d+)*)\]")


def _cite(text: str, ids: set[str]) -> str:
    """Keep [N1, F2]-style citations only to evidence that exists; drop the bracket if none survive."""

    def keep(m: re.Match) -> str:
        valid = [i.strip() for i in m.group(1).split(",") if i.strip() in ids]
        return f" [{', '.join(valid)}]" if valid else ""

    return _REFS.sub(keep, text or "").strip()


def clean(raw: dict, evidence: list[dict]) -> dict:
    """Keep only citations to evidence that exists; drop drivers that cite none."""
    ids = {e["id"] for e in evidence}
    drivers = []
    for d in raw.get("drivers") or []:
        cited = [i for i in dict.fromkeys(d.get("evidence") or []) if i in ids]
        if cited and d.get("headline"):
            drivers.append({**d, "detail": _cite(d.get("detail", ""), ids), "evidence": cited})
    return {"summary": _cite(raw.get("summary", ""), ids), "drivers": drivers[:4], "confidence": raw.get("confidence", "low")}


def investigate(company: str, ticker: str, sector: str | None, move: Move, items: list[Evidence], llm=None) -> dict:
    evidence = number(items)
    if not evidence:
        return {"summary": "No news or filings were found for this period.", "drivers": [], "confidence": "low",
                "evidence": [], "generated": datetime.now(UTC).isoformat()}  # fmt: skip
    if llm is None:
        from app.llm import get_llm

        llm = get_llm()
    shown = select(evidence, move)
    raw = llm.json(
        system=SYSTEM,
        user=prompt(company, ticker, sector, move, shown),
        schema=SCHEMA,
        role="answer",
        effort="low",
        max_tokens=2000,
    )
    return {**clean(raw, shown), "evidence": evidence, "generated": datetime.now(UTC).isoformat()}

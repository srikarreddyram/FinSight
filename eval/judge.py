"""LLM grading in one call per answer: correctness against the gold answer, and whether each cited
page supports what the answer attributes to it. (One call instead of two halves free-tier quota use.)"""

from __future__ import annotations

from app.llm import LLM

SYSTEM = """You grade answers from a financial-filings QA system. Be strict.

1. verdict: "correct" only if the candidate states the gold answer's key facts and figures:
- numbers must match the gold within 1% (after unit conversion, e.g. $1,577 million = $1.577 billion) or match the gold's rounding;
- yes/no questions must reach the same conclusion;
- for open-ended questions the central conclusion must match and the supporting points must not contradict the gold;
- extra correct detail is fine; any claim contradicting the gold makes it "incorrect";
- a refusal ("Not found in the filings") is "incorrect".

2. citations: for each cited page label, supported=true if that page's text contains the facts or figures the answer
attributes to it (figures may be rounded or rescaled; derived numbers such as growth rates only need their inputs on the page).
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "reason": {"type": "string"},
        "verdict": {"type": "string", "enum": ["correct", "incorrect"]},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "supported": {"type": "boolean"}},
                "required": ["label", "supported"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["reason", "verdict", "citations"],
    "additionalProperties": False,
}

PAGE_CHARS = 5000  # per cited page, keeps a grading call inside Gemma's 16K tokens/minute
MAX_PAGES = 4


class Judge:
    def __init__(self, llm: LLM | None = None):
        self.llm = llm or LLM()  # separate instance so judge calls aren't counted against the system under test

    def grade(self, question: str, gold: str, candidate: str, pages: dict[str, str]) -> tuple[bool, str, dict[str, bool]]:
        """pages: citation label -> full text of that page. Returns (correct, reason, {label: supported})."""
        pages = dict(list(pages.items())[:MAX_PAGES])
        blocks = "\n\n".join(f'<page label="{label}">\n{text[:PAGE_CHARS]}\n</page>' for label, text in pages.items())
        out = self.llm.json(
            system=SYSTEM,
            user=f"Question: {question}\n\nGold answer: {gold}\n\nCandidate answer:\n{candidate}\n\nCited pages:\n{blocks or '(none)'}",
            schema=SCHEMA,
            role="judge",
            effort="low",
            max_tokens=3000,  # 12 of 150 FinanceBench rows exhaust any cap (tried 8192 and 24576) reasoning; left ungraded
        )
        verdicts = {c["label"]: bool(c["supported"]) for c in out.get("citations", [])}
        return out["verdict"] == "correct", out["reason"], {label: verdicts.get(label, False) for label in pages}

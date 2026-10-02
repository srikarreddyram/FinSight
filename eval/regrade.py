"""Re-grade rows whose judge call failed (server errors), without re-answering the questions.

uv run python -m eval.regrade                 # latest results directory
uv run python -m eval.regrade eval/results/<timestamp>
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from eval import metrics
from eval.financebench_loader import load_questions
from eval.judge import Judge
from eval.run import EVAL_DIR, gold_page_parsed, page_text, summarize

log = logging.getLogger(__name__)


def regrade(out_dir: Path) -> int:
    rows = [json.loads(line) for line in (out_dir / "rows.jsonl").read_text().splitlines()]
    questions = {q.id: q for q in load_questions()}
    judge = Judge()
    fixed = 0
    for r in rows:
        if r.get("correct") is not None or not str(r.get("judge_reason", "")).startswith("judge error"):
            continue
        q = questions[r["id"]]
        pages = {c["label"]: page_text(c["doc_id"], c["page"]) for c in r.get("citations", [])}
        candidate = r["answer"] + ("\n" + r["table"] if r.get("table") else "")
        try:
            r["correct"], r["judge_reason"], r["citation_support"] = judge.grade(
                q.question, q.answer, candidate, {k: v for k, v in pages.items() if v}
            )
        except Exception as e:  # noqa: BLE001
            log.warning("%s: still failing (%s)", r["id"], e)
            continue
        support = r.get("citation_support") or {}
        r["failure"] = metrics.tag_failure(
            correct=r["correct"],
            refused=r["refused"],
            answerable=r["answerable"],
            recall10=r["recall10"],
            gold_page_parsed=gold_page_parsed(q) if r["recall10"] is False else None,
            citations_ok=all(support.values()) if support else None,
        )
        fixed += 1
    (out_dir / "rows.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    summary = json.loads((out_dir / "summary.json").read_text())
    for key in summary["results"]:
        run, set_name = key.split("/")
        subset = [r for r in rows if r["run"] == run and r["set"] == set_name]
        old = summary["results"][key]
        summary["results"][key] = {
            **summarize(subset, old.get("cost_usd")),
            "complete": old.get("complete"),
            "llm_calls": old.get("llm_calls"),
        }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return fixed


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else sorted((EVAL_DIR / "results").glob("2*/"))[-1]
    log.info("%s: re-graded %d rows", out_dir, regrade(out_dir))


if __name__ == "__main__":
    main()

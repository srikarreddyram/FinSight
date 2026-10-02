"""Tune the final ranking and the evidence-gate threshold without any LLM calls.

Candidates (filtered hybrid top 30) and cross-encoder scores are computed once per question; then
every ranking strategy is scored by recall@10. To keep the reported numbers honest, settings are
chosen on a random half of FinanceBench ("tune") and reported on the other half ("test").

    uv run python -m eval.tune_retrieval
"""

from __future__ import annotations

import itertools
import json
import random

from app.config import get_settings
from app.pipeline import Pipeline, PipelineConfig
from app.rerank import order
from eval import metrics
from eval.financebench_loader import load_questions
from eval.run import EVAL_DIR, eligible, load_set

BLENDS = [1.0, 0.8, 0.6, 0.4, 0.0]
TABLE_SLOTS = [0, 2, 3, 4]


def recall(cands, strategy) -> float:
    blend, slots = strategy
    from app.answer import to_citation

    hits = [metrics.recall_at_k([to_citation(i, h) for i, h in enumerate(order(hs, 10, blend, slots))], q) for q, hs in cands]
    return sum(hits) / len(hits)


def main() -> None:
    from ingest.index import indexed_docs
    from ingest.manifest import load_documents

    s = get_settings()
    pipe = Pipeline(PipelineConfig("E", llm_query_parser=False))
    indexed = set(indexed_docs())
    docs = load_documents()
    tickers = {docs[d].ticker for d in indexed if d in docs}
    qs = [q for q in load_questions() if eligible(q, indexed, tickers)]
    unans = [q for q in load_set("unanswerable") if eligible(q, indexed, tickers)]
    print(f"{len(qs)} FinanceBench questions, {len(unans)} unanswerable questions with indexed filings")

    def candidates(q):
        pq = pipe.parser.parse(q.question)
        return q, pipe.reranker.score(q.question, pipe._search(q.question, pq))

    cands = [candidates(q) for q in qs]
    random.Random(13).shuffle(cands)
    tune, test = cands[: len(cands) // 2], cands[len(cands) // 2 :]

    grid = list(itertools.product(BLENDS, TABLE_SLOTS))
    scores = {st: recall(tune, st) for st in grid}
    best = max(grid, key=lambda st: (scores[st], st == (1.0, 0)))
    rows = [("fusion only (no reranker)", (0.0, 0)), ("reranker only", (1.0, 0)), ("tuned", best)]
    print("\nrecall@10          tune    test   (blend, table_slots)")
    for name, st in rows:
        print(f"{name:26s} {scores[st]:.3f}  {recall(test, st):.3f}  {st}")

    # Evidence gate: best reranked score for answerable vs unanswerable questions.
    ans_top = sorted(max((h.rerank_score or 0) for h in hs) for _, hs in cands)
    un_top = sorted(max((h.rerank_score or 0) for h in candidates(q)[1]) or 0 for q in unans)
    best_t, best_acc = s.evidence_threshold, -1.0
    for t in sorted(set(ans_top + un_top)):
        acc = (sum(x >= t for x in ans_top) / len(ans_top) + sum(x < t for x in un_top) / max(len(un_top), 1)) / 2
        if acc > best_acc:
            best_t, best_acc = t, acc
    print(f"\ntop reranker score, median: answerable {metrics.median(ans_top)}, unanswerable {metrics.median(un_top)}")
    print(
        f"balanced-accuracy threshold: {best_t:.3f} (keeps {sum(x >= best_t for x in ans_top)}/{len(ans_top)} answerable, "
        f"refuses {sum(x < best_t for x in un_top)}/{len(un_top)} unanswerable)"
    )
    out = {
        "tune_n": len(tune),
        "test_n": len(test),
        "grid": {str(k): v for k, v in scores.items()},
        "best": best,
        "test_recall": {name: recall(test, st) for name, st in rows},
        "threshold": best_t,
    }
    (EVAL_DIR / "results").mkdir(exist_ok=True)
    (EVAL_DIR / "results" / "tune_retrieval.json").write_text(json.dumps(out, indent=2))
    print("\nSet FINSIGHT_RERANK_BLEND / FINSIGHT_TABLE_SLOTS / FINSIGHT_EVIDENCE_THRESHOLD to adopt these.")


if __name__ == "__main__":
    main()

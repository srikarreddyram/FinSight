"""Benchmark runner: ablation runs A-E over FinanceBench, the India set and the unanswerable set.

    uv run python -m eval.run --runs E --sets financebench --limit 20        # quick check
    uv run python -m eval.run --runs A B C D E --sets financebench unanswerable
    uv run python -m eval.run --runs B C D E --retrieval-only                # recall@10 only, no API calls

Each invocation writes eval/results/<timestamp>/{rows.jsonl,summary.json}; then build the report:
    uv run python -m eval.report
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import get_settings
from app.llm import LLM, QuotaExhausted
from app.pipeline import RUNS, Pipeline
from app.store import naive_collection
from eval import metrics
from eval.financebench_loader import EvalQuestion, Evidence, load_questions
from eval.judge import Judge

log = logging.getLogger(__name__)
EVAL_DIR = Path(__file__).resolve().parent


# --------------------------------------------------------------------------------------------
# Question sets
# --------------------------------------------------------------------------------------------


def load_set(name: str) -> list[EvalQuestion]:
    if name == "financebench":
        return load_questions()
    raw = yaml.safe_load((EVAL_DIR / f"{'india_set' if name == 'india' else name}.yaml").read_text())
    out = []
    for q in raw.get("questions") or []:
        if name == "unanswerable":
            out.append(
                EvalQuestion(
                    id=q["id"],
                    question=q["question"],
                    answer="Not found in the filings.",
                    set=name,
                    tickers=q.get("tickers", []),
                    answerable=False,
                )
            )
        elif q.get("answer"):
            ev = [Evidence(doc_id=e["doc_id"], page=int(e["page"]), text=e.get("text", "")) for e in q.get("evidence") or []]
            out.append(
                EvalQuestion(
                    id=q["id"],
                    question=q["question"],
                    answer=str(q["answer"]),
                    set=name,
                    tickers=q.get("tickers", []),
                    doc_ids=sorted({e.doc_id for e in ev}),
                    evidence=ev,
                )
            )
    return out


def eligible(q: EvalQuestion, indexed: set[str], tickers: set[str]) -> bool:
    """Only score questions whose filings are indexed; otherwise failures would measure ingestion gaps."""
    if q.doc_ids:
        return all(d in indexed for d in q.doc_ids)
    return all(t in tickers for t in q.tickers)


# --------------------------------------------------------------------------------------------
# Page text for citation checks
# --------------------------------------------------------------------------------------------


@lru_cache(maxsize=256)
def _parsed(doc_id: str):
    from ingest.manifest import load_documents, local_path
    from ingest.parse import cache_path, parse

    meta = load_documents().get(doc_id)
    if meta is None or not cache_path(doc_id, "structured").exists():
        return None
    return parse(meta, local_path(meta))


def page_text(doc_id: str, page: int) -> str:
    p = _parsed(doc_id)
    if p is None:
        return ""
    return "\n".join(e.text for e in p.elements if e.page <= page <= (e.page_end or e.page))


def gold_page_parsed(q: EvalQuestion) -> bool | None:
    """Did parsing keep the gold evidence's numbers on the gold page? False points at a parsing failure."""
    checks = []
    for e in q.evidence:
        text = page_text(e.doc_id, e.page)
        nums = [n for n in metrics.gold_numbers(e.text)[:12] if n >= 10]
        if not text or not nums:
            continue
        from app.numbers import appears_in

        checks.append(sum(appears_in(n, text) for n in nums) / len(nums) >= 0.6)
    return any(checks) if checks else None


# --------------------------------------------------------------------------------------------
# Scoring one question
# --------------------------------------------------------------------------------------------


def score(pipe: Pipeline, q: EvalQuestion, judge: Judge | None, retrieval_only: bool) -> dict:
    row: dict = {
        "id": q.id,
        "set": q.set,
        "run": pipe.cfg.name,
        "question": q.question,
        "gold": q.answer,
        "answerable": q.answerable,
        "question_type": q.question_type,
    }
    t0 = time.perf_counter()
    with pipe.llm.track() as usage:
        row.update(_run_pipeline(pipe, q, retrieval_only, t0))
    row["usage"] = dict(usage)
    retrieved, ans, pq = row.pop("_retrieved"), row.pop("_answer"), row.pop("_pq")
    row["retrieved"] = [{"doc_id": c.doc_id, "page": c.page, "page_end": c.page_end, "score": c.score} for c in retrieved]
    row["recall10"] = metrics.recall_at_k(retrieved, q, 10)
    row["parsed_query"] = pq.model_dump() if pq else None
    if retrieval_only or not judge:
        return row
    return _judge_row(row, q, ans, judge)


def _run_pipeline(pipe: Pipeline, q: EvalQuestion, retrieval_only: bool, t0: float) -> dict:
    from app.answer import to_citation

    row: dict = {}
    pq, sources, top10 = pipe.retrieve(q.question)
    if retrieval_only:
        retrieved = [to_citation(i, h) for i, h in enumerate(top10)]
        row["latency_s"] = round(time.perf_counter() - t0, 2)
        row["top_score"] = max((h.rerank_score or 0.0 for h in sources), default=None) if pipe.cfg.rerank else None
        return {**row, "_retrieved": retrieved, "_answer": None, "_pq": pq}
    ans = pipe.answer_from(q.question, pq, sources, top10)
    row.update(
        answer=ans.answer,
        table=ans.table_markdown,
        refused=ans.refused,
        latency_s=round(time.perf_counter() - t0, 2),
        stripped=ans.stripped_sentences,
        figures=[f.model_dump() for f in ans.figures],
        calculations=[c.model_dump() for c in ans.calculations],
        citations=[{"label": c.label, "doc_id": c.doc_id, "page": c.page} for c in ans.citations],
    )
    row["top_score"] = max((c.score or 0.0 for c in ans.retrieved), default=None) if pipe.cfg.rerank else None
    return {**row, "_retrieved": ans.retrieved, "_answer": ans, "_pq": pq}


def _judge_row(row: dict, q: EvalQuestion, ans, judge: Judge) -> dict:
    if q.answerable and not row["refused"]:
        pages = {c.label: page_text(c.doc_id, c.page) for c in ans.citations}
        candidate = ans.answer + ("\n" + ans.table_markdown if ans.table_markdown else "")
        try:
            row["correct"], row["judge_reason"], row["citation_support"] = judge.grade(
                q.question, q.answer, candidate, {k: v for k, v in pages.items() if v}
            )
        except QuotaExhausted:
            raise
        except Exception as e:  # noqa: BLE001
            row["correct"], row["judge_reason"], row["citation_support"] = None, f"judge error: {e}", {}
    else:
        row["correct"] = row["refused"] if not q.answerable else False
    if q.answerable and metrics.is_numeric_question(q):
        row["numeric_q"] = True
        row["numeric_ok"] = (not row["refused"]) and metrics.numeric_match(ans.answer + (ans.table_markdown or ""), q)
    support = row.get("citation_support") or {}
    row["failure"] = metrics.tag_failure(
        correct=row.get("correct"),
        refused=row["refused"],
        answerable=q.answerable,
        recall10=row["recall10"],
        gold_page_parsed=gold_page_parsed(q) if row["recall10"] is False else None,
        citations_ok=all(support.values()) if support else None,
    )
    return row


def summarize(rows: list[dict], cost_usd: float | None) -> dict:
    ans = [r for r in rows if r["answerable"]]
    unans = [r for r in rows if not r["answerable"]]
    cites = [v for r in ans for v in (r.get("citation_support") or {}).values()]
    return {
        "n": len(rows),
        "accuracy": metrics.rate([r.get("correct") for r in ans]) if ans and "correct" in ans[0] else None,
        "numeric_match": metrics.rate([r.get("numeric_ok") for r in ans if r.get("numeric_q")]),
        "numeric_n": sum(1 for r in ans if r.get("numeric_q")),
        "citation_precision": metrics.rate(cites),
        "recall_at_10": metrics.rate([r.get("recall10") for r in ans]),
        "correct_refusals": metrics.rate([r.get("refused") for r in unans]) if unans and "refused" in unans[0] else None,
        "false_refusals": metrics.rate([r.get("refused") for r in ans]) if ans and "refused" in ans[0] else None,
        "median_latency_s": metrics.median([r["latency_s"] for r in rows]),
        "cost_usd": round(cost_usd, 3) if cost_usd is not None else None,
        "failures": dict(Counter(r["failure"] for r in rows if r.get("failure"))),
        "top_score_answerable": metrics.median([r["top_score"] for r in ans if r.get("top_score") is not None]),
        "top_score_unanswerable": metrics.median([r["top_score"] for r in unans if r.get("top_score") is not None]),
    }


def previous_rows(models: dict, retrieval_only: bool) -> dict[tuple[str, str, str], dict]:
    """Rows already scored by earlier invocations with the same models and mode, keyed by (run, set, id).
    Free-tier quotas run out mid-benchmark; this lets the next day's run pick up where it stopped."""
    out: dict[tuple[str, str, str], dict] = {}
    for d in sorted((EVAL_DIR / "results").glob("*/")):
        sfile, rfile = d / "summary.json", d / "rows.jsonl"
        if not (sfile.exists() and rfile.exists()):
            continue
        meta = json.loads(sfile.read_text())
        if meta.get("models") != models or bool(meta.get("config", {}).get("retrieval_only")) != retrieval_only:
            continue
        for line in rfile.read_text().splitlines():
            r = json.loads(line)
            if retrieval_only or "correct" in r:
                out[(r["run"], r["set"], r["id"])] = r
    return out


def main() -> None:
    from ingest.index import indexed_docs
    from ingest.manifest import load_documents

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", nargs="+", default=["E"], choices=list(RUNS))
    ap.add_argument(
        "--sets", nargs="+", default=["financebench", "unanswerable"], choices=["financebench", "india", "unanswerable"]
    )
    ap.add_argument("--limit", type=int, help="random sample of N questions per set (fixed seed)")
    ap.add_argument("--retrieval-only", action="store_true", help="recall@10 without any LLM calls")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--no-llm-parser", action="store_true", help="heuristic query parsing only")
    ap.add_argument("--fresh", action="store_true", help="re-score everything instead of resuming earlier rows")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    s = get_settings()
    docs = load_documents()
    out_dir = EVAL_DIR / "results" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    # No quota fallback in benchmarks: every answer must come from the configured model; runs resume instead.
    system_llm = LLM(s.model_copy(update={"quota_fallback_model": None}))
    base = Pipeline(llm=system_llm)
    judge = None if args.retrieval_only else Judge(LLM(s.model_copy(update={"quota_fallback_model": None})))
    summary: dict = {
        "config": vars(args),
        "models": {"answer": s.answer_model, "fast": s.fast_model, "judge": s.judge_model},
        "results": {},
    }

    done = previous_rows(summary["models"], args.retrieval_only) if not args.fresh else {}
    stop = threading.Event()

    def run_one(pipe: Pipeline, q: EvalQuestion) -> dict | None:
        if stop.is_set():
            return None
        try:
            return score(pipe, q, judge, args.retrieval_only)
        except QuotaExhausted as e:
            if not stop.is_set():
                log.warning("%s. Stopping; rerun the same command later to resume.", e)
            stop.set()
            return None

    # Written up front (and again at the end) so a crashed run's rows can still be resumed.
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    with (out_dir / "rows.jsonl").open("w") as f:
        for run in args.runs:
            cfg = RUNS[run]
            if args.retrieval_only or args.no_llm_parser:
                cfg = cfg.__class__(**{**cfg.__dict__, "llm_query_parser": False})
            pipe = base.with_config(cfg)
            indexed = set(indexed_docs(naive_collection(s) if cfg.naive_index else s.collection))
            tickers = {docs[d].ticker for d in indexed if d in docs}
            for set_name in args.sets:
                qs = [q for q in load_set(set_name) if eligible(q, indexed, tickers)]
                if args.limit and len(qs) > args.limit:
                    qs = random.Random(7).sample(qs, args.limit)
                if not qs:
                    log.warning("run %s / %s: no eligible questions (index the filings first)", run, set_name)
                    continue
                reused = [done[(run, set_name, q.id)] for q in qs if (run, set_name, q.id) in done]
                todo = [q for q in qs if (run, set_name, q.id) not in done]
                log.info(
                    "run %s / %s: %d questions (%d already scored, %d to go)", run, set_name, len(qs), len(reused), len(todo)
                )
                calls0, cost0 = system_llm.calls(), system_llm.cost_usd()
                for r in reused:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
                new = []
                with ThreadPoolExecutor(args.workers) as pool:
                    futures = [pool.submit(run_one, pipe, q) for q in todo]
                    for fut in as_completed(futures):
                        r = fut.result()
                        if r is None:
                            continue
                        new.append(r)
                        f.write(json.dumps(r, ensure_ascii=False) + "\n")
                        f.flush()  # every answer costs quota: keep it even if the run dies
                        if len(new) % 10 == 0:
                            log.info("run %s / %s: %d/%d scored", run, set_name, len(new), len(todo))
                rows = reused + new
                res = summarize(rows, None if args.retrieval_only else system_llm.cost_usd() - cost0)
                res["complete"] = len(rows) == len(qs)
                res["llm_calls"] = {m: c - calls0.get(m, 0) for m, c in system_llm.calls().items() if c - calls0.get(m, 0)}
                summary["results"][f"{run}/{set_name}"] = res
                log.info("run %s / %s: %s", run, set_name, {k: v for k, v in res.items() if k != "failures"})
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    log.info("results in %s; build the report with: uv run python -m eval.report", out_dir)


if __name__ == "__main__":
    main()

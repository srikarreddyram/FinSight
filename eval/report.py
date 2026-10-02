"""Build eval/REPORT.md from eval/results/*/ (the newest result for each run/set wins).

uv run python -m eval.report
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

from app.pipeline import RUNS

EVAL_DIR = Path(__file__).resolve().parent
TARGETS = {"accuracy": 0.60, "numeric_match": 0.80, "citation_precision": 0.90, "recall_at_10": 0.85, "correct_refusals": 0.80}


def _pct(x) -> str:
    return "–" if x is None else f"{x * 100:.0f}%"


def _describe(run: str) -> tuple[str, str, str, str]:
    c = RUNS[run]
    return (
        "PyPDF, 1,000-token chunks" if c.naive_index else "Docling, section + table chunks",
        "Hybrid (BM25 + dense)" if c.hybrid else "Dense only",
        "Yes" if c.rerank else "No",
        "Yes" if c.filters else "No",
    )


def load() -> tuple[dict[str, dict], dict[str, list[dict]], dict]:
    results, rows, models = {}, {}, {}
    for d in sorted((EVAL_DIR / "results").glob("*/")):
        s = d / "summary.json"
        if not s.exists():
            continue
        summary = json.loads(s.read_text())
        by_key: dict[str, list[dict]] = {}
        for line in (d / "rows.jsonl").read_text().splitlines():
            r = json.loads(line)
            by_key.setdefault(f"{r['run']}/{r['set']}", []).append(r)
        for key, res in summary["results"].items():
            # an answered run supersedes a retrieval-only one, whatever the order
            if key in results and results[key].get("accuracy") is not None and res.get("accuracy") is None:
                continue
            results[key] = res
            rows[key] = by_key.get(key, [])
            models = summary.get("models", models)
    return results, rows, models


def build() -> str:
    results, rows, models = load()
    if not results:
        return "# FinSight evaluation\n\nNo results yet. Run `uv run python -m eval.run` first.\n"
    runs = sorted({k.split("/")[0] for k in results})
    out = [
        "# FinSight evaluation report",
        "",
        f"Generated {date.today().isoformat()} from `eval/results/`. Answer model `{models.get('answer')}`, "
        f"query parser / table summaries `{models.get('fast')}`, judge `{models.get('judge')}`.",
        "",
        "## Ablation (FinanceBench open sample)",
        "",
        "| Run | Parsing | Retrieval | Reranker | Filters | N | Accuracy | Numeric EM | Citation precision | Recall@10 | Median latency | Cost |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for run in runs:
        r = results.get(f"{run}/financebench")
        if not r:
            continue
        p, ret, rr, f = _describe(run)
        lat = f"{r['median_latency_s']} s" if r.get("median_latency_s") is not None else "–"
        calls = sum((r.get("llm_calls") or {}).values())
        if r.get("cost_usd"):
            cost = f"${r['cost_usd']:.2f}"
        elif calls:
            cost = f"free ({calls} calls)"
        else:
            cost = "–"
        n = f"{r['n']}" + ("" if r.get("complete", True) else " (partial)")
        out.append(
            f"| {run} | {p} | {ret} | {rr} | {f} | {n} | {_pct(r.get('accuracy'))} | {_pct(r.get('numeric_match'))} "
            f"| {_pct(r.get('citation_precision'))} | {_pct(r.get('recall_at_10'))} | {lat} | {cost} |"
        )
    out += [
        "",
        "Targets: " + ", ".join(f"{k.replace('_', ' ')} ≥ {v:.0%}" for k, v in TARGETS.items()) + ", median latency < 10 s.",
        "",
    ]

    other = [k for k in results if not k.endswith("/financebench")]
    if other:
        out += [
            "## Other sets",
            "",
            "| Run / set | N | Accuracy | Correct refusals | False refusals | Recall@10 |",
            "|---|---|---|---|---|---|",
        ]
        for k in sorted(other):
            r = results[k]
            out.append(
                f"| {k} | {r['n']} | {_pct(r.get('accuracy'))} | {_pct(r.get('correct_refusals'))} | {_pct(r.get('false_refusals'))} | {_pct(r.get('recall_at_10'))} |"
            )
        out.append("")

    best = max(runs)
    fails = Counter()
    examples: list[dict] = []
    for k, rs in rows.items():
        if k.startswith(f"{best}/"):
            for r in rs:
                if r.get("failure"):
                    fails[r["failure"]] += 1
                    examples.append(r)
    if fails:
        out += [f"## Where it still fails (run {best})", "", "| Category | Count |", "|---|---|"]
        out += [f"| {c} | {n} |" for c, n in fails.most_common()]
        out += ["", "Examples:", ""]
        for r in examples[:12]:
            ans = (r.get("answer") or "").replace("\n", " ")[:220]
            out.append(f"- **{r['failure']}** — {r['question'][:160]}  \n  gold: {r['gold'][:160]}  \n  ours: {ans}")
        out.append("")

    cal = [
        (k, r)
        for k, r in results.items()
        if r.get("top_score_answerable") is not None or r.get("top_score_unanswerable") is not None
    ]
    if cal:
        out += [
            "## Evidence-gate calibration",
            "",
            "Median top reranker score (sigmoid) of the best retrieved passage. The gate threshold "
            "(`FINSIGHT_EVIDENCE_THRESHOLD`) should sit between the two.",
            "",
            "| Run / set | Answerable | Unanswerable |",
            "|---|---|---|",
        ]
        for k, r in sorted(cal):
            out.append(f"| {k} | {r.get('top_score_answerable') or '–'} | {r.get('top_score_unanswerable') or '–'} |")
        out.append("")
    return "\n".join(out)


def main() -> None:
    text = build()
    (EVAL_DIR / "REPORT.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()

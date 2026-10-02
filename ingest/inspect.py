"""Eyeball parsed output before trusting it: parsing bugs are silent and poison everything downstream.

uv run python -m ingest.inspect 3M_2018_10K                 # section map + table overview
uv run python -m ingest.inspect 3M_2018_10K --page 60       # every element on a page
uv run python -m ingest.inspect 3M_2018_10K --tables 5      # print the first N table chunks in full
"""

from __future__ import annotations

import argparse
from collections import Counter

from app.config import get_settings
from ingest.chunk import chunk_structured
from ingest.manifest import load_documents, local_path
from ingest.parse import parse


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("doc_id")
    ap.add_argument("--page", type=int)
    ap.add_argument("--tables", type=int, default=0)
    args = ap.parse_args()

    meta = load_documents()[args.doc_id]
    parsed = parse(meta, local_path(meta))
    if args.page:
        for el in parsed.elements:
            if el.page <= args.page <= (el.page_end or el.page):
                print(f"--- {el.kind} [{el.section} | {el.heading[:60]}] context={el.context[:80]!r}")
                print(el.text[:3000])
        return

    print(f"{meta.doc_id}: {parsed.page_count} pages, parser={parsed.parser}")
    # Section map: first page each section appears on, and how many elements it has.
    first: dict[str, int] = {}
    counts: Counter = Counter()
    for el in parsed.elements:
        first.setdefault(el.section, el.page)
        counts[el.section] += 1
    for sec, page in sorted(first.items(), key=lambda x: x[1]):
        print(f"  {sec:22s} from p.{page:<4d} {counts[sec]} elements")
    chunks = chunk_structured(parsed, get_settings(), summarizer=None)
    kinds = Counter(c.chunk_type for c in chunks)
    print(f"chunks: {dict(kinds)}")
    for c in [c for c in chunks if c.chunk_type == "table"][: args.tables]:
        print(f"\n=== {c.chunk_id} p.{c.page}-{c.page_end} [{c.section}]\n{c.text[:2500]}")


if __name__ == "__main__":
    main()

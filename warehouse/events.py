"""EDGAR filing index for the Risk Engine's event pillar (platform PRD, Module 7).

    uv run python -m warehouse.events          # every universe company and its predecessors

Keeps the forms that signal trouble: late-filing notices (NT 10-K, NT 10-Q), amended annual reports (10-K/A),
and 8-Ks with their item numbers (4.01 auditor change, 4.02 non-reliance on previously issued financials).
Companies already in the table are skipped, so a run resumes.
"""

from __future__ import annotations

import logging
from datetime import date

import duckdb

from app.config import get_settings
from warehouse import db

log = logging.getLogger(__name__)

FORMS = {"NT 10-K", "NT 10-Q", "10-K/A", "8-K", "8-K/A", "10-K", "10-Q"}


def rows_from_submissions(cik: int, blocks: list[dict]) -> list[tuple]:
    out = {}
    for b in blocks:
        for accn, form, filed, items in zip(
            b["accessionNumber"], b["form"], b["filingDate"], b.get("items") or [""] * len(b["form"]), strict=True
        ):
            if form in FORMS:
                out[accn] = (cik, accn, form, date.fromisoformat(filed), items or None)
    return list(out.values())


def fetch(con: duckdb.DuckDBPyConnection) -> None:
    from ingest.fetch_edgar import SUBMISSIONS_URL, Edgar

    edgar = Edgar(get_settings().sec_user_agent)
    todo = [r[0] for r in con.execute(
        "select distinct cik from (select cik from universe union select predecessor from cik_links) "
        "where cik not in (select distinct cik from filing_index) order by 1"
    ).fetchall()]  # fmt: skip
    log.info("%d companies to index", len(todo))
    for i, cik in enumerate(todo, 1):
        try:
            sub = edgar.get(SUBMISSIONS_URL.format(cik=cik)).json()
            blocks = [sub["filings"]["recent"]] + [
                edgar.get(f"https://data.sec.gov/submissions/{p['name']}").json() for p in sub["filings"].get("files", [])
            ]
        except Exception as e:  # noqa: BLE001
            log.warning("CIK %d: %s", cik, e)
            continue
        rows = rows_from_submissions(cik, blocks)
        if rows:
            con.executemany("insert into filing_index values (?, ?, ?, ?, ?) on conflict do nothing", rows)
        if i % 100 == 0:
            log.info("%d/%d", i, len(todo))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    con = db.connect()
    fetch(con)
    log.info("filing_index: %s", con.execute("select form, count(*) from filing_index group by 1 order by 2 desc").fetchall())
    con.close()

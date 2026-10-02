"""SEC XBRL companyfacts: every value a company has reported, with the date and filing it came from.

    uv run python -m warehouse.xbrl MMM NKE PEP        # needs FINSIGHT_SEC_USER_AGENT in .env

The endpoint returns one JSON document per company. Each value lists its period, the accession number of
the filing that reported it, and `filed`, the date EDGAR accepted that filing. A value repeated in a later
filing (as a prior-year comparative, or restated) appears again with that filing's accession and date,
which is exactly the history a point-in-time warehouse needs.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import astuple, dataclass
from datetime import date, timedelta

import duckdb
import pandas as pd

from app.config import get_settings
from warehouse import db

log = logging.getLogger(__name__)

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
FORMS = {"10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F"}
TAXONOMIES = ("us-gaap", "dei", "ifrs-full")


@dataclass(frozen=True)
class Fact:
    cik: int
    taxonomy: str
    concept: str
    unit: str
    value: float
    period_start: date | None
    period_end: date
    filed_at: date
    accn: str
    form: str | None = None
    fy: int | None = None
    fp: str | None = None

    @property
    def available_at(self) -> date:
        # Filings accepted after the close can't be acted on the same day.
        return self.filed_at + timedelta(days=1)


def _day(s: str | None) -> date | None:
    return date.fromisoformat(s) if s else None


def parse_companyfacts(doc: dict, forms: set[str] | None = FORMS) -> list[Fact]:
    """Flatten a companyfacts document into one Fact per reported value (per filing)."""
    cik = int(doc["cik"])
    out: list[Fact] = []
    for taxonomy, concepts in doc.get("facts", {}).items():
        if taxonomy not in TAXONOMIES:
            continue
        for concept, body in concepts.items():
            for unit, values in body.get("units", {}).items():
                for v in values:
                    if forms and v.get("form") not in forms:
                        continue  # 8-Ks, S-1s etc. aren't periodic reports
                    if v.get("val") is None or not v.get("end") or not v.get("filed"):
                        continue
                    out.append(
                        Fact(
                            cik=cik,
                            taxonomy=taxonomy,
                            concept=concept,
                            unit=unit,
                            value=float(v["val"]),
                            period_start=_day(v.get("start")),
                            period_end=_day(v["end"]),
                            filed_at=_day(v["filed"]),
                            accn=v["accn"],
                            form=v.get("form"),
                            fy=v.get("fy"),
                            fp=v.get("fp"),
                        )
                    )
    return out


def insert_facts(con: duckdb.DuckDBPyConnection, facts: list[Fact], replace_ciks: bool = True) -> int:
    """Store facts. Re-fetching a company replaces its rows wholesale (the source is append-only, so the
    new pull is a superset); within a pull every filing's value is its own row."""
    if not facts:
        return 0
    if replace_ciks:
        for cik in {f.cik for f in facts}:
            con.execute("delete from facts where cik = ?", [cik])
    cols = ["cik", "taxonomy", "concept", "unit", "value", "period_start", "period_end", "filed_at", "available_at",
            "accn", "form", "fy", "fp"]  # fmt: skip
    rows = pd.DataFrame([(*astuple(f)[:8], f.available_at, *astuple(f)[8:]) for f in facts], columns=cols)
    con.register("new_facts", rows)  # one bulk insert: executemany goes row by row
    con.execute(f"insert into facts ({', '.join(cols)}) select * from new_facts")
    con.execute(
        "insert into filings (accn, cik, form, filed_at, fy, fp) "
        "select distinct on (accn) accn, cik, form, filed_at, fy, fp from new_facts on conflict do nothing"
    )
    con.unregister("new_facts")
    return len(rows)


def fetch(tickers: list[str]) -> None:
    from ingest.fetch_edgar import Edgar

    s = get_settings()
    if not s.sec_user_agent:
        raise SystemExit('Set FINSIGHT_SEC_USER_AGENT in .env, e.g. "FinSight research you@example.com" (SEC requires it)')
    edgar = Edgar(s.sec_user_agent)
    con = db.connect()
    missing = []
    for t in tickers:
        try:
            cik = edgar.cik(t)
        except SystemExit:  # not in SEC's current ticker list: delisted, acquired or renamed
            missing.append(t)
            continue
        doc = edgar.get(COMPANYFACTS_URL.format(cik=cik)).json()
        facts = parse_companyfacts(doc)
        n = insert_facts(con, facts)
        con.execute(
            "insert into companies (cik, ticker, name) values (?, ?, ?) "
            "on conflict (cik) do update set ticker = excluded.ticker, name = excluded.name",
            [cik, t.upper(), doc.get("entityName")],
        )
        log.info("%s (CIK %d): %d facts from %d filings", t, cik, n, len({f.accn for f in facts}))
    con.close()
    if missing:
        log.warning("not in SEC's current ticker list (use the CIK instead): %s", ", ".join(missing))


def fetch_universe() -> None:
    """companyfacts for every universe company not in the warehouse yet, by CIK (most removed companies have
    no ticker in SEC's current list). Resumable: companies already fetched are skipped."""
    from ingest.fetch_edgar import Edgar

    s = get_settings()
    edgar = Edgar(s.sec_user_agent)
    con = db.connect()
    todo = [r[0] for r in con.execute(
        "select distinct cik from (select cik from universe union select predecessor from cik_links) "
        "where cik not in (select distinct cik from facts) order by cik"
    ).fetchall()]  # fmt: skip
    log.info("%d companies to fetch", len(todo))
    for i, cik in enumerate(todo, 1):
        try:
            doc = edgar.get(COMPANYFACTS_URL.format(cik=cik)).json()
        except Exception as e:  # noqa: BLE001  (404: filed before XBRL, or never did)
            log.warning("CIK %d: %s", cik, e)
            continue
        n = insert_facts(con, parse_companyfacts(doc))
        if i % 25 == 0 or n == 0:
            log.info("%d/%d  CIK %d %s: %d facts", i, len(todo), cik, doc.get("entityName"), n)
    con.close()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tickers", nargs="*")
    ap.add_argument("--track", help="all companies from this manifest track (e.g. financebench)")
    ap.add_argument("--universe", action="store_true", help="every company in the universe table, by CIK")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.universe:
        return fetch_universe()
    tickers = list(args.tickers)
    if args.track:
        from ingest.manifest import load_documents

        tickers += sorted({m.ticker for m in load_documents().values() if m.track == args.track})
    fetch(list(dict.fromkeys(t.upper() for t in tickers)))


if __name__ == "__main__":
    main()

"""Insider trades from SEC's Form 3/4/5 data sets into `insider_trades`.

    uv run python -m warehouse.insiders                # every quarter from 2009, universe companies only

SEC publishes every Form 3, 4 and 5 as quarterly tab-separated files. Kept: Form 4 (and 4/A) open-market
purchases (code P) and sales (code S) of non-derivative securities by an issuer's directors and officers, with
the filing date, which is when the trade became public. Zips are cached in data/cache/form345, and quarters already
loaded are skipped, so a run resumes.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import date

import duckdb
import pandas as pd

from app.config import get_settings
from warehouse import db

log = logging.getLogger(__name__)

INDEX = "https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets"
FIRST_YEAR = 2009
FORMS = {"4", "4/A"}
CODES = {"P", "S"}  # open-market purchase, open-market sale


def _read(z: zipfile.ZipFile, name: str, cols: list[str]) -> pd.DataFrame:
    with z.open(name) as f:
        return pd.read_csv(f, sep="\t", usecols=cols, dtype=str, quoting=3, on_bad_lines="skip")


def parse_quarter(blob: bytes, ciks: set[int]) -> pd.DataFrame:
    """One quarter's zip -> trades by directors and officers of the given issuers."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    sub = _read(z, "SUBMISSION.tsv", ["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK"])
    sub = sub[sub["DOCUMENT_TYPE"].isin(FORMS)]
    sub["issuer_cik"] = pd.to_numeric(sub["ISSUERCIK"], errors="coerce")
    sub = sub[sub["issuer_cik"].isin(ciks)]
    own = _read(z, "REPORTINGOWNER.tsv", ["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP"])
    rel = own["RPTOWNER_RELATIONSHIP"].fillna("")
    own["director"] = rel.str.contains("Director", case=False)
    own["officer"] = rel.str.contains("Officer", case=False)
    own = own[own["director"] | own["officer"]]
    # A filing can list several owners (a fund and its manager): one row per filing, the first insider listed.
    own = own.drop_duplicates("ACCESSION_NUMBER")
    tr = _read(z, "NONDERIV_TRANS.tsv", ["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES", "TRANS_PRICEPERSHARE"])
    tr = tr[tr["TRANS_CODE"].isin(CODES)]
    df = tr.merge(sub, on="ACCESSION_NUMBER").merge(own, on="ACCESSION_NUMBER")
    if df.empty:
        return pd.DataFrame(
            columns=[
                "issuer_cik",
                "owner_cik",
                "filed_at",
                "trans_date",
                "code",
                "shares",
                "price",
                "director",
                "officer",
                "accession",
            ]
        )
    when = lambda s: pd.to_datetime(s, format="%d-%b-%Y", errors="coerce").dt.date  # noqa: E731  "31-JAN-2024"
    out = pd.DataFrame({
        "issuer_cik": df["issuer_cik"].astype(int),
        "owner_cik": pd.to_numeric(df["RPTOWNERCIK"], errors="coerce"),
        "filed_at": when(df["FILING_DATE"]),
        "trans_date": when(df["TRANS_DATE"]),
        "code": df["TRANS_CODE"],
        "shares": pd.to_numeric(df["TRANS_SHARES"], errors="coerce"),
        "price": pd.to_numeric(df["TRANS_PRICEPERSHARE"], errors="coerce"),
        "director": df["director"],
        "officer": df["officer"],
        "accession": df["ACCESSION_NUMBER"],
    })  # fmt: skip
    return out.dropna(subset=["owner_cik", "filed_at"]).reset_index(drop=True)


def quarters(index_html: str) -> list[tuple[str, str]]:
    """(name, url) of each quarterly zip on SEC's index page, from FIRST_YEAR on."""
    out = {}
    for path in re.findall(r'href="([^"]*?(\d{4}q[1-4])_form345\.zip)"', index_html):
        url, name = path
        if int(name[:4]) >= FIRST_YEAR:
            out[name] = url if url.startswith("http") else f"https://www.sec.gov{url}"
    return sorted(out.items())


def load(con: duckdb.DuckDBPyConnection) -> None:
    from ingest.fetch_edgar import Edgar

    edgar = Edgar(get_settings().sec_user_agent)
    cache = get_settings().data_dir / "cache" / "form345"
    cache.mkdir(parents=True, exist_ok=True)
    ciks = {r[0] for r in con.execute("select cik from universe union select predecessor from cik_links").fetchall()}
    done = {r[0] for r in con.execute("select quarter from insider_quarters").fetchall()}
    this_quarter = f"{date.today().year}q{(date.today().month - 1) // 3 + 1}"
    for name, url in quarters(edgar.get(INDEX).text):
        if name in done:
            continue
        path = cache / f"{name}_form345.zip"
        if not path.exists():
            path.write_bytes(edgar.get(url).content)
        trades = parse_quarter(path.read_bytes(), ciks)
        if len(trades):
            con.register("trades", trades)
            # The current quarter is reloaded on every run: replace its earlier rows rather than add to them.
            con.execute("delete from insider_trades where accession in (select accession from trades)")
            con.execute("insert into insider_trades select * from trades")
            con.unregister("trades")
        if name != this_quarter:  # the current quarter's file grows; reload it next time
            con.execute("insert into insider_quarters values (?)", [name])
        log.info("%s: %d trades", name, len(trades))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    con = db.connect()
    load(con)
    log.info(
        "insider_trades: %s",
        con.execute("select code, count(*), count(distinct issuer_cik) from insider_trades group by 1").fetchall(),
    )
    con.close()


if __name__ == "__main__":
    main()

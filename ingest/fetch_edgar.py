"""Fetch 10-K / 10-Q / 20-F filings from SEC EDGAR and print them to PDF so citations have page numbers.

EDGAR serves filings as HTML, which has no pages. Headless Chrome honours the filings' page-break CSS
when printing, so the PDF pages line up with the filing's own pagination.

SEC requires a User-Agent with contact details; set it once in .env:
    FINSIGHT_SEC_USER_AGENT="FinSight research you@example.com"

    uv run python -m ingest.fetch_edgar AAPL MSFT NVDA --years 3
    uv run python -m ingest.fetch_edgar AAPL --forms 10-Q --years 1
    uv run python -m ingest.fetch_edgar INFY HDB IBN WIT RDY MMYT --forms 20-F --track india
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

from app import fiscal
from app.config import get_settings
from app.schemas import Company, DocMeta
from ingest.manifest import load_companies, upsert

log = logging.getLogger(__name__)

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
DOC_TYPES = {"10-K": "10-K", "10-Q": "10-Q", "20-F": "20-F"}


class Edgar:
    def __init__(self, user_agent: str):
        self.http = httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}, timeout=60, follow_redirects=True
        )
        self._last = 0.0

    RETRY_WAITS = (5, 30, 120)  # seconds, after a dropped connection, a 429 or a server error
    # SEC allows 10 requests/second in total; a second job running beside a load should set this higher.
    interval = float(os.environ.get("FINSIGHT_SEC_INTERVAL", "0.15"))

    def _once(self, url: str) -> httpx.Response:
        wait = self.interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        return self.http.get(url)

    def get(self, url: str) -> httpx.Response:
        for pause in (*self.RETRY_WAITS, None):
            try:
                r = self._once(url)
            except httpx.TransportError:
                if pause is None:
                    raise
            else:
                if pause is None or (r.status_code != 429 and r.status_code < 500):
                    break
            log.warning("retrying %s in %ds", url, pause)
            time.sleep(pause)
        if r.status_code == 403:
            raise SystemExit(
                "SEC returned 403: FINSIGHT_SEC_USER_AGENT must include a contact email, e.g. 'FinSight research you@example.com'"
            )
        r.raise_for_status()
        return r

    def cik(self, ticker: str) -> int:
        if not hasattr(self, "_tickers"):
            self._tickers = {v["ticker"].upper(): int(v["cik_str"]) for v in self.get(TICKERS_URL).json().values()}
        try:
            return self._tickers[ticker.upper()]
        except KeyError:
            raise SystemExit(f"{ticker}: not found in SEC's ticker list") from None


def _settle(d: date) -> date:
    """52/53-week fiscal years can end a few days into the next month (Costco: 1 Sep); treat those as the prior month."""
    return d - timedelta(days=7) if d.day <= 7 else d


def fye_month(fiscal_year_end: str | None) -> int:
    """SEC's fiscalYearEnd is MMDD, e.g. "0331", "0928", "0101"."""
    if not fiscal_year_end:
        return 12
    m, d = int(fiscal_year_end[:2]), int(fiscal_year_end[2:])
    return _settle(date(2001, m, d)).month


def print_to_pdf(html: Path, pdf: Path, chrome: str) -> None:
    subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            "--run-all-compositor-stages-before-draw",
            f"--print-to-pdf={pdf}",
            html.resolve().as_uri(),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )


def fetch(tickers: list[str], forms: list[str], years: int, track: str) -> None:
    s = get_settings()
    if not s.sec_user_agent:
        raise SystemExit('Set FINSIGHT_SEC_USER_AGENT (e.g. "FinSight research you@example.com") in .env; SEC requires it.')
    if not Path(s.chrome_path).exists():
        raise SystemExit(f"Chrome not found at {s.chrome_path}; set FINSIGHT_CHROME_PATH (needed to paginate filings).")
    edgar = Edgar(s.sec_user_agent)
    known = load_companies()
    companies: list[Company] = []
    docs: list[DocMeta] = []

    for ticker in tickers:
        cik = edgar.cik(ticker)
        sub = edgar.get(SUBMISSIONS_URL.format(cik=cik)).json()
        fye = fye_month(sub.get("fiscalYearEnd"))
        co = known.get(ticker) or Company(
            ticker=ticker, name=sub["name"].title(), fiscal_year_end_month=fye, country="IN" if track == "india" else "US"
        )
        co = co.model_copy(update={"fiscal_year_end_month": fye})
        companies.append(co)
        recent = sub["filings"]["recent"]
        rows = [dict(zip(recent.keys(), vals, strict=True)) for vals in zip(*recent.values(), strict=True)]

        for form in forms:
            filings = [r for r in rows if r["form"] == form and r.get("reportDate")]
            seen_years: list[int] = []
            for r in filings:  # newest first
                period_end = _settle(date.fromisoformat(r["reportDate"]))
                fy = fiscal.fiscal_year_of(period_end, fye)
                period = "FY" if form in ("10-K", "20-F") else fiscal.quarter_of(period_end, fye)
                if fy not in seen_years:
                    if len(seen_years) >= years:
                        break
                    seen_years.append(fy)
                suffix = form.replace("-", "") if period == "FY" else f"{period}_{form.replace('-', '')}"
                doc_id = f"{ticker}_FY{fy}_{suffix}"
                if any(d.doc_id == doc_id for d in docs):
                    continue  # amendments / duplicates: keep the newest
                acc = r["accessionNumber"].replace("-", "")
                url = ARCHIVE_URL.format(cik=cik, acc=acc, doc=r["primaryDocument"])
                out_dir = s.filings_dir / ticker
                out_dir.mkdir(parents=True, exist_ok=True)
                pdf = out_dir / f"{doc_id}.pdf"
                if not pdf.exists():
                    html = out_dir / f"{doc_id}.htm"
                    html.write_bytes(edgar.get(url).content)
                    print_to_pdf(html, pdf, s.chrome_path)
                    html.unlink()
                    log.info("%s -> %s", url, pdf)
                docs.append(
                    DocMeta(
                        doc_id=doc_id,
                        ticker=ticker,
                        company=co.name,
                        doc_type=DOC_TYPES[form],
                        fiscal_year=fy,
                        period=period,
                        fiscal_year_end_month=fye,
                        url=url,
                        local_path=str(pdf.relative_to(s.data_dir.parent)),
                        track=track,
                    )
                )
    upsert(s.data_dir / f"manifest.{track}.yaml", companies, docs)
    log.info("wrote %d documents for %d companies to manifest.%s.yaml", len(docs), len(companies), track)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tickers", nargs="+")
    ap.add_argument("--forms", nargs="+", default=["10-K"], choices=list(DOC_TYPES))
    ap.add_argument("--years", type=int, default=3, help="most recent N fiscal years per form")
    ap.add_argument("--track", default="edgar")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    fetch([t.upper() for t in args.tickers], args.forms, args.years, args.track)


if __name__ == "__main__":
    main()

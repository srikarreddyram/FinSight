"""Dated evidence about a company: news headlines (Google News RSS) and its SEC 8-K filings (EDGAR, live).

Google News needs no key and returns each article's headline, publisher, link and time. Requests carry a
generic User-Agent: the contact email in FINSIGHT_SEC_USER_AGENT is for SEC only.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime

import httpx

log = logging.getLogger(__name__)

GOOGLE_NEWS = "https://news.google.com/rss/search"
HEADERS = {"User-Agent": "FinSight/0.1 (research project)"}
MAX_NEWS = 40

# 8-K item numbers -> what they announce. 9.01 (exhibits) only says what is attached, so it is left out.
ITEMS = {
    "1.01": "Material agreement",
    "1.02": "Agreement terminated",
    "1.03": "Bankruptcy or receivership",
    "1.05": "Cybersecurity incident",
    "2.01": "Acquisition or disposal completed",
    "2.02": "Results of operations",
    "2.03": "New debt obligation",
    "2.04": "Debt obligation accelerated",
    "2.05": "Restructuring or exit costs",
    "2.06": "Impairment",
    "3.01": "Listing standards notice or delisting",
    "3.02": "Unregistered equity sale",
    "3.03": "Change to shareholder rights",
    "4.01": "Auditor change",
    "4.02": "Prior financials no longer reliable",
    "5.01": "Change in control",
    "5.02": "Executive or director change",
    "5.03": "Bylaws or fiscal year change",
    "5.07": "Shareholder vote results",
    "7.01": "Regulation FD disclosure",
    "8.01": "Other events",
}


@dataclass(frozen=True)
class Evidence:
    kind: str  # "news" or "filing"
    title: str
    source: str
    url: str
    published: datetime  # UTC

    def as_json(self, id_: str) -> dict:
        return {**asdict(self), "id": id_, "published": self.published.isoformat()}


_SUFFIX = re.compile(
    r"[,.]?\s+(inc|incorporated|corp|corporation|co|company|plc|ltd|limited|holdings|group|n\.?v|s\.?a)\.?$", re.I
)


def short_name(name: str) -> str:
    """'Enova International, Inc.' -> 'Enova International': how the press names a company."""
    n = re.sub(r"\s*\(.*?\)", "", name).strip()
    for _ in range(2):
        n = _SUFFIX.sub("", n).strip(" ,")
    return n or name


def _norm(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()[:70]


def parse_google_news(xml: bytes | str) -> list[Evidence]:
    """Items of a Google News RSS feed, newest first, near-duplicate headlines removed."""
    root = ET.fromstring(xml)
    out, seen = [], set()
    for it in root.findall("./channel/item"):
        title, source = (it.findtext("title") or "").strip(), (it.findtext("source") or "").strip()
        if source and title.endswith(f" - {source}"):
            title = title[: -len(source) - 3].strip()
        when = it.findtext("pubDate")
        if not title or not when:
            continue
        key = _norm(title)
        if key in seen:
            continue
        seen.add(key)
        published = parsedate_to_datetime(when).astimezone(UTC)
        out.append(Evidence("news", title, source or "Google News", (it.findtext("link") or "").strip(), published))
    return sorted(out, key=lambda e: e.published, reverse=True)


def google_news(name: str, days: int, http: httpx.Client | None = None) -> list[Evidence]:
    """Headlines about a company from the last `days` days (at least 2)."""
    q = f'"{short_name(name)}" stock when:{max(2, days)}d'
    client = http or httpx.Client(headers=HEADERS, timeout=10, follow_redirects=True)
    r = client.get(GOOGLE_NEWS, params={"q": q, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    r.raise_for_status()
    return parse_google_news(r.content)[:MAX_NEWS]


def filings_8k(submissions: dict, cik: int, since: date) -> list[Evidence]:
    """8-K and 8-K/A filings since a date, from an EDGAR submissions document, each named by what it announces."""
    rec = submissions["filings"]["recent"]
    out = []
    for form, filed, accn, doc, items in zip(
        rec["form"],
        rec["filingDate"],
        rec["accessionNumber"],
        rec["primaryDocument"],
        rec.get("items") or [""] * len(rec["form"]),
        strict=False,
    ):
        if form not in ("8-K", "8-K/A") or date.fromisoformat(filed) < since:
            continue
        labels = [ITEMS[i] for i in (items or "").split(",") if i in ITEMS]
        title = f"{form}: {'; '.join(labels) if labels else 'Exhibits'}"
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-', '')}/{doc}"
        published = datetime.combine(date.fromisoformat(filed), datetime.min.time(), UTC)
        out.append(Evidence("filing", title, "SEC EDGAR", url, published))
    return out


def earnings_dates(submissions: dict, since: date) -> list[date]:
    """Days the company filed an 8-K reporting results (item 2.02), oldest first."""
    rec = submissions["filings"]["recent"]
    out = {
        date.fromisoformat(filed)
        for form, filed, items in zip(rec["form"], rec["filingDate"], rec.get("items") or [""] * len(rec["form"]), strict=False)
        if form == "8-K" and "2.02" in (items or "").split(",") and date.fromisoformat(filed) >= since
    }
    return sorted(out)


def submissions(cik: int) -> dict | None:
    """EDGAR's submissions document for a company, fetched for a waiting page (short timeouts, quick retries)."""
    from app.config import get_settings
    from ingest.fetch_edgar import SUBMISSIONS_URL, Edgar

    ua = get_settings().sec_user_agent
    if not ua:
        return None
    edgar = Edgar(ua)
    edgar.RETRY_WAITS = (1, 3)
    edgar.http.timeout = httpx.Timeout(10)
    return edgar.get(SUBMISSIONS_URL.format(cik=cik)).json()


def sec_8k(cik: int, since: date) -> list[Evidence]:
    sub = submissions(cik)
    return filings_8k(sub, cik, since) if sub else []


def evidence(name: str, cik: int | None, start: date) -> list[Evidence]:
    """News and filings from three days before the window to now, newest first. A source that fails is
    logged and skipped, so one outage never empties the panel."""
    days = (date.today() - start).days + 3
    found: list[Evidence] = []
    try:
        found += google_news(name, days)
    except Exception as e:  # noqa: BLE001
        log.warning("news for %s: %s", name, e)
    if cik:
        try:
            found += sec_8k(cik, start - timedelta(days=3))
        except Exception as e:  # noqa: BLE001
            log.warning("8-Ks for CIK %s: %s", cik, e)
    # Up to now, not just the last price day: this morning's news can explain yesterday's close.
    lo = datetime.combine(start - timedelta(days=3), datetime.min.time(), UTC)
    return sorted((e for e in found if e.published >= lo), key=lambda e: e.published, reverse=True)

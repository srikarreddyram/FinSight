"""Sectors from SEC SIC codes, mapped to 11 GICS-like sectors (GICS itself is licensed; SIC is free).

    uv run python -m warehouse.sectors          # every company in the warehouse without a sector yet

The mapping is by SIC range, so it follows what a company makes rather than how index providers classify it.
Known differences from GICS among the FinanceBench names: 3M files under 3841 (surgical instruments, so Health
Care here), Corning under 3357 (Materials, GICS says IT), PayPal under 7389 (Industrials, GICS says Financials),
CVS under 5912 (Consumer Staples, GICS says Health Care), Amcor under 3990 (Consumer Discretionary, GICS says
Materials). SEC also reports only the current code, not its history; codes rarely change, and sector-neutral
ranks only need a peer group, so both are accepted.
"""

from __future__ import annotations

import logging

from app.config import get_settings
from warehouse import db

log = logging.getLogger(__name__)

ENERGY, MATERIALS, INDUSTRIALS = "Energy", "Materials", "Industrials"
DISCRETIONARY, STAPLES, HEALTH = "Consumer Discretionary", "Consumer Staples", "Health Care"
FINANCIALS, TECH, COMMS = "Financials", "Information Technology", "Communication Services"
UTILITIES, REAL_ESTATE = "Utilities", "Real Estate"

# (first SIC, last SIC, sector): the first matching range wins, so narrow exceptions come before broad ranges.
RANGES: list[tuple[int, int, str]] = [
    (1200, 1399, ENERGY), (2900, 2999, ENERGY),
    (2830, 2836, HEALTH), (3840, 3851, HEALTH), (5122, 5122, HEALTH), (8000, 8099, HEALTH), (8731, 8731, HEALTH),
    (2840, 2844, STAPLES), (5140, 5149, STAPLES), (5331, 5331, STAPLES), (5399, 5399, STAPLES),
    (5400, 5499, STAPLES), (5912, 5912, STAPLES),
    (1531, 1531, DISCRETIONARY), (3021, 3021, DISCRETIONARY), (3630, 3639, DISCRETIONARY),
    (3651, 3651, DISCRETIONARY), (3710, 3716, DISCRETIONARY), (3750, 3751, DISCRETIONARY),
    (3570, 3579, TECH), (3660, 3699, TECH), (3812, 3812, INDUSTRIALS), (3800, 3839, TECH), (3860, 3899, TECH),
    (7370, 7379, TECH),
    (7310, 7319, COMMS), (2700, 2799, COMMS), (4800, 4899, COMMS), (7800, 7899, COMMS),
    (4950, 4959, INDUSTRIALS), (4900, 4999, UTILITIES),
    (6500, 6553, REAL_ESTATE), (6798, 6798, REAL_ESTATE), (6000, 6799, FINANCIALS),
    (100, 999, STAPLES), (1000, 1099, MATERIALS), (1400, 1499, MATERIALS), (1500, 1799, INDUSTRIALS),
    (2000, 2199, STAPLES), (2200, 2399, DISCRETIONARY), (2400, 2499, MATERIALS), (2500, 2599, DISCRETIONARY),
    (2600, 2699, MATERIALS), (2800, 2899, MATERIALS), (3000, 3099, MATERIALS), (3100, 3199, DISCRETIONARY),
    (3200, 3399, MATERIALS), (3400, 3699, INDUSTRIALS), (3700, 3799, INDUSTRIALS), (3900, 3999, DISCRETIONARY),
    (4000, 4799, INDUSTRIALS), (5000, 5199, INDUSTRIALS), (5200, 5999, DISCRETIONARY),
    (7000, 7299, DISCRETIONARY), (7500, 7599, INDUSTRIALS), (7300, 7399, INDUSTRIALS), (7900, 7999, DISCRETIONARY),
    (8200, 8299, DISCRETIONARY), (8100, 8999, INDUSTRIALS),
]  # fmt: skip


# SEC reports only a filer's current SIC. Yahoo lost its code when it became Altaba, an investment fund, after
# selling its operations in 2017; for its years in the index it was an internet company.
SIC_OVERRIDES = {1011006: 7370}


def sector(sic: int | None) -> str | None:
    if sic is None:
        return None
    return next((s for lo, hi, s in RANGES if lo <= sic <= hi), None)


def fetch() -> None:
    from ingest.fetch_edgar import SUBMISSIONS_URL, Edgar

    s = get_settings()
    if not s.sec_user_agent:
        raise SystemExit('Set FINSIGHT_SEC_USER_AGENT in .env, e.g. "FinSight research you@example.com" (SEC requires it)')
    edgar = Edgar(s.sec_user_agent)
    con = db.connect()
    for cik, ticker in con.execute("select cik, ticker from companies where sector is null order by ticker").fetchall():
        try:
            doc = edgar.get(SUBMISSIONS_URL.format(cik=cik)).json()
        except Exception as e:  # noqa: BLE001  (no submissions file)
            log.warning("%s (CIK %d): %s", ticker, cik, e)
            continue
        sic = int(doc["sic"]) if doc.get("sic") else SIC_OVERRIDES.get(cik)
        con.execute("update companies set sic = ?, sector = ? where cik = ?", [sic, sector(sic), cik])
        log.info("%-5s SIC %s (%s) -> %s", ticker, sic, doc.get("sicDescription"), sector(sic))
    con.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    fetch()

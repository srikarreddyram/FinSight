import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from signals.insider import compute as insider
from signals.momentum import MONTH, YEAR
from signals.momentum import compute as momentum


def test_momentum_measures_by_hand():
    # Flat for the first year-and-a-bit, +10% over months 2-12 back, then -5% in the last month.
    n = YEAR + 5
    r = np.zeros(n)
    r[n - YEAR : n - MONTH] = math.log(1.10) / (YEAR - MONTH)
    r[n - MONTH :] = math.log(0.95) / MONTH
    cum = np.cumsum(r)
    m = momentum(cum, n - 1)
    assert m["mom_12_1"] == pytest.approx(0.10, abs=1e-9)
    assert m["rev_1m"] == pytest.approx(-0.05, abs=1e-9)
    assert m["high_52w"] == pytest.approx(0.95, abs=1e-9)  # 5% below the high it reached a month ago
    assert all(math.isnan(v) for v in momentum(cum, YEAR - 1).values())  # less than a year of history


def test_insider_counts_only_trades_public_in_the_past_six_months():
    t = date(2024, 6, 30)
    trades = pd.DataFrame({
        "owner_cik": [1, 1, 2, 3, 4, 5],
        "filed_at": [t - timedelta(days=10), t - timedelta(days=40), t - timedelta(days=5), t, t - timedelta(days=200), t - timedelta(days=1)],
        "code": ["P", "P", "S", "P", "P", "S"],
    })  # fmt: skip
    feats, info = insider(trades, t)
    # Owner 3 filed on the month-end itself (public tomorrow) and owner 4 more than six months ago: neither counts.
    assert feats["insider_buyers_6m"] == 1 and feats["insider_net_6m"] == pytest.approx((1 - 2) / 3)
    assert info == t  # the newest trade counted was filed the day before, public on the month-end
    none, info_none = insider(trades.iloc[:0], t)
    assert none["insider_buyers_6m"] == 0 and math.isnan(none["insider_net_6m"]) and info_none is None


def test_insider_quarter_parsing_keeps_directors_and_officers_buying_and_selling():
    import io
    import zipfile

    from warehouse.insiders import parse_quarter, quarters

    def tsv(header, rows):
        return "\t".join(header) + "\n" + "\n".join("\t".join(r) for r in rows) + "\n"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("SUBMISSION.tsv", tsv(["ACCESSION_NUMBER", "FILING_DATE", "DOCUMENT_TYPE", "ISSUERCIK"],
                                         [["a1", "31-JAN-2024", "4", "0000320187"], ["a2", "01-FEB-2024", "4", "0000999999"], ["a3", "02-FEB-2024", "3", "0000320187"]]))  # fmt: skip
        z.writestr("REPORTINGOWNER.tsv", tsv(["ACCESSION_NUMBER", "RPTOWNERCIK", "RPTOWNER_RELATIONSHIP"],
                                             [["a1", "0001", "Director"], ["a2", "0002", "Officer"], ["a3", "0003", "Director"]]))  # fmt: skip
        z.writestr("NONDERIV_TRANS.tsv", tsv(["ACCESSION_NUMBER", "TRANS_DATE", "TRANS_CODE", "TRANS_SHARES", "TRANS_PRICEPERSHARE"],
                                             [["a1", "29-JAN-2024", "P", "100", "50.5"], ["a1", "29-JAN-2024", "M", "10", "1"], ["a2", "30-JAN-2024", "S", "5", "9"]]))  # fmt: skip
    df = parse_quarter(buf.getvalue(), {320187})
    assert len(df) == 1 and df.loc[0, "code"] == "P" and df.loc[0, "issuer_cik"] == 320187 and df.loc[0, "director"]
    assert (
        df.loc[0, "filed_at"] == date(2024, 1, 31) and df.loc[0, "price"] == 50.5
    )  # option exercise (M) and other issuers dropped
    html = 'href="/files/x/2008q4_form345.zip" href="/files/x/2009q1_form345.zip" href="https://www.sec.gov/files/y/2026q2_form345.zip"'
    assert [q for q, _ in quarters(html)] == ["2009q1", "2026q2"]

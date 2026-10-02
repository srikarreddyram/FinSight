"""The 10-K splitter on every real 10-K the Copilot has extracted (plain PDF text, kerning damage and all)."""

import json
import pathlib

import pytest

from warehouse.sections import split_10k

pytestmark = pytest.mark.integration

PARSED = pathlib.Path(__file__).resolve().parent.parent / "data" / "parsed" / "pypdf"
# These companies incorporate MD&A by reference to the annual report (Exhibit 13), so Item 7 is a stub.
MDNA_IN_EXHIBIT = {"CVSHEALTH_2018_10K", "JPMORGAN_2022_10K"}


def _docs():
    return sorted(PARSED.glob("*_10K.json"))


@pytest.mark.skipif(not _docs(), reason="parse the FinanceBench filings first")
def test_risk_factors_and_mdna_found_in_real_10ks():
    bad = []
    for path in _docs():
        d = json.loads(path.read_text())
        secs = split_10k("\n".join(e["text"] for e in d["elements"]))
        rf, md = secs.get("1A"), secs.get("7")
        mdna_ok = md is not None and (md.word_count > 3000 or path.stem in MDNA_IN_EXHIBIT)
        if not (rf and rf.word_count > 1000 and mdna_ok and len(secs) >= 18):
            bad.append(path.stem)
    assert not bad, f"splitter failed on: {bad}"

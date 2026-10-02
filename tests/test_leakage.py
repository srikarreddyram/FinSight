"""Phase B leakage guarantees, written before any model code (platform PRD, "Bias guardrails").

The panel pairs each (stock, month-end t) with features known at t and a forward return that starts after a
one-month embargo; walk-forward folds never train on a month whose return window reaches into the test
years. If any of these fail, no backtest number built on the panel can be trusted."""

import random
from datetime import date

import pandas as pd

from models import panel, walkforward
from warehouse import db, xbrl

CIK = {"AAA": 1, "BBB": 2}


def _warehouse():
    con = db.connect(":memory:")
    facts = []
    for tk, cik in CIK.items():
        for fy in range(2011, 2016):
            end = date(fy, 12, 31)
            filed = date(fy + 1, 2, 20)
            for concept, value in (("Assets", 100.0 + fy + cik), ("NetIncomeLoss", float(fy % 7 + cik))):
                start = None if concept == "Assets" else date(fy, 1, 1)
                facts.append(xbrl.Fact(cik, "us-gaap", concept, "USD", value, start, end, filed, f"{tk}{fy}", "10-K", fy, "FY"))
    xbrl.insert_facts(con, facts)
    days = pd.bdate_range("2011-01-01", "2017-12-31")
    rng = random.Random(3)
    rows = [(tk, d.date(), 10.0, rng.gauss(0.0004, 0.01), 1e6, "test") for tk in [*CIK, "SPY"] for d in days]
    con.executemany("insert into prices values (?, ?, ?, ?, ?, ?)", rows)
    return con


def roa(con, cik, as_of):
    """Return on assets from the latest annual facts public at as_of."""
    from warehouse import pit

    rows = pit.facts_asof(con, as_of, ciks=[cik], concepts=["Assets", "NetIncomeLoss"])
    if not rows:
        return {}, None
    latest = max(r["period_end"] for r in rows)
    got = {r["concept"]: r for r in rows if r["period_end"] == latest}
    if len(got) < 2:
        return {}, None
    info = max(r["available_at"] for r in got.values())
    return {"roa": got["NetIncomeLoss"]["value"] / got["Assets"]["value"]}, info


def _panel(con):
    months = panel.month_ends(date(2012, 1, 1), date(2016, 6, 30))
    return panel.build_panel(con, CIK, months, features=[roa], benchmark="SPY", horizon=12, embargo=1)


def test_every_feature_was_public_by_its_month_end():
    p = _panel(_warehouse())
    assert not p.empty
    known = p.dropna(subset=["roa"])
    assert (known["info_date"] <= known["month"]).all()
    # Before the first 10-K is filed (Feb 2012) there is nothing to know.
    assert p.loc[p["month"] < date(2012, 2, 21), "roa"].isna().all()


def test_target_starts_after_the_embargo_and_spans_the_horizon():
    p = _panel(_warehouse())
    for _, r in p.iterrows():
        assert r["target_start"] > r["month"]
        assert (r["target_start"].year - r["month"].year) * 12 + r["target_start"].month - r["month"].month == 1
        span = (r["target_end"].year - r["target_start"].year) * 12 + r["target_end"].month - r["target_start"].month
        assert span == 12
    # Rows whose 12-month window runs past the last price are left without a target, never truncated.
    assert p.loc[p["target_end"] > date(2017, 12, 29), "excess_ret"].isna().all()


def test_walk_forward_folds_purge_overlapping_targets():
    p = _panel(_warehouse())
    for fold in walkforward.folds(p, first_test_year=2014):
        train, test = p.loc[fold.train], p.loc[fold.test]
        first_test = test["month"].min()
        assert train["month"].max() < first_test
        assert (train["target_end"] < first_test).all(), "a training label overlaps the test period"
        assert test["month"].map(lambda d: d.year).nunique() == 1


def test_shuffled_target_has_no_rank_ic():
    rng = random.Random(11)
    months = [date(2015, m, 28) for m in range(1, 13)] * 1
    rows = []
    for m in months:
        for _ in range(200):
            signal = rng.random()
            rows.append({"month": m, "pred": signal, "excess_ret": signal + rng.gauss(0, 0.5)})
    df = pd.DataFrame(rows)
    assert walkforward.mean_rank_ic(df, "pred", "excess_ret") > 0.3
    shuffled = df.assign(
        excess_ret=df.groupby("month")["excess_ret"].transform(lambda s: s.sample(frac=1, random_state=5).to_numpy())
    )
    assert abs(walkforward.mean_rank_ic(shuffled, "pred", "excess_ret")) < 0.05

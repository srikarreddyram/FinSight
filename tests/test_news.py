import json
from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from news import moves
from news.investigate import clean, investigate, number, select
from news.sources import Evidence, filings_8k, parse_google_news, short_name

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>Nike shares drop on weak forecast - CNBC</title><link>https://news.example/1</link>
  <pubDate>Thu, 01 Oct 2026 16:00:01 GMT</pubDate><source url="https://cnbc.com">CNBC</source></item>
<item><title>Nike shares drop on weak forecast! - Yahoo Finance</title><link>https://news.example/2</link>
  <pubDate>Thu, 01 Oct 2026 17:00:00 GMT</pubDate><source url="https://yahoo.com">Yahoo Finance</source></item>
<item><title>Nike names new CFO - Reuters</title><link>https://news.example/3</link>
  <pubDate>Fri, 02 Oct 2026 09:30:00 GMT</pubDate><source url="https://reuters.com">Reuters</source></item>
</channel></rss>"""


def test_google_news_items_are_cleaned_dated_and_deduplicated():
    items = parse_google_news(RSS)
    assert [i.title for i in items] == ["Nike names new CFO", "Nike shares drop on weak forecast"]  # newest first
    assert items[0].source == "Reuters" and items[0].published == datetime(2026, 10, 2, 9, 30, tzinfo=UTC)
    assert short_name("Enova International, Inc.") == "Enova International" and short_name("Nike, Inc.") == "Nike"


def test_8k_filings_are_named_by_their_items():
    sub = {"filings": {"recent": {
        "form": ["8-K", "10-Q", "8-K", "8-K"],
        "filingDate": ["2026-10-01", "2026-09-30", "2026-09-29", "2026-08-01"],
        "accessionNumber": ["0000320187-26-000050", "x", "0000320187-26-000049", "y"],
        "primaryDocument": ["nke-8k.htm", "q.htm", "nke-8k2.htm", "old.htm"],
        "items": ["2.02,9.01", "", "5.02", "8.01"],
    }}}  # fmt: skip
    got = filings_8k(sub, 320187, since=date(2026, 9, 1))
    assert [e.title for e in got] == ["8-K: Results of operations", "8-K: Executive or director change"]
    assert got[0].url == "https://www.sec.gov/Archives/edgar/data/320187/000032018726000050/nke-8k.htm"


def _closes(n=400, seed=1):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2025-01-01", periods=n).date
    mkt = rng.normal(0.0004, 0.01, n)
    sec = mkt + rng.normal(0, 0.005, n)
    stock = 1.5 * mkt + 0.8 * (sec - mkt) + rng.normal(0, 0.004, n)
    stock[-1] += -0.08  # a company-specific shock on the last day
    px = lambda r: 100 * np.exp(np.cumsum(r))  # noqa: E731
    return pd.DataFrame({"STK": px(stock), "SPY": px(mkt), "XLK": px(sec)}, index=days)


def test_a_move_splits_into_parts_that_add_up_and_finds_the_shock():
    closes = _closes()
    m = moves.attribute(closes, "STK", 5, "XLK")
    assert m.beta_market == pytest.approx(1.5, abs=0.1) and m.beta_sector == pytest.approx(0.8, abs=0.15)
    assert m.market + m.sector + m.company == pytest.approx(m.change, abs=1e-9)
    assert m.change == pytest.approx(closes["STK"].iloc[-1] / closes["STK"].iloc[-6] - 1)
    assert m.key_days[-1].day == closes.index[-1] and m.key_days[-1].company < -0.07  # the shock is named
    assert m.company < -0.06 and m.unusual < -3


def test_without_a_sector_etf_the_market_alone_is_used():
    m = moves.attribute(_closes(), "STK", 1)
    assert m.sector == 0.0 and m.beta_sector is None and m.sector_etf is None
    assert m.market + m.company == pytest.approx(m.change)


def test_short_history_is_refused():
    with pytest.raises(ValueError):
        moves.attribute(_closes(n=60), "STK", 5, "XLK")


def test_scan_compares_with_the_market_and_the_sector():
    closes = _closes()
    df = moves.scan(closes, {"STK": "Information Technology", "SPY": None}, 5).set_index("ticker")
    change = closes.iloc[-1] / closes.iloc[-6] - 1
    assert df.loc["STK", "change"] == pytest.approx(change["STK"]) and df.loc["STK", "price"] == pytest.approx(
        closes["STK"].iloc[-1]
    )
    assert df.loc["STK", "vs_sector"] == pytest.approx(change["STK"] - change["XLK"])
    assert pd.isna(df.loc["SPY", "vs_sector"])  # no sector ETF to compare with


def _evidence(n_news=3):
    t0 = datetime(2026, 10, 1, 12, tzinfo=UTC)
    news = [Evidence("news", f"Headline {i}", "Wire", f"https://n/{i}", t0 - timedelta(days=i)) for i in range(n_news)]
    return number([*news, Evidence("filing", "8-K: Results of operations", "SEC EDGAR", "https://f/1", t0)])


def test_citations_to_unknown_evidence_are_dropped_and_uncited_drivers_removed():
    ev = _evidence()
    raw = {
        "summary": "Shares fell on results [N1, N9] and a rumour [X7].",
        "drivers": [
            {
                "headline": "Weak results",
                "detail": "Revenue missed [N1].",
                "effect": "pushed down",
                "evidence": ["N1", "F1", "N9"],
            },
            {"headline": "Invented", "detail": "Something [N9].", "effect": "pushed down", "evidence": ["N9"]},
        ],
        "confidence": "high",
    }
    out = clean(raw, ev)
    assert out["summary"] == "Shares fell on results [N1] and a rumour."
    assert [d["headline"] for d in out["drivers"]] == ["Weak results"] and out["drivers"][0]["evidence"] == ["N1", "F1"]


def test_the_model_reads_filings_and_the_news_nearest_the_key_days():
    ev = _evidence(n_news=40)
    move = moves.attribute(_closes(), "STK", 5, "XLK")
    move.key_days = [moves.KeyDay(date(2026, 9, 25), -0.05, -0.05)]
    shown = select(ev, move, k=5)
    ids = [e["id"] for e in shown]
    assert "F1" in ids and len(ids) == 5
    # Headline i is dated i days before 1 October (ID N{i+1}); the four nearest 25 September are i = 5 to 8.
    assert set(ids) == {"F1", "N6", "N7", "N8", "N9"}


def test_investigate_with_a_fake_model_and_with_no_evidence():
    class Fake:
        def json(self, **kw):
            assert "N1 |" in kw["user"] and "company-specific" in kw["user"]
            return {
                "summary": "Results [N1].",
                "drivers": [{"headline": "Results", "detail": "x", "effect": "pushed down", "evidence": ["N1"]}],
                "confidence": "medium",
            }

    move = moves.attribute(_closes(), "STK", 5, "XLK")
    items = [Evidence("news", "Results miss", "Wire", "https://n/1", datetime(2026, 10, 1, tzinfo=UTC))]
    out = investigate("Stock Co", "STK", "Information Technology", move, items, llm=Fake())
    assert out["drivers"][0]["evidence"] == ["N1"] and out["evidence"][0]["id"] == "N1"
    empty = investigate("Stock Co", "STK", None, move, [], llm=None)
    assert empty["drivers"] == [] and "No news" in empty["summary"]


@pytest.fixture
def moves_client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from news import api

    recs = tmp_path / "recs"
    recs.mkdir()
    rows = [
        {"ticker": "STK", "cik": 1, "name": "Stock Co", "sector": "Information Technology", "index": "S&P 500", "risk_grade": 3}
    ]
    (recs / "watchlist.json").write_text(json.dumps(rows))
    closes = _closes()
    monkeypatch.setattr(api, "RECS_DIR", recs)
    monkeypatch.setattr(api, "CACHE_DIR", tmp_path / "news")
    monkeypatch.setattr(api, "_prices", {})
    monkeypatch.setattr(api, "_news", {})
    monkeypatch.setattr(api.moves, "yahoo_closes", lambda tickers, period="15mo": closes)
    items = [Evidence("news", "Results miss", "Wire", "https://n/1", datetime.now(UTC))]
    monkeypatch.setattr(api.sources, "evidence", lambda name, cik, start: items)

    class Fake:
        calls = 0

        def json(self, **kw):
            Fake.calls += 1
            return {
                "summary": "Results [N1].",
                "drivers": [{"headline": "Results", "detail": "d", "effect": "pushed down", "evidence": ["N1"]}],
                "confidence": "medium",
            }

    monkeypatch.setattr("app.llm.get_llm", lambda: Fake())
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app), Fake


def test_company_move_then_a_cached_investigation(moves_client):
    client, fake = moves_client
    body = client.get("/moves/stk?window=1w").json()
    assert body["company"]["ticker"] == "STK" and body["move"]["days"] == 5 and body["evidence"][0]["id"] == "N1"
    assert body["analysis"] is None
    first = client.post("/moves/STK/investigate?window=1w").json()
    second = client.post("/moves/STK/investigate?window=1w").json()
    assert first["drivers"][0]["evidence"] == ["N1"] and second == first and fake.calls == 1  # the second comes from the cache
    assert client.get("/moves/STK?window=1w").json()["analysis"]["summary"] == "Results [N1]."


def test_unknown_ticker_and_bad_window(moves_client):
    client, _ = moves_client
    assert client.get("/moves/ZZZ").status_code == 404
    assert client.get("/moves/STK?window=2y").status_code == 422


def test_earnings_days_come_from_8k_item_2_02():
    from news.sources import earnings_dates

    sub = {"filings": {"recent": {"form": ["8-K", "8-K", "10-Q", "8-K", "8-K"], "filingDate": ["2026-10-01", "2026-09-15", "2026-08-01", "2026-06-30", "2026-06-23"],
                                  "items": ["2.02,9.01", "5.02", "", "2.02", "2.02"]}}}  # fmt: skip
    assert earnings_dates(sub, date(2026, 1, 1)) == [date(2026, 6, 23), date(2026, 10, 1)]  # 30 June repeats 23 June


def test_price_history_with_earnings_markers(moves_client, monkeypatch):
    from news import api

    client, _ = moves_client
    monkeypatch.setattr(api, "_history", {})
    monkeypatch.setattr(api, "_earnings_days", lambda cik, since: [since])
    body = client.get("/moves/STK/history?range=1m").json()
    assert len(body["points"]) == 22 and body["earnings"] == [body["points"][0]["day"]]
    assert body["change"] == pytest.approx(body["points"][-1]["close"] / body["points"][0]["close"] - 1, abs=1e-4)
    assert client.get("/moves/STK/history?range=10y").status_code == 422


def test_earnings_reactions_span_two_sessions_and_rank_the_latest():
    from news.earnings import reactions, summary

    days = pd.bdate_range("2026-01-05", periods=10).date
    stock = [100, 100, 100, 90, 90, 90, 90, 99, 99, 99]  # falls 10% on day 3, rises 10% on day 7
    spy = [100] * 10
    closes = pd.DataFrame({"STK": stock, "SPY": spy}, index=days)
    rows = reactions(closes, "STK", [days[3], days[6], days[9]])  # the last date has no session after it
    assert [r["date"] for r in rows] == [str(days[3]), str(days[6])]
    assert rows[0]["change"] == pytest.approx(-0.10) and rows[1]["change"] == pytest.approx(0.10)  # close before -> session after
    s = summary(rows)
    assert s["count"] == 2 and s["up"] == 1 and s["typical"] == pytest.approx(0.10)
    assert s["last"]["date"] == str(days[6]) and s["last_rank"] == 1.0 and s["last_biggest_since"] is None


def test_overview_groups_the_scan_by_index(moves_client):
    from news import api

    client, _ = moves_client
    rows = [
        {"ticker": t, "cik": i, "name": f"{t} Co", "sector": "Information Technology", "index": idx}
        for i, (t, idx) in enumerate([("AAA", "S&P 500"), ("BBB", "S&P 500"), ("CCC", "S&P 500"), ("DDD", "S&P 600")])
    ]
    (api.RECS_DIR / "watchlist.json").write_text(json.dumps(rows))
    spark = [["2026-10-05", 7773.95], ["2026-10-06", 7825.39]]
    scan = {
        "as_of": "2026-10-06 00:00:00", "built": "2026-10-06T20:00:00+00:00",
        "windows": {"1d": {"falls": [], "gains": [], "breadth": {"up": 2, "down": 2}, "market": 0.006,
                           "all": [["AAA", 0.05, 10.0, 0.04], ["BBB", -0.03, 20.0, -0.035], ["CCC", 0.01, 30.0, None], ["DDD", -0.2, 5.0, -0.19]]}},
        "series": {"^GSPC": {"price": 7825.39, "spark": spark, "changes": {"1d": 0.0066}}, "XLK": {"price": 300.0, "spark": spark, "changes": {"1d": 0.012}}},
    }  # fmt: skip
    api.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    api._scan_path(date.today()).write_text(json.dumps(scan))
    (api.CACHE_DIR / "analysis").mkdir()
    api._analysis_path("BBB", date(2026, 10, 6), "1d").write_text(json.dumps({"summary": "Guidance cut [N1]."}))
    body = client.get("/moves/overview?window=1d").json()
    sp500, sp400, sp600 = body["indexes"]
    assert (sp500["level"], sp500["change"], sp500["up"], sp500["down"]) == (7825.39, 0.0066, 2, 1)
    assert [r["ticker"] for r in sp500["gainers"]] == ["AAA", "CCC"] and [r["ticker"] for r in sp500["losers"]] == ["BBB"]
    assert sp400["level"] is None and sp400["gainers"] == [] and sp600["losers"][0]["ticker"] == "DDD"
    assert body["sectors"] == [{"name": "Information Technology", "etf": "XLK", "change": 0.012}]
    # The S&P 500's company-specific moves: up, then down, each once; CCC has no sector comparison.
    assert [(e["ticker"], e["analysis"]) for e in body["explained"]] == [
        ("AAA", None),
        ("BBB", {"summary": "Guidance cut [N1]."}),
    ]


def test_index_series_for_the_home_page():
    from news.api import _series

    days = [date(2026, 8, 1) + timedelta(days=i) for i in range(30)]
    closes = pd.DataFrame({"^GSPC": [100.0 + i for i in range(30)], "XLK": [50.0] * 29 + [None]}, index=days)
    out = _series(closes, ["^GSPC", "XLK", "MISSING"])
    g = out["^GSPC"]
    assert g["price"] == 129.0 and len(g["spark"]) == 22 and g["spark"][-1] == ["2026-08-30", 129.0]
    assert g["changes"]["1d"] == pytest.approx(129 / 128 - 1) and g["changes"]["1m"] == pytest.approx(129 / 108 - 1)
    assert out["XLK"]["price"] == 50.0 and "MISSING" not in out  # a missing last close falls back to the one before

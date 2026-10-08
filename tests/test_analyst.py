"""The Analyst's research note: figure and citation checks, 10-K parsing, and the API with a stand-in model."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from analyst.context import money, passage_title, passages, risk_titles
from analyst.note import check, clean, figures, grounded

ITEMS = [
    {"id": "K1", "kind": "tenk", "title": "Wholesale", "text": "Wholesale revenues were $27.5 billion, up 6% on a currency-neutral basis.", "url": "u", "meta": {"item": "7"}},
    {"id": "K2", "kind": "tenk", "title": "Competition is intense.", "text": "", "url": "u", "meta": {"item": "1A"}},
    {"id": "X1", "kind": "fact", "title": "Revenue, FY2026 (year to May 31, 2026)", "text": "$46.40B", "url": None, "meta": {}},
    {"id": "N1", "kind": "news", "title": "Stock downgraded to sell", "text": "", "url": "n", "meta": {"date": "2026-10-06"}},
    {"id": "D1", "kind": "data", "title": "12-month return", "text": "−47.6%", "url": None, "meta": {"value": True}},
    {"id": "D2", "kind": "data", "title": "Risk driver", "text": "Largest fall −51.1%", "url": None, "meta": {"value": False}},
]  # fmt: skip
IDS = {i["id"] for i in ITEMS}
FACTS = {i["id"]: i["text"] for i in ITEMS if i["kind"] == "fact" or i["meta"].get("value")}
TEXTS = {i["id"]: f"{i['title']} {i['text']}" for i in ITEMS}


def run(text: str) -> tuple[str, list[str]]:
    return check(text, IDS, FACTS, TEXTS)


def test_figures_match_across_formats():
    assert figures("$27.5 billion and $27.50B and 6 percent") == {(Decimal("27.5"), "b"), (Decimal("6"), "%")}
    assert grounded(figures("rose 6%"), "up 6 % on the year")  # a table's "6 %" is the same figure
    assert not grounded(figures("$27.5 million"), "$27.5 billion")  # same number, wrong unit
    assert not grounded(figures("fell 9%"), "down 6% and 27.5")


def test_placeholders_fill_and_cite_their_item():
    assert run("Revenue was {X1}.") == ("Revenue was $46.40B [X1].", ["X1"])
    text, cited = run("The stock returned {D1} as analysts turned negative [N1].")
    assert text == "The stock returned −47.6% as analysts turned negative [N1] [D1]." and cited == ["N1", "D1"]


def test_a_quoted_figure_must_be_in_a_cited_item():
    assert run("Wholesale revenues were $27.5B, up 6% [K1].")[0] == "Wholesale revenues were $27.5B, up 6% [K1]."
    assert run("Wholesale revenues were $27.5B [N1].")[0] == ""  # cited, but the headline doesn't say it
    assert run("Wholesale revenues were $27.5B.")[0] == ""  # not cited at all
    assert run("Direct fell 9% [K1].")[0] == ""  # not in the passage


def test_what_cannot_be_filled_is_dropped():
    assert run("Revenue was {K1} [K1].")[0] == ""  # a passage holds no single figure
    assert run("The largest fall was {D2} [D2].")[0] == ""  # a data item that isn't a value
    assert run("Revenue was {X9}.")[0] == ""  # an item that wasn't given
    assert run("Competition is intense [K2, Z9].") == ("Competition is intense [K2].", ["K2"])  # unknown IDs removed


def test_years_and_filing_names_are_not_figures():
    assert run("In fiscal 2026 the 10-K's Item 1A flags competition [K2].")[0].startswith("In fiscal 2026")


def test_clean_keeps_cited_points_and_fact_ids_only():
    raw = {
        "headline": "Growth stalls at {X1} [X1]",
        "summary": "Revenue was {X1}. Margins rose 99% [K1].",
        "bull": [
            {"title": "Wholesale", "text": "Wholesale revenues were $27.5 billion [K1]."},
            {"title": "Vague", "text": "Things look fine."},
        ],
        "bear": ["Analysts downgraded the stock [N1]."],
        "watch": [{"title": "Typed", "text": "Watch the 12% margin [K1]."}],
        "key_facts": ["X1", "D1", "K1", "X1"],
    }
    note = clean(raw, ITEMS)
    assert note["headline"] == "Growth stalls at $46.40B"
    assert note["summary"] == "Revenue was $46.40B [X1]."  # the sentence with a figure from nowhere is gone
    assert [p["title"] for p in note["bull"]] == ["Wholesale"]  # the uncited point is gone
    assert note["bear"][0]["evidence"] == ["N1"] and note["bear"][0]["title"] == "Analysts downgraded the stock"
    assert note["watch"] == [] and note["key_facts"] == ["X1"]


def test_risk_headings_and_passages():
    text = "\n".join([
        "Item 1A. Risk Factors",
        "Global economic conditions could have a material adverse effect on our business and results.",
        "Our results depend on consumer demand. Demand has been weak in several markets lately and may stay weak.",
        "• A bullet that lists one of several factors in a longer explanation of the risk.",
        "This report contains forward-looking statements that involve risks and uncertainties about our business.",
        "Competition in our industry is intense and could reduce our market share and our margins.",
        "12",
    ])  # fmt: skip
    assert risk_titles(text) == [
        "Global economic conditions could have a material adverse effect on our business and results.",
        "Competition in our industry is intense and could reduce our market share and our margins.",
    ]
    mda = "\n".join(
        ["• Revenue rose " + "a " * 60 + ".", "Table of Contents", "| a | b | c | d |", "Margins fell " + "b " * 120 + "."]
    )
    chunks = passages(mda, words=100)
    assert (
        len(chunks) == 1
        and chunks[0].startswith("Revenue rose")
        and "Table of Contents" not in chunks[0]
        and "|" not in chunks[0]
    )
    assert passage_title("(7) (3) — (3) — EARNINGS BEFORE INTEREST AND TAXES $ 1,387", words=4) == "EARNINGS BEFORE INTEREST AND…"


def test_money():
    assert (money(46.4e9), money(-2.18e9), money(5.12e12), money(950e6), money(1234)) == (
        "$46.40B",
        "−$2.18B",
        "$5.12T",
        "$950M",
        "$1,234",
    )


def test_finsight_figures_skip_what_is_missing(monkeypatch):
    from analyst.api import finsight_items
    from news import api as news_api

    def no_prices(row, window):
        raise ValueError("no prices")

    monkeypatch.setattr(news_api, "_move", no_prices)
    monkeypatch.setattr(news_api, "earnings_reactions", lambda ticker: {"summary": {"count": 0}})
    drivers = [{"label": "Quick ratio", "effect": "raises risk", "value": None}, {"label": "Downside deviation", "effect": "raises risk", "value": "16.3%"}]  # fmt: skip
    row = {"ticker": "BNK", "risk_grade": 2, "risk_label": "Moderate", "expected_vol": 0.25, "risk_drivers": drivers}
    items = finsight_items(row, 1)
    assert [(i.id, i.text) for i in items] == [("D1", "Moderate (2 of 5)"), ("D2", "25.0%"), ("D3", "16.3%")]


@pytest.fixture
def analyst_client(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from analyst import api
    from news import api as news_api

    recs = tmp_path / "recs"
    recs.mkdir()
    (recs / "watchlist.json").write_text(json.dumps([{"ticker": "STK", "cik": 1, "name": "Stock Co", "sector": "Industrials"}]))
    monkeypatch.setattr(news_api, "RECS_DIR", recs)
    monkeypatch.setattr(api, "CACHE", tmp_path / "analyst")
    monkeypatch.setattr(api, "_context", {})
    built = []
    monkeypatch.setattr(api, "build_items", lambda row: built.append(row["ticker"]) or ITEMS)

    class Fake:
        calls = 0

        def json(self, **kw):
            Fake.calls += 1
            return {"headline": "Steady", "summary": "Revenue was {X1}.", "bull": [{"title": "Wholesale", "text": "Up 6% [K1]."}], "bear": [], "watch": [], "key_facts": ["X1"]}  # fmt: skip

    monkeypatch.setattr("app.llm.get_llm", lambda: Fake())
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app), Fake, built


def test_note_is_written_once_from_the_gathered_sources(analyst_client):
    client, fake, built = analyst_client
    assert client.get("/analyst/stk").json() is None
    assert client.post("/analyst/STK/context").json() == {"tenk": 2, "facts": 1, "news": 1, "data": 2, "filed": None}
    first = client.post("/analyst/STK").json()
    assert first["summary"] == "Revenue was $46.40B [X1]." and first["bull"][0]["evidence"] == ["K1"]
    assert built == ["STK"]  # the note used the gathered sources rather than reading them again
    assert client.post("/analyst/STK").json()["generated"] == first["generated"] and fake.calls == 1  # cached for the day
    assert client.get("/analyst/STK").json()["headline"] == "Steady"
    client.post("/analyst/STK?refresh=true")
    assert fake.calls == 2 and built == ["STK", "STK"]
    assert client.post("/analyst/ZZZ").status_code == 404
    listed = client.get("/analyst").json()
    assert [(n["ticker"], n["name"], n["headline"], n["bull"], n["bear"]) for n in listed] == [
        ("STK", "Stock Co", "Steady", 1, 0)
    ]

import json

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from recs import api


@pytest.fixture
def client(tmp_path, monkeypatch):
    recs, study = tmp_path / "recs", tmp_path / "study"
    recs.mkdir()
    study.mkdir()
    (recs / "watchlist.json").write_text(json.dumps([{"ticker": "AAA", "return_rank": 90.0, "risk_grade": 2}]))
    (recs / "meta.json").write_text(json.dumps({"as_of": "2026-09-30"}))
    months = pd.to_datetime(["2020-01-31", "2020-02-29"])
    pd.DataFrame({"ticker": ["AAA", "AAA", "BBB", "BBB"], "month": list(months) * 2, "roe": [0.1, None, 0.3, 0.2],
                  "roe_rank": [0.25, None, 0.75, 0.75]}).to_parquet(study / "panel.parquet")  # fmt: skip
    pd.DataFrame({"ticker": ["AAA", "BBB"] * 2, "month": [months[0]] * 2 + [months[1]] * 2, "pred_lgbm": [1.0, 2.0, 3.0, 1.0],
                  "excess_ret": [0.1, -0.1, 0.2, 0.0]}).to_parquet(study / "predictions.parquet")  # fmt: skip
    risk = pd.DataFrame({"ticker": [f"S{i}" for i in range(9)] + ["AAA"], "month": [months[0]] * 10,
                         "pred_vol": range(10), "pred_downside": range(10), "fwd_vol": 0.3, "severe": 0.0, "vol_12m": 0.2})  # fmt: skip
    risk.to_parquet(study / "risk_predictions.parquet")
    monkeypatch.setattr(api, "RECS_DIR", recs)
    monkeypatch.setattr(api, "STUDY_DIR", study)
    app = FastAPI()
    app.include_router(api.router)
    return TestClient(app)


def test_watchlist_and_meta(client):
    assert client.get("/recs/meta").json() == {"as_of": "2026-09-30"}
    assert client.get("/recs/watchlist").json()[0]["ticker"] == "AAA"


def test_company_card_with_history_and_nulls(client):
    body = client.get("/recs/company/aaa").json()
    assert body["card"]["risk_grade"] == 2
    assert [r["month"] for r in body["signal_history"]] == ["2020-01-31", "2020-02-29"]
    assert body["signal_history"][1]["roe"] is None  # missing stays null, not NaN
    assert [r["return_rank"] for r in body["return_history"]] == [50.0, 100.0]
    assert body["risk_history"][0]["grade"] == 5  # the riskiest of ten
    assert body["signals"][0]["label"] == "Return on equity"


def test_unknown_ticker_and_missing_data(client, monkeypatch, tmp_path):
    assert client.get("/recs/company/ZZZ").status_code == 404
    monkeypatch.setattr(api, "RECS_DIR", tmp_path / "nowhere")
    r = client.get("/recs/backtest")
    assert r.status_code == 503 and "recs.build" in r.json()["detail"]

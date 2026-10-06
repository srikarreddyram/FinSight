"""Endpoints for what is moving a stock.

GET  /moves/scan?window=1w             biggest company-specific gains and falls across the universe (built in the
                                       background on first request, then cached for a few hours)
GET  /moves/{ticker}/history?range=1y  daily closes for the price chart, with earnings days marked
GET  /moves/{ticker}?window=1w         the move split into market, sector and company-specific parts, plus the
                                       dated news and filings, and the cached analysis if there is one
POST /moves/{ticker}/investigate       the cited analysis (one LLM call; cached per ticker, day and window)

Windows: 1d, 1w (5 trading days), 1m (21). Company details come from the watchlist the dashboard already serves.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, Query

from news import moves, sources
from news.investigate import investigate, number

log = logging.getLogger(__name__)
router = APIRouter(prefix="/moves", tags=["moves"])

RECS_DIR = Path("data/recs")
CACHE_DIR = Path("data/news")
PRICE_TTL = 3600  # seconds
NEWS_TTL = 1800
SCAN_TTL = 3 * 3600
Window = Query("1w", pattern="^(1d|1w|1m)$")

_prices: dict[str, tuple[float, pd.DataFrame]] = {}
_news: dict[tuple[str, str], tuple[float, list]] = {}
_scan_lock = threading.Lock()
_scan_state: dict = {"building": False, "error": None, "started": None}


def _watchlist() -> dict[str, dict]:
    path = RECS_DIR / "watchlist.json"
    if not path.exists():
        raise HTTPException(503, "The dashboard data is not built yet. Run `uv run python -m recs.build`.")
    return {r["ticker"]: r for r in json.loads(path.read_text())}


def _company(ticker: str) -> dict:
    row = _watchlist().get(ticker.upper())
    if row is None:
        raise HTTPException(404, f"{ticker} is not in the current universe")
    return row


def _closes(ticker: str, etf: str | None) -> pd.DataFrame:
    hit = _prices.get(ticker)
    if hit and time.time() - hit[0] < PRICE_TTL:
        return hit[1]
    df = moves.yahoo_closes([t for t in (ticker, moves.MARKET, etf) if t])
    _prices[ticker] = (time.time(), df)
    return df


def _evidence(row: dict, start: date, window: str) -> list[sources.Evidence]:
    key = (row["ticker"], window)
    hit = _news.get(key)
    if hit and time.time() - hit[0] < NEWS_TTL:
        return hit[1]
    found = sources.evidence(row.get("name") or row["ticker"], row.get("cik"), start)
    _news[key] = (time.time(), found)
    return found


def _move(row: dict, window: str) -> moves.Move:
    etf = moves.SECTOR_ETF.get(row.get("sector") or "")
    try:
        return moves.attribute(_closes(row["ticker"], etf), row["ticker"], moves.WINDOWS[window], etf)
    except (KeyError, ValueError) as e:
        raise HTTPException(422, f"No usable price history for {row['ticker']}: {e}") from e


def _analysis_path(ticker: str, end: date, window: str) -> Path:
    return CACHE_DIR / "analysis" / f"{ticker}_{end}_{window}.json"


# ---------------------------------------------------------------- the universe scan


def _scan_path(day: date) -> Path:
    return CACHE_DIR / f"scan_{day}.json"


def _build_scan() -> None:
    try:
        rows = _watchlist()
        tickers = sorted(t for t in rows if "~" not in t)
        closes = moves.yahoo_closes_chunked([moves.MARKET, *sorted(set(moves.SECTOR_ETF.values())), *tickers], period="3mo")
        sectors = {t: rows[t].get("sector") for t in tickers}
        out = {"as_of": str(closes.index[-1]), "built": datetime.now(UTC).isoformat(), "windows": {}}
        for name, days in moves.WINDOWS.items():
            df = moves.scan(closes, sectors, days)
            df["excess"] = df["vs_sector"].fillna(df["vs_market"])
            for col in ("name", "index", "sector", "risk_grade"):
                df[col] = df["ticker"].map(lambda t, c=col: rows[t].get(c))
            df = df.sort_values("excess")
            out["windows"][name] = {
                "falls": json.loads(df.head(50).to_json(orient="records")),
                "gains": json.loads(df.tail(50).iloc[::-1].to_json(orient="records")),
                "breadth": {"up": int((df["change"] > 0).sum()), "down": int((df["change"] < 0).sum())},
                "market": float(closes[moves.MARKET].iloc[-1] / closes[moves.MARKET].iloc[-days - 1] - 1),
            }
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _scan_path(date.today()).write_text(json.dumps(out))
        _scan_state["error"] = None
    except Exception as e:  # noqa: BLE001 - reported to the page, which can retry
        log.exception("movers scan failed")
        _scan_state["error"] = str(e)
    finally:
        _scan_state["building"] = False


def _run_scan_process() -> None:
    """The scan in its own process: yfinance can't download in two threads at once, so a scan in this process
    would make every company page wait for it."""
    import subprocess
    import sys

    try:
        done = subprocess.run([sys.executable, "-m", "news.api"], capture_output=True, text=True, timeout=900)
        _scan_state["error"] = None if done.returncode == 0 else (done.stderr.strip().splitlines() or ["scan failed"])[-1]
    except Exception as e:  # noqa: BLE001
        _scan_state["error"] = str(e)
    finally:
        _scan_state["building"] = False


@router.get("/scan")
def scan(window: str = Window, limit: int = Query(25, ge=1, le=50)) -> dict:
    path = _scan_path(date.today())
    fresh = path.exists() and time.time() - path.stat().st_mtime < SCAN_TTL
    if not fresh:
        with _scan_lock:
            if not _scan_state["building"]:
                _scan_state.update(building=True, started=datetime.now(UTC).isoformat())
                threading.Thread(target=_run_scan_process, daemon=True).start()
        if not path.exists():
            return {
                "status": "error" if _scan_state["error"] else "building",
                "error": _scan_state["error"],
                "started": _scan_state["started"],
            }
    data = json.loads(path.read_text())
    w = data["windows"][window]
    return {"status": "ready", "as_of": data["as_of"], "built": data["built"], "window": window, "market": w["market"],
            "breadth": w["breadth"], "falls": w["falls"][:limit], "gains": w["gains"][:limit]}  # fmt: skip


# ---------------------------------------------------------------- one company


RANGES = {"1m": 21, "6m": 126, "1y": 252, "5y": 1260}
_history: dict[tuple[str, str], tuple[float, pd.DataFrame]] = {}
_earnings: dict[int, tuple[float, list]] = {}


def _earnings_days(cik: int | None, since: date) -> list[date]:
    if not cik:
        return []
    hit = _earnings.get(cik)
    if not (hit and time.time() - hit[0] < SCAN_TTL):
        try:
            sub = sources.submissions(cik)
            hit = (time.time(), sources.earnings_dates(sub, date(2000, 1, 1)) if sub else [])
        except Exception as e:  # noqa: BLE001 - the chart works without markers
            log.warning("earnings dates for CIK %s: %s", cik, e)
            hit = (time.time(), [])
        _earnings[cik] = hit
    return [d for d in hit[1] if d >= since]


@router.get("/{ticker}/history")
def price_history(ticker: str, range: str = Query("1y", pattern="^(1m|6m|1y|5y)$")) -> dict:  # noqa: A002
    row = _company(ticker)
    period = "6y" if range == "5y" else "15mo"
    key = (row["ticker"], period)
    hit = _history.get(key)
    if not (hit and time.time() - hit[0] < PRICE_TTL):
        try:
            hit = (time.time(), moves.yahoo_closes([row["ticker"]], period=period))
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        _history[key] = hit
    px = hit[1][row["ticker"]].dropna().iloc[-RANGES[range] - 1 :]
    if px.empty:
        raise HTTPException(422, f"No price history for {row['ticker']}")
    start = px.index[0]
    return {
        "ticker": row["ticker"],
        "range": range,
        "points": [{"day": str(d), "close": round(float(v), 4)} for d, v in px.items()],
        "change": float(px.iloc[-1] / px.iloc[0] - 1),
        "earnings": [str(d) for d in _earnings_days(row.get("cik"), start)],
    }


@router.get("/{ticker}")
def company_move(ticker: str, window: str = Window) -> dict:
    row = _company(ticker)
    move = _move(row, window)
    found = _evidence(row, move.start, window)
    cached = _analysis_path(row["ticker"], move.end, window)
    return {
        "company": {k: row.get(k) for k in ("ticker", "name", "sector", "index")},
        "window": window,
        "move": move.as_json(),
        "evidence": number(found),
        "analysis": json.loads(cached.read_text()) if cached.exists() else None,
    }


@router.post("/{ticker}/investigate")
def investigate_move(ticker: str, window: str = Window, refresh: bool = False) -> dict:
    from app.llm import LLMError, QuotaExhausted

    row = _company(ticker)
    move = _move(row, window)
    path = _analysis_path(row["ticker"], move.end, window)
    if path.exists() and not refresh:
        return json.loads(path.read_text())
    try:
        result = investigate(
            row.get("name") or row["ticker"], row["ticker"], row.get("sector"), move, _evidence(row, move.start, window)
        )
    except QuotaExhausted as e:
        raise HTTPException(429, "The daily analysis limit has been reached; try again tomorrow.") from e
    except LLMError as e:
        raise HTTPException(502, f"The analysis didn't finish: {e}") from e
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result))
    return result


if __name__ == "__main__":  # the scan, run as its own process by /moves/scan
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    _build_scan()
    import os

    os._exit(1 if _scan_state["error"] else 0)  # yfinance leaves network threads behind that would keep the process alive

"""Build the hosted demo's static snapshot in web/public/demo/ from a running API and the local data.

    uv run uvicorn app.api:app &          # the API must be up (it serves the dashboard data and the Copilot)
    uv run python scripts/build_demo.py   # then: scripts/deploy_demo.sh

What goes in:
- the dashboard's data (meta, watchlist, signals, backtest, risk) and every company page, histories stored as
  columns rather than rows (about 25 KB a company instead of 140)
- a year of daily closes for every company (one shared trading calendar, one list of closes each) with its
  earnings days, from the warehouse's 8-K index
- the Movers lists for each window, the price-move panels of the top movers and a few well-known companies, and
  AI explanations for the top five gainers and losers in each window and the well-known companies over a week
- the market map for each window, and the home page's market overview with its explained moves
- AI research notes for the well-known companies and the week's three largest gainers and losers
- the Copilot's answers to its example questions, with the filing pages they cite

One LLM call per explanation, note and answer (about 55 in all), on the free tier. Re-running reuses the API's
cached explanations and today's notes.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import sys
from pathlib import Path

import duckdb
import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from news import moves  # noqa: E402

API = "http://localhost:8000"
OUT = ROOT / "web" / "public" / "demo"
WINDOWS = ("1d", "1w", "1m")
TOP_PANELS = 10  # per side and window: price-move panels
TOP_ANALYSES = 5  # per side and window: AI explanations
TOP_NOTES = 3  # per side, over a week: research notes
WELL_KNOWN = ["NKE", "AAPL", "NVDA", "MSFT", "AMZN", "TSLA", "JPM", "GOOGL", "META", "LITE"]

log = logging.getLogger("build_demo")


def write(path: str, data) -> None:
    p = OUT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, separators=(",", ":")))


def rounded(v):
    return round(v, 4) if isinstance(v, float) else v


def columns(rows: list[dict], keys: list[str]) -> dict:
    return {"keys": keys, "cols": [[rounded(r.get(k)) for r in rows] for k in keys]}


def company_pages(http: httpx.Client, tickers: list[str]) -> None:
    for i, t in enumerate(tickers, 1):
        r = http.get(f"/recs/company/{t}")
        if r.status_code != 200:
            log.warning("%s: %s", t, r.status_code)
            continue
        c = r.json()
        sig_keys = ["month", *[f"{s['signal']}_rank" for s in c["signals"]]]
        c["signal_history"] = columns(c["signal_history"], sig_keys)
        c["return_history"] = columns(c["return_history"], ["month", "return_rank", "excess_ret"])
        c["risk_history"] = columns(c["risk_history"], ["month", "grade", "fwd_vol", "severe", "vol_12m"])
        write(f"recs/company/{t}.json", c)
        if i % 250 == 0:
            log.info("company pages: %d/%d", i, len(tickers))


def histories(rows: dict[str, dict]) -> None:
    """A year of closes per company against one shared calendar, plus earnings days (indexes into it)."""
    tickers = sorted(t for t in rows if "~" not in t)
    closes = moves.yahoo_closes_chunked([moves.MARKET, *tickers], period="15mo")
    closes = closes.iloc[-253:]
    calendar = [str(d) for d in closes.index]
    write("moves/calendar.json", calendar)
    con = duckdb.connect(str(ROOT / "data" / "warehouse.duckdb"), read_only=True)
    earn = con.execute(
        "select cik, list(distinct filed_at order by filed_at) from filing_index "
        "where form = '8-K' and items like '%2.02%' and filed_at >= ? group by cik",
        [closes.index[0]],
    ).fetchall()
    con.close()
    earnings = {cik: [str(d) for d in days] for cik, days in earn}
    for t in tickers:
        if t not in closes:
            continue
        series = closes[t]
        first = series.first_valid_index()
        if first is None:
            continue
        offset = calendar.index(str(first))
        values = [None if v != v else round(float(v), 2) for v in series.iloc[offset:]]  # v != v: NaN
        days = calendar[offset:]
        # An earnings filing on a non-trading day marks the next trading day.
        idx = sorted(
            {next((i for i, d in enumerate(days) if d >= e), None) for e in earnings.get(rows[t].get("cik"), [])} - {None}
        )
        write(f"moves/history/{t}.json", {"c": values, "e": idx})
    log.info("histories: %d companies, %d trading days", len(tickers), len(calendar))


def earnings(rows: dict[str, dict]) -> None:
    """Each company's move around its earnings reports over five years (same measure as the live endpoint)."""
    from news.earnings import reactions, summary
    from news.sources import collapse_reports

    tickers = sorted(t for t in rows if "~" not in t)
    closes = moves.yahoo_closes_chunked([moves.MARKET, *tickers], period="6y")
    since = closes.index[-1].replace(year=closes.index[-1].year - 5)
    con = duckdb.connect(str(ROOT / "data" / "warehouse.duckdb"), read_only=True)
    dates = dict(con.execute(
        "select cik, list(distinct filed_at) from filing_index where form = '8-K' and items like '%2.02%' and filed_at >= ? group by cik",
        [since],
    ).fetchall())  # fmt: skip
    con.close()
    n = 0
    for t in tickers:
        days = collapse_reports(dates.get(rows[t].get("cik"), []))
        if t not in closes or not days:
            continue
        ev = reactions(closes, t, days)
        if ev:
            write(
                f"moves/earnings/{t}.json",
                {"ticker": t, "events": [{k: rounded(v) for k, v in e.items()} for e in ev], "summary": summary(ev)},
            )
            n += 1
    log.info("earnings reactions: %d companies", n)


def movers(http: httpx.Client) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """The scan for each window; returns (panels, analyses) to snapshot as (ticker, window) pairs."""
    panels, analyses = set(), set()
    for w in WINDOWS:
        scan = http.get("/moves/scan", params={"window": w, "limit": 25}).json()
        if scan.get("status") != "ready":
            raise SystemExit(f"The movers scan isn't ready ({scan.get('status')}); open /moves/scan once and wait a minute.")
        write(f"moves/scan_{w}.json", scan)
        write(f"moves/map_{w}.json", http.get("/moves/map", params={"window": w}).json())
        for side in ("gains", "falls"):
            top = [r["ticker"] for r in scan[side]]
            panels |= {(t, w) for t in top[:TOP_PANELS]}
            analyses |= {(t, w) for t in top[:TOP_ANALYSES]}
    return panels, analyses


def move_panels(http: httpx.Client, panels: set, analyses: set) -> None:
    for t, w in sorted(panels):
        r = http.get(f"/moves/{t}", params={"window": w})
        if r.status_code == 200:
            write(f"moves/{t}/move_{w}.json", r.json())
    for t, w in sorted(analyses):
        r = http.post(f"/moves/{t}/investigate", params={"window": w})
        if r.status_code == 200:
            write(f"moves/{t}/analysis_{w}.json", r.json())
            # Re-save the panel so it shows the explanation without a click.
            panel = http.get(f"/moves/{t}", params={"window": w}).json()
            write(f"moves/{t}/move_{w}.json", panel)
        else:
            log.warning("explanation %s %s: %s %s", t, w, r.status_code, r.text[:200])
    log.info("move panels: %d, explanations: %d", len(panels), len(analyses))


def notes(http: httpx.Client, tickers: list[str]) -> None:
    """Research notes; the API writes today's note if there isn't one and returns the cached note if there is."""
    done = 0
    for t in tickers:
        r = http.post(f"/analyst/{t}", timeout=300)
        if r.status_code == 200:
            write(f"analyst/{t}.json", r.json())
            done += 1
        else:
            log.warning("note %s: %s %s", t, r.status_code, r.text[:200])
    log.info("research notes: %d of %d", done, len(tickers))
    listed = http.get("/analyst", params={"limit": 50}).json()
    write("analyst/index.json", [n for n in listed if (OUT / "analyst" / f"{n['ticker']}.json").exists()])


def copilot(http: httpx.Client) -> None:
    write("documents.json", http.get("/documents").json())
    # One quoted string per line inside the EXAMPLES array, in either quote style.
    examples = [
        m.group(2) for m in re.finditer(r"""^\s*(['"])(.+)\1,?\s*$""", (ROOT / "web" / "src" / "examples.ts").read_text(), re.M)
    ]
    index = {}
    for i, q in enumerate(examples):
        r = http.post("/ask", json={"question": q, "run": "E"}, timeout=180)
        if r.status_code != 200:
            log.warning("answer %d: %s", i, r.status_code)
            continue
        a = r.json()
        write(f"answers/{i}.json", a)
        index[q] = f"{i}.json"
        cites = a.get("citations") or []
        for c in [*cites, *(a.get("closest") or []), *(a.get("retrieved") or [])[:3]]:
            name = OUT / "pages" / f"{c['doc_id']}_p{c['page']}.png"
            if name.exists():
                continue
            img = http.get(f"/documents/{c['doc_id']}/page/{c['page']}.png", params={
                "snippet": (c.get("highlight") or c.get("snippet") or "")[:1500], "rows": str(c.get("chunk_type") == "table").lower(),
            })  # fmt: skip
            if img.status_code == 200:
                name.parent.mkdir(parents=True, exist_ok=True)
                name.write_bytes(img.content)
    write("answers/index.json", index)
    log.info("copilot: %d answers", len(index))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if OUT.exists():
        shutil.rmtree(OUT)
    http = httpx.Client(base_url=API, timeout=120)
    for name in ("meta", "watchlist", "signals", "backtest", "risk"):
        write(f"recs/{name}.json", http.get(f"/recs/{name}").json())
    rows = {r["ticker"]: r for r in json.loads((OUT / "recs" / "watchlist.json").read_text())}
    company_pages(http, sorted(rows))
    histories(rows)
    earnings(rows)
    panels, analyses = movers(http)
    well_known = [t for t in WELL_KNOWN if t in rows]
    panels |= {(t, w) for t in well_known for w in WINDOWS}
    analyses |= {(t, "1w") for t in well_known}
    # The home page explains the S&P 500's largest company-specific moves of the day: snapshot those too.
    explained = {(e["ticker"], "1d") for e in http.get("/moves/overview", params={"window": "1d"}).json().get("explained", [])}
    move_panels(http, panels | explained, analyses | explained)
    write("moves/overview_1d.json", http.get("/moves/overview", params={"window": "1d"}).json())
    week = json.loads((OUT / "moves" / "scan_1w.json").read_text())
    movers_1w = [r["ticker"] for side in ("gains", "falls") for r in week[side][:TOP_NOTES]]
    notes(http, list(dict.fromkeys(well_known + movers_1w)))
    copilot(http)
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    log.info("snapshot: %d files, %.1f MB -> %s", sum(1 for f in OUT.rglob("*") if f.is_file()), size / 1e6, OUT)


if __name__ == "__main__":
    main()

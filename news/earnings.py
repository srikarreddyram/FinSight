"""How a stock has reacted to its earnings reports.

An earnings date is the day the company filed an 8-K with item 2.02 (results of operations). Companies report
before the open or after the close, and the filing date doesn't say which, so the reaction is measured over two
sessions: from the close before the filing date to the close of the trading day after it. That window holds the
reaction either way; it is shown next to the market's (SPY) move over the same days.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


def reactions(closes: pd.DataFrame, ticker: str, dates: list[date], market: str = "SPY") -> list[dict]:
    """One row per earnings date with prices on both sides: the stock's change and the market's."""
    px = closes[[ticker, market]].dropna()
    days = np.array(px.index)
    out = []
    for d in sorted(set(dates)):
        before = np.searchsorted(days, d, side="left") - 1  # last close before the filing date
        on = np.searchsorted(days, d, side="left")  # the filing date, or the next trading day
        after = on + 1
        if before < 0 or after >= len(days):
            continue
        s0, s1 = px[ticker].iloc[before], px[ticker].iloc[after]
        m0, m1 = px[market].iloc[before], px[market].iloc[after]
        change = float(s1 / s0 - 1)
        out.append({"date": str(d), "change": change, "market": float(m1 / m0 - 1), "vs_market": change - float(m1 / m0 - 1)})
    return out


def summary(rows: list[dict]) -> dict:
    """Typical size of the move, how often it was up, and where the latest one ranks against the rest."""
    if not rows:
        return {"count": 0}
    vs = np.array([r["vs_market"] for r in rows])
    last = rows[-1]
    earlier = vs[:-1]
    worse = int((earlier < last["vs_market"]).sum()) if len(earlier) else 0
    # "Largest since": how many earlier reports back you have to go to find a bigger move in the same direction.
    since = None
    for r in reversed(rows[:-1]):
        bigger = r["vs_market"] <= last["vs_market"] if last["vs_market"] < 0 else r["vs_market"] >= last["vs_market"]
        if bigger:
            since = r["date"]
            break
    return {
        "count": len(rows),
        "typical": float(np.median(np.abs(vs))),
        "up": int((vs > 0).sum()),
        "largest_up": max(rows, key=lambda r: r["vs_market"]),
        "largest_down": min(rows, key=lambda r: r["vs_market"]),
        "last": last,
        "last_rank": worse / len(earlier) if len(earlier) else None,  # share of earlier reactions below the latest
        "last_biggest_since": since,  # None: the biggest move in this direction in the whole history
    }

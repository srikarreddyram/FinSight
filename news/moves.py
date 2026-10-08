"""How much of a stock's move was the market, its sector, and the company itself.

Daily log returns are regressed on the market (SPY) and on the sector's excess over the market (its SPDR sector
ETF minus SPY) over the year before the window:

    r_stock = a + b_m * r_SPY + b_s * (r_sector - r_SPY) + e

Over the window, the market part is b_m * sum(r_SPY), the sector part b_s * sum(r_sector - r_SPY), and the rest
(including a) is company-specific. Log returns add up, so the three parts sum exactly to the total; they are
then scaled to the simple percentage change shown. The days with the largest residuals e are where to look for
company news.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

MARKET = "SPY"
SECTOR_ETF = {
    "Energy": "XLE", "Materials": "XLB", "Industrials": "XLI", "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP", "Health Care": "XLV", "Financials": "XLF", "Information Technology": "XLK",
    "Communication Services": "XLC", "Utilities": "XLU", "Real Estate": "XLRE",
}  # fmt: skip
# The three S&P indexes whose members make up the universe, by their own levels (for the home page).
INDEXES = {"S&P 500": "^GSPC", "S&P 400": "^SP400", "S&P 600": "^SP600"}
WINDOWS = {"1d": 1, "1w": 5, "1m": 21}
ESTIMATION_DAYS = 252
MIN_ESTIMATION_DAYS = 120

Closes = Callable[[list[str], str], pd.DataFrame]
# yfinance's download() keeps results in module-level state, so two at once (the universe scan and a company
# page) overwrite each other's and both come back empty. One download at a time.
_YAHOO = threading.Lock()
SCAN_CHUNK = 150


def yahoo_closes(tickers: list[str], period: str = "15mo") -> pd.DataFrame:
    """Adjusted daily closes, one column per ticker (dividends and splits folded in)."""
    import yfinance as yf

    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    with _YAHOO:
        df = yf.download(tickers, period=period, auto_adjust=True, progress=False, threads=True, group_by="column")
    if df.empty:
        raise ValueError(f"Yahoo returned no prices for {', '.join(tickers[:5])}{'…' if len(tickers) > 5 else ''}")
    closes = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]].rename(columns={"Close": tickers[0]})
    closes.index = pd.to_datetime(closes.index).date
    return closes.dropna(how="all")


def yahoo_closes_chunked(tickers: list[str], period: str = "3mo", chunk: int = SCAN_CHUNK) -> pd.DataFrame:
    """The same for a long list, in chunks, so a company page's download can run between them."""
    parts = []
    for i in range(0, len(tickers), chunk):
        try:
            parts.append(yahoo_closes(tickers[i : i + chunk], period))
        except ValueError as e:  # one empty chunk shouldn't sink the scan
            log.warning("%s", e)
        time.sleep(0.5)  # the lock isn't fair: pause so a waiting company page gets its turn
    if not parts:
        raise ValueError("Yahoo returned no prices")
    return pd.concat(parts, axis=1).sort_index()


@dataclass
class KeyDay:
    day: date
    change: float  # the stock's simple return that day
    company: float  # the company-specific (residual) part of it


@dataclass
class Move:
    ticker: str
    days: int
    start: date  # last close before the window
    end: date  # last close in the window
    price_start: float
    price_end: float
    change: float  # simple return over the window
    market: float  # contributions to `change`, in the same units; they sum to it
    sector: float
    company: float
    beta_market: float
    beta_sector: float | None
    sector_etf: str | None
    r2: float
    unusual: float  # company-specific part in standard deviations of its usual move over this many days
    key_days: list[KeyDay] = field(default_factory=list)

    def as_json(self) -> dict:
        d = asdict(self)
        d["start"], d["end"] = str(self.start), str(self.end)
        d["key_days"] = [{**asdict(k), "day": str(k.day)} for k in self.key_days]
        return d


def attribute(closes: pd.DataFrame, ticker: str, days: int, sector_etf: str | None = None) -> Move:
    """Break the last `days` trading days of `ticker` into market, sector and company-specific parts."""
    cols = [ticker, MARKET] + ([sector_etf] if sector_etf and sector_etf in closes else [])
    px = closes[cols].dropna()
    if len(px) < days + MIN_ESTIMATION_DAYS + 1:
        raise ValueError(f"{ticker}: not enough price history ({len(px)} days)")
    r = np.log(px).diff().dropna()
    window, est = r.iloc[-days:], r.iloc[-days - ESTIMATION_DAYS : -days]
    factors = [MARKET] + ([sector_etf] if len(cols) == 3 else [])

    def design(frame: pd.DataFrame) -> np.ndarray:
        x = [frame[MARKET].to_numpy()]
        if len(factors) == 2:
            x.append((frame[sector_etf] - frame[MARKET]).to_numpy())
        return np.column_stack(x)

    x_est = np.column_stack([np.ones(len(est)), design(est)])
    coef, *_ = np.linalg.lstsq(x_est, est[ticker].to_numpy(), rcond=None)
    fitted = x_est @ coef
    resid_est = est[ticker].to_numpy() - fitted
    ss_tot = float(((est[ticker] - est[ticker].mean()) ** 2).sum())
    r2 = 1 - float((resid_est**2).sum()) / ss_tot if ss_tot > 0 else 0.0

    xw = design(window)
    total = float(window[ticker].sum())
    market = float(coef[1] * xw[:, 0].sum())
    sector = float(coef[2] * xw[:, 1].sum()) if len(factors) == 2 else 0.0
    company = total - market - sector
    simple = math.expm1(total)
    scale = simple / total if abs(total) > 1e-12 else 1.0  # log points -> the simple change shown

    resid = window[ticker].to_numpy() - coef[0] - xw @ coef[1:]
    order = np.argsort(-np.abs(resid))[: min(3, days)]
    key_days = [
        KeyDay(window.index[i], math.expm1(float(window[ticker].iloc[i])), math.expm1(float(resid[i]))) for i in sorted(order)
    ]
    sigma = float(resid_est.std(ddof=len(coef)))
    return Move(
        ticker=ticker, days=days, start=px.index[-days - 1], end=px.index[-1],
        price_start=float(px[ticker].iloc[-days - 1]), price_end=float(px[ticker].iloc[-1]),
        change=simple, market=market * scale, sector=sector * scale, company=company * scale,
        beta_market=float(coef[1]), beta_sector=float(coef[2]) if len(factors) == 2 else None,
        sector_etf=sector_etf if len(factors) == 2 else None, r2=r2,
        unusual=company / (sigma * math.sqrt(days)) if sigma > 0 else 0.0, key_days=key_days,
    )  # fmt: skip


def scan(closes: pd.DataFrame, sectors: dict[str, str | None], days: int) -> pd.DataFrame:
    """Every ticker's change over the last `days` trading days, and how it compares with the market and its
    sector ETF. A quick screen: the regression above runs per company, on its page."""
    px = closes.ffill()
    last, first = px.iloc[-1], px.iloc[-days - 1]
    change = last / first - 1
    daily = px.iloc[-days - 1 :].pct_change().iloc[1:]
    # The largest single-day move in the window: a spin-off Yahoo didn't adjust for shows up as one huge day.
    max_day = daily.apply(lambda c: c.loc[c.abs().idxmax()] if c.notna().any() else float("nan"))
    rows = []
    for tk, sec in sectors.items():
        if tk not in change or pd.isna(change[tk]):
            continue
        etf = SECTOR_ETF.get(sec or "")
        rows.append({
            "ticker": tk, "price": float(last[tk]), "change": float(change[tk]), "vs_market": float(change[tk] - change[MARKET]),
            "vs_sector": float(change[tk] - change[etf]) if etf in change else None,
            "max_day": float(max_day[tk]) if pd.notna(max_day.get(tk)) else None,
        })  # fmt: skip
    return pd.DataFrame(rows)

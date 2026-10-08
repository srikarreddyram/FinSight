"""Plain-language names for signals and risk measures, shared by the explanations and the dashboard."""

from __future__ import annotations

import math

# name -> (label, family, format): pct = share shown as %, pp = change in percentage points, x = multiple,
# num = plain number, flag = yes/no
SIGNALS: dict[str, tuple[str, str, str]] = {
    "f_score": ("Piotroski F-score", "Accounting quality", "num"),
    "accruals": ("Accruals ratio", "Accounting quality", "pct"),
    "altman_z": ("Altman Z-score", "Accounting quality", "num"),
    "beneish_m": ("Beneish M-score", "Accounting quality", "num"),
    "revenue_growth": ("Revenue growth", "Fundamentals", "pct"),
    "revenue_growth_chg": ("Change in revenue growth", "Fundamentals", "pp"),
    "asset_growth": ("Asset growth", "Fundamentals", "pct"),
    "gross_margin": ("Gross margin", "Fundamentals", "pct"),
    "gross_margin_chg": ("Change in gross margin", "Fundamentals", "pp"),
    "operating_margin": ("Operating margin", "Fundamentals", "pct"),
    "operating_margin_chg": ("Change in operating margin", "Fundamentals", "pp"),
    "net_margin": ("Net margin", "Fundamentals", "pct"),
    "net_margin_chg": ("Change in net margin", "Fundamentals", "pp"),
    "roe": ("Return on equity", "Fundamentals", "pct"),
    "roe_chg": ("Change in return on equity", "Fundamentals", "pp"),
    "roa": ("Return on assets", "Fundamentals", "pct"),
    "roa_chg": ("Change in return on assets", "Fundamentals", "pp"),
    "leverage": ("Liabilities to assets", "Fundamentals", "pct"),
    "leverage_chg": ("Change in liabilities to assets", "Fundamentals", "pp"),
    "debt_to_equity": ("Debt to equity", "Fundamentals", "x"),
    "earnings_yield": ("Earnings yield", "Valuation", "pct"),
    "mom_12_1": ("12-month momentum (skipping the last month)", "Price", "pct"),
    "rev_1m": ("Last month's return", "Price", "pct"),
    "high_52w": ("Price vs 52-week high", "Price", "pct"),
    "insider_buyers_6m": ("Insiders buying, past 6 months", "Insider activity", "num"),
    "insider_net_6m": ("Net insider buying, past 6 months", "Insider activity", "num"),
    "book_to_market": ("Book-to-market", "Valuation", "x"),
    "fcf_yield": ("Free-cash-flow yield", "Valuation", "pct"),
    "sales_to_price": ("Sales-to-price", "Valuation", "x"),
    "sim_risk_factors": ("Risk Factors similarity to last year's 10-K", "Filing text", "pct"),
    "sim_mda": ("MD&A similarity to last year's 10-K", "Filing text", "pct"),
    "risk_factors_words": ("Risk Factors length (log words)", "Filing text", "num"),
    "risk_factors_words_chg": ("Growth in Risk Factors length", "Filing text", "pct"),
    "fog_mda": ("MD&A reading difficulty (Fog index)", "Filing text", "num"),
    # Risk Engine measures
    "net_debt_to_ebitda": ("Net debt to EBITDA", "Financial health", "x"),
    "interest_coverage": ("Interest coverage", "Financial health", "x"),
    "current_ratio": ("Current ratio", "Financial health", "x"),
    "quick_ratio": ("Quick ratio", "Financial health", "x"),
    "cash_burn": ("Cash burn (share of cash used in a year)", "Financial health", "pct"),
    "earnings_vol": ("Earnings volatility (5-year ROA)", "Earnings quality", "pct"),
    "dividend_cut": ("Dividend cut", "Earnings quality", "flag"),
    "vol_12m": ("Trailing 12-month volatility", "Market risk", "pct"),
    "beta": ("Beta to the S&P 500", "Market risk", "num"),
    "mdd_12m": ("Largest fall in the past 12 months", "Market risk", "pct"),
    "downside_dev": ("Downside deviation", "Market risk", "pct"),
    "log_dollar_volume": ("Trading volume (log dollars)", "Market risk", "num"),
    "ret_12m": ("12-month return", "Market risk", "pct"),
    "going_concern": ("Going-concern doubt in the 10-K", "Disclosure risk", "flag"),
    "material_weakness": ("Material weakness in internal control", "Event risk", "flag"),
    "late_filings_12m": ("Late-filing notices, past 12 months", "Event risk", "num"),
    "amended_10k_12m": ("Amended 10-Ks, past 12 months", "Event risk", "num"),
    "auditor_change_24m": ("Auditor changes, past 24 months", "Event risk", "num"),
    "non_reliance_24m": ("Non-reliance notices, past 24 months", "Event risk", "num"),
}
PILLAR_LABELS = {
    "health": "Financial health", "quality": "Earnings quality", "market": "Market risk",
    "disclosure": "Disclosure risk", "events": "Event risk",
}  # fmt: skip


def label(name: str) -> str:
    return SIGNALS.get(name, (name, "", "num"))[0]


def fmt(name: str, value: float | None) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    kind = SIGNALS.get(name, ("", "", "num"))[2]
    if kind == "pct":
        return f"{value * 100:.1f}%"
    if kind == "pp":
        return f"{value * 100:+.1f} pts"
    if kind == "x":
        return f"{value:.2f}×"
    if kind == "flag":
        return "yes" if value >= 0.5 else "no"
    return f"{value:.2f}" if abs(value) < 100 else f"{value:,.0f}"


def base(feature: str) -> tuple[str, str]:
    """'leverage_chg_srank' -> ('leverage_chg', 'sector'); 'vol_12m_r' or 'vol_12m' -> ('vol_12m', 'market')."""
    for suffix, scope in (("_srank", "sector"), ("_rank", "market"), ("_r", "market")):
        if feature.endswith(suffix) and feature[: -len(suffix)] in SIGNALS:
            return feature[: -len(suffix)], scope
    return feature, "market"

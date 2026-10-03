"""The Risk Engine's panel: the signal panel's stock-months plus the five pillars and the risk targets.

    uv run python -m risk.panel        # needs the study's panel.parquet (uv run python -m models.study)

Rows and point-in-time rules are the Signal Lab's. Pillar measures already built as signals (Altman Z,
accruals, Beneish M, leverage, 10-K similarity) are reused; the rest come from risk/pillars.py (filings) and
risk/market.py (prices). `target_end` is the end of the 12-month risk window, so walk-forward folds purge on it.
"""

from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor

import duckdb
import pandas as pd

from models import STUDY_DIR as STUDY
from models import THREADS
from models.study import _build_chunk, _stays
from risk.market import market_panel
from risk.pillars import disclosure_event_features, health_quality_features
from warehouse import db

log = logging.getLogger(__name__)

REUSED = ["altman_z", "accruals", "beneish_m", "leverage", "leverage_chg", "sim_risk_factors", "sim_mda",
          "risk_factors_words_chg", "fog_mda"]  # fmt: skip
PILLARS = {
    "health": ["altman_z", "leverage", "net_debt_to_ebitda", "interest_coverage", "current_ratio", "quick_ratio", "cash_burn"],
    "quality": ["accruals", "beneish_m", "earnings_vol", "dividend_cut"],
    "market": ["vol_12m", "beta", "mdd_12m", "downside_dev", "log_dollar_volume", "ret_12m"],
    "disclosure": ["sim_risk_factors", "sim_mda", "risk_factors_words_chg", "fog_mda", "going_concern"],
    "events": ["material_weakness", "late_filings_12m", "amended_10k_12m", "auditor_change_24m", "non_reliance_24m"],
}
# Direction of risk for the scorecard: +1 = higher is riskier, -1 = lower is riskier.
DIRECTION = {
    "altman_z": -1, "leverage": 1, "net_debt_to_ebitda": 1, "interest_coverage": -1, "current_ratio": -1,
    "quick_ratio": -1, "cash_burn": 1, "accruals": 1, "beneish_m": 1, "earnings_vol": 1, "dividend_cut": 1,
    "vol_12m": 1, "beta": 1, "mdd_12m": -1, "downside_dev": 1, "log_dollar_volume": -1, "ret_12m": -1,
    "sim_risk_factors": -1, "sim_mda": -1, "risk_factors_words_chg": 1, "fog_mda": 1, "going_concern": 1,
    "material_weakness": 1, "late_filings_12m": 1, "amended_10k_12m": 1, "auditor_change_24m": 1, "non_reliance_24m": 1,
}  # fmt: skip
MEASURES = [m for ms in PILLARS.values() for m in ms]


def build(con: duckdb.DuckDBPyConnection, workers: int = THREADS) -> pd.DataFrame:
    base = pd.read_parquet(STUDY / "panel.parquet")
    base["month"] = pd.to_datetime(base["month"]).dt.date
    months = sorted(base["month"].unique())
    stays = _stays(con)
    names = dict(base[["ticker", "cik"]].drop_duplicates().itertuples(index=False))
    items = sorted(names.items())
    chunks = [dict(items[i::workers]) for i in range(workers)]
    log.info("filing pillars: %d companies x %d months, %d workers", len(names), len(months), workers)
    families = [health_quality_features, disclosure_event_features]
    with ProcessPoolExecutor(workers) as pool:
        parts = list(pool.map(_build_chunk, [(str(db.default_path()), c, months, stays, families) for c in chunks if c]))
    fam = pd.concat(parts, ignore_index=True)
    new = [c for c in fam.columns if c in DIRECTION and c not in REUSED]
    fam = fam[["ticker", "month", *new, "info_date"]].rename(columns={"info_date": "risk_info_date"})
    log.info("market pillar and targets")
    mkt = market_panel(con, sorted(base["ticker"].unique()), months)
    keep = [c for c in ("ticker", "cik", "month", "sector", "tier", "info_date") if c in base]
    p = base[[*keep, *REUSED]].merge(fam, on=["ticker", "month"], how="left")
    p = p.merge(mkt, on=["ticker", "month"], how="left")
    p["target_end"] = p["risk_target_end"]
    return p


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    con = duckdb.connect(str(db.default_path()), read_only=True)
    p = build(con)
    p.to_parquet(STUDY / "risk_panel.parquet")
    log.info("risk panel: %d rows; coverage %s", len(p), p[MEASURES + ["fwd_vol", "severe"]].notna().mean().round(2).to_dict())
    log.info("severe-loss rate %.3f; median forward vol %.3f", p["severe"].mean(), p["fwd_vol"].median())


if __name__ == "__main__":
    main()

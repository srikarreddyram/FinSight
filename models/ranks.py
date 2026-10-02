"""Monthly cross-sectional percentile ranks, raw and sector-neutral (platform PRD, Signal Lab).

Ranks make signals comparable across months and robust to outliers (a 95% revenue jump and a 40% one are both
"top of the cross-section"). Sector-neutral ranks compare a stock only with its sector peers that month, so a
signal that mostly says "utilities carry debt" doesn't masquerade as stock selection.

Ranks are (rank - 0.5) / n, so they are centred on 0.5 and a stock alone in its group gets exactly 0.5.
Missing values stay missing and don't count towards n."""

from __future__ import annotations

import pandas as pd


def _pct(s: pd.Series) -> pd.Series:
    n = s.notna().sum()
    return (s.rank(method="average") - 0.5) / n if n else s


def add_ranks(panel: pd.DataFrame, features: list[str], sector_col: str = "sector") -> pd.DataFrame:
    """Adds `<feature>_rank` (within month) and `<feature>_srank` (within month and sector) columns."""
    out = panel.copy()
    by_month = out.groupby("month")
    by_sector = out.groupby(["month", out[sector_col].fillna("Unknown")])
    for f in features:
        out[f"{f}_rank"] = by_month[f].transform(_pct)
        out[f"{f}_srank"] = by_sector[f].transform(_pct)
    return out

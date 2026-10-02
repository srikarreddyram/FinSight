"""Walk-forward validation: expanding training window, one test year per fold, purged of overlapping labels.

A row's label is a 12-month return starting after an embargo, so a training row from late in the year before
the test year has a label window that runs into the test year. Those rows are purged: a training row is
kept only if its target_end is before the first test month.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class Fold:
    year: int
    train: pd.Index
    test: pd.Index


def folds(panel: pd.DataFrame, first_test_year: int, last_test_year: int | None = None) -> list[Fold]:
    years = panel["month"].map(lambda d: d.year)
    last = last_test_year or int(years.max())
    out = []
    for y in range(first_test_year, last + 1):
        test = panel.index[years == y]
        if len(test) == 0:
            continue
        first_test = date(y, 1, 1)
        train = panel.index[(panel["month"] < first_test) & (panel["target_end"] < first_test)]
        out.append(Fold(year=y, train=train, test=test))
    return out


def rank_ic_by_month(df: pd.DataFrame, pred: str, target: str, min_names: int = 5) -> pd.Series:
    """Spearman correlation between predicted and realised ranks, per month."""

    def ic(g: pd.DataFrame) -> float:
        g = g[[pred, target]].dropna()
        if len(g) < min_names:
            return float("nan")
        return g[pred].rank().corr(g[target].rank())

    return df.groupby("month")[[pred, target]].apply(ic).dropna()


def mean_rank_ic(df: pd.DataFrame, pred: str, target: str, min_names: int = 5) -> float:
    return float(rank_ic_by_month(df, pred, target, min_names).mean())

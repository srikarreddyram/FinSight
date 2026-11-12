"""The one-month ranker's pieces: the earnings-reaction and low-risk signals, the target, and the purge."""

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from models.monthly import monthly_t, one_month_targets
from models.panel import Returns
from models.walkforward import folds
from signals.earnings import compute as ear
from signals.lowrisk import aligned
from signals.lowrisk import compute as lowrisk


def _weekdays(start: date, n: int) -> np.ndarray:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return np.array(out)


def test_earnings_reaction_is_the_two_session_move_against_the_market():
    days = _weekdays(date(2024, 1, 1), 60)
    r, m = np.zeros(60), np.zeros(60)
    r[20], r[21], m[20], m[21] = math.log(1.06), math.log(1.02), math.log(1.01), 0.0  # report filed on days[20]
    cum, mcum = np.cumsum(r), np.cumsum(m)
    report = days[20]
    feats, info = ear(days, cum, days, mcum, [report], days[40])
    assert feats["ear"] == pytest.approx(1.06 * 1.02 - 1 - 0.01) and info == days[21]
    # the day after the report hasn't closed yet: nothing to use
    assert math.isnan(ear(days, cum, days, mcum, [report], days[20])[0]["ear"])
    assert ear(days, cum, days, mcum, [report], days[21])[0]["ear"] == pytest.approx(1.06 * 1.02 - 1 - 0.01)
    # a report on a Saturday counts from the next trading day; one over 100 days old is stale
    saturday = days[19] + timedelta(days=1) if days[19].weekday() == 4 else days[24] + timedelta(days=1)
    assert not math.isnan(ear(days, cum, days, mcum, [saturday], days[40])[0]["ear"])
    assert math.isnan(ear(days, cum, days, mcum, [report], report + timedelta(days=120))[0]["ear"])
    # the latest usable report wins
    r2 = r.copy()
    r2[50] = math.log(0.90)
    assert ear(days, np.cumsum(r2), days, mcum, [report, days[50]], days[55])[0]["ear"] == pytest.approx(-0.10)


def test_low_risk_measures_by_hand():
    rng = np.random.default_rng(0)
    m = rng.normal(0, 0.01, 252)
    noise = rng.normal(0, 0.02, 252)
    out = lowrisk(1.5 * m + noise, m)
    assert out["beta_1y"] == pytest.approx(1.5, abs=0.25)
    assert out["vol_1y"] == pytest.approx((1.5 * m + noise).std(ddof=1) * math.sqrt(252))
    resid = (1.5 * m + noise)[-21:] - out["beta_1y"] * m[-21:]
    assert out["ivol_1m"] == pytest.approx(resid.std(ddof=1) * math.sqrt(252))
    assert all(math.isnan(v) for v in lowrisk(noise[:150], m[:150]).values())  # under 200 days of history


def test_market_returns_align_to_the_stocks_days():
    market_days = np.array([date(2024, 1, d) for d in (2, 3, 4, 5)])
    level = np.array([0.0, 0.01, 0.03, 0.06])
    out = aligned(np.array([date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 6)]), market_days, level)
    assert math.isnan(out[0]) and out[1] == pytest.approx(0.02) and math.isnan(out[2])


def _returns(series: dict[str, tuple[np.ndarray, np.ndarray]]) -> Returns:
    r = object.__new__(Returns)
    r.series = {k: (d, np.cumsum(np.log1p(x))) for k, (d, x) in series.items()}
    return r


def test_the_target_skips_the_first_trading_day_after_the_month_end():
    days = _weekdays(date(2024, 1, 29), 30)  # late January to early March
    spy = np.zeros(30)
    stock = np.zeros(30)
    feb = [i for i, d in enumerate(days) if d.month == 2]
    stock[feb[0]] = 0.50  # the first trading day of February: before the position is entered
    stock[feb[1]] = 0.10
    spy[feb[2]] = 0.02
    rets = _returns({"SPY": (days, spy), "AAA": (days, stock), "GONE": (days[:10], stock[:10])})
    rows = pd.DataFrame({"ticker": ["AAA", "GONE", "AAA"], "month": [date(2024, 1, 31), date(2024, 1, 31), date(2024, 2, 29)]})
    t = one_month_targets(rets, rows)
    a = t.iloc[0]
    assert a["target_start"] == days[feb[0]] and a["target_end"] == date(2024, 2, 29)
    assert a["fwd_ret"] == pytest.approx(0.10) and a["excess_ret"] == pytest.approx(0.10 - 0.02)
    assert math.isnan(t.iloc[1]["fwd_ret"])  # prices stop inside the month
    assert math.isnan(t.iloc[2]["fwd_ret"])  # March hasn't finished in the data


def test_one_month_labels_purge_only_december():
    months = [date(2019, 11, 30), date(2019, 12, 31), date(2020, 1, 31)]
    panel = pd.DataFrame({"month": months, "target_end": [date(2019, 12, 31), date(2020, 1, 31), date(2020, 2, 29)]})
    [fold] = folds(panel, 2020, 2020)
    assert list(fold.train) == [0] and list(fold.test) == [2]  # December's return is January's: it can't train


def test_monthly_t_counts_months_as_observations():
    ic = pd.Series([0.02, 0.04, 0.00, 0.06])
    mean, t, n = monthly_t(ic)
    assert mean == pytest.approx(0.03) and n == 4
    assert t == pytest.approx(0.03 / ic.std(ddof=1) * 2)

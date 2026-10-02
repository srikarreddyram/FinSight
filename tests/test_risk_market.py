from datetime import date

import numpy as np
import pandas as pd
import pytest

from risk.market import SEVERE, _mdd, measures


def _prices(rets, start="2019-01-01"):
    days = pd.bdate_range(start, periods=len(rets)).date
    return pd.DataFrame({"day": days, "ret": rets, "raw_close": 10.0, "raw_volume": 1000.0})


def test_drawdown_starts_from_the_first_close():
    assert _mdd(np.array([0.1, -0.5, 0.2])) == pytest.approx(1.1 * 0.5 / 1.1 - 1)
    assert _mdd(np.array([-0.2])) == pytest.approx(-0.2)


def test_features_use_the_past_and_targets_the_future():
    rng = np.random.default_rng(0)
    calm, wild = rng.normal(0, 0.005, 400), rng.normal(0, 0.03, 400)
    stock = _prices(np.concatenate([calm, wild]))
    spy = _prices(np.concatenate([calm, calm]))
    t = stock["day"].iloc[399]  # the last calm day
    t = date(t.year, t.month, 1) - pd.Timedelta(days=1).to_pytimedelta()  # a month-end inside the calm stretch
    row = measures(stock, spy, [t], last_day=stock["day"].iloc[-1]).iloc[0]
    assert row["vol_12m"] < 0.12  # trailing: calm
    assert row["beta"] == pytest.approx(1.0, abs=0.05)  # it moved with SPY in the calm stretch
    assert row["fwd_vol"] > 0.3  # forward: wild


def test_a_stock_that_stops_trading_is_severe_only_if_it_already_crashed():
    crash = _prices(np.concatenate([np.zeros(300), np.full(20, -0.05)]))  # -64% then delisted
    quiet = _prices(np.concatenate([np.zeros(300), np.full(20, 0.001)]))
    spy = _prices(np.zeros(800))
    t, last = date(2020, 1, 31), spy["day"].iloc[-1]
    assert measures(crash, spy, [t], last).iloc[0]["severe"] == 1.0
    assert np.isnan(measures(quiet, spy, [t], last).iloc[0]["severe"])
    assert SEVERE == -0.40

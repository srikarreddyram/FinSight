from datetime import date

import pandas as pd
import pytest

from models.backtest import backtest, forward_1m, stats
from warehouse import db

JAN, FEB = date(2020, 1, 31), date(2020, 2, 29)


def _rows():
    # Four stocks, q=0.25: one long, one short each month. A leads in January; B takes over in February.
    return pd.DataFrame(
        {"month": [JAN] * 4 + [FEB] * 4, "ticker": list("ABCD") * 2,
         "pred": [4, 3, 2, 1, 3, 4, 2, 1], "ret_1m": [0.10, 0.05, 0.0, -0.05, 0.02, 0.08, 0.0, -0.10],
         "bench_1m": [0.01] * 4 + [0.02] * 4}
    )  # fmt: skip


def test_legs_turnover_and_costs_by_hand():
    bt = backtest(_rows(), "pred", q=0.25, cost_bps=10)
    assert bt.loc[JAN, "long_short"] == pytest.approx(0.10 - (-0.05))
    assert bt.loc[JAN, "turnover"] == pytest.approx(2.0)  # from cash into +1 A and -1 D
    assert bt.loc[FEB, "long_short"] == pytest.approx(0.08 - (-0.10))
    assert bt.loc[FEB, "turnover"] == pytest.approx(2.0)  # sell A, buy B; the short in D is unchanged
    assert bt.loc[FEB, "long_short_net"] == pytest.approx(0.18 - 2.0 * 0.001)


def test_stats():
    s = stats(pd.Series([0.1, -0.1, 0.1]))
    assert s["ann_return"] == pytest.approx((1.1 * 0.9 * 1.1) ** 4 - 1)
    assert s["max_drawdown"] == pytest.approx(-0.1)


def test_forward_return_starts_after_the_signal_month():
    con = db.connect(":memory:")
    days = pd.bdate_range("2020-01-27", "2020-03-06")
    rets = {d.date(): (0.5 if d.date() == date(2020, 1, 31) else 0.01) for d in days}  # a jump on the signal day
    con.executemany(
        "insert into prices values (?, ?, 1, ?, 0, 'test')", [(tk, d, r) for tk in ("A", "SPY") for d, r in rets.items()]
    )
    out = forward_1m(con, pd.DataFrame({"month": [JAN], "ticker": ["A"]}))
    feb_days = sum(1 for d in rets if date(2020, 2, 1) <= d <= FEB)
    assert out["ret_1m"][0] == pytest.approx(1.01**feb_days - 1)  # the 31 January jump is not held

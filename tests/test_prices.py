from datetime import date

import pandas as pd
import pytest

from warehouse import db, prices


def _yahoo(days, close, adj, splits=None, volume=None):
    idx = pd.DatetimeIndex([pd.Timestamp(d, tz="America/New_York") for d in days])
    return pd.DataFrame(
        {
            "Close": close,
            "Adj Close": adj,
            "Volume": volume or [1000.0] * len(days),
            "Dividends": 0.0,
            "Stock Splits": splits or [0.0] * len(days),
        },
        index=idx,
    )


D = [date(2020, 1, d) for d in (2, 3, 6, 7, 8, 9, 10)]


def test_raw_close_undoes_later_splits():
    # 2-for-1 split on Jan 7: Yahoo shows pre-split closes halved (50 instead of 100).
    h = _yahoo(
        D[:4],
        close=[50.0, 51.0, 52.0, 26.5],
        adj=[50.0, 51.0, 52.0, 26.5],
        splits=[0, 0, 0, 2.0],
        volume=[2000.0, 2000.0, 2000.0, 1000.0],
    )
    out = prices.normalise(h, "abc")
    assert out["raw_close"].tolist() == [100.0, 102.0, 104.0, 26.5]
    assert out["raw_volume"].tolist() == [1000.0, 1000.0, 1000.0, 1000.0]
    assert out["ret"].iloc[3] == pytest.approx(26.5 / 52.0 - 1)  # adjusted: a small dip, not -50%
    assert out["ticker"].iloc[0] == "ABC"


def test_append_after_yahoo_rescales_history_keeps_returns_consistent(tmp_path):
    first = _yahoo(D[:4], close=[10.0, 11.0, 12.0, 13.0], adj=[10.0, 11.0, 12.0, 13.0])
    assert prices.update("abc", history=lambda t, s: first, root=tmp_path) == 4
    # Later download: a dividend on Jan 9 made Yahoo scale every earlier adjusted close by 0.98.
    later = _yahoo(D[3:], close=[13.0, 14.0, 13.5, 14.2], adj=[13.0 * 0.98, 14.0 * 0.98, 13.5, 14.2])

    def history(ticker, start):
        assert start == date(2020, 1, 7)  # resumes from the last cached day
        return later

    assert prices.update("abc", history=history, root=tmp_path) == 3
    cached = prices._read(tmp_path / "ABC.parquet")
    assert cached["day"].map(lambda d: d.date() if hasattr(d, "date") else d).tolist() == D
    rets = cached["ret"].tolist()
    assert rets[3] == pytest.approx(13.0 / 12.0 - 1)  # old rows untouched
    assert rets[4] == pytest.approx(14.0 / 13.0 - 1)  # first new day computed on one basis
    assert rets[5] == pytest.approx(13.5 / (14.0 * 0.98) - 1)  # dividend day: total return
    assert prices.update("abc", history=lambda t, s: later.iloc[-1:], root=tmp_path) == 0  # nothing new


def test_unknown_ticker_writes_nothing(tmp_path):
    assert prices.update("gone", history=lambda t, s: pd.DataFrame(), root=tmp_path) == 0
    assert not (tmp_path / "GONE.parquet").exists()


def test_load_is_idempotent(tmp_path):
    h = _yahoo(D[:3], close=[10.0, 11.0, 12.0], adj=[10.0, 11.0, 12.0])
    prices.update("abc", history=lambda t, s: h, root=tmp_path)
    con = db.connect(":memory:")
    assert prices.load(con, root=tmp_path) == 3
    assert prices.load(con, root=tmp_path) == 3

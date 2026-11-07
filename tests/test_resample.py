import pandas as pd
import pytest

from smc_trader.data.resample import resample_ohlc

COLS = ["open", "high", "low", "close", "volume", "close_time"]


def _m1(times, **over):
    idx = pd.DatetimeIndex(times, name="time")
    n = len(idx)
    df = pd.DataFrame(
        {"open": 5.0, "high": 6.0, "low": 4.0, "close": 5.0, "volume": 1.0, "spread": 0.1},
        index=idx,
    )
    assert len(df) == n
    for k, v in over.items():
        df.iloc[0 if k.startswith("first_") else -1, df.columns.get_loc(k.split("_", 1)[1])] = v
    return df


def _range(start, end):
    return pd.date_range(start, end, freq="1min", tz="UTC")


def test_15_m1_become_one_m15():
    times = _range("2024-01-02 10:00", "2024-01-02 10:14")
    m1 = _m1(times, first_open=1.0, last_close=2.0)
    m1.iloc[3, m1.columns.get_loc("high")] = 9.0
    m1.iloc[5, m1.columns.get_loc("low")] = 0.5
    out = resample_ohlc(m1, "M15")
    assert len(out) == 1
    row = out.iloc[0]
    assert out.index[0] == pd.Timestamp("2024-01-02 10:00", tz="UTC")
    assert (row.open, row.high, row.low, row.close) == (1.0, 9.0, 0.5, 2.0)
    assert row.volume == 15
    assert row.close_time == pd.Timestamp("2024-01-02 10:15", tz="UTC")
    assert "spread" not in out.columns


def test_gaps_do_not_create_empty_buckets():
    times = _range("2024-01-02 10:00", "2024-01-02 10:14").append(
        _range("2024-01-02 10:45", "2024-01-02 10:59")
    )
    out = resample_ohlc(_m1(times), "M15")
    assert len(out) == 2
    assert not out.isna().any().any()


def test_incomplete_tail_dropped_by_default():
    m1 = _m1(_range("2024-01-02 10:00", "2024-01-02 10:07"))
    out = resample_ohlc(m1, "M15")
    assert out.empty
    assert list(out.columns) == COLS
    assert len(resample_ohlc(m1, "M15", drop_incomplete_tail=False)) == 1


def test_naive_index_raises():
    m1 = _m1(_range("2024-01-02 10:00", "2024-01-02 10:14"))
    m1.index = m1.index.tz_localize(None)
    with pytest.raises(ValueError, match="tz-aware"):
        resample_ohlc(m1, "M15")


def test_unsorted_and_duplicated_input_is_normalized():
    m1 = _m1(_range("2024-01-02 10:00", "2024-01-02 10:14"), first_open=1.0, last_close=2.0)
    dup = m1.iloc[[0]].copy()
    dup["open"] = 3.0  # duplicate of 10:00 appearing later wins
    messy = pd.concat([m1.iloc[::-1], dup])
    out = resample_ohlc(messy, "M15")
    assert out.iloc[0].open == 3.0
    assert out.iloc[0].close == 2.0


def test_unknown_tf_raises():
    m1 = _m1(_range("2024-01-02 10:00", "2024-01-02 10:14"))
    with pytest.raises(ValueError, match="Timeframe desconhecido"):
        resample_ohlc(m1, "INVALID")

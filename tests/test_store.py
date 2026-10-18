import pandas as pd

from smc_trader.data.store import load_candles, save_m1


def _m1(start, n, value=1.0):
    idx = pd.date_range(start, periods=n, freq="1min", tz="UTC", name="time")
    return pd.DataFrame(
        {"open": value, "high": value + 1, "low": value - 1, "close": value,
         "volume": 1.0, "spread": 0.1},
        index=idx,
    )


def test_roundtrip_adds_close_time(tmp_path):
    df = _m1("2024-01-02 10:00", 5)
    save_m1(tmp_path, "EURUSD", df)
    out = load_candles(tmp_path, "EURUSD", "M1")
    assert len(out) == 5
    assert (out["close_time"] == out.index + pd.Timedelta(minutes=1)).all()
    assert out.index.tz is not None


def test_incremental_save_merges_and_newer_wins(tmp_path):
    save_m1(tmp_path, "EURUSD", _m1("2024-01-02 10:00", 3, 1.0))
    save_m1(tmp_path, "EURUSD", _m1("2024-01-02 10:02", 3, 7.0))
    out = load_candles(tmp_path, "EURUSD", "M1")
    assert len(out) == 5
    assert out.index.is_unique and out.index.is_monotonic_increasing
    assert out.loc[pd.Timestamp("2024-01-02 10:02", tz="UTC"), "open"] == 7.0
    assert out.loc[pd.Timestamp("2024-01-02 10:01", tz="UTC"), "open"] == 1.0


def test_load_m15_resamples_and_filters(tmp_path):
    save_m1(tmp_path, "EURUSD", _m1("2024-01-02 10:00", 60))
    start = pd.Timestamp("2024-01-02 10:15", tz="UTC")
    end = pd.Timestamp("2024-01-02 10:45", tz="UTC")
    out = load_candles(tmp_path, "EURUSD", "M15", start, end)
    assert list(out.index) == [start, pd.Timestamp("2024-01-02 10:30", tz="UTC")]

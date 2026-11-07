import pytest
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


def test_missing_file_names_symbol_and_path(tmp_path):
    with pytest.raises(FileNotFoundError, match="EURUSD") as e:
        load_candles(tmp_path, "EURUSD")
    assert "dukascopy" in str(e.value)
    assert "EURUSD_M1_dukascopy.parquet" in str(e.value)


def test_unknown_tf_raises(tmp_path):
    save_m1(tmp_path, "EURUSD", _m1("2024-01-02 10:00", 5))
    with pytest.raises(ValueError, match="(?i)timeframe desconhecido"):
        load_candles(tmp_path, "EURUSD", "INVALID")


def test_sources_do_not_mix(tmp_path):
    save_m1(tmp_path, "EURUSD", _m1("2024-01-02 10:00", 3, 1.0), source="dukascopy")
    save_m1(tmp_path, "EURUSD", _m1("2024-01-02 10:00", 2, 9.0), source="mt5")
    duka = load_candles(tmp_path, "EURUSD", source="dukascopy")
    mt5 = load_candles(tmp_path, "EURUSD", source="mt5")
    assert len(duka) == 3 and (duka["open"] == 1.0).all()
    assert len(mt5) == 2 and (mt5["open"] == 9.0).all()
    assert (tmp_path / "EURUSD_M1_mt5.parquet").exists()


def test_invalid_source_raises(tmp_path):
    with pytest.raises(ValueError, match="source"):
        save_m1(tmp_path, "EURUSD", _m1("2024-01-02 10:00", 1), source="foo")
    with pytest.raises(ValueError, match="source"):
        load_candles(tmp_path, "EURUSD", source="foo")


def test_save_is_atomic_on_failure(tmp_path, monkeypatch):
    original = _m1("2024-01-02 10:00", 3, 1.0)
    save_m1(tmp_path, "EURUSD", original)

    def boom(self, *args, **kwargs):
        raise OSError("disco cheio")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", boom)
    with pytest.raises(OSError):
        save_m1(tmp_path, "EURUSD", _m1("2024-01-02 10:05", 3, 7.0))
    monkeypatch.undo()
    out = load_candles(tmp_path, "EURUSD")
    assert len(out) == 3 and (out["open"] == 1.0).all()
    assert [p.name for p in tmp_path.iterdir()] == ["EURUSD_M1_dukascopy.parquet"]

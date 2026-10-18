from pathlib import Path

import pandas as pd
import pytest

from smc_trader.config import DataConfig
from smc_trader.data.mt5_bridge import import_mt5_csv

HEADER = "time,open,high,low,close,tick_volume,spread,real_volume"


def _epoch(text: str) -> int:
    return int(pd.Timestamp(text).tz_localize("UTC").timestamp())


def _write(path: Path, rows: list[tuple[str, float]]) -> Path:
    lines = [HEADER]
    for ts, close in rows:
        lines.append(f"{_epoch(ts)},1.0,2.0,0.5,{close},10,3,0")
    path.write_text("\n".join(lines) + "\n")
    return path


def test_server_time_ny_plus_7(tmp_path):
    csv = _write(
        tmp_path / "a.csv",
        [("2024-01-15 12:00", 1.0), ("2024-03-20 12:00", 1.0), ("2024-07-15 12:00", 1.0)],
    )
    df = import_mt5_csv(csv, DataConfig())
    assert [t.strftime("%Y-%m-%d %H:%M") for t in df.index] == [
        "2024-01-15 10:00",
        "2024-03-20 09:00",
        "2024-07-15 09:00",
    ]
    assert str(df.index.tz) == "UTC"
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "spread"]
    assert df["volume"].iloc[0] == 10.0


def test_server_timezone_option(tmp_path):
    csv = _write(tmp_path / "a.csv", [("2024-03-20 12:00", 1.0)])
    cfg = DataConfig(server_timezone="Europe/Athens", server_ny_offset_hours=None)
    df = import_mt5_csv(csv, cfg)
    assert df.index[0] == pd.Timestamp("2024-03-20 10:00", tz="UTC")


def test_duplicates_and_unsorted_rows(tmp_path):
    csv = _write(
        tmp_path / "a.csv",
        [("2024-01-15 12:02", 5.0), ("2024-01-15 12:01", 1.0), ("2024-01-15 12:01", 9.0)],
    )
    df = import_mt5_csv(csv, DataConfig())
    assert len(df) == 2
    assert df.index.is_monotonic_increasing
    assert df["close"].iloc[0] == 9.0


def test_ambiguous_ny_time_is_dropped(tmp_path):
    csv = _write(
        tmp_path / "a.csv", [("2024-11-03 08:30", 1.0), ("2024-01-15 12:00", 2.0)]
    )
    df = import_mt5_csv(csv, DataConfig())
    assert len(df) == 1
    assert df.index[0] == pd.Timestamp("2024-01-15 10:00", tz="UTC")

"""Testes para o requisito M-09: Reprodutibilidade de relatórios de backtest."""

import json
from pathlib import Path

import pandas as pd

from smc_trader.analysis import Analysis
from smc_trader.backtest.exporter import (
    compute_reproducibility_metadata,
    export_backtest_package,
)
from smc_trader.backtest.types import BacktestConfig, BacktestResult


def test_compute_reproducibility_metadata(tmp_path: Path):
    dates = pd.date_range("2024-01-01", periods=10, freq="1min", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [100.0] * 10,
            "high": [101.0] * 10,
            "low": [99.0] * 10,
            "close": [100.5] * 10,
            "volume": [10] * 10,
        },
        index=dates,
    )
    p_file = tmp_path / "EURUSD_M1.parquet"
    df.to_parquet(p_file)

    cfg = BacktestConfig()
    meta = compute_reproducibility_metadata(
        symbol="EURUSD",
        c_m1=df,
        config=cfg,
        parquet_path=p_file,
    )

    assert meta["symbol"] == "EURUSD"
    assert meta["candle_count"] == 10
    assert meta["parquet_sha256"] is not None
    assert len(meta["parquet_sha256"]) == 64
    assert meta["config_sha256"] is not None
    assert len(meta["config_sha256"]) == 64
    assert meta["git_commit"] != ""


def test_export_backtest_package_includes_reproducibility(tmp_path: Path):
    dates = pd.date_range("2024-01-01", periods=30, freq="1min", tz="UTC")
    df_m1 = pd.DataFrame(
        {
            "open": [100.0] * 30,
            "high": [101.0] * 30,
            "low": [99.0] * 30,
            "close": [100.5] * 30,
            "volume": [10] * 30,
        },
        index=dates,
    )
    df_m15 = df_m1.resample("15min").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    ).dropna()

    cfg = BacktestConfig()
    res = BacktestResult(trades=[], metrics={"total_trades": 0}, config=cfg)
    analysis = Analysis(
        pivots=pd.DataFrame(),
        events=[],
        fvgs=[],
        sweeps=[],
        zones=[],
        breakers=[],
    )

    out_dir = export_backtest_package(
        symbol="TEST_REPRO",
        result=res,
        c_m1=df_m1,
        c_m15=df_m15,
        analysis=analysis,
        base_dir=tmp_path,
    )

    repro_file = out_dir / "reproducibility.json"
    assert repro_file.exists()
    with open(repro_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["symbol"] == "TEST_REPRO"
    assert data["candle_count"] == 30
    assert "parquet_sha256" in data
    assert "config_sha256" in data

    manifest_file = out_dir / "audit_manifest.json"
    assert manifest_file.exists()
    with open(manifest_file, "r", encoding="utf-8") as f:
        m_data = json.load(f)
    assert "reproducibility" in m_data
    assert m_data["reproducibility"]["candle_count"] == 30

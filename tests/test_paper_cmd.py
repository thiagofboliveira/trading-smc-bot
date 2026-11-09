"""Testes do serviço de Paper Trading e simulação do Dia 0 (E3)."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from smc_trader.broker.paper_broker import PaperBroker
from smc_trader.cli import main
from smc_trader.core.types import Employee, EmployeeStage, SignalRecord
from smc_trader.store.database import Database
from smc_trader.store.repository import StoreRepository


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    return tmp_path / "test_paper.db"


def test_paper_broker_live_signals_and_execution():
    """Testa geração de sinal e execução com stop intrabar no PaperBroker."""
    db = Database(":memory:")
    repo = StoreRepository(db)

    emp = Employee(
        id="arthur-d1-rev",
        name="Arthur (D1 Reversion)",
        strategy_id="d1_mean_reversion",
        symbol="NAS100",
        timeframe="D1",
        stage=EmployeeStage.HIRED,
    )
    repo.add_employee(emp)

    broker = PaperBroker(repo, spread=1.0, slippage=0.5)

    # 1. Cria sinal
    sig = SignalRecord(
        id="sig_paper_1",
        employee_id="arthur-d1-rev",
        timestamp="2026-11-09T14:30:00Z",
        direction="long",
        entry_price=18000.0,
        stop_loss=17900.0,
        take_profit=18200.0,
        valid_until="2026-11-09T17:00:00Z",
    )
    repo.record_signal(sig)

    # 2. Executa sinal na barra 1
    ts1 = pd.Timestamp("2026-11-09 14:31:00", tz="UTC")
    trade_instant = broker.execute_signal(
        sig,
        timestamp=ts1,
        open_=18010.0,
        high=18050.0,
        low=17990.0,
        close=18020.0,
    )
    assert trade_instant is None
    assert len(broker.open_positions) == 1

    # 3. Barra 2 atinge o Take Profit
    ts2 = pd.Timestamp("2026-11-09 14:45:00", tz="UTC")
    closed = broker.on_bar_close(
        symbol="ASSET",
        timestamp=ts2,
        open_=18020.0,
        high=18250.0,
        low=18010.0,
        close=18210.0,
    )
    assert len(closed) == 1
    trade = closed[0]
    assert trade.exit_reason == "tp"
    assert trade.r_multiple > 0

    # 4. Verifica se gravou no banco de dados
    db_trades = repo.get_trades(employee_id="arthur-d1-rev", source="paper")
    assert len(db_trades) == 1
    assert db_trades[0].id == trade.id


def test_cli_paper_dry_run(temp_db: Path, capsys: pytest.CaptureFixture[str]):
    """Testa execução de 'smc paper --dry-run'."""
    db_str = str(temp_db)
    res = main(["paper", "--dry-run", "--db-path", db_str])
    assert res == 0
    out = capsys.readouterr().out
    assert "SMC PAPER TRADER" in out
    assert "Modo Dry-Run" in out


def test_cli_paper_replay(tmp_path: Path, temp_db: Path, capsys: pytest.CaptureFixture[str]):
    """Testa replay de série de candles no Paper Trading."""
    db_str = str(temp_db)
    parquet_path = tmp_path / "sample_m1.parquet"

    # Cria candles sintéticos
    rng = np.random.default_rng(42)
    dt_idx = pd.date_range("2024-01-01 14:00:00", periods=50, freq="1min", tz="UTC")
    df = pd.DataFrame(
        {
            "open": 18000.0 + rng.normal(0, 5, 50),
            "high": 18010.0 + rng.normal(0, 5, 50),
            "low": 17990.0 + rng.normal(0, 5, 50),
            "close": 18005.0 + rng.normal(0, 5, 50),
            "volume": 100.0,
        },
        index=dt_idx,
    )
    df.to_parquet(parquet_path)

    res = main(["paper", "--replay", str(parquet_path), "--db-path", db_str])
    assert res == 0
    out = capsys.readouterr().out
    assert "Modo Replay ativado" in out
    assert "Replay concluído" in out

"""Testes do MT5Broker com validação de governança e confirmação humana (E6)."""

from smc_trader.broker.mt5_broker import MT5Broker
from smc_trader.core.types import Employee, EmployeeStage, SignalRecord
from smc_trader.execution.kill_switch import KillSwitch, KillSwitchConfig
from smc_trader.execution.mt5_interface import MockMT5Client
from smc_trader.store.database import Database
from smc_trader.store.repository import StoreRepository


def test_mt5_broker_blocks_non_hired_employee():
    """Garante que modelos em experiência ou candidatos NUNCA operam dinheiro real (P2/P4)."""
    db = Database(":memory:")
    repo = StoreRepository(db)
    client = MockMT5Client(initial_balance=50000.0)
    broker = MT5Broker(client=client, repo=repo)

    emp_probation = Employee(
        id="victor-orb-ny",
        name="Victor (ORB Cash Open)",
        strategy_id="orb_15_ny",
        symbol="NAS100",
        timeframe="M15",
        stage=EmployeeStage.PROBATION,
    )
    repo.add_employee(emp_probation)

    sig = SignalRecord(
        id="sig_test_live_1",
        employee_id="victor-orb-ny",
        timestamp="2026-11-09T14:30:00Z",
        direction="long",
        entry_price=18500.0,
        stop_loss=18450.0,
        take_profit=18600.0,
        valid_until="2026-11-09T17:00:00Z",
    )
    repo.record_signal(sig)

    success, msg, ticket = broker.execute_confirmed_signal(emp_probation, sig)
    assert success is False
    assert "EXECUÇÃO RECUSADA" in msg
    assert "apenas modelos CONTRATADOS" in msg
    assert ticket == 0


def test_mt5_broker_executes_hired_employee_order():
    """Valida envio de ordem de modelo contratado com sizing dinâmico e gravação no store."""
    db = Database(":memory:")
    repo = StoreRepository(db)
    client = MockMT5Client(initial_balance=10000.0)
    client.connect()
    broker = MT5Broker(client=client, repo=repo, default_risk_pct=1.0)

    emp_hired = Employee(
        id="arthur-d1-rev",
        name="Arthur (D1 Reversion)",
        strategy_id="d1_mean_reversion",
        symbol="NAS100",
        timeframe="D1",
        stage=EmployeeStage.HIRED,
    )
    repo.add_employee(emp_hired)

    sig = SignalRecord(
        id="sig_test_live_2",
        employee_id="arthur-d1-rev",
        timestamp="2026-11-09T14:30:00Z",
        direction="long",
        entry_price=18000.0,
        stop_loss=17800.0,
        take_profit=18400.0,
        valid_until="2026-11-09T17:00:00Z",
    )
    repo.record_signal(sig)

    success, msg, ticket = broker.execute_confirmed_signal(emp_hired, sig)
    assert success is True
    assert ticket > 0
    assert "enviada com sucesso" in msg

    # Verifica se gravou no store SQLite
    live_trades = repo.get_trades(employee_id="arthur-d1-rev", source="live")
    assert len(live_trades) == 1
    assert live_trades[0].id == f"live_{ticket}"


def test_mt5_broker_kill_switch_protection():
    """Valida bloqueio automático quando o Kill Switch está acionado."""
    db = Database(":memory:")
    repo = StoreRepository(db)
    client = MockMT5Client(initial_balance=10000.0)
    client.connect()

    # Kill switch com parada de emergência ou limite diário acionado
    ks = KillSwitch(KillSwitchConfig(max_daily_loss_pct=2.0))
    ks.is_active = True
    ks.trigger_reason = "Perda diária acumulada de 5.0% excedeu o teto"

    broker = MT5Broker(client=client, repo=repo, kill_switch=ks)

    emp_hired = Employee(
        id="arthur-d1-rev",
        name="Arthur (D1 Reversion)",
        strategy_id="d1_mean_reversion",
        symbol="NAS100",
        timeframe="D1",
        stage=EmployeeStage.HIRED,
    )
    repo.add_employee(emp_hired)

    sig = SignalRecord(
        id="sig_test_live_3",
        employee_id="arthur-d1-rev",
        timestamp="2026-11-09T14:30:00Z",
        direction="long",
        entry_price=18000.0,
        stop_loss=17800.0,
        take_profit=18400.0,
        valid_until="2026-11-09T17:00:00Z",
    )
    repo.record_signal(sig)

    success, msg, ticket = broker.execute_confirmed_signal(emp_hired, sig)
    assert success is False
    assert "KILL SWITCH" in msg
    assert ticket == 0

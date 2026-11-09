"""Testes unitários da camada de persistência SQLite e gestão de funcionários (E2-4, E2-6)."""

from smc_trader.core.types import (
    DecisionRecord,
    Employee,
    EmployeeStage,
    SignalRecord,
    TradeRecord,
)
from smc_trader.store.database import Database
from smc_trader.store.repository import StoreRepository
from smc_trader.store.seed import seed_default_roster


def test_database_initialization_and_schema():
    """Valida se o schema SQLite é criado corretamente em memória."""
    db = Database(":memory:")
    with db.get_connection() as conn:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
            ).fetchall()
        ]
        assert "employee" in tables
        assert "strategy" in tables
        assert "signal" in tables
        assert "decision" in tables
        assert "trade" in tables
        assert "equity" in tables
        assert "run" in tables


def test_employee_crud():
    """Testa criação, leitura, atualização de estágio e remoção de funcionários."""
    db = Database(":memory:")
    repo = StoreRepository(db)

    emp = Employee(
        id="test-emp",
        name="Test Employee",
        strategy_id="d1_mean_reversion",
        symbol="NAS100",
        timeframe="D1",
        stage=EmployeeStage.CANDIDATE,
        virtual_capital=15000.0,
        params={"param1": 10},
        avatar="🧪",
    )
    repo.add_employee(emp)

    fetched = repo.get_employee("test-emp")
    assert fetched is not None
    assert fetched.name == "Test Employee"
    assert fetched.virtual_capital == 15000.0
    assert fetched.stage == EmployeeStage.CANDIDATE
    assert fetched.params == {"param1": 10}

    # Atualização de estágio
    ok = repo.update_employee_stage("test-emp", EmployeeStage.PROBATION)
    assert ok is True
    assert repo.get_employee("test-emp").stage == EmployeeStage.PROBATION

    # Listagem por estágio
    probation_list = repo.list_employees(EmployeeStage.PROBATION)
    assert len(probation_list) == 1
    assert probation_list[0].id == "test-emp"

    candidate_list = repo.list_employees(EmployeeStage.CANDIDATE)
    assert len(candidate_list) == 0

    # Remoção
    deleted = repo.delete_employee("test-emp")
    assert deleted is True
    assert repo.get_employee("test-emp") is None


def test_promotion_criteria_compliance():
    """Garante cumprimento estrito da regra de ouro do AGENTS.md na promoção."""
    db = Database(":memory:")
    repo = StoreRepository(db)

    # 1. Candidato -> Experiência sempre permitido
    emp_cand = Employee(
        id="candidato-1",
        name="Candidato",
        strategy_id="orb_15_ny",
        symbol="NAS100",
        timeframe="M15",
        stage=EmployeeStage.CANDIDATE,
    )
    repo.add_employee(emp_cand)
    ok, _ = repo.check_promotion_criteria("candidato-1")
    assert ok is True

    # 2. Experiência -> Contratado: D1 Mean Reversion aprovada
    emp_d1 = Employee(
        id="arthur-test",
        name="Arthur Test",
        strategy_id="d1_mean_reversion",
        symbol="NAS100",
        timeframe="D1",
        stage=EmployeeStage.PROBATION,
    )
    repo.add_employee(emp_d1)
    ok_d1, msg_d1 = repo.check_promotion_criteria("arthur-test")
    assert ok_d1 is True
    assert "t = 2.13" in msg_d1

    # 3. Experiência -> Contratado: ORB não possui t >= 2.0 (Reprovada)
    emp_orb = Employee(
        id="victor-test",
        name="Victor Test",
        strategy_id="orb_15_ny",
        symbol="NAS100",
        timeframe="M15",
        stage=EmployeeStage.PROBATION,
    )
    repo.add_employee(emp_orb)
    ok_orb, msg_orb = repo.check_promotion_criteria("victor-test")
    assert ok_orb is False
    assert "não atingiu significância estatística" in msg_orb


def test_seed_default_roster():
    """Valida carga padrão de estratégias e funcionários."""
    db = Database(":memory:")
    repo = StoreRepository(db)
    seed_default_roster(repo)

    emps = repo.list_employees()
    assert len(emps) == 8
    emp_ids = {e.id for e in emps}
    assert "arthur-d1-rev" in emp_ids
    assert "victor-orb-ny" in emp_ids
    assert "bernardo-trend-mme20" in emp_ids

    # Arthur é o único contratado inicialmente
    arthur = repo.get_employee("arthur-d1-rev")
    assert arthur.stage == EmployeeStage.HIRED


def test_signals_decisions_trades_and_company_status():
    """Testa ciclo de vida de trades e cálculo do telão da empresa."""
    db = Database(":memory:")
    repo = StoreRepository(db)
    seed_default_roster(repo)

    # Registra sinal
    sig = SignalRecord(
        id="sig-1",
        employee_id="arthur-d1-rev",
        timestamp="2026-11-09T14:30:00Z",
        direction="long",
        entry_price=18500.0,
        stop_loss=18400.0,
        take_profit=18700.0,
        valid_until="2026-11-09T17:00:00Z",
    )
    repo.record_signal(sig)

    # Registra decisão
    dec = DecisionRecord(
        id="dec-1",
        signal_id="sig-1",
        user="thiago",
        action="enter",
        timestamp="2026-11-09T14:31:00Z",
    )
    repo.record_decision(dec)

    # Registra trade fechado (Paper)
    tr = TradeRecord(
        id="tr-1",
        employee_id="arthur-d1-rev",
        source="paper",
        direction="long",
        entry_time="2026-11-09T14:32:00Z",
        entry_price=18500.0,
        exit_time="2026-11-09T16:00:00Z",
        exit_price=18700.0,
        r_multiple=2.0,
        pnl=200.0,
        exit_reason="tp",
        costs=2.0,
    )
    repo.record_trade(tr)

    # Consulta trades
    trades = repo.get_trades(employee_id="arthur-d1-rev", source="paper")
    assert len(trades) == 1
    assert trades[0].r_multiple == 2.0

    # Telão da Empresa (SPEC_PRODUTO.md)
    status = repo.get_company_status(source="paper")
    assert status["total_trades"] == 1
    assert status["win_rate"] == 100.0
    assert status["total_r"] == 2.0
    assert status["total_pnl"] == 200.0
    assert status["active_employees"] >= 2  # Arthur (Hired) + Victor (Probation)

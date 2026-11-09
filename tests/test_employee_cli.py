"""Testes dos comandos de CLI para funcionários e auditoria de estratégias (E2-5, E2-8)."""

from pathlib import Path

import pytest

from smc_trader.cli import main


@pytest.fixture
def temp_db(tmp_path: Path) -> Path:
    """Retorna caminho para arquivo SQLite isolado em diretório temporário."""
    return tmp_path / "test_smc.db"


def test_cli_employee_seed_and_list(temp_db: Path, capsys: pytest.CaptureFixture[str]):
    """Testa semeadura inicial e listagem via CLI."""
    db_str = str(temp_db)

    # Executa seed
    res_seed = main(["employee", "seed", "--db-path", db_str])
    assert res_seed == 0
    out_seed = capsys.readouterr().out
    assert "Time padrão de funcionários e estratégias populado" in out_seed

    # Executa list
    res_list = main(["employee", "list", "--db-path", db_str])
    assert res_list == 0
    out_list = capsys.readouterr().out
    assert "arthur-d1-rev" in out_list
    assert "CONTRATADO" in out_list
    assert "victor-orb-ny" in out_list


def test_cli_employee_show_and_suspend(temp_db: Path, capsys: pytest.CaptureFixture[str]):
    """Testa detalhamento e suspensão funcional."""
    db_str = str(temp_db)
    main(["employee", "seed", "--db-path", db_str])
    capsys.readouterr()

    # Show
    res_show = main(["employee", "show", "arthur-d1-rev", "--db-path", db_str])
    assert res_show == 0
    out_show = capsys.readouterr().out
    assert "Arthur (D1 Reversion)" in out_show
    assert "d1_mean_reversion" in out_show

    # Suspend
    res_susp = main(["employee", "suspend", "arthur-d1-rev", "--db-path", db_str])
    assert res_susp == 0
    out_susp = capsys.readouterr().out
    assert "afastado temporariamente" in out_susp


def test_cli_employee_promotion_rules(temp_db: Path, capsys: pytest.CaptureFixture[str]):
    """Testa proteção contra contratação precoce sem evidência estatística."""
    db_str = str(temp_db)
    main(["employee", "seed", "--db-path", db_str])
    capsys.readouterr()

    # Victor (orb_15_ny) está em experiência. Tentativa de promoção deve falhar sem --force
    res_fail = main(["employee", "promote", "victor-orb-ny", "--db-path", db_str])
    assert res_fail == 1
    out_fail = capsys.readouterr().out
    assert "PROMOÇÃO RECUSADA" in out_fail

    # Promoção com --force
    res_force = main(["employee", "promote", "victor-orb-ny", "--force", "--db-path", db_str])
    assert res_force == 0
    out_force = capsys.readouterr().out
    assert "promovido para: 🟢 CONTRATADO" in out_force
    assert "AVISO: Promoção forçada pelo usuário" in out_force


def test_cli_strategy_check(capsys: pytest.CaptureFixture[str]):
    """Testa comando smc strategy check."""
    res = main(["strategy", "check", "d1_mean_reversion"])
    assert res == 0
    out = capsys.readouterr().out
    assert "APROVADA" in out
    assert "Invariância de Prefixo" in out

from pathlib import Path

import pytest
from pydantic import ValidationError

from smc_trader.cli import _spread_for
from smc_trader.config import ContractSpec, load_config


def test_config_default_tem_contratos_dos_ativos_do_fibo_e_da_b3():
    cfg = load_config(Path("config/default.yaml"))
    for sym in ("XAUUSD", "NAS100", "BRENT", "EURUSD", "GBPUSD", "USDJPY", "DAX40", "WIN", "WDO"):
        assert sym in cfg.contracts, sym
        assert cfg.contracts[sym].spread > 0


def test_spread_vem_da_config_e_nao_do_codigo():
    cfg = load_config(Path("config/default.yaml"))
    assert _spread_for("XAUUSD", cfg) == cfg.contracts["XAUUSD"].spread


def test_simbolo_sem_contrato_falha_alto_em_vez_de_usar_spread_1():
    cfg = load_config(Path("config/default.yaml"))
    with pytest.raises(KeyError, match="FOO"):
        _spread_for("FOO", cfg)


def test_b3_tem_tick_e_valor_do_ponto():
    cfg = load_config(Path("config/default.yaml"))
    assert cfg.contracts["WIN"].tick_size == 5.0
    assert cfg.contracts["WIN"].point_value == 0.2
    assert cfg.contracts["WDO"].tick_size == 0.5
    assert cfg.contracts["WDO"].point_value == 10.0


def test_contrato_nao_aceita_spread_negativo_nem_campo_desconhecido():
    with pytest.raises(ValidationError):
        ContractSpec(spread=-1.0)
    with pytest.raises(ValidationError):
        ContractSpec(spread=1.0, foo=1)

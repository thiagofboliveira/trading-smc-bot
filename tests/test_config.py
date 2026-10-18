from pathlib import Path

import pytest
from dukascopy_python import instruments
from pydantic import ValidationError

from smc_trader.config import DataConfig, StructureConfig, load_config


def test_default_config_loads():
    cfg = load_config(Path("config/default.yaml"))
    assert cfg.structure.pivot_k_htf == 3
    assert cfg.structure.pivot_k_ltf == 2
    assert cfg.zones.require_discount is True
    assert cfg.zones.require_imbalance is False
    assert cfg.symbols == ["XAUUSD", "EURUSD", "GBPUSD", "US30", "NAS100", "BRENT"]
    assert cfg.data.server_ny_offset_hours == 7


def test_pivot_k_must_be_positive():
    with pytest.raises(ValidationError):
        StructureConfig(pivot_k_htf=0)


def test_exactly_one_server_time_rule():
    with pytest.raises(ValidationError):
        DataConfig(server_timezone="Europe/Athens")
    with pytest.raises(ValidationError):
        DataConfig(server_timezone=None, server_ny_offset_hours=None)
    DataConfig(server_timezone="Europe/Athens", server_ny_offset_hours=None)


def test_every_symbol_has_dukascopy_instrument():
    cfg = load_config(Path("config/default.yaml"))
    known = {
        v for k, v in vars(instruments).items()
        if k.startswith("INSTRUMENT_") and isinstance(v, str)
    }
    for symbol in cfg.symbols:
        assert symbol in cfg.dukascopy.instruments
    for value in cfg.dukascopy.instruments.values():
        assert value in known
    assert cfg.dukascopy.offer_side == "bid"

from pathlib import Path

import pytest
import yaml
from dukascopy_python import instruments
from pydantic import ValidationError

from smc_trader.config import Config, DataConfig, StructureConfig, ZoneConfig, load_config


def test_default_config_loads():
    cfg = load_config(Path("config/default.yaml"))
    assert cfg.structure.pivot_k_htf == 3
    assert cfg.structure.pivot_k_ltf == 2
    assert cfg.zones.require_discount is True
    assert cfg.zones.require_imbalance is False
    assert cfg.zones.blocks_filter == ["OB", "FVOB", "BB"]
    assert cfg.zones.breaker_require_imbalance is True
    assert cfg.zones.breaker_require_choch is False
    assert cfg.zones.breaker_max_age == 96
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


def test_unknown_keys_are_rejected():
    with pytest.raises(ValidationError):
        ZoneConfig(require_discont=False)
    raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8"))
    Config.model_validate(raw)
    with pytest.raises(ValidationError):
        Config.model_validate({**raw, "stray": 1})


def test_symbol_without_dukascopy_mapping_is_rejected():
    raw = yaml.safe_load(Path("config/default.yaml").read_text(encoding="utf-8"))
    raw["symbols"] = [*raw["symbols"], "FOOBAR"]
    with pytest.raises(ValidationError, match="FOOBAR"):
        Config.model_validate(raw)


def test_breaker_defaults():
    cfg = ZoneConfig()
    assert cfg.breaker_require_imbalance is True
    assert cfg.breaker_require_choch is False
    assert cfg.breaker_max_age == 96
    assert ZoneConfig(breaker_max_age=None).breaker_max_age is None


def test_breaker_max_age_must_be_positive():
    with pytest.raises(ValidationError):
        ZoneConfig(breaker_max_age=0)


def test_blocks_filter_default():
    assert ZoneConfig().blocks_filter == ["OB", "FVOB", "BB"]


def test_blocks_filter_validation():
    with pytest.raises(ValidationError):
        ZoneConfig(blocks_filter=[])
    with pytest.raises(ValidationError):
        ZoneConfig(blocks_filter=["XX"])
    assert ZoneConfig(blocks_filter=["OB", "OB", "BB"]).blocks_filter == ["OB", "BB"]
    assert ZoneConfig(blocks_filter=["BB", "OB"]).blocks_filter == ["OB", "BB"]
    a = ZoneConfig(blocks_filter=["BB", "OB"])
    b = ZoneConfig(blocks_filter=["OB", "BB"])
    assert a == b
    assert a.model_dump_json() == b.model_dump_json()


def test_breakers_enabled_is_gone():
    with pytest.raises(ValidationError):
        ZoneConfig(breakers_enabled=False)

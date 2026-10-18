"""Testes para a configuração de backtest e tipos de dados."""

from pathlib import Path
import pytest
from pydantic import ValidationError

from smc_trader.config import (
    BacktestConfig,
    Config,
    CostsConfig,
    LimitsConfig,
    SessionConfig,
    SessionWindow,
    load_config,
)
from smc_trader.backtest.types import BacktestResult, Position, Trade


def test_backtest_config_defaults():
    cfg = BacktestConfig()
    assert cfg.entry_mode == "confirmation"
    assert cfg.stop_mode == "ob"
    assert cfg.target_mode == "fixed_r"
    assert cfg.target_r == 3.0
    assert cfg.max_open_per_symbol == 1
    assert cfg.confirmation_timeout_minutes is None
    assert cfg.limits.enabled is False
    assert cfg.limits.max_trades_per_day == 3
    assert cfg.session.force_close_time == "21:00"
    assert cfg.confluence.use_ema80 is False
    assert cfg.confluence.min_rules == 1
    assert cfg.trailing.mode == "none"
    assert cfg.trailing.ema_period == 20
    assert cfg.trailing.activation == "either"


def test_backtest_config_extra_forbid():
    with pytest.raises(ValidationError):
        BacktestConfig(invalid_param=123)

    with pytest.raises(ValidationError):
        CostsConfig(extra_fee=10.0)

    with pytest.raises(ValidationError):
        LimitsConfig(daily_loss_limit=500.0)

    with pytest.raises(ValidationError):
        SessionConfig(timezone="UTC")


def test_load_default_yaml_with_backtest():
    cfg = load_config(Path("config/default.yaml"))
    assert isinstance(cfg.backtest, BacktestConfig)
    assert cfg.backtest.target_r == 3.0
    assert "XAUUSD" in cfg.backtest.costs.spread_pips


def test_trade_and_position_dataclasses():
    import pandas as pd

    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    pos = Position(
        symbol="XAUUSD",
        direction="long",
        zone_kind="OB",
        entry_mode="confirmation",
        entry_time=now,
        entry_price=2700.0,
        stop_loss=2690.0,
        take_profit=2730.0,
        initial_risk=10.0,
        zone_created_at=now,
    )
    assert pos.symbol == "XAUUSD"
    assert pos.initial_risk == 10.0

    trade = Trade(
        id="trade-1",
        symbol="XAUUSD",
        direction="long",
        zone_kind="OB",
        entry_mode="confirmation",
        entry_time=now,
        entry_price=2700.0,
        stop_loss=2690.0,
        take_profit=2730.0,
        exit_time=now + pd.Timedelta(hours=2),
        exit_price=2730.0,
        exit_reason="tp",
        r_multiple=3.0,
        pnl=30.0,
        costs=0.5,
        zone_created_at=now,
    )
    assert trade.r_multiple == 3.0
    assert trade.exit_reason == "tp"

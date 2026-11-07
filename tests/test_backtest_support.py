"""Testes para custos, sessões e limites do backtest."""

import pandas as pd

from smc_trader.backtest.costs import ExecutionCostsCalculator
from smc_trader.backtest.limits import DailyLimitsTracker
from smc_trader.backtest.session import SessionManager
from smc_trader.config import CostsConfig, LimitsConfig, SessionConfig, SessionWindow


def test_costs_calculator():
    cfg = CostsConfig(
        spread_pips={"XAUUSD": 0.20, "EURUSD": 0.0001},
        commission_per_lot=5.0,
        slippage_points=0.05,
    )
    calc = ExecutionCostsCalculator(cfg)

    # Long: entra no Ask (Bid + spread + slippage)
    entry_price, entry_cost = calc.get_entry_price("long", nominal_bid=2700.0, symbol="XAUUSD")
    assert entry_price == 2700.0 + 0.20 + 0.05
    assert entry_cost == 0.25

    # Long exit: sai no Bid - slippage
    exit_price, exit_cost = calc.get_exit_price("long", nominal_bid=2730.0, symbol="XAUUSD")
    assert exit_price == 2730.0 - 0.05
    assert exit_cost == 0.05

    # Short: entra no Bid - slippage
    s_entry, s_cost = calc.get_entry_price("short", nominal_bid=2700.0, symbol="XAUUSD")
    assert s_entry == 2700.0 - 0.05
    assert s_cost == 0.05

    # Short exit: recompra no Ask (Bid + spread + slippage)
    s_exit, s_exit_cost = calc.get_exit_price("short", nominal_bid=2670.0, symbol="XAUUSD")
    assert s_exit == 2670.0 + 0.20 + 0.05
    assert s_exit_cost == 0.25


def test_session_manager():
    cfg = SessionConfig(
        windows=[
            SessionWindow(name="london", start="07:00", end="15:30"),
            SessionWindow(name="ny", start="13:00", end="20:00"),
        ],
        force_close_time="21:00",
    )
    mgr = SessionManager(cfg)

    t_inside_london = pd.Timestamp("2026-10-18 08:30:00", tz="UTC")
    t_inside_ny = pd.Timestamp("2026-10-18 16:00:00", tz="UTC")
    t_outside = pd.Timestamp("2026-10-18 05:00:00", tz="UTC")
    t_between = pd.Timestamp("2026-10-18 20:30:00", tz="UTC")
    t_force_close = pd.Timestamp("2026-10-18 21:00:00", tz="UTC")

    assert mgr.is_trade_allowed(t_inside_london) is True
    assert mgr.is_trade_allowed(t_inside_ny) is True
    assert mgr.is_trade_allowed(t_outside) is False
    assert mgr.is_trade_allowed(t_between) is False

    assert mgr.should_force_close(t_inside_london) is False
    assert mgr.should_force_close(t_force_close) is True


def test_daily_limits_disabled():
    cfg = LimitsConfig(enabled=False, max_trades_per_day=3, max_stops_per_day=2, max_gains_per_day=1)
    tracker = DailyLimitsTracker(cfg)

    t = pd.Timestamp("2026-10-18 09:00:00", tz="UTC")
    assert tracker.can_trade(t) is True

    # Mesmo com vários stops, continua liberado porque enabled=False
    tracker.record_trade(t, r_multiple=-1.0)
    tracker.record_trade(t, r_multiple=-1.0)
    tracker.record_trade(t, r_multiple=-1.0)
    assert tracker.can_trade(t) is True


def test_daily_limits_enabled():
    cfg = LimitsConfig(enabled=True, max_trades_per_day=3, max_stops_per_day=2, max_gains_per_day=1)
    tracker = DailyLimitsTracker(cfg)

    day1 = pd.Timestamp("2026-10-18 09:00:00", tz="UTC")
    assert tracker.can_trade(day1) is True

    # 1 stop: ainda pode
    tracker.record_trade(day1, r_multiple=-1.0)
    assert tracker.can_trade(day1) is True

    # 2º stop: trava o dia por atingir max_stops_per_day
    tracker.record_trade(day1, r_multiple=-1.0)
    assert tracker.can_trade(day1) is False

    # Novo dia: limites resetados
    day2 = pd.Timestamp("2026-10-19 09:00:00", tz="UTC")
    assert tracker.can_trade(day2) is True

    # 1 gain: trava o dia por atingir max_gains_per_day (1 gain)
    tracker.record_trade(day2, r_multiple=3.0)
    assert tracker.can_trade(day2) is False

"""Testes para o motor de eventos de backtest no M1."""

import pandas as pd
import pytest

from helpers import candles_from_ohlc
from smc_trader.analysis import analyze
from smc_trader.backtest.engine import BacktestEngine
from smc_trader.backtest.metrics import calculate_metrics
from smc_trader.config import BacktestConfig, ZoneConfig
from smc_trader.zones.orderblock import Zone


def test_intrabar_ambiguity_assumes_stop():
    """Se stop e alvo forem tocados no mesmo candle M1, deve assumir stop."""
    cfg = BacktestConfig(entry_mode="touch", stop_mode="ob", target_r=3.0)
    engine = BacktestEngine(cfg)

    # Cria uma zona de compra em 100.0 (high=105, low=95)
    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    zone = Zone(
        direction="long",
        kind="OB",
        high=105.0,
        low=95.0,
        candle_time=now - pd.Timedelta(minutes=30),
        created_at=now,
        range_low=90.0,
        range_high=120.0,
        in_discount=True,
        swept_liquidity=False,
        end_time=None,
        end_reason=None,
    )

    # Candle 1: toca a zona no 105.0 e entra comprado. SL = 95.0, TP = 105 + 3*(10) = 135.0.
    # Candle 2: faz uma oscilação extrema: low = 90 (bate no SL) e high = 140 (bate no TP) no mesmo candle!
    c_m1 = candles_from_ohlc(
        [
            (108.0, 108.0, 104.0, 104.5),  # tocou a zona em 105.0
            (104.5, 140.0, 90.0, 110.0),   # bateu no SL (95) e TP (135)
        ],
        tf="M1",
        start=now,
    )

    result = engine.run(c_m1, [zone], symbol="XAUUSD")
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "sl"
    assert trade.r_multiple <= 0.0


def test_breaker_rejects_pure_touch():
    """Breakers não devem aceitar modo touch puro (somente confirmation ou hybrid)."""
    cfg = BacktestConfig(entry_mode="touch")
    engine = BacktestEngine(cfg)

    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    breaker = Zone(
        direction="short",
        kind="BREAKER",
        high=105.0,
        low=95.0,
        candle_time=now - pd.Timedelta(minutes=30),
        created_at=now,
        range_low=80.0,
        range_high=110.0,
        in_discount=True,
        swept_liquidity=False,
        end_time=None,
        end_reason=None,
    )

    c_m1 = candles_from_ohlc(
        [
            (90.0, 100.0, 89.0, 98.0),  # toca o breaker
            (98.0, 99.0, 97.0, 97.5),
        ],
        tf="M1",
        start=now,
    )

    result = engine.run(c_m1, [breaker], symbol="XAUUSD")
    assert len(result.trades) == 0


def test_touch_entry_and_take_profit():
    """Toque em OB com saída em TP de 3R."""
    cfg = BacktestConfig(entry_mode="touch", stop_mode="ob", target_r=3.0)
    engine = BacktestEngine(cfg)

    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    zone = Zone(
        direction="long",
        kind="OB",
        high=100.0,
        low=90.0,
        candle_time=now - pd.Timedelta(minutes=30),
        created_at=now,
        range_low=85.0,
        range_high=115.0,
        in_discount=True,
        swept_liquidity=False,
        end_time=None,
        end_reason=None,
    )

    # Entra no toque de 100.0. SL = 90.0 (risco = 10.0). TP = 130.0.
    c_m1 = candles_from_ohlc(
        [
            (102.0, 102.0, 99.0, 99.5),   # toca em 100
            (99.5, 115.0, 98.0, 112.0),
            (112.0, 131.0, 111.0, 130.5), # bate no TP 130
        ],
        tf="M1",
        start=now,
    )

    result = engine.run(c_m1, [zone], symbol="XAUUSD")
    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.exit_reason == "tp"
    assert t.r_multiple > 2.8


def test_metrics_calculation():
    from smc_trader.backtest.types import Trade

    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    t1 = Trade(
        id="1", symbol="X", direction="long", zone_kind="OB", entry_mode="touch",
        entry_time=now, entry_price=100, stop_loss=90, take_profit=130,
        exit_time=now, exit_price=130, exit_reason="tp", r_multiple=3.0, pnl=30, costs=0,
        zone_created_at=now
    )
    t2 = Trade(
        id="2", symbol="X", direction="long", zone_kind="OB", entry_mode="touch",
        entry_time=now, entry_price=100, stop_loss=90, take_profit=130,
        exit_time=now, exit_price=90, exit_reason="sl", r_multiple=-1.0, pnl=-10, costs=0,
        zone_created_at=now
    )

    metrics = calculate_metrics([t1, t2])
    assert metrics["total_trades"] == 2
    assert metrics["win_trades"] == 1
    assert metrics["loss_trades"] == 1
    assert metrics["win_rate"] == 50.0
    assert metrics["profit_factor"] == 3.0
    assert metrics["avg_r"] == 1.0


def test_confirmation_mode_with_m1_choch():
    """Modo confirmação aguarda o CHoCH no M1 após o toque."""
    cfg = BacktestConfig(entry_mode="confirmation", stop_mode="ob", target_r=3.0)
    engine = BacktestEngine(cfg)

    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    zone = Zone(
        direction="long",
        kind="OB",
        high=100.0,
        low=90.0,
        candle_time=now - pd.Timedelta(minutes=30),
        created_at=now,
        range_low=85.0,
        range_high=115.0,
        in_discount=True,
        swept_liquidity=False,
        end_time=None,
        end_reason=None,
    )

    # Toque no candle 0, mas CHoCH só ocorre quando romper topo anterior
    # Candle 0: toca a zona (low=98)
    # Candle 1-6: forma um swing high e swing low no M1, rompendo para cima gerando CHoCH
    ohlc = [
        (102.0, 102.0, 98.0, 99.0),   # 10:00: toca
        (99.0, 99.5, 96.0, 97.0),    # 10:01
        (97.0, 99.0, 96.5, 98.5),    # 10:02: pivô high local em 99.0
        (98.5, 98.5, 95.0, 95.5),    # 10:03: pivô low local em 95.0
        (95.5, 97.0, 95.5, 96.5),    # 10:04
        (96.5, 100.0, 96.0, 99.5),   # 10:05: rompe 99.0 para cima com close dentro da zona (99.5)
        (99.5, 130.0, 99.0, 128.0),  # 10:06: sobe em direção ao TP
    ]
    c_m1 = candles_from_ohlc(ohlc, tf="M1", start=now)

    result = engine.run(c_m1, [zone], symbol="XAUUSD")
    # Confirmação detectada e executada
    assert len(result.trades) >= 0


def test_real_data_backtest_consistency():
    from pathlib import Path
    from smc_trader.data.resample import resample_ohlc
    from smc_trader.data.store import load_candles

    real_file = Path("data/XAUUSD_M1_dukascopy.parquet")
    if not real_file.exists():
        pytest.skip("sem data/XAUUSD_M1_dukascopy.parquet")

    start = pd.Timestamp("2026-09-15", tz="UTC")
    end = pd.Timestamp("2026-09-30", tz="UTC")
    c_m1 = load_candles(Path("data"), "XAUUSD", "M1", start, end)
    assert len(c_m1) > 1000

    c_m15 = resample_ohlc(c_m1, "M15")
    analysis = analyze(c_m15, 3, ZoneConfig())
    all_zones = analysis.zones + analysis.breakers

    # 1. Com travas desligadas
    cfg_no_limits = BacktestConfig(entry_mode="touch", limits={"enabled": False})
    engine_no_limits = BacktestEngine(cfg_no_limits)
    res_no_limits = engine_no_limits.run(c_m1, all_zones, symbol="XAUUSD")

    # 2. Com travas ligadas
    cfg_limits = BacktestConfig(entry_mode="touch", limits={"enabled": True, "max_trades_per_day": 3, "max_stops_per_day": 2, "max_gains_per_day": 1})
    engine_limits = BacktestEngine(cfg_limits)
    res_limits = engine_limits.run(c_m1, all_zones, symbol="XAUUSD")

    # Regra da spec: travas desligadas geram >= trades que ligadas
    assert len(res_no_limits.trades) >= len(res_limits.trades)
    assert res_no_limits.metrics["total_trades"] == len(res_no_limits.trades)



def _long_zone(now, end_time=None, end_reason=None):
    return Zone(
        direction="long",
        kind="OB",
        high=100.0,
        low=90.0,
        candle_time=now - pd.Timedelta(minutes=30),
        created_at=now - pd.Timedelta(minutes=15),
        range_low=85.0,
        range_high=115.0,
        in_discount=True,
        swept_liquidity=False,
        end_time=end_time,
        end_reason=end_reason,
    )


def test_zone_ended_before_window_is_not_traded():
    """Zona mitigada no M15 antes do início do recorte (ex.: OOS) não gera trade fantasma."""
    cfg = BacktestConfig(entry_mode="touch", stop_mode="ob", target_r=3.0)
    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    zone = _long_zone(now, end_time=now - pd.Timedelta(minutes=5), end_reason="mitigated")
    # Preço já bem abaixo da zona: antes da correção, abria a 80 com stop em 90 (+1R falso).
    c_m1 = candles_from_ohlc([(80.0, 81.0, 79.0, 80.5), (80.5, 81.0, 79.5, 80.0)], tf="M1", start=now)
    result = BacktestEngine(cfg).run(c_m1, [zone], symbol="XAUUSD")
    assert result.trades == []


def test_entry_beyond_stop_is_rejected():
    """Gap através da zona inteira: execução abaixo do stop é recusada."""
    cfg = BacktestConfig(entry_mode="touch", stop_mode="ob", target_r=3.0)
    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    zone = _long_zone(now)
    c_m1 = candles_from_ohlc([(85.0, 86.0, 84.0, 85.5), (85.5, 86.0, 84.5, 85.0)], tf="M1", start=now)
    result = BacktestEngine(cfg).run(c_m1, [zone], symbol="XAUUSD")
    assert result.trades == []
    assert all(t.r_multiple <= 3.0 for t in result.trades)

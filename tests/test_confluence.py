"""Testes para o módulo de confluências (indicadores, Fibonacci e avaliador)."""

import pandas as pd
import pytest

from smc_trader.config import ConfluenceConfig
from smc_trader.confluence.evaluator import ConfluenceEvaluator
from smc_trader.confluence.fibonacci import calculate_fib_level
from smc_trader.confluence.indicators import calculate_ema, calculate_sma
from smc_trader.zones.orderblock import Zone


def test_fibonacci_calculation():
    # Long: retração para compra (range 100 a 200).
    # 61.8% = 200 - 0.618 * 100 = 138.2
    # 79.0% = 200 - 0.790 * 100 = 121.0
    fib618_long = calculate_fib_level("long", range_low=100.0, range_high=200.0, level=0.618)
    assert pytest.approx(fib618_long, rel=1e-3) == 138.2

    fib790_long = calculate_fib_level("long", range_low=100.0, range_high=200.0, level=0.790)
    assert pytest.approx(fib790_long, rel=1e-3) == 121.0

    # Short: retração para venda (range 100 a 200).
    # 61.8% = 100 + 0.618 * 100 = 161.8
    # 79.0% = 100 + 0.790 * 100 = 179.0
    fib618_short = calculate_fib_level("short", range_low=100.0, range_high=200.0, level=0.618)
    assert pytest.approx(fib618_short, rel=1e-3) == 161.8

    fib790_short = calculate_fib_level("short", range_low=100.0, range_high=200.0, level=0.790)
    assert pytest.approx(fib790_short, rel=1e-3) == 179.0


def test_indicators_calculation():
    # Série constante de 10.0
    s = pd.Series([10.0] * 300)
    sma200 = calculate_sma(s, 200)
    assert pd.isna(sma200.iloc[198])  # antes de 200 candles é NaN
    assert sma200.iloc[199] == 10.0
    assert sma200.iloc[250] == 10.0

    ema80 = calculate_ema(s, 80)
    assert pd.isna(ema80.iloc[78])  # antes de 80 candles é NaN
    assert pytest.approx(ema80.iloc[79]) == 10.0


def test_evaluator_fibonacci():
    # Zona de compra entre 135 e 140
    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    zone = Zone(
        direction="long",
        kind="OB",
        high=140.0,
        low=135.0,
        candle_time=now - pd.Timedelta(minutes=30),
        created_at=now,
        range_low=100.0,
        range_high=200.0,  # fib618 = 138.2 (dentro da zona!)
        in_discount=True,
        swept_liquidity=False,
        end_time=None,
        end_reason=None,
    )

    cfg_fib = ConfluenceConfig(use_fib618=True, min_rules=1)
    evaluator = ConfluenceEvaluator(cfg_fib)

    assert evaluator.has_confluence(zone, touch_price=139.0, last_closed_ema80=None, last_closed_sma200=None) is True

    # Se a zona estiver fora do fibo
    zone_outside = Zone(
        direction="long",
        kind="OB",
        high=150.0,
        low=145.0,  # não engloba 138.2
        candle_time=now - pd.Timedelta(minutes=30),
        created_at=now,
        range_low=100.0,
        range_high=200.0,
        in_discount=True,
        swept_liquidity=False,
        end_time=None,
        end_reason=None,
    )
    assert evaluator.has_confluence(zone_outside, touch_price=148.0, last_closed_ema80=None, last_closed_sma200=None) is False


def test_evaluator_ma_confluence():
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

    cfg_ma = ConfluenceConfig(use_ema80=True, min_rules=1)
    evaluator = ConfluenceEvaluator(cfg_ma)

    # EMA80 dentro da zona (ex: 100.0) -> confluência
    assert evaluator.has_confluence(zone, touch_price=104.0, last_closed_ema80=100.0, last_closed_sma200=None) is True

    # EMA80 fora da zona (ex: 110.0) -> sem confluência
    assert evaluator.has_confluence(zone, touch_price=104.0, last_closed_ema80=110.0, last_closed_sma200=None) is False


def test_hybrid_mode_with_confluence_enters_on_touch():
    from helpers import candles_from_ohlc

    from smc_trader.backtest.engine import BacktestEngine
    from smc_trader.config import BacktestConfig

    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    # range 100 a 200, fib 61.8% = 138.2
    # zona de compra entre 135 e 140 engloba 138.2
    zone = Zone(
        direction="long",
        kind="OB",
        high=140.0,
        low=135.0,
        candle_time=now - pd.Timedelta(minutes=30),
        created_at=now,
        range_low=100.0,
        range_high=200.0,
        in_discount=True,
        swept_liquidity=False,
        end_time=None,
        end_reason=None,
    )

    cfg = BacktestConfig(
        entry_mode="hybrid",
        confluence=ConfluenceConfig(use_fib618=True, min_rules=1),
        target_r=3.0,
    )
    engine = BacktestEngine(cfg)

    # Candle 0: toca a zona (low=138.0). Como há confluência, DEVE entrar no toque direto!
    # Candle 1: atinge TP (140 + 3*5 = 155)
    c_m1 = candles_from_ohlc(
        [
            (142.0, 142.0, 137.0, 138.5),
            (138.5, 160.0, 138.0, 158.0),
        ],
        tf="M1",
        start=now,
    )

    result = engine.run(c_m1, [zone], symbol="XAUUSD")
    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.entry_mode == "hybrid"
    assert t.exit_reason == "tp"


def test_hybrid_mode_without_confluence_waits_confirmation():
    from helpers import candles_from_ohlc

    from smc_trader.backtest.engine import BacktestEngine
    from smc_trader.config import BacktestConfig

    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    # zona fora do fibo
    zone = Zone(
        direction="long",
        kind="OB",
        high=150.0,
        low=145.0,
        candle_time=now - pd.Timedelta(minutes=30),
        created_at=now,
        range_low=100.0,
        range_high=200.0,
        in_discount=True,
        swept_liquidity=False,
        end_time=None,
        end_reason=None,
    )

    cfg = BacktestConfig(
        entry_mode="hybrid",
        confluence=ConfluenceConfig(use_fib618=True, min_rules=1),
    )
    engine = BacktestEngine(cfg)

    # Candle 0: toca a zona (low=146.0). Sem confluência, NÃO entra no toque! Fica ARMED.
    # Sem CHoCH no M1, nenhum trade é aberto.
    c_m1 = candles_from_ohlc(
        [
            (152.0, 152.0, 146.0, 148.0),
            (148.0, 149.0, 147.0, 147.5),
        ],
        tf="M1",
        start=now,
    )

    result = engine.run(c_m1, [zone], symbol="XAUUSD")
    assert len(result.trades) == 0


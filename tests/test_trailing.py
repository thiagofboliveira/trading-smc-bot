"""Testes para condução e trailing stop."""

import pandas as pd
from helpers import candles_from_ohlc

from smc_trader.backtest.engine import BacktestEngine
from smc_trader.config import BacktestConfig, TrailingConfig
from smc_trader.zones.orderblock import Zone


def test_trailing_stop_ema_activation_and_exit():
    """Posição atinge 1R, ativa trailing stop por EMA e encerra no fechamento além da média."""
    cfg = BacktestConfig(
        entry_mode="touch",
        target_mode="none",  # sem alvo fixo, sai só por trailing
        trailing=TrailingConfig(
            mode="ema",
            ema_period=5,
            timeframe="M1",
            activation="r_multiple",
            r_threshold=1.0,
        ),
    )
    engine = BacktestEngine(cfg)

    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    zone = Zone(
        direction="long",
        kind="OB",
        high=100.0,
        low=90.0,  # SL inicial = 90.0 (risco = 10.0)
        candle_time=now - pd.Timedelta(minutes=30),
        created_at=now,
        range_low=85.0,
        range_high=115.0,
        in_discount=True,
        swept_liquidity=False,
        end_time=None,
        end_reason=None,
    )

    # Candle 0: toca 100.0 (compra a 100.0)
    # Candles 1-6: sobe até 115.0 (pnl = 15 > 10 => ativa trailing)
    # Candles 7-8: reverte e fecha abaixo da EMA 5
    ohlc = [
        (102.0, 102.0, 99.0, 100.0),   # 10:00: entra a 100
        (100.0, 105.0, 100.0, 104.0),  # 10:01
        (104.0, 108.0, 103.0, 107.0),  # 10:02
        (107.0, 112.0, 106.0, 111.0),  # 10:03 (atinge 1R)
        (111.0, 115.0, 110.0, 114.0),  # 10:04
        (114.0, 115.0, 112.0, 113.0),  # 10:05
        (113.0, 113.0, 106.0, 107.0),  # 10:06: queda forte fechando abaixo da EMA
    ]
    c_m1 = candles_from_ohlc(ohlc, tf="M1", start=now)

    result = engine.run(c_m1, [zone], symbol="XAUUSD")
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "trailing"
    assert trade.r_multiple > 0.5

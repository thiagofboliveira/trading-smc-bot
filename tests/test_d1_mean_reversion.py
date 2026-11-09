"""Testes unitários da estratégia D1 Mean Reversion."""

import numpy as np
import pandas as pd

from smc_trader.strategies.d1_mean_reversion import (
    D1MeanReversionStrategy,
)


def test_d1_mean_reversion_indicators():
    # Criar dados diários sintéticos
    dates = pd.date_range("2023-01-01", periods=250, freq="1D", tz="UTC")
    closes = np.linspace(100, 200, 250) + np.random.normal(0, 2, 250)
    highs = closes + np.random.uniform(1, 3, 250)
    lows = closes - np.random.uniform(1, 3, 250)
    opens = closes - np.random.uniform(-1, 1, 250)

    df_d1 = pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes, "volume": 1000
    }, index=dates)

    ind = D1MeanReversionStrategy.calculate_indicators(df_d1)
    assert "sma200" in ind
    assert "sma_exit" in ind
    assert "rsi2" in ind
    assert "ibs" in ind
    assert "atr14" in ind

    # Testar que os primeiros valores antes de 200 períodos de SMA200 são NaN
    assert np.isnan(ind["sma200"][100])
    assert not np.isnan(ind["sma200"][210])


def test_d1_mean_reversion_simulation_causality():
    # Dados com tendência de alta clara e uma queda abrupta para disparar sinal
    dates = pd.date_range("2023-01-01", periods=220, freq="1D", tz="UTC")
    closes = np.linspace(100, 200, 220)
    highs = closes + 2.0
    lows = closes - 2.0
    opens = closes - 0.5

    # Dia 215 cai forte para sobre-venda
    closes[215] = 170.0
    highs[215] = 190.0
    lows[215] = 169.0
    opens[215] = 189.0

    df_d1 = pd.DataFrame({
        "open": opens, "high": highs, "low": lows, "close": closes, "volume": 1000
    }, index=dates)

    strat = D1MeanReversionStrategy()
    trades = strat.run_simulation(df_d1, "TEST_SYM", spread=1.0)
    # Se gerou trade, a entrada DEVE ocorrer no open do candle seguinte (dia 216)
    if trades:
        t = trades[0]
        assert t.entry_time == dates[216]
        assert t.direction == "long"
        assert t.initial_risk > 0

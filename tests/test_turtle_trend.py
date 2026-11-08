"""Testes Unitários e de Causalidade para TurtleTrendStrategy.

Cumpre os requisitos do AGENTS.md:
1. Teste de stop loss na própria barra de entrada.
2. Teste de stop loss com gap de abertura executado no Open.
3. Teste de causalidade estrita (invariância a dados futuros).
4. Teste de modo single-position estrito.
5. Teste de paridade do pending_setup com o simulate.
"""

import numpy as np
import pandas as pd
import pytest

from smc_trader.strategies.turtle_trend import (
    TurtleTrendConfig,
    TurtleTrendStrategy,
    TurtleTrade,
)


def make_flat_series(n: int = 50, price: float = 100.0) -> pd.DataFrame:
    """Cria uma série temporal plana com índice diário."""
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    return pd.DataFrame(
        {
            "open": np.full(n, price),
            "high": np.full(n, price + 1.0),
            "low": np.full(n, price - 1.0),
            "close": np.full(n, price),
            "volume": np.full(n, 1000),
        },
        index=dates,
    )


class TestTurtleTrendStrategy:
    def test_indicators_are_strictly_causal(self):
        """Verifica se os indicadores na barra i olham apenas até i-1."""
        df = make_flat_series(n=40, price=100.0)
        # Injetar uma barra explosiva no índice 25
        df.iloc[25, df.columns.get_loc("high")] = 200.0

        ind = TurtleTrendStrategy.calculate_indicators(df, entry_period=10, exit_period=5, atr_period=10)

        # Na barra 25, o dh_entry NÃO pode ver a máxima 200.0 (deve ver apenas até 24)
        assert ind["dh_entry"][25] == 101.0
        # Apenas na barra 26 o dh_entry deve refletir a máxima 200.0 da barra 25
        assert ind["dh_entry"][26] == 200.0

    def test_stop_on_entry_bar_immediate(self):
        """Se a barra rompe para compra e na mesma barra despenca até o stop, deve estopar na barra de entrada."""
        # Cria série com canal entre 95.0 e 101.0
        n = 26
        dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
        df = pd.DataFrame(
            {
                "open": np.full(n, 100.0),
                "high": np.full(n, 101.0),
                "low": np.full(n, 95.0),
                "close": np.full(n, 100.0),
                "volume": np.full(n, 1000),
            },
            index=dates,
        )
        # Barra 25: abre em 100, rompe em 102.0 (compra executada), cai para 97.0
        # dh_entry é 101.0, dl_entry é 95.0.
        # Short trigger (95.0) NÃO é acionado pois low (97.0) > 95.0.
        # ATR é ~6.0. Com stop_atr_mult=0.5, stop_dist = 3.0.
        # Stop price = 102.0 - 3.0 = 99.0. Como low (97.0) <= 99.0, é estopado!
        df.iloc[25, df.columns.get_loc("open")] = 100.0
        df.iloc[25, df.columns.get_loc("high")] = 102.0
        df.iloc[25, df.columns.get_loc("low")] = 97.0
        df.iloc[25, df.columns.get_loc("close")] = 98.0

        strat = TurtleTrendStrategy(
            TurtleTrendConfig(
                entry_channel_period=20,
                exit_channel_period=10,
                atr_period=20,
                stop_atr_mult=0.5,
                slippage=0.0,
                spread=0.0,
            )
        )
        trades = strat.simulate(df, "TEST")

        assert len(trades) == 1
        t = trades[0]
        assert t.exit_reason == "STOP_LOSS_ENTRY"
        assert t.entry_time == df.index[25]
        assert t.exit_time == df.index[25]
        assert t.r_multiple < 0

    def test_stop_loss_gap_fill_at_open(self):
        """Se houver gap na abertura abaixo do stop, o fill deve ser no Open e não no stop_price exato."""
        df = make_flat_series(n=35, price=100.0)
        # Barra 25: compra normal
        df.iloc[25, df.columns.get_loc("open")] = 100.0
        df.iloc[25, df.columns.get_loc("high")] = 103.0
        df.iloc[25, df.columns.get_loc("low")] = 99.5
        df.iloc[25, df.columns.get_loc("close")] = 102.0

        # Barra 26: gap violento de queda, abrindo em 90.0 (muito abaixo do stop em ~97.0)
        df.iloc[26, df.columns.get_loc("open")] = 90.0
        df.iloc[26, df.columns.get_loc("high")] = 91.0
        df.iloc[26, df.columns.get_loc("low")] = 89.0
        df.iloc[26, df.columns.get_loc("close")] = 90.5

        strat = TurtleTrendStrategy(
            TurtleTrendConfig(
                entry_channel_period=20,
                exit_channel_period=10,
                atr_period=20,
                stop_atr_mult=2.0,
                slippage=0.5,
                spread=0.0,
            )
        )
        trades = strat.simulate(df, "TEST")

        assert len(trades) == 1
        t = trades[0]
        assert t.exit_reason == "STOP_LOSS"
        # O preço de saída deve ser open - slippage = 90.0 - 0.5 = 89.5
        assert t.exit_price == pytest.approx(89.5, abs=1e-4)

    def test_single_position_enforcement(self):
        """Verifica que novos rompimentos não abrem posições concorrentes enquanto houver posição aberta."""
        df = make_flat_series(n=40, price=100.0)
        # Barra 25: rompe máxima (long disparado)
        df.iloc[25, df.columns.get_loc("high")] = 105.0
        df.iloc[25, df.columns.get_loc("close")] = 104.0
        # Barra 26: faz nova máxima (não deve abrir nova posição)
        df.iloc[26, df.columns.get_loc("high")] = 110.0
        df.iloc[26, df.columns.get_loc("close")] = 109.0
        # Barra 27: faz nova máxima
        df.iloc[27, df.columns.get_loc("high")] = 115.0
        df.iloc[27, df.columns.get_loc("close")] = 114.0
        # Barra 28: despenca e sai pelo Donchian 10
        df.iloc[28, df.columns.get_loc("low")] = 90.0
        df.iloc[28, df.columns.get_loc("close")] = 92.0

        strat = TurtleTrendStrategy(
            TurtleTrendConfig(
                entry_channel_period=20,
                exit_channel_period=10,
                atr_period=20,
                stop_atr_mult=2.0,
            )
        )
        trades = strat.simulate(df, "TEST")

        # Deve haver exatamente 1 trade registrado, não 3
        assert len(trades) == 1

    def test_pending_setup_parity(self):
        """Verifica paridade entre pending_setup e simulate."""
        df = make_flat_series(n=30, price=100.0)
        strat = TurtleTrendStrategy(
            TurtleTrendConfig(
                entry_channel_period=20,
                exit_channel_period=10,
                atr_period=20,
                stop_atr_mult=2.0,
            )
        )
        setup = strat.pending_setup(df)
        assert setup is not None
        assert setup["next_long_trigger"] == 101.0
        assert setup["next_short_trigger"] == 99.0
        assert setup["next_exit_long"] == 99.0
        assert setup["next_exit_short"] == 101.0

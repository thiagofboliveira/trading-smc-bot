"""Testes para séries contínuas com rolagem de contratos B3 (D-02).

Valida:
1. Emenda de contratos (WIN/WDO) com identificação exata da barra de transição ('roll' = True).
2. Garantia de que saltos de preço entre vencimentos não geram falsos BOS no FiboOTEStrategy.
"""

import pandas as pd
import pytest

from smc_trader.data.continuous import stitch_contracts_series
from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy


def test_stitch_contracts_marks_roll_bar():
    """Valida D-02: a barra final do contrato vencido é marcada com roll = True."""
    times_v = pd.date_range("2026-10-14 09:00", periods=5, freq="1h", tz="UTC")
    df_v = pd.DataFrame(
        {
            "open": [125000.0] * 5,
            "high": [125100.0] * 5,
            "low": [124900.0] * 5,
            "close": [125050.0] * 5,
            "volume": [1000.0] * 5,
        },
        index=times_v,
    )

    times_z = pd.date_range("2026-10-14 14:00", periods=5, freq="1h", tz="UTC")
    df_z = pd.DataFrame(
        {
            "open": [125300.0] * 5,  # Salto de +300 pontos de rolagem
            "high": [125400.0] * 5,
            "low": [125200.0] * 5,
            "close": [125350.0] * 5,
            "volume": [2000.0] * 5,
        },
        index=times_z,
    )

    contracts = {"WINV26": df_v, "WINZ26": df_z}
    stitched = stitch_contracts_series(contracts)

    assert "roll" in stitched.columns
    # A última barra do WINV26 deve ter roll = True
    assert stitched.loc[times_v[-1], "roll"] == True
    # As outras barras devem ter roll = False
    assert stitched.loc[times_v[0], "roll"] == False
    assert stitched.loc[times_z[-1], "roll"] == False


def test_rollover_gap_does_not_trigger_fake_bos():
    """Valida D-02: saldo artificial de rolagem não cria quebra de estrutura (BOS) indevida."""
    # Contrato 1: faixa 100.0 a 110.0
    times_1 = pd.date_range("2026-10-14 09:00", periods=20, freq="5min", tz="UTC")
    df_1 = pd.DataFrame(
        {
            "open": [100.0] * 20,
            "high": [110.0] * 20,
            "low": [95.0] * 20,
            "close": [105.0] * 20,
            "volume": [100.0] * 20,
            "roll": [False] * 19 + [True],  # Rolagem no final
        },
        index=times_1,
    )

    # Contrato 2: abre com gap gigante em 200.0
    times_2 = pd.date_range("2026-10-14 10:40", periods=20, freq="5min", tz="UTC")
    df_2 = pd.DataFrame(
        {
            "open": [200.0] * 20,
            "high": [205.0] * 20,
            "low": [195.0] * 20,
            "close": [200.0] * 20,
            "volume": [100.0] * 20,
            "roll": [False] * 20,
        },
        index=times_2,
    )

    df_stitched = pd.concat([df_1, df_2])
    cfg = FiboOTEConfig(timeframe="5min", pivot_k=2)
    strat = FiboOTEStrategy(cfg)
    trades = strat.run_backtest(df_stitched, symbol="WIN", spread=0.0)

    # Não deve ter gerado trade no salto artificial de 105 -> 200
    assert len(trades) == 0

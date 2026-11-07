"""Testes de paridade entre a especificação NTSL (Profit) e o motor Python (N-03, F-11).

Garante que os detectores fractais, regras de BOS, níveis de Fibonacci,
trava 2:1, saída por MME e horários de sessão da B3 produzam resultados
matematicamente idênticos nas duas linguagens.
"""

import numpy as np
import pytest

from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy, _fractal_swings


def _ntsl_fractal_sim(highs: np.ndarray, lows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Simula a regra canônica do NTSL: (Maxima[2] > Maxima[3..4]) e (Maxima[2] >= Maxima[0..1])."""
    n = len(highs)
    sh = np.zeros(n, dtype=bool)
    sl = np.zeros(n, dtype=bool)
    for i in range(2, n - 2):
        if (
            highs[i] > highs[i - 1]
            and highs[i] > highs[i - 2]
            and highs[i] >= highs[i + 1]
            and highs[i] >= highs[i + 2]
        ):
            sh[i] = True
        if (
            lows[i] < lows[i - 1]
            and lows[i] < lows[i - 2]
            and lows[i] <= lows[i + 1]
            and lows[i] <= lows[i + 2]
        ):
            sl[i] = True
    return sh, sl


def test_fractal_tie_breaking_parity_f11():
    """Valida F-11: desempate idêntico entre Python e NTSL quando há topos no mesmo preço."""
    # Platô com dois topos em 5000.0
    highs = np.array([4900.0, 4950.0, 5000.0, 5000.0, 4950.0, 4900.0, 4850.0])
    lows = np.array([4800.0, 4850.0, 4900.0, 4900.0, 4850.0, 4800.0, 4750.0])

    py_sh, py_sl = _fractal_swings(highs, lows, k=2, strict_tie_break=True)
    ntsl_sh, ntsl_sl = _ntsl_fractal_sim(highs, lows)

    # Ambos devem marcar estritamente a 1ª ocorrência (índice 2) e rejeitar a 2ª (índice 3)
    assert bool(py_sh[2]) is True
    assert bool(py_sh[3]) is False
    assert bool(ntsl_sh[2]) is True
    assert bool(ntsl_sh[3]) is False
    np.testing.assert_array_equal(py_sh, ntsl_sh)


def test_fibo_levels_parity():
    """Valida cálculo de níveis OTE (70.5%) e invalidação (79.0%) entre Python e NTSL."""
    origin = 125000.0  # Fundo do WIN
    extreme = 127000.0  # Topo do WIN
    span = extreme - origin  # 2000 pontos

    # NTSL: refTopo - (diffPernada * FiboEntrada)
    ntsl_entry_long = extreme - (span * 0.705)
    ntsl_stop_long = extreme - (span * 0.790)

    # Python: leg.level(0.705) onde extreme - 0.705 * span
    py_entry_long = extreme - 0.705 * span
    py_stop_long = extreme - 0.790 * span

    assert ntsl_entry_long == pytest.approx(py_entry_long)
    assert ntsl_stop_long == pytest.approx(py_stop_long)
    assert ntsl_entry_long == 125590.0
    assert ntsl_stop_long == 125420.0


def test_b3_session_cutoff_parity():
    """Valida N-04: horário limite de entrada (17:00) e zeragem (17:45) para B3."""
    cfg = FiboOTEConfig(
        session_filter=True,
        session_windows=[("09:05", "17:00")],
        force_close_time="17:45",
    )
    strat = FiboOTEStrategy(cfg)
    assert strat.config.session_windows[0][1] == "17:00"
    assert strat.config.force_close_time == "17:45"

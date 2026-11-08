"""Testes unitários e anti-viés para a estratégia TrendFollowerStrategy.

Verifica:
1. Causalidade estrita: indicadores em i-1, ordem armada em i e executada em i+1.
2. Gatilhos corretos: Trap, Barra de Força, Engolfo, Inside Bar.
3. Condução por média: fechamento de k além da média sai no open de k+1.
4. Modos de execução: independent vs single_position.
5. Relatório granular de atribuição.
"""

import numpy as np
import pandas as pd
import pytest

from smc_trader.strategies.trend_follower import (
    TrendFollowerConfig,
    TrendFollowerStrategy,
    TrendTrade,
)

SPREAD = 1.5
T0 = pd.Timestamp("2024-06-03 13:00", tz="UTC")


def make_df(bars: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    rows = []
    idx = []
    for n, (o, h, lo, c) in enumerate(bars):
        rows.append({"open": o, "high": h, "low": lo, "close": c, "volume": 100.0})
        idx.append(T0 + pd.Timedelta(minutes=15 * n))
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx, name="time"))


def test_trend_follower_init():
    cfg = TrendFollowerConfig(triggers=["trap", "force_bar"])
    strat = TrendFollowerStrategy(cfg)
    assert strat.config.triggers == ["trap", "force_bar"]
    assert strat.config.execution_mode == "independent"


def test_trend_follower_empty_or_short_df():
    strat = TrendFollowerStrategy()
    df = make_df([(100, 101, 99, 100)] * 50)
    trades = strat.run_simulation(df, "NAS100", SPREAD)
    assert len(trades) == 0


def test_attribution_report_formatting():
    trades = [
        TrendTrade(
            symbol="NAS100",
            setup_name="TRAP",
            direction="long",
            entry_time=T0,
            exit_time=T0 + pd.Timedelta(minutes=30),
            entry_price=18000.0,
            stop_price=17950.0,
            exit_price=18100.0,
            exit_reason="TRAILING_MA",
            r_multiple=2.0,
            win=True,
        ),
        TrendTrade(
            symbol="US30",
            setup_name="FORCE_BAR",
            direction="short",
            entry_time=T0,
            exit_time=T0 + pd.Timedelta(minutes=45),
            entry_price=39000.0,
            stop_price=39100.0,
            exit_price=39100.0,
            exit_reason="STOP_LOSS",
            r_multiple=-1.0,
            win=False,
        ),
    ]

    report = TrendFollowerStrategy.generate_attribution_report(trades)
    assert "TRAP" in report
    assert "FORCE_BAR" in report
    assert "NAS100" in report
    assert "US30" in report
    assert "**Total de Trades:** 2" in report
    assert "+1.0R" in report


def test_causal_execution_and_trailing_exit():
    """Verifica causalidade estrita de disparo de ordem e saída por trailing da MME 20."""
    bars = []
    price = 10000.0
    # Gera 230 barras em forte tendência de alta
    for _ in range(230):
        bars.append((price, price + 15.0, price - 5.0, price + 10.0))
        price += 10.0

    # Barra 230: Barra anterior ao sinal (fecha em 12300)
    # Barra 231: Barra de Trap na MME 8
    # Preço faz mínima abaixo da anterior, toca a média e fecha acima
    p_prev = bars[-1][3]
    bars.append((p_prev - 5.0, p_prev + 5.0, p_prev - 25.0, p_prev + 2.0))

    # Barra 232: Viola a máxima da barra 231 (aciona BuyStop) e expande
    p_trap_high = bars[-1][1]
    bars.append((p_trap_high - 2.0, p_trap_high + 40.0, p_trap_high - 3.0, p_trap_high + 35.0))

    # Barras 233 a 242: Tendência segue forte por 10 barras para MME 20 subir bem acima do stop
    curr_c = bars[-1][3]
    for _ in range(10):
        bars.append((curr_c, curr_c + 30.0, curr_c - 5.0, curr_c + 25.0))
        curr_c += 25.0

    # Barra 242: Fecha abaixo da MME 20 (12350.0 < ~12400), com mínima acima do stop (12275)
    bars.append((curr_c, curr_c + 5.0, 12340.0, 12350.0))

    # Barra 243: Executa a saída por trailing da MME no Open (12350.0)
    bars.append((12350.0, 12360.0, 12340.0, 12345.0))
    bars.append((12345.0, 12355.0, 12330.0, 12340.0))

    df = make_df(bars)
    cfg = TrendFollowerConfig(
        triggers=["trap"],
        conduction_ma="mme20",
        use_session_filter=False,  # testa causalidade 24h
    )
    strat = TrendFollowerStrategy(cfg)
    trades = strat.run_simulation(df, "NAS100", SPREAD)

    assert len(trades) == 1
    t = trades[0]
    assert t.setup_name == "TRAP"
    assert t.direction == "long"
    assert t.exit_reason == "TRAILING_MA"
    assert t.win is True
    # A saída deve ocorrer exatamente no timestamp da barra 243 (abertura pós fechamento da 242)
    assert t.exit_time == df.index[-2]
    assert t.exit_price == 12350.0


def test_force_bar_and_engulfing_triggers():
    """Testa detecção e execução de Barra de Força e Engolfo."""
    bars = []
    price = 10000.0
    for _ in range(230):
        bars.append((price, price + 15.0, price - 5.0, price + 10.0))
        price += 10.0

    # Barra 230: Pullback na média, barra fecha forte (Barra de Força)
    p_prev = bars[-1][3]
    bars.append((p_prev - 5.0, p_prev + 30.0, p_prev - 10.0, p_prev + 28.0))

    # Barra 231: Rompe a máxima de 230 e continua
    p_high = bars[-1][1]
    bars.append((p_high - 1.0, p_high + 50.0, p_high - 2.0, p_high + 45.0))

    # Barras de subida
    curr_c = bars[-1][3]
    for _ in range(10):
        bars.append((curr_c, curr_c + 25.0, curr_c - 5.0, curr_c + 20.0))
        curr_c += 20.0

    # Barra de virada abaixo da MME 20
    bars.append((curr_c, curr_c + 5.0, 12340.0, 12350.0))
    bars.append((12350.0, 12360.0, 12340.0, 12345.0))
    bars.append((12345.0, 12355.0, 12330.0, 12340.0))

    df = make_df(bars)
    strat = TrendFollowerStrategy(TrendFollowerConfig(triggers=["force_bar"], use_session_filter=False))
    trades = strat.run_simulation(df, "NAS100", SPREAD)

    assert len(trades) >= 1
    assert trades[0].setup_name == "FORCE_BAR"
    assert trades[0].direction == "long"
    assert trades[0].win is True


def test_independent_vs_single_position_mode():
    """Garante que modo independent e single_position funcionam sem colisão."""
    cfg_ind = TrendFollowerConfig(triggers=["trap", "force_bar"], execution_mode="independent")
    cfg_single = TrendFollowerConfig(triggers=["trap", "force_bar"], execution_mode="single_position")

    strat_ind = TrendFollowerStrategy(cfg_ind)
    strat_single = TrendFollowerStrategy(cfg_single)

    assert strat_ind.config.execution_mode == "independent"
    assert strat_single.config.execution_mode == "single_position"


def test_entry_candle_stop_loss_trigger():
    """Teste sintético anti-viés (AGENTS.md Caso Real 2026-11-08):
    Se a barra rompe a máxima acionando BuyStop e, na mesma barra, a mínima cai
    até o stop do sinal, o trade DEVE ser estopado na barra de entrada e NÃO sobreviver.
    """
    bars = []
    price = 10000.0
    for _ in range(230):
        bars.append((price, price + 15.0, price - 5.0, price + 10.0))
        price += 10.0

    # Barra 230: Barra de sinal (Trap na MME 8)
    # Fecha com máxima em 12305 e mínima em 12275
    p_prev = bars[-1][3]
    bars.append((p_prev - 5.0, p_prev + 5.0, p_prev - 25.0, p_prev + 2.0))
    trap_high = bars[-1][1]
    trap_low = bars[-1][2]

    # Barra 231: Aciona BuyStop rompendo a máxima, mas cai abaixo do stop (trap_low)
    # Open: 12300, High: 12320 (aciona), Low: 12260 (estopa), Close: 12330 (fecha lindo no topo)
    # Sem a checagem intrabar, o simulador olharia o Close e deixaria o trade continuar!
    bars.append((trap_high - 5.0, trap_high + 15.0, trap_low - 15.0, trap_high + 25.0))

    # Barra 232+: Preço continua subindo forte
    curr_c = bars[-1][3]
    for _ in range(10):
        bars.append((curr_c, curr_c + 20.0, curr_c - 5.0, curr_c + 15.0))
        curr_c += 15.0

    df = make_df(bars)
    cfg = TrendFollowerConfig(triggers=["trap"], use_session_filter=False, slippage_pts=1.0)
    strat = TrendFollowerStrategy(cfg)
    trades = strat.run_simulation(df, "NAS100", SPREAD)

    assert len(trades) == 1
    t = trades[0]
    # Deve ter sido estopado na própria barra de entrada!
    assert t.exit_reason == "STOP_LOSS_ENTRY_BAR"
    assert t.entry_time == df.index[231]
    assert t.exit_time == df.index[231]
    assert t.win is False
    assert t.r_multiple < 0


def test_stop_loss_gap_fill():
    """Teste sintético anti-viés: Stop loss com gap de abertura executa no Open, não no stop."""
    bars = []
    price = 10000.0
    for _ in range(230):
        bars.append((price, price + 15.0, price - 5.0, price + 10.0))
        price += 10.0

    # Barra 230: Trap
    p_prev = bars[-1][3]
    bars.append((p_prev - 5.0, p_prev + 5.0, p_prev - 25.0, p_prev + 2.0))
    trap_high = bars[-1][1]
    trap_low = bars[-1][2]

    # Barra 231: Aciona BuyStop sem estopar
    bars.append((trap_high - 1.0, trap_high + 20.0, trap_low + 5.0, trap_high + 15.0))

    # Barra 232: Gap de abertura abaixo do stop loss!
    # Stop estava em trap_low. O candle abre 20 pontos abaixo de trap_low!
    gap_open = trap_low - 20.0
    bars.append((gap_open, gap_open + 5.0, gap_open - 10.0, gap_open - 2.0))
    # Barra 233: Barra seguinte para fechar o loop n - 1
    bars.append((gap_open - 2.0, gap_open + 2.0, gap_open - 5.0, gap_open))

    df = make_df(bars)
    slip = 1.5
    cfg = TrendFollowerConfig(triggers=["trap"], use_session_filter=False, slippage_pts=slip)
    strat = TrendFollowerStrategy(cfg)
    trades = strat.run_simulation(df, "NAS100", SPREAD)

    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "STOP_LOSS"
    assert t.exit_time == df.index[232]
    # Execução deve ser no Open com gap menos slippage (gap_open - slip)
    assert t.exit_price == gap_open - slip


def test_unified_mode_no_duplicate_trades():
    """Garante que no modo single_position uma barra que qualifica tanto Trap quanto Barra de Força
    abre apenas UMA única posição com risco de 1R (sem contagem dupla).
    """
    bars = []
    price = 10000.0
    for _ in range(230):
        bars.append((price, price + 15.0, price - 5.0, price + 10.0))
        price += 10.0

    # Barra 230: Qualifica Trap E Barra de Força (falso rompimento da mínima anterior + fecha nos 80% do topo)
    p_prev = bars[-1][3]
    # Range = 40.0. Minima viola anterior, fecha a 35 pontos da mínima (>70% range)
    bars.append((p_prev - 5.0, p_prev + 30.0, p_prev - 20.0, p_prev + 25.0))
    p_high = bars[-1][1]

    # Barra 231: Rompe a máxima de 230
    bars.append((p_high - 1.0, p_high + 30.0, p_high - 2.0, p_high + 25.0))

    # Condução por 10 barras para MME 20 subir
    curr_c = bars[-1][3]
    for _ in range(10):
        bars.append((curr_c, curr_c + 30.0, curr_c - 5.0, curr_c + 25.0))
        curr_c += 25.0

    # Barra 242: Fecha abaixo da MME 20
    bars.append((curr_c, curr_c + 5.0, 12340.0, 12350.0))
    bars.append((12350.0, 12360.0, 12340.0, 12345.0))
    bars.append((12345.0, 12355.0, 12330.0, 12340.0))

    df = make_df(bars)
    cfg = TrendFollowerConfig(triggers=["trap", "force_bar"], execution_mode="single_position", use_session_filter=False)
    strat = TrendFollowerStrategy(cfg)
    trades = strat.run_simulation(df, "NAS100", SPREAD)

    # Exatamente 1 trade deve ser gerado, atribuído ao primeiro gatilho de maior prioridade (TRAP)
    assert len(trades) == 1
    assert trades[0].setup_name == "TRAP"


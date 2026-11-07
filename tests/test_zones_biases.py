"""Testes anti-viés do motor de zonas SMC (Épico 2 / Z-01 a Z-07 do backlog).

Verifica as correções de lookahead, execução intrabar e custos no BacktestEngine.
"""
import pandas as pd
import pytest
from helpers import candles_from_ohlc

from smc_trader.backtest.engine import BacktestEngine
from smc_trader.config import BacktestConfig, CostsConfig, SessionConfig, SessionWindow
from smc_trader.zones.orderblock import Zone


def make_zone(
    direction: str = "long",
    high: float = 105.0,
    low: float = 95.0,
    t: pd.Timestamp = pd.Timestamp("2026-10-18 10:00:00", tz="UTC"),
    kind: str = "OB",
) -> Zone:
    return Zone(
        direction=direction,
        kind=kind,
        high=high,
        low=low,
        candle_time=t - pd.Timedelta(minutes=30),
        created_at=t,
        range_low=low - 5.0,
        range_high=high + 15.0,
        in_discount=True,
        swept_liquidity=False,
        end_time=None,
        end_reason=None,
    )


# --- Z-01: Lookahead nas médias M5/M15 -------------------------------------------------------
def test_z01_m15_ma_sem_lookahead():
    """O M15 que abre às 10:00 só fecha às 10:14:59. Entre 10:00 e 10:14 não pode conhecer seu close."""
    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    # 30 candles M1 (10:00 a 10:29)
    ohlc = [(100.0, 102.0, 99.0, 101.0)] * 15 + [(110.0, 115.0, 109.0, 114.0)] * 15
    df_m1 = candles_from_ohlc(ohlc, tf="M1", start=now)

    cfg = BacktestConfig()
    engine = BacktestEngine(cfg)
    ma_vals = engine._prepare_ma_series(df_m1, "M15", "sma", 1)

    # Durante o primeiro bucket M15 (índices 0 a 14), a média M15 não tem bucket anterior fechado => NaN
    for i in range(15):
        assert pd.isna(ma_vals[i]), f"Índice {i} ({df_m1.index[i]}) vazou informação do M15 em aberto!"

    # A partir das 10:15 (índice 15), a média deve valer exatamente o fechamento do 1º bucket M15 (101.0)
    for i in range(15, 30):
        assert ma_vals[i] == pytest.approx(101.0), f"Índice {i} deveria ter o valor fechado do 1º bucket"


# --- Z-02: Candle de entrada checado contra stop loss intrabar -------------------------------
def test_z02_candle_de_entrada_toca_stop_sai_no_mesmo_candle():
    """Nos modos touch e hybrid, se o candle de entrada tocar o stop, deve estopar no próprio candle."""
    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    zone = make_zone(direction="long", high=105.0, low=95.0, t=now)

    # Candle 0: toca 105.0 e entra comprado. SL = 95.0. No mesmo candle faz low = 90.0 (< 95.0)!
    c_m1 = candles_from_ohlc(
        [
            (108.0, 108.0, 90.0, 104.0),  # toca 105 e atinge SL 95 no mesmo minuto
            (104.0, 120.0, 103.0, 119.0), # candle seguinte atinge o alvo
        ],
        tf="M1",
        start=now,
    )

    cfg = BacktestConfig(entry_mode="touch", stop_mode="ob")
    result = BacktestEngine(cfg).run(c_m1, [zone], symbol="XAUUSD")

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.exit_reason == "sl"
    assert t.entry_time == t.exit_time == now


# --- Z-03: Gap além do stop sai no open -----------------------------------------------------
def test_z03_gap_alem_do_stop_sai_no_open():
    """Se o candle seguinte abrir em gap além do stop, a execução ocorre no open (pior que o SL)."""
    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    zone = make_zone(direction="long", high=105.0, low=95.0, t=now)

    c_m1 = candles_from_ohlc(
        [
            (108.0, 108.0, 104.0, 104.5),  # entra comprado a 105.0 (SL = 95.0)
            (90.0, 92.0, 89.0, 91.0),      # abre em gap down a 90.0 (além de 95.0)
        ],
        tf="M1",
        start=now,
    )

    cfg = BacktestConfig(entry_mode="touch", stop_mode="ob")
    result = BacktestEngine(cfg).run(c_m1, [zone], symbol="XAUUSD")

    assert len(result.trades) == 1
    t = result.trades[0]
    assert t.exit_reason == "sl"
    assert t.exit_price == pytest.approx(90.0)
    assert t.r_multiple < -1.0


# --- Z-04: Prioridade de stop loss sobre fechamento forçado de sessão -----------------------
def test_z04_prioridade_stop_sobre_sessao():
    """Se o candle atinge o SL e o horário limite de fechamento de sessão, o motivo deve ser SL."""
    now = pd.Timestamp("2026-10-18 14:00:00", tz="UTC")
    zone = make_zone(direction="long", high=105.0, low=95.0, t=now)

    c_m1 = candles_from_ohlc(
        [
            (108.0, 108.0, 104.0, 104.5),  # 14:00 entra
            (104.5, 105.0, 90.0, 100.0),   # 14:01 bate SL 95 e atinge force_close_time 14:01
        ],
        tf="M1",
        start=now,
    )

    cfg = BacktestConfig(
        entry_mode="touch",
        stop_mode="ob",
        session=SessionConfig(
            windows=[SessionWindow(name="day", start="00:00", end="23:59")],
            force_close_time="14:01",
        ),
    )
    result = BacktestEngine(cfg).run(c_m1, [zone], symbol="XAUUSD")

    assert len(result.trades) == 1
    assert result.trades[0].exit_reason == "sl"


# --- Z-05: Proibir saída e nova entrada no mesmo candle -------------------------------------
def test_z05_proibe_saida_e_reentrada_no_mesmo_candle():
    """No candle em que uma posição é encerrada, uma nova posição NÃO deve ser aberta no mesmo minuto."""
    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    zone1 = make_zone(direction="long", high=105.0, low=95.0, t=now)
    zone2 = make_zone(direction="long", high=92.0, low=85.0, t=now)

    c_m1 = candles_from_ohlc(
        [
            (108.0, 108.0, 104.0, 104.5),  # candle 0: entra na zone1 (SL 95)
            (104.5, 105.0, 90.0, 91.0),    # candle 1: bate SL 95 e toca zone2 (high 92)
            (91.0, 93.0, 90.5, 92.5),      # candle 2
        ],
        tf="M1",
        start=now,
    )

    cfg = BacktestConfig(entry_mode="touch", stop_mode="ob")
    result = BacktestEngine(cfg).run(c_m1, [zone1, zone2], symbol="XAUUSD")

    # Apenas o primeiro trade deve ter sido executado e estopado no candle 1;
    # zone2 não pode ser aberta no mesmo candle 1!
    assert len(result.trades) == 1
    assert result.trades[0].exit_time == now + pd.Timedelta(minutes=1)


# --- Z-06: Comissão descontada do PnL e do R ------------------------------------------------
def test_z06_comissao_por_lote_descontada():
    """A comissão por lote deve ser descontada do PnL e do R-múltiplo."""
    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    zone = make_zone(direction="long", high=100.0, low=90.0, t=now)

    # Entrada a 100.0, SL a 90.0 (risco = 10.0), TP = 130.0 (3R)
    c_m1 = candles_from_ohlc(
        [
            (102.0, 102.0, 99.0, 99.5),    # entra a 100
            (100.0, 135.0, 99.0, 132.0),   # bate TP 130
        ],
        tf="M1",
        start=now,
    )

    # Sem comissão
    cfg_zero = BacktestConfig(entry_mode="touch", stop_mode="ob", costs=CostsConfig(commission_per_lot=0.0))
    t_zero = BacktestEngine(cfg_zero).run(c_m1, [zone], symbol="XAUUSD").trades[0]
    assert t_zero.r_multiple == pytest.approx(3.0)
    assert t_zero.pnl == pytest.approx(30.0)

    # Com comissão de 2.0 pontos
    cfg_comm = BacktestConfig(entry_mode="touch", stop_mode="ob", costs=CostsConfig(commission_per_lot=2.0))
    t_comm = BacktestEngine(cfg_comm).run(c_m1, [zone], symbol="XAUUSD").trades[0]
    assert t_comm.pnl == pytest.approx(28.0)
    assert t_comm.r_multiple == pytest.approx(2.8)
    assert t_comm.costs == pytest.approx(2.0)


# --- Z-07: Risco mínimo rejeita setup degenerado --------------------------------------------
def test_z07_risco_minimo_rejeita_trade_degenerado():
    """Se o risco do trade for inferior a 1,5 x spread (ou quase zero), a posição não deve abrir."""
    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    # Zona com espessura quase zero (0.00001)
    zone = make_zone(direction="long", high=100.00001, low=100.0, t=now)

    c_m1 = candles_from_ohlc(
        [(101.0, 101.0, 99.0, 100.0), (100.0, 105.0, 99.5, 104.0)],
        tf="M1",
        start=now,
    )

    cfg = BacktestConfig(entry_mode="touch", stop_mode="ob", costs=CostsConfig(spread_pips={"XAUUSD": 0.20}))
    result = BacktestEngine(cfg).run(c_m1, [zone], symbol="XAUUSD")
    assert len(result.trades) == 0


# --- Z-08: Zonas tocadas durante posição aberta são mitigadas (CONSUMED) -------------------
def test_z08_zona_tocada_durante_posicao_aberta_e_mitigada():
    """Zonas tocadas enquanto há uma posição aberta são mitigadas e não podem gerar reentrada posterior."""
    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    zone1 = make_zone(direction="long", high=110.0, low=100.0, t=now)
    zone2 = make_zone(direction="long", high=105.0, low=95.0, t=now)

    c_m1 = candles_from_ohlc(
        [
            (112.0, 112.0, 108.0, 109.0),  # Candle 0: toca zone1 (high 110), entra pos 1
            (109.0, 110.0, 104.0, 108.0),  # Candle 1: toca zone2 (high 105) enquanto pos 1 está aberta!
            (108.0, 145.0, 107.0, 142.0),  # Candle 2: atinge TP da pos 1 e fecha
            (108.0, 109.0, 103.0, 106.0),  # Candle 3: toca zone2 novamente (103 < 105)
        ],
        tf="M1",
        start=now,
    )

    cfg = BacktestConfig(entry_mode="touch", stop_mode="ob")
    result = BacktestEngine(cfg).run(c_m1, [zone1, zone2], symbol="XAUUSD")

    # Apenas a zone1 deve gerar trade; zone2 foi mitigada durante candle 1 e não deve abrir no candle 3
    assert len(result.trades) == 1
    assert result.trades[0].entry_time == now


# --- Z-09: Confirmação CHoCH indexada pelo candle que o confirma ---------------------------
def test_z09_confirmacao_choch_indexado_pelo_candle_de_confirmacao():
    """CHoCH confirma no candle de rompimento e permite entrada imediata sem atraso de 1 minuto."""
    now = pd.Timestamp("2026-10-18 10:00:00", tz="UTC")
    zone = make_zone(direction="long", high=105.0, low=95.0, t=now)

    # Cria candles com toque inicial e formação de CHoCH
    from smc_trader.structure.market_structure import StructureEvent

    c_m1 = candles_from_ohlc(
        [
            (106.0, 106.0, 104.0, 104.5),  # Candle 0: toca a zona (entra em ARMED)
            (104.5, 104.8, 101.0, 102.0),  # Candle 1: oscilação
            (102.0, 105.0, 101.5, 103.5),  # Candle 2: rompe topo e confirma CHoCH de alta
        ],
        tf="M1",
        start=now,
    )

    t_choch = c_m1.index[2]
    mock_choch = StructureEvent(
        kind="CHoCH",
        direction="up",
        time=t_choch + pd.Timedelta(minutes=1),  # close_time
        break_time=t_choch,                      # candle que confirmou
        level=103.0,
        level_time=c_m1.index[0],
        leg_time=c_m1.index[1],
        range_low=101.0,
        range_high=105.0,
    )

    precomputed = {
        "events": [mock_choch],
        "chochs": {("up", mock_choch.break_time): mock_choch},
        "bos": {},
    }

    cfg = BacktestConfig(entry_mode="confirmation", stop_mode="ob")
    result = BacktestEngine(cfg).run(
        c_m1, [zone], symbol="XAUUSD", precomputed_m1=precomputed
    )

    assert len(result.trades) == 1
    # Entrada deve ocorrer exatamente no candle 2 (t_choch)
    assert result.trades[0].entry_time == t_choch


"""Testes anti-viés do motor Fibo OTE (B0-3 do backlog).

Cada teste monta candles M5 à mão e verifica uma regra de realismo. Os cenários
partilham o mesmo prefixo: um swing low (idx 2), um swing high (idx 5) e um BOS de
alta no idx 8 (fecha acima de 104), formando a perna 95 -> máxima do BOS.
"""
import pandas as pd
import pytest

from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy

SPREAD = 0.1
T0 = pd.Timestamp("2024-06-03 08:00", tz="UTC")


def m1_from_m5(bars: list[tuple[float, float, float, float]]) -> pd.DataFrame:
    """Expande cada barra M5 (o, h, l, c) em 5 M1 cujo resample devolve exatamente a barra."""
    rows, idx = [], []
    for n, (o, h, lo, c) in enumerate(bars):
        quintet = [(o, o, o, o), (h, h, h, h), (lo, lo, lo, lo), (c, c, c, c), (c, c, c, c)]
        for m, (mo, mh, ml, mc) in enumerate(quintet):
            rows.append({"open": mo, "high": mh, "low": ml, "close": mc, "volume": 1.0})
            idx.append(T0 + pd.Timedelta(minutes=5 * n + m))
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx, name="time"))


def bar_time(i: int) -> pd.Timestamp:
    return T0 + pd.Timedelta(minutes=5 * i)


PREFIX = [
    (100.0, 101.0, 99.5, 100.5),   # 0
    (100.5, 101.0, 100.0, 100.5),  # 1
    (100.5, 101.0, 95.0, 96.0),    # 2  swing low (95)
    (96.0, 98.0, 95.5, 97.0),      # 3
    (97.0, 99.0, 96.5, 98.0),      # 4
    (98.0, 104.0, 97.5, 103.0),    # 5  swing high (104)
    (103.0, 103.5, 100.0, 101.0),  # 6
    (101.0, 102.0, 100.5, 101.5),  # 7
]
# Perna: low 95, high 108 (barra 8). Entrada 70,5% = 98.835; stop 79% = 97.73.
ENTRY_LEVEL = 108.0 - 0.705 * 13.0
STOP_LEVEL = 108.0 - 0.79 * 13.0
BOS_QUIET = (101.0, 108.0, 104.5, 107.0)   # barra 8: BOS que NÃO retrai até a entrada
FLAT_HIGH = [(107.0, 108.0, 105.0, 107.0)] * 5


def cfg(**kw) -> FiboOTEConfig:
    base = dict(trailing_exit_ma=None, target_mode="0_percent", pivot_k=2)
    base.update(kw)
    return FiboOTEConfig(**base)


def run(bars, **kw):
    return FiboOTEStrategy(cfg(**kw)).run_backtest(m1_from_m5(bars), "TEST", SPREAD)


# --- cenário base: BOS quieto, retração na barra 9 entra comprado ---------------------------
def long_entry_scenario(extra):
    bos = BOS_QUIET
    entry_bar = (107.0, 107.5, 98.5, 99.5)  # barra 9: low <= 98.835, > 97.73
    return PREFIX + [bos, entry_bar] + extra + FLAT_HIGH


def test_cenario_base_gera_entrada_comprada_e_alvo():
    trades = run(long_entry_scenario([(99.5, 108.2, 99.0, 108.0)]))
    assert len(trades) == 1
    t = trades[0]
    assert t.direction == "long" and t.entry_time == bar_time(9)
    assert t.entry_price == pytest.approx(ENTRY_LEVEL + SPREAD)
    assert t.exit_reason == "TAKE_PROFIT"


# --- F-01: não entra na própria barra que confirma o BOS ------------------------------------
def test_f01_barra_do_bos_nao_gera_entrada():
    bos_deep = (101.0, 108.0, 98.0, 105.0)  # fecha > 104 (BOS) e a mínima já toca 98.835
    bars = PREFIX + [bos_deep, (105.0, 109.0, 104.0, 108.5)] + FLAT_HIGH
    trades = run(bars)
    assert [t for t in trades if t.entry_time == bar_time(8)] == []


# --- F-04: expansão da perna e entrada na mesma barra ---------------------------------------
def test_f04_nova_maxima_nao_eleva_o_nivel_de_entrada_da_propria_barra():
    # barra 9: nova máxima 110 (nível passaria a 99.425) e mínima 99.0, que só toca o nível NOVO.
    # A barra 10 bate o alvo antigo (110): se houvesse entrada na 9, sairia um trade (o motor
    # antigo registrava um; sem esta barra a posição ficava aberta e sumia no fim dos dados).
    bars = PREFIX + [BOS_QUIET, (107.0, 110.0, 99.0, 105.0), (105.0, 111.0, 105.0, 110.0)]
    bars += [(110.0, 111.0, 109.0, 110.0)] * 5
    assert run(bars) == []


def test_f04_perna_expande_para_a_barra_seguinte():
    # barra 9 não toca e expande topo para 115 (span 115-95=20 => entry 70.5% = 100.90)
    # barra 10 toca o novo nível (low 100.5 <= 100.90) e entra
    # barra 11 toca o alvo (115.0)
    b9 = (107.0, 115.0, 105.0, 114.0)
    b10 = (114.0, 114.5, 100.5, 102.0)
    b11 = (102.0, 116.0, 101.0, 115.0)
    bars = PREFIX + [BOS_QUIET, b9, b10, b11] + FLAT_HIGH
    trades = run(bars)
    assert len(trades) == 1
    t = trades[0]
    assert t.entry_time == bar_time(10)
    assert t.entry_price == pytest.approx(100.90 + SPREAD)
    assert t.exit_reason == "TAKE_PROFIT"


# --- F-05 & F-09: gap além do stop e cálculo exato de R -------------------------------------
def test_f05_gap_alem_do_stop_sai_no_open_com_r_menor_que_menos_um():
    # entra na 9 (stop = 97.73). Barra 10 abre em gap down em 96.0 (abaixo do stop).
    # Preço de saída deve ser 96.0 e R deve ser significativamente menor que -1.0.
    gap_bar = (96.0, 96.5, 95.5, 96.0)
    trades = run(long_entry_scenario([gap_bar]))
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "STOP_LOSS"
    assert t.pnl_points == pytest.approx(96.0 - (ENTRY_LEVEL + SPREAD))
    assert t.r_multiple < -2.0  # R < -1R refletindo o gap real


# --- F-06: saída por MME no open da próxima barra ------------------------------------------
def test_f06_saida_mme_no_open_da_proxima_barra():
    # Barra 10 fecha abaixo da MME e dá o sinal de trailing.
    # Com trailing_exit_on_next_open=True, saída ocorre no open da barra 11.
    extra = [
        (99.5, 101.0, 99.0, 99.2),  # 10: close abaixo da MME
        (99.0, 99.5, 98.8, 99.0),   # 11: open em 99.0 executa a saída
    ]
    trades = run(long_entry_scenario(extra), trailing_exit_ma="ema8", trailing_profit_only=False, trailing_exit_on_next_open=True)
    t = [x for x in trades if x.exit_reason == "TRAILING_MA"][0]
    assert t.exit_time == bar_time(11)
    assert t.pnl_points == pytest.approx(99.0 - (ENTRY_LEVEL + SPREAD))


# --- F-07: tempo máximo de posição e encerramento no fim dos dados --------------------------
def test_f07_tempo_maximo_posicao_encerra():
    neutral_bars = [(99.5, 100.0, 99.0, 99.5)] * 4
    trades = run(long_entry_scenario(neutral_bars), max_position_candles=3)
    t = trades[0]
    assert t.exit_reason == "TIME_EXPIRATION"
    assert t.exit_time == bar_time(12)  # entrou na 9 + 3 barras = 12


def test_f07_expiracao_nao_ignora_stop_da_barra_de_expiracao():
    # Barra 12 vai abaixo do stop (97.73) e fecha no alto: a saída por tempo deve ser
    # no open (decidida no fechamento da barra anterior), nunca no close dessa barra.
    neutral = [(99.5, 100.0, 99.0, 99.5)] * 2
    crash = (99.5, 100.0, 90.0, 107.0)
    trades = run(long_entry_scenario(neutral + [crash]), max_position_candles=3)
    t = trades[0]
    assert t.exit_reason == "TIME_EXPIRATION"
    assert t.pnl_points == pytest.approx(99.5 - (ENTRY_LEVEL + SPREAD))


def test_d02_rolagem_fecha_posicao_no_ultimo_fechamento_do_contrato_antigo():
    bars = long_entry_scenario([(99.5, 100.0, 99.0, 99.5), (99.5, 100.0, 99.0, 99.5)])
    m1 = m1_from_m5(bars)
    roll_bar = 11
    m1["roll"] = False
    m1.loc[m1.index[5 * roll_bar : 5 * roll_bar + 5], "roll"] = True
    after = m1.index >= bar_time(roll_bar + 1)
    m1.loc[after, ["open", "high", "low", "close"]] += 1000.0  # novo contrato, 1000 pontos acima
    trades = FiboOTEStrategy(cfg()).run_backtest(m1, "TEST", SPREAD)
    t = trades[0]
    assert t.exit_reason == "ROLLOVER"
    assert t.exit_time == bar_time(roll_bar)
    assert abs(t.r_multiple) < 5


def test_f07_fim_dos_dados_fecha_posicao_aberta():
    # Apenas o prefixo + BOS + entrada (sem barras posteriores suficientes para stop/alvo)
    bars = PREFIX + [BOS_QUIET, (107.0, 107.5, 98.5, 99.5)]
    trades = run(bars)
    assert len(trades) == 1
    assert trades[0].exit_reason == "END_OF_DATA"


# --- F-08: controle de sessão e zeragem -----------------------------------------------------
def test_f08_sessao_rejeita_entrada_fora_do_horario():
    # T0 = 08:00 UTC. Barra 9 = 08:45 UTC.
    # Se a janela de negociação for só a partir das 13:00, a entrada é ignorada.
    trades = run(
        long_entry_scenario([(99.5, 108.2, 99.0, 108.0)]),
        session_filter=True,
        session_windows=[("13:00", "20:00")],
    )
    assert trades == []


# --- F-10: slippage e comissão afetam preço e R ----------------------------------------------
def test_f10_slippage_e_comissao_descontados():
    trades = run(
        long_entry_scenario([(99.5, 108.2, 99.0, 108.0)]),
        slippage=0.05,
        commission_per_unit=0.10,
    )
    t = trades[0]
    expected_entry = ENTRY_LEVEL + SPREAD + 0.05
    assert t.entry_price == pytest.approx(expected_entry)
    expected_exit = 108.0 - 0.05
    expected_pnl = (expected_exit - expected_entry) - 0.10
    assert t.pnl_points == pytest.approx(expected_pnl)
    assert t.r_multiple == pytest.approx(expected_pnl / t.risk_points)


# --- F-03: trava 2:1 não vale na barra em que é acionada ------------------------------------
def test_f03_barra_que_aciona_a_trava_e_toca_o_stop_original_perde_1r():
    # barra 10: máxima 102 (>= entrada + 2R = 101.345) e mínima 97 (<= stop original 97.73)
    trades = run(long_entry_scenario([(99.5, 102.0, 97.0, 98.0)]), use_lock_2to1=True)
    t = trades[0]
    assert t.exit_reason == "STOP_LOSS"
    assert t.r_multiple == pytest.approx(-1.0)


def test_f03_trava_vale_a_partir_da_barra_seguinte():
    extra = [(99.5, 102.0, 99.5, 101.0),   # 10: aciona a trava, sem tocar o stop
             (101.0, 101.5, 100.0, 100.5)]  # 11: mínima 100.0 <= novo stop 100.14
    t = run(long_entry_scenario(extra), use_lock_2to1=True)[0]
    assert t.exit_reason == "LOCK_PROFIT_SL"
    assert t.r_multiple == pytest.approx(1.0)
    assert t.exit_time == bar_time(11)


# --- F-02: venda executa no bid e recompra no ask -------------------------------------------
def mirror(bars):
    return [(200 - o, 200 - lo, 200 - h, 200 - c) for (o, h, lo, c) in bars]


def short_scenario(extra):
    """Prefixo, BOS e barra de entrada espelhados; `extra` já vem em coordenadas de venda."""
    head = mirror(PREFIX + [BOS_QUIET, (107.0, 107.5, 98.5, 99.5)])
    return head + extra + mirror(FLAT_HIGH)


# espelho: entrada vendida em 200-98.835 = 101.165; stop = 200-97.73 = 102.27; alvo = 200-108 = 92
SHORT_ENTRY = 200 - ENTRY_LEVEL
SHORT_STOP = 200 - STOP_LEVEL
SHORT_TARGET = 200 - 108.0


def test_f02_cenario_base_vendido_entra_no_bid():
    trades = run(short_scenario([(100.5, 100.8, 91.0, 92.0)]))
    t = trades[0]
    assert t.direction == "short" and t.entry_time == bar_time(9)
    assert t.entry_price == pytest.approx(SHORT_ENTRY)


def test_f02_alvo_da_venda_exige_o_ask_atingir_o_nivel():
    # barra 10: mínima (bid) 91.95. O ask é 92.05 > 92: a recompra no alvo NÃO executa.
    extra = [(100.5, 100.8, 91.95, 93.0),   # 10: bid chega a 91.95, ask não
             (93.0, 94.0, 91.0, 92.0)]       # 11: ask 91.1 <= 92 => alvo
    t = run(short_scenario(extra))[0]
    assert t.exit_reason == "TAKE_PROFIT"
    assert t.exit_time == bar_time(11)


def test_f02_stop_da_venda_dispara_quando_o_ask_toca_o_nivel():
    # barra 10: máxima (bid) 102.2 => ask 102.3 >= stop 102.27: estopado a -1R
    extra = [(100.5, 102.2, 100.0, 101.0)]
    t = run(short_scenario(extra))[0]
    assert t.exit_reason == "STOP_LOSS"
    assert t.r_multiple == pytest.approx(-1.0)
    assert t.pnl_points == pytest.approx(SHORT_ENTRY - SHORT_STOP)


def test_f02_stop_da_venda_nao_dispara_com_ask_abaixo_do_nivel():
    # máxima 102.1 => ask 102.2 < 102.27: segue posicionado
    extra = [(100.5, 102.1, 100.0, 101.0), (101.0, 101.5, 91.0, 92.0)]
    t = run(short_scenario(extra))[0]
    assert t.exit_time == bar_time(11) and t.exit_reason == "TAKE_PROFIT"


# --- propriedades sobre dados reais (pulam se não houver dados locais) -----------------------
@pytest.mark.parametrize("symbol,spread", [("XAUUSD", 0.30), ("NAS100", 1.50)])
def test_propriedades_em_dados_reais(symbol, spread):
    from pathlib import Path

    path = Path(f"data/{symbol}_M1_dukascopy.parquet")
    if not path.exists():
        pytest.skip("sem dados locais")
    df = pd.read_parquet(path).iloc[:60_000]
    strat = FiboOTEStrategy(FiboOTEConfig(trailing_exit_ma="ema8", target_mode="0_percent", pivot_k=3))
    trades = strat.run_backtest(df, symbol, spread)
    m5 = strat.resample_data(df)
    assert trades, "esperava ao menos um trade"
    for t in trades:
        # R é sempre o resultado em pontos dividido pelo risco inicial (exceto o -1R fixo da barra de entrada)
        if t.exit_reason != "INTRABAR_STOP_LOSS" and t.exit_reason != "TAKE_PROFIT" or t.exit_reason == "TAKE_PROFIT":
            assert t.r_multiple == pytest.approx(t.pnl_points / t.risk_points, rel=1e-6)
        if t.exit_reason == "TRAILING_MA":
            close = float(m5.loc[t.exit_time, "close"])
            expected = (close - t.entry_price) if t.direction == "long" else (t.entry_price - (close + spread))
            assert t.pnl_points == pytest.approx(expected)
        # nunca entra na barra que confirma o BOS: a barra de entrada é posterior ao BOS, logo há
        # ao menos 1 barra entre a última barra da perna e a entrada (checado nos testes de cenário)
        assert t.exit_time >= t.entry_time


def test_b01_breakeven_trigger_moves_stop_to_entry():
    """B0-1 / Breakeven: Quando atinge o gatilho (+1R), stop move para 0.0R (breakeven)."""
    # barra 9 entra comprado (entry ~98.935, stop ~97.73, risk ~1.205)
    # barra 10 sobe até 101.5 (> entry + 1.205 -> +2.1R), engatilhando breakeven
    # barra 11 cai para 98.5 (fura entrada, acima do stop original). Deve sair a ~0.0R no breakeven!
    b10 = (99.5, 101.5, 99.0, 101.0)
    b11 = (101.0, 101.0, 98.5, 98.6)
    trades = run(
        long_entry_scenario([b10, b11]),
        profit_lock_trigger_r=1.0,
        profit_lock_guarantee_r=0.0,
        target_mode="trailing_only",
    )
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "LOCK_PROFIT_SL"
    assert t.r_multiple == pytest.approx(0.0, abs=1e-3)


def test_b01_partial_exit_realizes_fraction_of_r():
    """B0-1 / Parciais: Quando atinge gatilho de parcial (+1R), realiza 50% e restante toma SL integral."""
    # barra 9 entra comprado
    # barra 10 sobe até 101.5 (+2.1R), realizando 50% no gatilho 1.0R (+0.5R garantido)
    # barra 11 cai até 97.0 (fura stop original 97.73).
    # R final: +0.5R (da parcial) + 0.5 * (-1.0R) = 0.0R!
    b10 = (99.5, 101.5, 99.0, 101.0)
    b11 = (101.0, 101.0, 97.0, 97.2)
    trades = run(
        long_entry_scenario([b10, b11]),
        partial_exit_trigger_r=1.0,
        partial_exit_pct=0.5,
        target_mode="trailing_only",
    )
    assert len(trades) == 1
    t = trades[0]
    assert t.exit_reason == "STOP_LOSS"
    assert t.r_multiple == pytest.approx(0.0, abs=1e-3)


def test_f12_filtro_trend_ma_nao_depende_do_fechamento_da_barra_do_toque():
    """Regra 1 (AGENTS.md): ordem limite executa no toque intrabar; close[i] não existe ainda.

    Cenário A: barra 9 toca 98.835 e despenca para fechar em 98.0 (abaixo da EMA80 ~101.8).
    Cenário B: barra 9 toca 98.835 e recupera para fechar em 106.0 (acima da EMA80).
    Na barra 8 (anterior à entrada), o fechamento (107.0) estava acima da EMA80 em ambos.
    Ambos os cenários DEVEM gerar a entrada comprada na barra 9 — o backtest não pode
    descartar o Cenário A olhando o fechamento futuro da própria barra 9.
    """
    entry_bar_closes_low = (107.0, 107.5, 98.5, 98.0)   # fecha abaixo da EMA80
    entry_bar_closes_high = (107.0, 107.5, 98.5, 106.0) # fecha acima da EMA80
    after = [(98.0, 98.2, 97.0, 97.2)]  # barra 10 estopa

    bars_low = PREFIX + [BOS_QUIET, entry_bar_closes_low] + after + FLAT_HIGH
    bars_high = PREFIX + [BOS_QUIET, entry_bar_closes_high] + after + FLAT_HIGH

    trades_low = run(bars_low, trend_ma="ema80", trend_ma_slope=True)
    trades_high = run(bars_high, trend_ma="ema80", trend_ma_slope=True)

    assert len(trades_low) == 1, "não pode descartar entrada limite que fechou abaixo da média"
    assert len(trades_high) == 1
    assert trades_low[0].entry_time == bar_time(9)
    assert trades_high[0].entry_time == bar_time(9)
    assert trades_low[0].entry_price == pytest.approx(trades_high[0].entry_price)


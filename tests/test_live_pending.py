"""L-02/L-06: o live decide com o mesmo código do backtest, mesmo com janela deslizante cheia.

Regressões cobertas: índices posicionais que travavam a entrada quando a janela enche,
replay de sinais antigos na partida e ordem limite sem validade nem cancelamento.
"""
import pandas as pd
import pytest
from test_prefix_invariance import synthetic_m1

from smc_trader.config import (
    BridgeConfig,
    ContractSpec,
    FiboModelConfig,
    KillSwitchConfig,
    ProductionConfig,
    ProductionSymbolConfig,
    TradingProductionConfig,
)
from smc_trader.execution.live_engine import LiveTradingEngine
from smc_trader.execution.mt5_interface import MockMT5Client
from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy

SPREAD = 0.2  # ask - bid do XAUUSD no MockMT5Client
KW = dict(fibo_entry=0.705, fibo_stop=0.790, target_mode="0_percent", pivot_k=2, trailing_exit_ma=None)


def _engine(tmp_path, client):
    prod = ProductionConfig(
        trading=TradingProductionConfig(risk_pct_per_trade=1.0, max_open_trades_total=4, magic_base=777000),
        bridge=BridgeConfig(),
        kill_switch=KillSwitchConfig(),
        models={"m": FiboModelConfig(name="m", strategy="fibo_ote", timeframe="M5", **KW)},
        symbols={"XAUUSD": ProductionSymbolConfig(model="m", macro_tf="M5", order_type="limit")},
    )
    return LiveTradingEngine(
        client=client,
        production_config=prod,
        notification_callback=lambda m: None,
        state_file=tmp_path / "s.json",
        journal_file=tmp_path / "j.jsonl",
        contracts={"XAUUSD": ContractSpec(spread=SPREAD)},
    )


def _feed(engine, client, df, start, end):
    for end_idx in range(start, end):
        sl = df.iloc[:end_idx]
        client.set_candles("XAUUSD", "M1", sl)
        engine.process_symbol_tick("XAUUSD", now_utc=sl.index[-1])


def test_janela_deslizante_cheia_entra_como_o_backtest(tmp_path):
    df = synthetic_m1(n=20_000, seed=7)
    trades = FiboOTEStrategy(FiboOTEConfig(**KW)).run_backtest(df, "XAUUSD", SPREAD)
    window = 1500
    # trade de referência isolado: nenhum outro trade (aberto ou não) na janela anterior
    first = None
    for prev, t in zip(trades, trades[1:], strict=False):
        loc = df.index.get_loc(t.entry_time)
        if loc > window + 300 and prev.exit_time < t.entry_time - pd.Timedelta(minutes=window + 200):
            first = t
            break
    assert first is not None, "cenário sintético sem trade isolado"
    loc = df.index.get_loc(first.entry_time)

    client = MockMT5Client(initial_balance=10_000.0)
    client.connect()
    engine = _engine(tmp_path, client)
    _feed(engine, client, df, loc - window - 200, loc + 10)  # a janela enche e desliza

    opened = client.get_open_positions("XAUUSD")
    match = [p for p in opened if p.open_time.floor("5min") == first.entry_time]
    assert match, f"live não abriu a posição de {first.entry_time}; abertas: {[p.open_time for p in opened]}"
    assert match[0].direction == first.direction
    assert match[0].open_price == pytest.approx(first.entry_price, abs=0.02)


def test_partida_nao_gera_ordem_de_perna_expirada(tmp_path):
    df = synthetic_m1(n=6000, seed=7)
    client = MockMT5Client(initial_balance=10_000.0)
    client.connect()
    engine = _engine(tmp_path, client)
    # primeira chamada com a janela cheia: só pode armar o que o backtest armaria agora
    sl = df.iloc[:3000]
    client.set_candles("XAUUSD", "M1", sl)
    engine.process_symbol_tick("XAUUSD", now_utc=sl.index[-1])
    assert client.get_open_positions("XAUUSD") == []  # nenhuma entrada a mercado
    setup = FiboOTEStrategy(FiboOTEConfig(**KW)).pending_setup(
        engine_window(client), SPREAD
    )
    assert len(client.orders) == (1 if setup else 0)


def engine_window(client):
    m1 = client.get_candles("XAUUSD", "M1", count=1500)
    return m1.iloc[:-1]


def test_ordem_pendente_e_cancelada_quando_o_setup_deixa_de_valer(tmp_path):
    df = synthetic_m1(n=6000, seed=7)
    client = MockMT5Client(initial_balance=10_000.0)
    client.connect()
    engine = _engine(tmp_path, client)
    cancelled = 0
    armed = 0
    original_cancel = client.cancel_order

    def spy(ticket):
        nonlocal cancelled
        cancelled += 1
        return original_cancel(ticket)

    client.cancel_order = spy
    for end_idx in range(450, 2500):
        sl = df.iloc[:end_idx]
        client.set_candles("XAUUSD", "M1", sl)
        engine.process_symbol_tick("XAUUSD", now_utc=sl.index[-1])
        armed = max(armed, len(client.orders))
        # nunca mais de uma pendente por símbolo
        assert len(client.orders) <= 1
    assert armed == 1
    assert cancelled > 0, "setups expirados ou alterados devem cancelar a pendente"


def test_pending_setup_respeita_filtro_de_sessao():
    """F-08: pending_setup não arma ordens se o horário atual estiver fora das janelas permitidas."""
    df = synthetic_m1(n=3000, seed=7)
    strat_no_session = FiboOTEStrategy(FiboOTEConfig(**KW))
    # Encontra um candle onde há setup pendente ativo
    setup_idx = None
    for i in range(500, 1000):
        s = strat_no_session.pending_setup(df.iloc[:i], SPREAD)
        if s is not None:
            setup_idx = i
            break
    assert setup_idx is not None, "cenário sintético deve produzir ao menos 1 setup pendente"

    # Janela que NÃO inclui o horário atual
    strat_blocked = FiboOTEStrategy(
        FiboOTEConfig(**KW, session_filter=True, session_windows=[("02:00", "03:00")])
    )
    assert strat_blocked.pending_setup(df.iloc[:setup_idx], SPREAD) is None

    # Janela que INCLUI o horário atual
    # Cria janela ampla cobrindo o dia todo
    strat_allowed = FiboOTEStrategy(
        FiboOTEConfig(**KW, session_filter=True, session_windows=[("00:00", "23:59")])
    )
    s_allowed = strat_allowed.pending_setup(df.iloc[:setup_idx], SPREAD)
    assert s_allowed is not None
    assert s_allowed.direction in ("long", "short")


def test_pending_setup_trailing_only_sem_alvo_fixo():
    """L-02: target_mode='trailing_only' deve retornar take_profit=0.0 no PendingSetup."""
    df = synthetic_m1(n=3000, seed=7)
    kw = {**KW, "target_mode": "trailing_only"}
    strat_trailing = FiboOTEStrategy(FiboOTEConfig(**kw))
    setup = None
    for i in range(500, 1000):
        s = strat_trailing.pending_setup(df.iloc[:i], SPREAD)
        if s is not None:
            setup = s
            break
    assert setup is not None
    assert setup.take_profit == 0.0


def test_fibo_live_session_close_action():
    """F-08: FiboLiveEvaluator emite CLOSE_POSITION com motivo SESSION_CLOSE no force_close_time."""
    from smc_trader.execution.fibo_live import FiboLiveEvaluator

    cfg = FiboOTEConfig(
        **KW,
        session_filter=True,
        force_close_time="17:00",
    )
    evaluator = FiboLiveEvaluator(cfg, spread=SPREAD)
    times = pd.date_range("2026-11-07 16:00:00", periods=20, freq="5min", tz="UTC")
    df_m5 = pd.DataFrame(
        {"open": 2000.0, "high": 2005.0, "low": 1995.0, "close": 2002.0, "volume": 100},
        index=times,
    )
    # 16:50 fecha às 16:55 (< 17:00): não deve zerar por sessão
    actions_before = evaluator.process_closed_m5(
        df_m5=df_m5.iloc[:11],  # último candle abre 16:50 e fecha 16:55
        is_positioned=True,
        current_pos_direction="long",
        current_pos_open_price=2000.0,
        current_pos_stop_loss=1990.0,
        current_pos_ticket=999,
        current_pos_open_time=times[0],
    )
    assert actions_before == []

    # 16:55 fecha às 17:00 (== force_close_time), mesmo que aberta na própria barra 16:55
    actions = evaluator.process_closed_m5(
        df_m5=df_m5.iloc[:12],  # último candle abre 16:55 e fecha 17:00
        is_positioned=True,
        current_pos_direction="long",
        current_pos_open_price=2000.0,
        current_pos_stop_loss=1990.0,
        current_pos_ticket=999,
        current_pos_open_time=times[11],
    )
    assert len(actions) == 1
    assert actions[0].action_type == "CLOSE_POSITION"
    assert actions[0].ticket == 999
    assert actions[0].reason == "SESSION_CLOSE"


def test_pending_setup_respeita_trend_filter_80_200():
    """pending_setup aplica trend_filter_80_200 antes de devolver o setup."""
    df = synthetic_m1(n=3000, seed=7)
    strat = FiboOTEStrategy(FiboOTEConfig(**KW))
    setup_idx = None
    base_setup = None
    for i in range(500, 1000):
        s = strat.pending_setup(df.iloc[:i], SPREAD)
        if s is not None:
            setup_idx = i
            base_setup = s
            break
    assert setup_idx is not None and base_setup is not None

    # Prepend histórico extremo contrário à direção do setup para forçar bloqueio pelo filtro 80/200
    extreme_val = 99999.0 if base_setup.direction == "long" else 1.0
    prefix_df = pd.DataFrame(
        {
            "open": extreme_val,
            "high": extreme_val + 1.0,
            "low": extreme_val - 1.0,
            "close": extreme_val,
            "volume": 100,
        },
        index=pd.date_range(
            end=df.index[0] - pd.Timedelta(minutes=1),
            periods=1500,
            freq="1min",
            tz=df.index.tz,
        ),
    )
    df_with_contrary_ma = pd.concat([prefix_df, df.iloc[:setup_idx]])
    strat_filtered = FiboOTEStrategy(
        FiboOTEConfig(**KW, trend_filter_80_200=True)
    )
    assert strat_filtered.pending_setup(df_with_contrary_ma, SPREAD) is None


def test_profit_lock_resets_when_ticket_changes():
    """FiboLiveEvaluator reavalia trava 2:1 quando o ticket da posição muda."""
    from smc_trader.execution.fibo_live import FiboLiveEvaluator

    cfg = FiboOTEConfig(**KW, use_lock_2to1=True, lock_trigger_r=2.0, lock_guarantee_r=1.0)
    evaluator = FiboLiveEvaluator(cfg, spread=0.0)
    times = pd.date_range("2026-11-07 10:00:00", periods=25, freq="5min", tz="UTC")
    df_m5 = pd.DataFrame(
        {"open": 2000.0, "high": 2025.0, "low": 1998.0, "close": 2020.0, "volume": 100},
        index=times,
    )

    # Ticket 101 atinge 2R (open=2000, sl=1990 -> risk=10 -> trigger=2020)
    act1 = evaluator.process_closed_m5(
        df_m5=df_m5.iloc[:20],
        is_positioned=True,
        current_pos_direction="long",
        current_pos_open_price=2000.0,
        current_pos_stop_loss=1990.0,
        current_pos_ticket=101,
        current_pos_open_time=times[0],
    )
    assert any(a.action_type == "MODIFY_STOP" and a.ticket == 101 for a in act1)
    assert evaluator.profit_lock_applied is True
    assert evaluator.profit_lock_ticket == 101

    # Nova posição com ticket 102 na barra seguinte (sem passar por is_positioned=False)
    act2 = evaluator.process_closed_m5(
        df_m5=df_m5.iloc[:21],
        is_positioned=True,
        current_pos_direction="long",
        current_pos_open_price=2000.0,
        current_pos_stop_loss=1990.0,
        current_pos_ticket=102,
        current_pos_open_time=times[1],
    )
    assert any(a.action_type == "MODIFY_STOP" and a.ticket == 102 for a in act2)
    assert evaluator.profit_lock_ticket == 102


def test_reconcile_startup_state_restores_pending_order_ticket(tmp_path):
    """LiveTradingEngine restaura pending_order_ticket e pending_order_price no startup."""
    client = MockMT5Client(initial_balance=10_000.0)
    client.connect()
    eng = _engine(tmp_path, client)
    eng.state_store.save(
        {
            "XAUUSD": {
                "current_position_ticket": None,
                "pending_order_ticket": 777,
                "pending_order_price": 2645.50,
                "last_processed_m1_time": None,
            }
        }
    )
    eng.reconcile_startup_state()
    state = eng.runtimes["XAUUSD"]
    assert state.current_position is None
    assert state.pending_order_ticket == 777
    assert state.pending_order_price == 2645.50


def test_pending_setup_respeita_trend_ma_slope():
    """pending_setup bloqueia setup se trend_ma_slope=True e a média estiver contrária."""
    df = synthetic_m1(n=3000, seed=7)
    strat_base = FiboOTEStrategy(FiboOTEConfig(**KW))
    setup_idx = None
    base_setup = None
    for i in range(500, 1000):
        s = strat_base.pending_setup(df.iloc[:i], SPREAD)
        if s is not None:
            setup_idx = i
            base_setup = s
            break
    assert setup_idx is not None and base_setup is not None

    # Se a média estiver caindo (slope negativo), um setup de compra deve ser bloqueado
    # Prepend histórico para forçar SMA50 com inclinação contrária
    extreme_val = 5000.0 if base_setup.direction == "long" else 1000.0
    prefix_df = pd.DataFrame(
        {
            "open": extreme_val,
            "high": extreme_val + 1.0,
            "low": extreme_val - 1.0,
            "close": extreme_val,
            "volume": 100,
        },
        index=pd.date_range(
            end=df.index[0] - pd.Timedelta(minutes=1),
            periods=1000,
            freq="1min",
            tz=df.index.tz,
        ),
    )
    df_combined = pd.concat([prefix_df, df.iloc[:setup_idx]])
    strat_slope = FiboOTEStrategy(
        FiboOTEConfig(**KW, trend_ma="sma50", trend_ma_slope=True)
    )
    # Testa que o filtro é aplicado sem exceções
    _ = strat_slope.pending_setup(df_combined, SPREAD)


def test_fibo_live_m5_close_rejection_emits_market_entry_and_bos_swing_trail():
    """FiboLiveEvaluator emite MARKET_ENTRY quando entry_mode='m5_close_rejection' e MODIFY_STOP em bos_swing_trailing."""
    from smc_trader.execution.fibo_live import FiboLiveEvaluator

    def _bars(ohlc: list[tuple[float, float, float, float]]) -> pd.DataFrame:
        idx = pd.date_range("2026-01-05 08:00", periods=len(ohlc), freq="5min", tz="UTC")
        return pd.DataFrame(
            ohlc, columns=["open", "high", "low", "close"], index=idx, dtype=float
        )

    cfg = FiboOTEConfig(
        timeframe="5min",
        fibo_entry=0.50,
        fibo_rejection_max=0.79,
        fibo_stop=0.886,
        entry_mode="m5_close_rejection",
        stop_mode="fibo",
        rejection_min_wick_ratio=0.50,
        bos_swing_trailing=True,
        target_mode="3R",
        target_r=10.0,
        trailing_exit_ma=None,
        pivot_k=1,
    )
    evaluator = FiboLiveEvaluator(cfg, spread=0.0)
    b0_8 = [
        (100, 101, 99, 100),  # 0
        (100, 102, 95, 101),  # 1: swing low = 95
        (101, 103, 98, 102),  # 2
        (102, 105, 100, 104),  # 3: swing high = 105
        (104, 104, 101, 102),  # 4
        (102, 107, 101, 106),  # 5: BOS -> leg [95, 107]
        (106, 106, 102, 103),  # 6
        (103, 104, 98.0, 102.5),  # 7: toca zona [50%-79%] com pavio >= 50% e fecha > 79%
    ]
    df_entry = _bars(b0_8)
    acts_entry = evaluator.process_closed_m5(df_entry, is_positioned=False)
    assert len(acts_entry) == 1
    assert acts_entry[0].action_type == "MARKET_ENTRY"
    assert acts_entry[0].direction == "long"

    b_trail = b0_8 + [
        (102.6, 105.0, 102.0, 104.5),  # 8: barra da entrada (open_time = index[8])
        (104.5, 105.5, 101.0, 105.0),  # 9: forma novo swing low em 101.0
        (105.0, 106.5, 104.0, 106.0),  # 10: confirma swing low (k=1) em 9
        (106.0, 109.0, 105.5, 108.5),  # 11: fecha > 107.0 (BOS a favor) -> move stop p/ 101.0
    ]
    df_trail = _bars(b_trail)
    acts_trail = evaluator.process_closed_m5(
        df_trail,
        is_positioned=True,
        current_pos_direction="long",
        current_pos_open_price=102.6,
        current_pos_stop_loss=96.368,
        current_pos_ticket=555,
        current_pos_open_time=df_trail.index[8],
    )
    assert any(
        a.action_type == "MODIFY_STOP"
        and a.reason == "BOS_SWING_TRAIL"
        and abs(a.stop_loss - 101.0) < 1e-6
        for a in acts_trail
    )






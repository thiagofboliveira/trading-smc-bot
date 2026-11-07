"""L-02/L-06: o live decide com o mesmo código do backtest, mesmo com janela deslizante cheia.

Regressões cobertas: índices posicionais que travavam a entrada quando a janela enche,
replay de sinais antigos na partida e ordem limite sem validade nem cancelamento.
"""
import pandas as pd
import pytest
from test_prefix_invariance import synthetic_m1

from smc_trader.config import (
    BridgeConfig,
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

"""Testes de conformidade do SimBroker com as regras anti-viés (AGENTS.md)."""

import pandas as pd

from smc_trader.broker.sim_broker import SimBroker
from smc_trader.core.types import OrderIntent, OrderIntentType


def test_sim_broker_intrabar_stop_rule():
    """Garante que a barra de entrada checa stop intrabar e NUNCA é alvejada (AGENTS.md)."""
    broker = SimBroker(spread=1.0, slippage=0.5)

    # Ordem limite de compra em 100.0 com stop em 95.0 e alvo em 110.0
    intent = OrderIntent(
        intent_type=OrderIntentType.PLACE_LIMIT,
        direction="long",
        price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
    )
    broker.submit_order(intent, bar_idx=0)

    # Barra 1: Preço abre em 102.0, desce até 93.0 (toca entrada 100 e fura stop 95), máxima vai a 112.0
    # O simulador DEVE executar o stop intrabar (sl_intrabar), e NUNCA o alvo 112.0
    ts = pd.Timestamp("2024-01-01 10:00:00", tz="UTC")
    closed = broker.process_bar(
        bar_idx=1,
        timestamp=ts,
        open_=102.0,
        high=112.0,
        low=93.0,
        close=96.0,
        symbol="TEST",
    )

    assert len(closed) == 1
    trade = closed[0]
    assert trade.exit_reason == "sl_intrabar"
    assert trade.r_multiple < 0  # Prejuízo confirmado
    assert len(broker.positions) == 0  # Não sobreviveu


def test_sim_broker_gap_stop_loss():
    """Garante que stop com gap na abertura preenche no open acrescido de slippage."""
    broker = SimBroker(spread=0.0, slippage=1.0)

    # Posição já aberta
    intent = OrderIntent(
        intent_type=OrderIntentType.PLACE_LIMIT,
        direction="long",
        price=100.0,
        stop_loss=90.0,
        take_profit=120.0,
    )
    broker.submit_order(intent, bar_idx=0)
    # Fill normal na barra 1
    broker.process_bar(
        bar_idx=1,
        timestamp=pd.Timestamp("2024-01-01 10:00:00", tz="UTC"),
        open_=101.0,
        high=103.0,
        low=99.0,
        close=100.0,
        symbol="TEST",
    )
    assert len(broker.positions) == 1

    # Barra 2 abre com gap abaixo do stop (open em 85.0 quando stop era 90.0)
    closed = broker.process_bar(
        bar_idx=2,
        timestamp=pd.Timestamp("2024-01-01 10:05:00", tz="UTC"),
        open_=85.0,
        high=87.0,
        low=84.0,
        close=86.0,
        symbol="TEST",
    )
    assert len(closed) == 1
    trade = closed[0]
    # Exit price deve ser min(open, stop) - slippage = 85.0 - 1.0 = 84.0
    assert trade.exit_price == 84.0
    assert trade.exit_reason == "sl"


def test_sim_broker_take_profit_on_subsequent_bar():
    """Garante que o alvo pode ser atingido em barras subsequentes se não foi estopado."""
    broker = SimBroker(spread=0.0, slippage=0.0)

    intent = OrderIntent(
        intent_type=OrderIntentType.PLACE_LIMIT,
        direction="long",
        price=100.0,
        stop_loss=90.0,
        take_profit=110.0,
    )
    broker.submit_order(intent, bar_idx=0)

    # Barra 1: Fill normal
    broker.process_bar(
        bar_idx=1,
        timestamp=pd.Timestamp("2024-01-01 10:00:00", tz="UTC"),
        open_=101.0,
        high=102.0,
        low=99.0,
        close=100.5,
        symbol="TEST",
    )
    assert len(broker.positions) == 1

    # Barra 2: Alvo atingido
    closed = broker.process_bar(
        bar_idx=2,
        timestamp=pd.Timestamp("2024-01-01 10:05:00", tz="UTC"),
        open_=101.0,
        high=111.0,
        low=100.5,
        close=110.5,
        symbol="TEST",
    )
    assert len(closed) == 1
    assert closed[0].exit_reason == "tp"
    assert closed[0].exit_price >= 110.0

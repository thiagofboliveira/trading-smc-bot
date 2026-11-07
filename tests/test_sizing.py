"""Testes para o cálculo de tamanho de posição (L-04 do backlog)."""
import pytest
from smc_trader.execution.sizing import calculate_lot_size
from smc_trader.execution.types import SymbolInfo


@pytest.fixture
def base_symbol():
    return SymbolInfo(
        symbol="EURUSD",
        bid=1.0850,
        ask=1.0851,
        point=0.00001,
        digits=5,
        spread=0.0001,
        min_lot=0.01,
        max_lot=100.0,
        lot_step=0.01,
        tick_value=1.0,   # $1 por tick
        tick_size=0.00001, # tick_size == point
        trade_contract_size=100000.0,
    )


def test_l04_equity_zero_or_negative_returns_zero(base_symbol):
    """L-04: Equity zero ou negativo deve retornar 0.0, nunca min_lot."""
    assert calculate_lot_size(equity=0.0, risk_pct=1.0, entry_price=1.0850, stop_loss=1.0800, symbol_info=base_symbol) == 0.0
    assert calculate_lot_size(equity=-1000.0, risk_pct=1.0, entry_price=1.0850, stop_loss=1.0800, symbol_info=base_symbol) == 0.0


def test_l04_zero_stop_distance_returns_zero(base_symbol):
    """L-04: Stop loss no mesmo preço de entrada deve retornar 0.0."""
    assert calculate_lot_size(equity=10000.0, risk_pct=1.0, entry_price=1.0850, stop_loss=1.0850, symbol_info=base_symbol) == 0.0


def test_l04_tick_size_different_from_point():
    """L-04: Quando tick_size != point, tick_value é por tick_size (não por point)."""
    # Exemplo: DAX40 onde point=0.01, mas tick_size=0.10 e tick_value=2.50
    # 1 ponto inteiro (1.0 de preço) = 10 ticks = $25.00 por lote
    sym = SymbolInfo(
        symbol="DAX40",
        bid=18000.0,
        ask=18001.0,
        point=0.01,
        digits=2,
        spread=1.0,
        min_lot=0.01,
        max_lot=100.0,
        lot_step=0.01,
        tick_value=2.50,
        tick_size=0.10,
    )
    # Risco: 1% de $10.000 = $100
    # Stop distance: 20 pontos de preço (18000 -> 17980)
    # Custo por lote = 20 * (2.50 / 0.10) = 20 * 25.0 = $500 por lote
    # Lote bruto = $100 / $500 = 0.20 lotes
    lot = calculate_lot_size(equity=10000.0, risk_pct=1.0, entry_price=18000.0, stop_loss=17980.0, symbol_info=sym)
    assert lot == 0.20


def test_l04_min_lot_exceeds_allowed_risk_returns_zero(base_symbol):
    """L-04: Se o lote mínimo estourar o risco financeiro, NÃO opera (retorna 0.0)."""
    # Conta pequena: $100 de saldo, risco 1% = $1.00 de risco
    # Stop distance: 50 pips (0.0050) -> Custo para min_lot (0.01):
    # 0.01 lote * (0.0050 * 100000) = $5.00 de risco ($5.00 > $1.00 * 1.1)
    # Não deve forçar 0.01 lote porque arriscaria 5% da conta!
    lot = calculate_lot_size(equity=100.0, risk_pct=1.0, entry_price=1.0850, stop_loss=1.0800, symbol_info=base_symbol)
    assert lot == 0.0

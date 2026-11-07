"""Cálculo dinâmico de tamanho de lote (Position Sizing) para ordens no MetaTrader 5."""

import math
from smc_trader.execution.types import SymbolInfo


def calculate_lot_size(
    equity: float,
    risk_pct: float,
    entry_price: float,
    stop_loss: float,
    symbol_info: SymbolInfo,
) -> float:
    """Calcula o lote exato respeitando o risco percentual do saldo e os limites da corretora.

    Fórmula:
        Risco_Financeiro = Equity * (risk_pct / 100.0)
        Distância_Stop = |entry_price - stop_loss|
        Distância_Pontos = Distância_Stop / point
        Valor_Ponto_1Lote = tick_value / (tick_size / point) = tick_value (ou aproximado por contract_size)
        Lote_Bruto = Risco_Financeiro / (Distância_Pontos * tick_value)
    """
    if equity <= 0:
        return symbol_info.min_lot

    risk_amount = equity * (risk_pct / 100.0)
    sl_distance = abs(entry_price - stop_loss)

    if sl_distance <= 0:
        return symbol_info.min_lot

    # Distância em pontos do ativo
    points = sl_distance / symbol_info.point if symbol_info.point > 0 else sl_distance

    # Custo por ponto para 1 lote padrão
    tick_val = symbol_info.tick_value if symbol_info.tick_value > 0 else 1.0
    cost_per_lot = points * tick_val

    if cost_per_lot <= 0:
        return symbol_info.min_lot

    raw_lot = risk_amount / cost_per_lot

    # Arredonda para o múltiplo de lot_step mais próximo
    step = symbol_info.lot_step if symbol_info.lot_step > 0 else 0.01
    rounded_lot = math.floor(raw_lot / step) * step

    # Aplica limites mínimo e máximo
    if rounded_lot < symbol_info.min_lot:
        rounded_lot = symbol_info.min_lot
    elif rounded_lot > symbol_info.max_lot:
        rounded_lot = symbol_info.max_lot

    # Arredonda para o número de casas decimais do lot_step
    decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 2
    return round(rounded_lot, decimals)

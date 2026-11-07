"""Cálculo dinâmico de tamanho de lote (Position Sizing) para ordens no MetaTrader 5."""

import math
from smc_trader.execution.types import SymbolInfo


def calculate_lot_size(
    equity: float,
    risk_pct: float,
    entry_price: float,
    stop_loss: float,
    symbol_info: SymbolInfo,
    max_risk_tolerance_mult: float = 1.1,
) -> float:
    """Calcula o lote exato respeitando o risco percentual do saldo e os limites da corretora.

    L-04:
    - Se equity <= 0 ou distância do stop <= 0, retorna 0.0.
    - tick_value no MT5 é cotado por tick_size (valor por ponto de preço = tick_value / tick_size).
    - Se min_lot exceder o risco financeiro permitido (com tolerância), NÃO opera e retorna 0.0.
    """
    if equity <= 0 or risk_pct <= 0:
        return 0.0

    risk_amount = equity * (risk_pct / 100.0)
    sl_distance = abs(entry_price - stop_loss)

    if sl_distance <= 0:
        return 0.0

    # L-04: tick_value é por tick_size no MT5
    tick_sz = symbol_info.tick_size if symbol_info.tick_size > 0 else (symbol_info.point if symbol_info.point > 0 else 1e-4)
    tick_val = symbol_info.tick_value if symbol_info.tick_value > 0 else 1.0

    value_per_price_unit = tick_val / tick_sz
    cost_per_lot = sl_distance * value_per_price_unit

    if cost_per_lot <= 0:
        return 0.0

    raw_lot = risk_amount / cost_per_lot

    # Arredonda para o múltiplo de lot_step mais próximo para baixo
    step = symbol_info.lot_step if symbol_info.lot_step > 0 else 0.01
    rounded_lot = math.floor(raw_lot / step) * step

    # Aplica limites mínimo e máximo
    if rounded_lot < symbol_info.min_lot:
        # L-04: Se o lote mínimo estourar o risco além da tolerância, não opera
        min_lot_risk = symbol_info.min_lot * cost_per_lot
        if min_lot_risk > risk_amount * max_risk_tolerance_mult:
            return 0.0
        rounded_lot = symbol_info.min_lot
    elif rounded_lot > symbol_info.max_lot:
        rounded_lot = symbol_info.max_lot

    decimals = max(0, -int(math.floor(math.log10(step)))) if step < 1 else 2
    return round(rounded_lot, decimals)

from typing import Literal


def calculate_fib_level(
    direction: Literal["long", "short"], range_low: float, range_high: float, level: float
) -> float:
    """Calcula o nível de retração de Fibonacci a partir do range.

    Compra (long): retração da perna de alta, medida do topo para o fundo:
      nivel = range_high - level * (range_high - range_low)

    Venda (short): retração da perna de baixa, medida do fundo para o topo:
      nivel = range_low + level * (range_high - range_low)
    """
    diff = range_high - range_low
    if direction == "long":
        return float(range_high - level * diff)
    else:
        return float(range_low + level * diff)

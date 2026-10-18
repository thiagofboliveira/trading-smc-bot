from typing import Literal


def equilibrium(range_low: float, range_high: float) -> float:
    return (range_low + range_high) / 2


def in_discount(
    direction: Literal["long", "short"],
    zone_low: float,
    zone_high: float,
    range_low: float,
    range_high: float,
) -> bool:
    """Compra: meio da zona <= equilíbrio (desconto). Venda: >= (prêmio)."""
    mid = (zone_low + zone_high) / 2
    eq = equilibrium(range_low, range_high)
    return mid <= eq if direction == "long" else mid >= eq

from typing import Literal

from smc_trader.config import CostsConfig


class ExecutionCostsCalculator:
    """Calculador de preços e custos de execução para dados em formato BID (ex: Dukascopy)."""

    def __init__(self, config: CostsConfig) -> None:
        self.config = config

    def get_spread(self, symbol: str) -> float:
        return self.config.spread_pips.get(symbol, 0.0)

    def get_entry_price(
        self, direction: Literal["long", "short"], nominal_bid: float, symbol: str
    ) -> tuple[float, float]:
        """Calcula o preço real de entrada e o custo incorrido.

        Long compra no Ask (Bid + spread + slippage).
        Short vende no Bid - slippage.
        """
        spread = self.get_spread(symbol)
        slippage = self.config.slippage_points
        if direction == "long":
            exec_price = nominal_bid + spread + slippage
            cost = spread + slippage
        else:
            exec_price = nominal_bid - slippage
            cost = slippage
        return float(exec_price), float(cost)

    def get_exit_price(
        self, direction: Literal["long", "short"], nominal_bid: float, symbol: str
    ) -> tuple[float, float]:
        """Calcula o preço real de saída e o custo incorrido.

        Long vende no Bid - slippage.
        Short recompra no Ask (Bid + spread + slippage).
        """
        spread = self.get_spread(symbol)
        slippage = self.config.slippage_points
        if direction == "long":
            exec_price = nominal_bid - slippage
            cost = slippage
        else:
            exec_price = nominal_bid + spread + slippage
            cost = spread + slippage
        return float(exec_price), float(cost)

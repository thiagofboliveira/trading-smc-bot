"""Exemplo de estratégia externa de cruzamento de médias móveis (SDK E2-7, E8-4).

Demonstra a implementação da interface BaseStrategy sem acoplamento ao motor.
Regra Causal (AGENTS.md):
- evaluate recebe apenas candles já fechados.
- O último candle fechado é candles.iloc[-1].
- Se SMA rápida cruzou acima da SMA lenta no fechamento anterior, emite ordem para a próxima barra.
"""

from typing import Any

import pandas as pd

from smc_trader.core.strategy import BaseStrategy
from smc_trader.core.types import OrderIntent, OrderIntentType


class SMACrossoverStrategy(BaseStrategy):
    """Estratégia de cruzamento de médias puramente causal."""

    def __init__(
        self,
        fast_period: int = 9,
        slow_period: int = 21,
        stop_pts: float = 20.0,
        tp_pts: float = 40.0,
    ) -> None:
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.stop_pts = stop_pts
        self.tp_pts = tp_pts

    @property
    def name(self) -> str:
        return "sma_cross_plugin"

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_warmup_bars(self) -> int:
        return self.slow_period + 5

    def evaluate(
        self,
        candles: pd.DataFrame,
        open_position: dict[str, Any] | None = None,
    ) -> list[OrderIntent]:
        if len(candles) < self.get_warmup_bars():
            return []

        # Se já há posição aberta, não abre nova
        if open_position is not None:
            return []

        closes = candles["close"]
        sma_fast = closes.rolling(self.fast_period).mean()
        sma_slow = closes.rolling(self.slow_period).mean()

        prev_fast = float(sma_fast.iloc[-2])
        prev_slow = float(sma_slow.iloc[-2])
        curr_fast = float(sma_fast.iloc[-1])
        curr_slow = float(sma_slow.iloc[-1])
        last_close = float(closes.iloc[-1])

        # Cruzamento de alta
        if prev_fast <= prev_slow and curr_fast > curr_slow:
            return [
                OrderIntent(
                    intent_type=OrderIntentType.PLACE_LIMIT,
                    direction="long",
                    price=last_close,
                    stop_loss=last_close - self.stop_pts,
                    take_profit=last_close + self.tp_pts,
                    expiry_bars=3,
                    comment="SMA Golden Cross",
                )
            ]

        # Cruzamento de baixa
        if prev_fast >= prev_slow and curr_fast < curr_slow:
            return [
                OrderIntent(
                    intent_type=OrderIntentType.PLACE_LIMIT,
                    direction="short",
                    price=last_close,
                    stop_loss=last_close + self.stop_pts,
                    take_profit=last_close - self.tp_pts,
                    expiry_bars=3,
                    comment="SMA Death Cross",
                )
            ]

        return []

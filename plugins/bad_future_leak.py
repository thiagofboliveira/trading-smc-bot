"""Estratégia inválida com viés de olhar o futuro (Lookahead Bias / Violação Causal).

Criada intencionalmente para teste e demonstração do validador anti-viés (E2-8).
Tenta normalizar pelo máximo de toda a série ou muda o sinal histórico.
"""

from typing import Any

import pandas as pd

from smc_trader.core.strategy import BaseStrategy
from smc_trader.core.types import OrderIntent, OrderIntentType


class BadFutureLeakStrategy(BaseStrategy):
    """Estratégia que viola o Princípio P2 e a Regra de Ouro (AGENTS.md)."""

    @property
    def name(self) -> str:
        return "bad_future_leak"

    @property
    def version(self) -> str:
        return "0.0.1-flawed"

    def evaluate(
        self,
        candles: pd.DataFrame,
        open_position: dict[str, Any] | None = None,
    ) -> list[OrderIntent]:
        if len(candles) < 20:
            return []

        # VIOLAÇÃO 1: Normaliza a série inteira pelo máximo absoluto disponível
        # Isso faz com que adicionar um novo candle no futuro altere o valor de todos os candles passados!
        max_val = candles["close"].max()
        last_close = float(candles["close"].iloc[-1])
        ratio = last_close / max_val

        # Se o ratio mudar no futuro quando um novo topo for feito,
        # o sinal na mesma barra do passado muda (violação estrita de invariância de prefixo)
        if ratio > 0.98:
            return [
                OrderIntent(
                    intent_type=OrderIntentType.PLACE_LIMIT,
                    direction="long",
                    price=last_close,
                    stop_loss=last_close - 20.0,
                    take_profit=last_close + 40.0,
                    expiry_bars=2,
                    comment="Invalid Lookahead Normalization",
                )
            ]
        return []

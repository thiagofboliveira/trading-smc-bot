"""Interface pública do SDK para estratégias (E2-1, E2-7).

Garante que qualquer estratégia obedeça ao Princípio P1:
'A estratégia existe em um lugar só' - o mesmo núcleo alimenta backtest,
paper trading e live execution sem divergências.
"""

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd

from smc_trader.core.types import OrderIntent


class BaseStrategy(ABC):
    """Classe base abstrata do SDK para implementação de estratégias."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome identificador da estratégia."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Versão semântica do código da lógica."""
        ...

    @abstractmethod
    def evaluate(
        self,
        candles: pd.DataFrame,
        open_position: dict[str, Any] | None = None,
    ) -> list[OrderIntent]:
        """Avalia a janela de candles fechados e retorna intenções.

        Regra de ouro (AGENTS.md):
        Uma decisão tomada no instante t só pode usar informação disponível em t.
        Todos os candles em 'candles' devem ser barras já FECHADAS.
        """
        ...

    def get_warmup_bars(self) -> int:
        """Número mínimo de barras históricas necessárias para aquecimento."""
        return 50

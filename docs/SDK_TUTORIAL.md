# Tutorial do SDK de Estratégias — SMC Trader

Este tutorial ensina como desenvolver, testar e registrar sua própria estratégia na plataforma SMC Trader utilizando a interface pública do SDK (`BaseStrategy`), sem precisar alterar o código-fonte da aplicação.

---

## 1. Princípios de Design

A plataforma segue princípios estritos de causalidade e governança quantitativa:

1. **Princípio P1 (Núcleo Único):** A estratégia existe em um único lugar. O método `evaluate` alimenta backtest, paper trading e live execution de forma idêntica.
2. **Princípio P2 & Regra de Ouro (`AGENTS.md`):** Uma decisão tomada no instante $t$ só pode utilizar dados conhecidos em $t$.
   - O argumento `candles` recebido pelo método `evaluate` contém **apenas barras já fechadas** (até $t-1$).
   - O último candle fechado é `candles.iloc[-1]`.
   - Ordens emitidas (`OrderIntent`) são executadas pelo broker no candle seguinte ($t$ ou posterior).
   - O stop loss é obrigatoriamente testado na própria barra de entrada pelo motor.

---

## 2. A Interface `BaseStrategy`

Todas as estratégias customizadas devem herdar de `smc_trader.core.strategy.BaseStrategy`:

```python
from abc import ABC, abstractmethod
from typing import Any
import pandas as pd
from smc_trader.core.types import OrderIntent

class BaseStrategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str:
        """Identificador único da estratégia."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Versão semântica (ex: '1.0.0')."""
        ...

    @abstractmethod
    def evaluate(
        self,
        candles: pd.DataFrame,
        open_position: dict[str, Any] | None = None,
    ) -> list[OrderIntent]:
        """Avalia candles fechados e retorna lista de intenções de ordem."""
        ...

    def get_warmup_bars(self) -> int:
        """Número mínimo de barras históricas necessárias para aquecimento dos cálculos."""
        return 50
```

---

## 3. Tipos de Intenção de Ordem (`OrderIntent`)

A estratégia não se comunica diretamente com corretoras. Ela emite intenções puras que o `SimBroker`, `PaperBroker` ou `MT5Broker` executam:

```python
from smc_trader.core.types import OrderIntent, OrderIntentType

intent = OrderIntent(
    intent_type=OrderIntentType.PLACE_LIMIT,  # ou OrderIntentType.PLACE_STOP
    direction="long",                         # "long" ou "short"
    price=18500.0,                            # Preço do limite ou gatilho de stop
    stop_loss=18450.0,                        # Nível estrito de stop loss
    take_profit=18600.0,                      # Alvo de lucro (opcional)
    expiry_bars=3,                            # Validade em barras fechadas
    comment="Pullback na Média",
)
```

---

## 4. Passo a Passo: Criando sua Primeira Estratégia

Crie um arquivo `.py` na pasta `plugins/` (por exemplo, `plugins/minha_estrategia.py`):

```python
from typing import Any
import pandas as pd
from smc_trader.core.strategy import BaseStrategy
from smc_trader.core.types import OrderIntent, OrderIntentType

class MinhaEstrategia(BaseStrategy):
    def __init__(self, periodo_media: int = 20, stop_pts: float = 30.0) -> None:
        self.periodo_media = periodo_media
        self.stop_pts = stop_pts

    @property
    def name(self) -> str:
        return "minha_estrategia"

    @property
    def version(self) -> str:
        return "1.0.0"

    def get_warmup_bars(self) -> int:
        return self.periodo_media + 5

    def evaluate(
        self,
        candles: pd.DataFrame,
        open_position: dict[str, Any] | None = None,
    ) -> list[OrderIntent]:
        # 1. Checa aquecimento
        if len(candles) < self.get_warmup_bars():
            return []

        # 2. Se já existe posição aberta, não abre outra
        if open_position is not None:
            return []

        # 3. Calcula indicador estritamente causal sobre fechamentos passados
        closes = candles["close"]
        sma = closes.rolling(self.periodo_media).mean()

        last_close = float(closes.iloc[-1])
        sma_val = float(sma.iloc[-1])

        # Se fechamento fechou acima da média, envia ordem limite de compra no fechamento
        if last_close > sma_val and float(closes.iloc[-2]) <= float(sma.iloc[-2]):
            return [
                OrderIntent(
                    intent_type=OrderIntentType.PLACE_LIMIT,
                    direction="long",
                    price=last_close,
                    stop_loss=last_close - self.stop_pts,
                    take_profit=last_close + (self.stop_pts * 2.0),
                    expiry_bars=2,
                    comment="Cruzamento Causal",
                )
            ]

        return []
```

---

## 5. Auditoria Anti-Viés Obrigatória

Antes de qualquer estratégia virar um Funcionário no Escritório ou operar em Paper/Live, ela deve ser auditada pelo validador causal da CLI:

```bash
python -m smc_trader.cli strategy check plugins/minha_estrategia.py
```

O auditor verifica automaticamente:
1. **Invariância de Prefixo:** Garante que a adição de novas barras futuras não altere decisões ou operações do passado.
2. **Causalidade $i-1$:** Garante que nenhum indicador ou filtro dependa de fechamentos que ainda não ocorreram na barra de entrada.
3. **Checagem Intrabar de Stop:** Garante que toda ordem executada seja testada contra a mínima/máxima da própria barra de fill.

Se o auditor detectar qualquer violação (como olhar fechamentos futuros ou normalizações centradas), a estratégia é **REPROVADA** e não pode ser cadastrada como funcionário.

---

## 6. Registrando como Funcionário

Uma vez aprovada, cadastre sua estratégia como um novo funcionário na empresa:

```bash
python -m smc_trader.cli employee add \
  --name "Alice Quant" \
  --strategy minha_estrategia \
  --symbol NAS100 \
  --timeframe M15 \
  --capital 10000 \
  --avatar "👩‍💻"
```

Ela iniciará como **Candidata** no escritório. Ao atingir os critérios de aprovação de backtest e estabilidade, pode ser promovida para **Em Experiência** (Paper Trading) e, finalmente, para **Contratada** (Execução Confirmada).

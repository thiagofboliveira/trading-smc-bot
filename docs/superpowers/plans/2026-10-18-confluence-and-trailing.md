# Confluências e Condução (Trailing Stop) — Plano 2c

> **Goal:** Implementar as confluências técnicas (EMA 80, SMA 200, Fibonacci 61,8% e 79,0%), o modo de entrada híbrido completo e o sistema de condução (trailing stop por EMA e por BOS com ativação por 1R / novo BOS).

**Architecture:**
1. **Confluências (`src/smc_trader/confluence/`):**
   - `ConfluenceConfig` em `src/smc_trader/config.py`.
   - `indicators.py`: cálculo de EMA e SMA com warmup adequado e sem look-ahead (utiliza valores fechados até o candle anterior).
   - `fibonacci.py`: cálculo dos níveis de retração de Fibo a partir do range da zona.
   - `evaluator.py`: avaliador que determina se há confluência no momento do toque (`has_confluence(zone, touch_time, touch_candle)`).
2. **Modo Híbrido (`hybrid`):**
   - Plugado no `BacktestEngine`: no primeiro toque, avalia confluência. Se positiva, entra no toque; se negativa, cai para `ARMED` esperando confirmação.
3. **Condução / Trailing Stop (`src/smc_trader/backtest/trailing.py`):**
   - `TrailingConfig` em `src/smc_trader/config.py`.
   - Gerencia a transição de estado da posição: `INACTIVE -> ACTIVATED`.
   - Ativação por `1R`, `on_new_bos` ou `either`.
   - Movimentação do stop:
     - `ema`: fecha posição quando candle fecha além da média.
     - `bos`: avança stop para o extremo do novo BOS a favor.

**Tech Stack:** Python 3.12, pydantic v2, pandas, numpy, pytest.

---

## Tasks do Plano 2c

### Task 1: Modelos de Configuração para Confluências e Trailing Stop
- Estender `src/smc_trader/config.py`:
  - `ConfluenceConfig`: flags `ema80`, `sma200`, `fib618`, `fib790`, `ma_timeframe`, `tolerance`, `min_rules`.
  - `TrailingConfig`: `mode` (none/ema/bos), `ema_period`, `timeframe`, `activation` (either/r_multiple/on_new_bos), `r_threshold`.
  - Integrar em `BacktestConfig` com `extra="forbid"`.
  - Atualizar `config/default.yaml`.
  - Testes unitários de validação.

### Task 2: Indicadores Técnicos e Retração de Fibonacci
- `src/smc_trader/confluence/indicators.py`: funções para EMA e SMA sem look-ahead.
- `src/smc_trader/confluence/fibonacci.py`: cálculo de níveis 61.8% e 79.0% para zonas de compra e venda.
- Testes unitários validando precisão matemática e respeito ao gating temporal.

### Task 3: Avaliador de Confluências e Integração no Modo Híbrido
- `src/smc_trader/confluence/evaluator.py`: `evaluate_confluence(zone, candle, indicators, config) -> bool`.
- Integração no `BacktestEngine` para o modo `hybrid`.
- Testes cobrindo:
  - Entrada no toque quando há confluência.
  - Fallback para confirmação quando não há confluência.
  - Comportamento de Breakers no modo híbrido.

### Task 4: Sistema de Condução e Trailing Stop
- `src/smc_trader/backtest/trailing.py`: `TrailingManager` gerenciando ativação e atualização do stop.
- Condução por `ema` (saída no fechamento além da média).
- Condução por `bos` (avanço do stop para o fundo/topo do novo BOS).
- Integração com o loop do `BacktestEngine`.
- Testes unitários com séries sintéticas para cada variante.

### Task 5: Validação com Dados Reais e Integração CLI
- Testes com dados reais de XAUUSD M1 comparando trades com e sem trailing, com e sem confluência.
- Atualização do `docs/STATUS.md`.

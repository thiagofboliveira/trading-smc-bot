# Motor de Backtest no M1 — Plano 2b

> **Goal:** Construir o motor de backtest próprio, orientado a eventos, que consome as zonas M15 geradas por `analyze()` e executa a leitura intrabar no M1 com os modos de entrada (`touch`, `confirmation`, `hybrid`), modos de stop (`ob`, `swing`, `m1_swing`), alvo fixo 3R, sessões, custos e limites desligáveis, sem look-ahead.

**Architecture:**
O fluxo opera em duas escalas de tempo:
1. **Macro (M15):** `analyze()` detecta a estrutura, zonas OB/FVOB e Breakers no M15 a partir de `candles_m15`.
2. **Micro (M1):** Uma engine orientada a eventos consome os `candles_m1` em ordem cronológica. Para cada candle M1:
   - Verifica sessões e horários permitidos.
   - Atualiza posições abertas (checa stop e alvo intrabar M1; se ambos atingidos no mesmo candle, assume stop).
   - Gerencia armamento de zonas M15:
     - Uma zona passa a ser observada a partir de `zone.created_at`.
     - Detecta o primeiro toque no M1 (dentro de `[zone.low, zone.high]`).
     - Se `touch`: entra no preço de toque (respeitando spread/slippage e custos). Breakers rejeitam entrada por toque puro.
     - Se `confirmation`: após o primeiro toque, arma a zona e aguarda um CHoCH no M1 na direção do setup cujo fechamento esteja dentro de `[zone.low, zone.high]`, confirmado com `pivot_k_ltf`. O armamento expira se a zona for invalidada no M15, ao fim da sessão, ou por timeout configurável.
     - Se `hybrid`: avalia confluências no momento do primeiro toque. Com confluência, entra no toque; sem confluência, cai para o fluxo de confirmação. (No Plano 2b, como as confluências de médias/fibo completas são do Plano 2c, o motor recebe uma função/protocolo de confluência que por padrão retorna `False`, equivalendo a `confirmation` como definido na spec).
   - Respeita travas de produção (máx. 3 trades/dia, pára após 2 stops ou 1 gain), desligáveis no backtest (`limits.enabled = false`).
   - Respeita o limite de 1 posição aberta por símbolo (`max_open_per_symbol = 1`).
   - Calcula métricas completas de performance (número de trades, taxa de acerto, R médio, expectativa matemática, profit factor, max drawdown em R, retorno mensal).

**Tech Stack:** Python 3.12, pydantic v2, pandas, numpy, pytest.

**Specs de referência:**
- `docs/superpowers/specs/2026-10-18-smc-day-trade-design.md`
- `docs/superpowers/specs/2026-10-18-breaker-confluencia-design.md`

---

## Estrutura de Módulos Proposta

```
src/smc_trader/
  backtest/
    __init__.py
    types.py         # Trade, Order, Position, BacktestResult, DailyStats
    costs.py         # Cálculo de custos (spread, comissão, slippage)
    session.py       # Validação de sessões de negociação e horário limite
    limits.py        # Travas diárias (3 trades/dia, 2 stops ou 1 gain)
    engine.py        # BacktestEngine (loop M1, armamento, execução, saídas)
    metrics.py       # Cálculo de métricas e estatísticas em R e moeda
```

---

## Tasks do Plano 2b

### Task 1: Modelos de Configuração e Tipos do Backtest
- [x] Estender `src/smc_trader/config.py` com `BacktestConfig`, `CostsConfig`, `SessionConfig`, `LimitsConfig`, com `extra="forbid"`.
- [x] Atualizar `config/default.yaml` com os novos blocos e valores padrão.
- [x] Criar `src/smc_trader/backtest/types.py` com dataclasses imutáveis: `Trade`, `Position`, `DailyStats`, `BacktestResult`.
- [x] Testes unitários para validação de config e integridade dos tipos.

### Task 2: Módulos de Suporte: Custos, Sessões e Travas Diárias
- [x] `src/smc_trader/backtest/costs.py`: cálculo de slippage, spread e comissão por contrato/lote.
- [x] `src/smc_trader/backtest/session.py`: verificação se timestamp UTC está dentro das janelas de sessão (Londres/NY) e se atingiu horário de fechamento forçado.
- [x] `src/smc_trader/backtest/limits.py`: rastreador de trades por dia, contagem de stops/gains consecutivos, bloqueio após 2 stops ou 1 gain diário, ou 3 trades (quando `enabled=True`).
- [x] Testes unitários para cada módulo cobrindo casos de borda e viradas de dia UTC.

### Task 3: Gerenciamento de Armamento e Entradas no M1 (Touch e Confirmation)
- [x] Lógica de armamento de zonas a partir de `zone.created_at`.
- [x] Primeiro toque: detecção no M1 sem usar `end_time` de mitigação do M15. Breakers rejeitam toque puro.
- [x] Confirmação M1: rastreamento de pivôs M1 (`pivot_k_ltf`) e detecção de CHoCH intrabar M1 com fechamento dentro da zona.
- [x] Cálculo de stops: `ob`, `swing` (da perna M15), `m1_swing` (do swing do CHoCH).
- [x] Alvo 3R (`fixed_r`).
- [x] Testes com séries sintéticas para cada combinação de entrada e stop.

### Task 4: Motor de Eventos M1 (`BacktestEngine`)
- [x] Orquestração do loop M1 cronológico:
  - Atualização de posições existentes (stop e alvo no mesmo candle M1 → assume stop).
  - Fechamento por horário limite diário (se configurado).
  - Avaliação de armamento de novas zonas e abertura de posições (respeitando `max_open_per_symbol` e travas).
- [x] Garantia estrita de não-antecipação (sem look-ahead).
- [x] Testes unitários e de integração com candles M1 e M15.

### Task 5: Métricas de Performance e Relatório de Backtest
- [x] `src/smc_trader/backtest/metrics.py`: cálculo de nº trades, win rate (%), R médio, expectativa matemática, profit factor, drawdown máximo em R e breakdown mensal.
- [x] Integração do CLI `smc backtest`: comando executável para rodar backtest em símbolo e período salvando relatório.
- [x] Testes de integridade matemática das métricas com trades simulados.

### Task 6: Validação de Integração com Dados Reais
- [x] Teste de ponta a ponta com dados reais M1 de XAUUSD carregados via store Parquet.
- [x] Verificação de consistência: número de trades com travas desligadas >= com travas ligadas.
- [x] Atualização do `docs/STATUS.md`.

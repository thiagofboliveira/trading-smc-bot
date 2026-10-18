# Plano 2d — Grade de Exploração e Refinamento SMC

Data: 2026-10-18
Branch: `feat/backtest-engine`
Objetivo: Implementar o executor da grade de parâmetros SMC, divisão cronológica In-Sample (70%) e Out-of-Sample (30%), walk-forward rolante (2 meses treino + 1 mês teste), hash reprodutível de configuração, análise de atribuição por fator (bloco, entrada, stop, trailing, confluências) e CLI `smc grid`.

---

## 1. Contexto e Motivação

Conforme estabelecido nas especificações (`docs/superpowers/specs/2026-10-18-breaker-confluencia-design.md`), o usuário quer testar o catálogo completo de variantes SMC para filtrar e refinar a melhor estratégia (R:R 1:3, acerto >= 35%).
O motor M1 já está completo com suporte a OB, FVOB, Breakers, confluências (EMA80, SMA200, Fibo) e trailing stop (EMA e BOS). Agora precisamos rodar a busca sistemática no histórico real (M1 de março a outubro de 2026) com rigor estatístico contra overfitting.

---

## 2. Componentes

### 2.1. Definições da Grade (`src/smc_trader/backtest/grid.py`)
- Espaço de busca:
  - `blocks_filter`: `["OB"]`, `["FVOB"]`, `["BB"]`, `["OB", "FVOB", "BB"]`
  - `entry_mode`: `touch`, `confirmation`, `hybrid`
    - Regra: Se `blocks_filter == ["BB"]` e `entry_mode == "touch"`, variante inválida (descartada, pois Breaker não aceita toque puro).
  - `stop_mode`: `ob`, `swing`, `m1_swing`
    - Regra: `m1_swing` só é válido com `entry_mode in ("confirmation", "hybrid")`. Se for `touch`, descartado.
  - `trailing_mode`: `none`, `ema`, `bos`
  - `confluence_profile`: variações das regras para `hybrid`:
    - `all_active`: ema80=True, sma200=True, fib618=True, fib790=True
    - `ema_only`: ema80=True, sma200=False, fib618=False, fib790=False
    - `sma_only`: ema80=False, sma200=True, fib618=False, fib790=False
    - `fib_only`: ema80=False, sma200=False, fib618=True, fib790=True
    - `none`: nenhuma regra (hybrid recai 100% para confirmation)
- Hash SHA-256 canônico e determinístico para cada combinação.

### 2.2. Divisão de Dados e Validação Cruzada (`src/smc_trader/backtest/split.py`)
- Split Cronológico:
  - In-Sample (70%): primeiras 70% das barras M1.
  - Out-of-Sample (30%): últimas 30% das barras M1.
- Walk-Forward Rolante:
  - Treino: 60 dias (2 meses).
  - Teste: 30 dias (1 mês).
  - Passo: 30 dias (avanço de 1 mês).
- Critérios de Qualificação:
  - Mínimo de trades (`min_trades >= 30`). Abaixo disso = `"amostra insuficiente"`.
  - Expectativa positiva no OOS ($E > 0$).
  - Cálculo do OOS Performance Drop: $(E_{OOS} - E_{IS}) / E_{IS}$.

### 2.3. Execução Otimizada (`src/smc_trader/backtest/runner.py`)
- Para evitar recomputar repetidamente M15 / pivôs / estruturas em cada combinação:
  - Computa uma vez a análise M15 base (`analyze(c_m15)` com candidatas a OB e Breakers completos).
  - Pré-calcula indicadores M1 (EMA80, SMA200) e pivôs/eventos M1.
  - Executa as combinações filtrando as zonas conforme `blocks_filter` e aplicando as regras de entrada/stop/trailing daquela configuração.
- Rastremento de Breakers precoces (que tocam/invalidam no 1º candle M15).

### 2.4. Análise de Atribuição e Relatório (`src/smc_trader/backtest/attribution.py`)
- Decomposição marginal: média de métricas comparando variantes com e sem cada fator:
  - Impacto do Bloco: OB vs FVOB vs BB vs Todos.
  - Impacto da Entrada: Touch vs Confirmation vs Hybrid.
  - Impacto do Stop: OB vs Swing vs M1 Swing.
  - Impacto do Trailing: None vs EMA vs BOS.
  - Impacto de Confluências: EMA80 vs SMA200 vs Fibo.
- Geração de relatório em Markdown rico e JSON estruturado.

### 2.5. Integração na CLI (`src/smc_trader/cli.py`)
- Comando `smc grid <symbol>`:
  - `--from`, `--to`
  - `--min-trades` (padrão 30)
  - `--out` (caminho para Markdown ou JSON)
  - `--data-root`, `--config`

---

## 3. Plano de Testes
- `tests/test_grid.py`:
  - Geração canônica de combinações e validação de regras de exclusão.
  - Hashing determinístico.
  - Divisão de dados cronológica IS/OOS e janelas de walk-forward.
  - Relatório de atribuição computando deltas de expectativa corretamente.
- Execução em dados reais de `XAUUSD` e geração do relatório final.

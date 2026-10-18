# Status do projeto — Assistente de Day Trade SMC

Atualizado em 2026-10-18. Branch atual: `feat/backtest-engine` (empilhada sobre `feat/breaker-block` → `feat/foundation`; nada foi mesclado nem enviado).

Meta: backtest comparativo de variantes (bloco, entrada, stop, alvo, condução, confluências) para escolher, ao fim do mês, a melhor estratégia e filtros. R:R 1:3, acerto ≥ 35%.

## Já feito

### Plano 1 — Fundação até visualização
- [x] Scaffold (Python 3.12, uv, pydantic + YAML, pytest, CLI `smc`)
- [x] Config (`config.py`, `config/default.yaml`) com `extra="forbid"`
- [x] Dados: Dukascopy (primário), MT5 via Wine (secundário), import CSV, store Parquet atômico, M5/M15 reamostrados do M1
- [x] Dados baixados: 6 símbolos (XAUUSD, EURUSD, GBPUSD, US30, NAS100, BRENT), M1 de 2026-03-01 a 2026-10-16
- [x] Estrutura: pivôs (sem antecipação), BOS/CHoCH
- [x] Zonas: FVG, sweeps de liquidez, premium/discount, OB/FVOB
- [x] Gráfico HTML (`smc chart`) para validar contra a leitura manual

### Plano 1b — Breaker Block
- [x] Breaker rompido com imbalance (FVG), no M15, com tempo de vida e invalidação
- [x] `analyze()` devolve `Analysis(pivots, events, fvgs, sweeps, zones, breakers)`
- [x] Validação em dados reais (sem antecipação em todos os cortes)

### Plano `blocks-filter`
- [x] `zones.blocks_filter: [OB, FVOB, BB]` (ordem canônica, sem repetição, não vazio)
- [x] `smc chart --blocks OB,FVOB,BB`

### Plano 2a — Performance (concluído)
- [x] **Task 1:** oráculo de referência (`tests/reference_impl.py`, nunca editar), `tests/test_equivalence.py`, `tests/test_boundaries.py`, `scripts/bench.py`. 369 testes passando (commit `e728fba`).
- [x] **Task 2:** `build_zones` e `build_breakers` com buscas ordenadas (`np.searchsorted`, lookups O(1) e eliminação de cópias de DataFrame), teste encadeado e teste de não mutação. (commit `58a5bc1`).
- [x] **Task 3:** vetorizar `find_pivots` (`sliding_window_view`) e `find_fvgs` (máscaras booleanas e `flatnonzero`). (commit `dea094e`).
- [x] 466 testes passando na suíte completa (`uv run pytest -q`).

Resultados finais (12k candles M15):
- `find_pivots`: 0,014 s (meta < 0,10 s; antes 0,326 s)
- `find_fvgs`: 0,079 s (meta < 0,10 s; antes 0,390 s)
- `build_zones`: 0,076 s (meta < 0,40 s; antes 1,524 s)
- `build_breakers`: 0,069 s (meta < 0,50 s; antes 7,749 s)
- `analyze`: 0,815 s (meta < 1,50 s; antes 17,214 s)
Em 30k candles M1: `analyze` caiu de 82,6 s para 2,698 s.

### Plano 2b — Motor de backtest no M1 (concluído)
- [x] Entrada por toque (`touch`), por confirmação (`confirmation` com CHoCH no M1) e híbrida (`hybrid`)
- [x] Stops `ob` / `swing` / `m1_swing`; alvo `fixed_r` (3R) e `none`
- [x] Custos: spread por símbolo (`spread_pips`), comissão por lote, slippage
- [x] Sessões configuráveis (`SessionConfig` com janelas Londres/NY UTC) e horário limite de fechamento forçado
- [x] Limites de produção (máx. 3 operações/dia, para após 2 stops ou 1 gain), desligáveis no backtest (`limits.enabled = false`)
- [x] Uma posição aberta por símbolo (`max_open_per_symbol: 1`); ambiguidade intrabar: stop e alvo no mesmo candle M1 → assume stop
- [x] Métricas: nº de trades, taxa de acerto, R médio, expectativa matemática, profit factor, max drawdown em R, resultado mensal
- [x] CLI `smc backtest <symbol>` funcional com saída no terminal e exportação JSON
- [x] 480 testes passando na suíte completa (`uv run pytest -q`)

### Plano 2c — Condução e confluências (concluído)
- [x] Indicadores técnicos: EMA e SMA configuráveis sem look-ahead (`src/smc_trader/confluence/indicators.py`)
- [x] Retração de Fibonacci 61,8% e 79,0% para pernas BOS e breakers (`src/smc_trader/confluence/fibonacci.py`)
- [x] Avaliador de confluências no momento do primeiro toque (`src/smc_trader/confluence/evaluator.py`)
- [x] Modo híbrido (`entry_mode: "hybrid"`): entra no primeiro toque se houver confluência ativa suficiente; caso contrário aguarda confirmação CHoCH no M1
- [x] Trailing stop (`src/smc_trader/backtest/trailing.py`): modos `none`, `ema` e `bos`; ativação por `1r`, `new_bos` ou `either`; trailing dinâmico intrabar
- [x] 487 testes passando na suíte completa (`uv run pytest -q`)

### Plano 2d — Grade e refinamento (concluído)
- [x] Modelos e gerador de combinações válidas da grade (`src/smc_trader/backtest/grid.py`) com 234 variantes canônicas e hash SHA-256 reprodutível.
- [x] Divisão temporal estrita In-Sample (70%) e Out-of-Sample (30%) e walk-forward rolante sem look-ahead (`src/smc_trader/backtest/split.py`).
- [x] Motor de execução da grade (`src/smc_trader/backtest/runner.py`) com pré-computação M1 e gestão O(1) de zonas ativas e trailing stop.
- [x] Cálculo e reporte de Breakers precoces (36,2% tocam no 1º candle M15 após criação, confirmando a spec).
- [x] Análise de atribuição marginal por fator (bloco, entrada, stop, trailing, confluências) e gerador de relatórios Markdown e JSON (`src/smc_trader/backtest/attribution.py`).
- [x] CLI `smc grid <symbol>` integrada e validada em dados reais de XAUUSD (relatório em `out/grid_report_xauusd.md`).
- [x] Estratégia campeã em robustez fora da amostra (OOS): Hash `2e697e30e86b1d24` (OB + Confirmação CHoCH M1 + Stop Swing + Alvo 3R), alcançando **Expectativa +1.55R**, **Taxa de Acerto 60.0%**, **Profit Factor 7.36** e **Max Drawdown 0.9R**.
- [x] 493 testes passando na suíte completa (`uv run pytest -q`) em 56 segundos.

## O que falta

### Plano 3 — Backlog Futuro (deixado anotado para depois)
- [ ] Confluência RSI (divergência), Wyckoff e Elliott
- [ ] Scanner ao vivo e alertas no Telegram (execução manual na v1)
- [ ] Pontos menores adiados nos ledgers do SDD

## Decisões em aberto (suas)
- [ ] Como integrar os branches empilhados: mesclar local, push + PR (não há remote configurado) ou manter como está

## Documentos de referência
- Spec principal: `docs/superpowers/specs/2026-10-18-smc-day-trade-design.md`
- Spec do breaker, entrada híbrida e confluências: `docs/superpowers/specs/2026-10-18-breaker-confluencia-design.md`
- Planos: `docs/superpowers/plans/` (fundação, breaker-block, blocks-filter, performance)

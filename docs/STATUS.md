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

## O que falta

### Plano 2b — Motor de backtest no M1
- [ ] Entrada por toque, por confirmação (CHoCH no M1) e híbrida (primeiro toque; confluência decide)
- [ ] Stops `ob` / `swing` / `m1_swing`; alvo `fixed_r` (3R) ou `none`
- [ ] Custos: spread por símbolo (Dukascopy não tem spread), comissão, slippage
- [ ] Sessões configuráveis e horário limite
- [ ] Limites de produção (máx. 3 operações/dia, para após 2 stops ou 1 gain), desligáveis no backtest
- [ ] Uma posição aberta por símbolo; stop e alvo no mesmo candle → assume stop
- [ ] Métricas: nº de trades, acerto, R médio, expectativa, profit factor, drawdown em R, resultado mensal

### Plano 2c — Condução e confluências
- [ ] Trailing `none` / `ema` (período configurável) / `bos`; ativação por novo BOS, 1R ou o que vier primeiro; timeframe configurável
- [ ] Indicadores EMA80 e SMA200
- [ ] Confluência de Fibonacci 61,8 / 79 com o POI
- [ ] Modo híbrido: confirmação, exceto com confluência (aí entra no toque)

### Plano 2d — Grade e refinamento
- [ ] Runner da grade: `blocks_filter` × `entry_mode` × stop × alvo × trailing × confluências, por símbolo e por mês
- [ ] Divisão IS/OOS 70/30 e walk-forward (2 meses de treino, 1 de teste); mínimo de 30 trades; ≥ 6 meses de M1
- [ ] Hash reprodutível da configuração
- [ ] Relatório de atribuição (com e sem cada fator); reportar à parte os breakers que terminam no 1º candle M15 após a criação (~1/3)

### Plano 3 — Depois
- [ ] Confluência RSI (divergência), Wyckoff e Elliott
- [ ] Scanner ao vivo e alertas no Telegram (execução manual na v1)
- [ ] Pontos menores adiados nos ledgers do SDD

## Decisões em aberto (suas)
- [ ] Como integrar os branches empilhados: mesclar local, push + PR (não há remote configurado) ou manter como está

## Documentos de referência
- Spec principal: `docs/superpowers/specs/2026-10-18-smc-day-trade-design.md`
- Spec do breaker, entrada híbrida e confluências: `docs/superpowers/specs/2026-10-18-breaker-confluencia-design.md`
- Planos: `docs/superpowers/plans/` (fundação, breaker-block, blocks-filter, performance)

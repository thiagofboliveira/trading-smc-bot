# Plano — Assistente de Day Trade SMC (M15 → M1) em Python

## Contexto

O Thiago opera SMC (com Elliott, Wyckoff e divergência de RSI), buscando R:R 1:3 e taxa de acerto ≥ 35%.
O objetivo é um projeto Python que:
1. **automatize a leitura objetiva** do setup dele (macro no M15 → execução no M1);
2. **faça backtest comparativo** de variantes (entrada, stop, alvo, condução) para, ao fim do mês, fechar a estratégia de melhor retorno;
3. em produção (v1), **envie alertas** com o setup pronto — a execução é manual.

Diretório `finance-analysis/` está vazio → projeto novo.

## Decisões já tomadas (pelo usuário)

- **Mercado:** Forex/Commodities via **MT5** rodando sob **Wine no Linux**.
- **Ativos iniciais:** XAUUSD, EURUSD, GBPUSD, US30, NAS100, BRENT (nomes de símbolo configuráveis por corretora).
- **Setup (compra; venda é espelho):**
  - M15: estrutura → viés por BOS → na perna corretiva, **OB/FVOB** = candle contrário em região de *discount* (premium na venda) seguido de imbalance (FVG). Zona é descartada se mitigada ou se houver CHoCH contra o viés no M15.
  - M1: entrada por flag `entry_mode`: `touch` (toque na zona) | `confirmation` (CHoCH no M1 dentro da zona, stop curto).
  - Stop por flag `stop_mode`: `ob` (além do OB) | `swing` (além do fundo/topo da correção) | `m1_swing` (no modo confirmação).
- **Alvo** configurável: `fixed_r` (padrão 3R) | `none` (só condução) — para comparar.
- **Condução (trailing)** configurável: `none` | `ema` (período padrão 20, saída no fechamento além da média) | `bos` (a cada novo BOS a favor, stop vai para o fundo que originou o rompimento).
  - Ativação: `on_new_bos` | `r_multiple` (padrão 1R) | `either` (padrão — o que vier primeiro). Antes disso vale o stop inicial.
  - Timeframe da condução configurável (M1/M5/M15).
- **Horário:** configurável; padrão sessões Londres + NY (ex.: 07:00–16:00 UTC) + horário limite para zerar.
- **Travas de produção:** máx. 3 operações/dia, para após 2 stops ou 1 gain. **No backtest, desligáveis** (`limits.enabled`).
- **Produção v1:** scanner ao vivo + alerta Telegram (zona, entrada, stop, alvo, lote); execução automática fica para depois.

## Decisões minhas (sinalizar ao usuário)

- Python 3.12, `uv`, `pandas`/`numpy`, `pydantic` + YAML para config, `plotly` para gráficos HTML, `pytest`, `httpx` para Telegram.
- **Engine de backtest própria, orientada a eventos** (não vectorbt/backtesting.py): o fluxo multi-timeframe + condução + travas diárias não cabe bem nessas libs.
- **Ponte MT5:** script rodando no Python-Windows sob Wine exporta histórico M1 para Parquet; M5/M15 são **reamostrados a partir do M1** (garante consistência). Para o modo ao vivo, usar `mt5linux` (ponte RPyC Wine↔Linux), com fallback de polling via arquivos.
- **Sem viés de antecipação:** pivô só confirmado após `k` candles à direita fecharem; OB só utilizável após o fechamento do candle que confirma o BOS.
- Ambiguidade intrabar no M1 (stop e alvo no mesmo candle) → assume **stop** (conservador).
- Custos: spread (do histórico ou fixo por símbolo), comissão por lote, slippage configurável. Resultado medido em **R** e em moeda (risco % da conta, lote pelo contrato do símbolo).
- RSI-divergência, Wyckoff (faixa + spring/UTAD) e Elliott entram como **fatores de pontuação da zona** (não gatilhos), registrados em cada trade para análise de atribuição. Elliott é o último a ser implementado.

## Estrutura do projeto

```
finance-analysis/
  pyproject.toml
  config/default.yaml                # estratégia, sessões, custos, travas, símbolos
  config/experiments/grid.yaml       # matriz de variantes a comparar
  scripts/wine/export_history.py     # roda no Python-Windows (Wine) → Parquet
  src/smc_trader/
    config.py                        # modelos pydantic
    data/store.py, data/resample.py, data/mt5_bridge.py
    structure/pivots.py, structure/market_structure.py   # swings, BOS, CHoCH (base comum)
    zones/orderblock.py, zones/fvg.py, zones/liquidity.py, zones/premium_discount.py
    confluence/rsi_divergence.py, confluence/wyckoff.py, confluence/elliott.py
    strategy/setup.py      # M15: gera zonas pendentes com score
    strategy/entry.py      # M1: touch | confirmation
    strategy/management.py # stop inicial, alvo, trailing ema|bos, ativação
    strategy/risk.py, strategy/session.py, strategy/limits.py
    backtest/engine.py, backtest/costs.py, backtest/metrics.py, backtest/runner.py, backtest/report.py
    live/scanner.py, live/alerts.py
    viz/chart.py           # marca estrutura/zonas/trades em HTML
    cli.py                 # export, detect, chart, backtest, grid, live
  tests/                   # candles sintéticos por detector + testes de não-antecipação
```

## Fases de implementação

1. **Base:** scaffold, config, ponte de exportação via Wine, store Parquet, reamostragem M1→M5/M15.
2. **Estrutura:** pivôs, BOS/CHoCH (M15 e M1) com confirmação sem antecipação.
3. **Zonas:** OB/FVOB, FVG, sweep de liquidez, premium/discount, mitigação/invalidação.
4. **Visualização + checkpoint com o usuário:** gráficos HTML com marcações para ele validar contra a leitura manual e calibrar `k` dos pivôs.
5. **Engine de backtest:** entradas (touch/confirmation), stops, alvos, condução (ema/bos + ativação), sessões, travas on/off, custos.
6. **Runner de experimentos + relatório:** grade `entry_mode × stop_mode × target × trailing × ativação` por símbolo; métricas: nº trades, acerto, R médio, expectativa, profit factor, drawdown em R, curva de capital, resultado mensal; split in-sample/out-of-sample (walk-forward).
7. **Confluência:** divergência RSI → Wyckoff → Elliott, com atribuição (acerto/expectativa com vs. sem cada fator).
8. **Ao vivo:** scanner multi-símbolo + alertas Telegram, respeitando as travas diárias.

Na execução, a spec será salva em `finance-analysis/docs/superpowers/specs/2026-10-18-smc-day-trade-design.md` e o plano detalhado gerado via `superpowers:writing-plans`, com TDD por detector.

## Verificação

- `uv run pytest`: testes unitários com candles sintéticos para cada detector (pivô, BOS, CHoCH, OB/FVOB, FVG, sweep, divergência) e para a gestão (trailing, ativação, travas diárias, ambiguidade intrabar).
- **Teste de não-antecipação:** rodar detectores em dados truncados no tempo t deve gerar exatamente as mesmas zonas/sinais até t que a execução completa.
- `smc chart XAUUSD --from ... --to ...` → HTML revisado pelo usuário (checkpoint da fase 4).
- `smc backtest --config config/default.yaml` em 1 mês de XAUUSD → conferir manualmente 5–10 trades no gráfico.
- `smc grid --config config/experiments/grid.yaml` → relatório comparativo; validar que as travas desligadas geram ≥ trades que ligadas.
- Ao vivo: rodar o scanner em conta demo e confirmar recebimento dos alertas no Telegram.

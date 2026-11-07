# Backlog de Correções e Melhorias — SMC Trader

**Data:** 2026-11-07 · **Branch de referência:** `feat/backtest-engine` (commit `f1c411d`)
**Origem:** code review completo do repositório (motor Fibo, motor de zonas SMC, execução MT5, NTSL, scripts).

---

## 1. Resumo

Os resultados que sustentam os modelos oficiais (+809R/ano, 68% de acerto, PF 1,48) vêm de vieses do simulador, não de vantagem real da estratégia. O modo `live` também não envia ordens reais.

Evidências medidas com os dados locais (`data/`, M1 Dukascopy de mar a out/2026, 6 ativos) com o motor corrigido (`scripts/compare_fibo_engines.py`):

| Medição | Antigo | Corrigido | Diferença |
|---|---|---|---|
| Modelo `estrutural` (61,8% / stop 100% / MME8) | +411.8R | −300.2R | −712.0R |
| Modelo `trailing` (61,8% / stop 79% / MME8) | +296.8R | −610.1R | −906.9R |
| Modelo `blindado` (61,8% / stop 100% / trava 2:1) | +362.4R | −300.2R | −662.6R |

**Status atual do backlog:**
- **25 de 61 itens concluídos (~41%)**
- **9 de 22 P0s concluídos (41%)**
- Todos os vieses críticos dos motores Fibo (F-01 a F-10) e zonas SMC (Z-01 a Z-07, Z-10) corrigidos e cobertos por 571 testes automatizados (18 testes anti-viés Fibo, 7 testes invariância de prefixo, 7 testes anti-viés zonas).

**Conclusão:** primeiro corrigir o simulador e revalidar. Só depois investir em execução ao vivo. Pode ser que, sem os vieses, a estratégia não tenha vantagem. Esse resultado também é valioso, porque evita perder dinheiro real.

### Definição de pronto ("funcional e realista")

"Sem viés" absoluto não existe em backtest. O objetivo é tornar cada suposição **explícita, conservadora e testada**. O algoritmo é considerado pronto quando:

1. Existe **um único motor** de estratégia, usado por backtest, paper trading e live.
2. Toda regra anti-viés do backlog tem **teste automatizado** com candles sintéticos.
3. O teste de **invariância de prefixo** (seção 3, B0-4) passa: truncar os dados no tempo *t* não altera nenhuma decisão tomada antes de *t*.
4. Custos (spread bid/ask, comissão, slippage) são aplicados nos **dois lados** de cada trade, para long e short.
5. Parâmetros são escolhidos **só no in-sample / janelas de treino**, e o resultado reportado é walk-forward fora da amostra.
6. O paper trading de no mínimo 8 semanas tem diferença ≤ 15% entre o R esperado (backtest no mesmo período) e o R realizado.
7. Python, MQL5 e NTSL seguem a **mesma especificação escrita** e têm teste de paridade.

---

## 2. Visão geral do backlog

Prioridade: **P0** = bloqueia qualquer conclusão ou uso real · **P1** = necessário para realismo · **P2** = qualidade e evolução.
Esforço: **P** ≤ 0,5 dia · **M** 1–2 dias · **G** 3–5 dias.

| ID | Item | Prioridade | Esforço | Status |
|---|---|---|---|---|
| B0-1 | Motor Fibo único; scripts deixam de ter simuladores próprios | P0 | M | Pendente |
| B0-2 | Refatorar `fibo_ote.py` (long/short unificados, estado tipado) | P0 | M | **Concluído** |
| B0-3 | Suíte de testes anti-viés com candles sintéticos | P0 | M | **Concluído** |
| B0-4 | Teste de invariância de prefixo (detector genérico de lookahead) | P0 | P | **Concluído** |
| F-01 | Entrada na própria barra que confirma o BOS | P0 | P | **Concluído** |
| F-02 | Spread dos shorts não cobrado nas saídas | P0 | P | **Concluído** |
| F-03 | Trava 2:1 assume máxima antes da mínima | P0 | P | **Concluído** |
| F-04 | Expansão da perna e entrada na mesma barra | P0 | P | **Concluído** |
| F-05 | Gap além do stop preenchido no preço do stop | P1 | P | **Concluído** |
| F-06 | Saída por MME executada no próprio fechamento | P1 | P | **Concluído** |
| F-07 | `max_holding_candles` não limita a posição; trades abertos descartados | P1 | P | **Concluído** |
| F-08 | Sem controle de sessão/fim de semana no motor Fibo | P1 | P | **Concluído** |
| F-09 | R-múltiplo fixo (−1,0 / 3,0) em vez de calculado por preço | P2 | P | **Concluído** |
| F-10 | Spread/slippage/comissão hardcoded na CLI e nos scripts | P1 | P | **Concluído** |
| F-11 | Empate em swings (`==max`) diverge do NTSL | P2 | P | Pendente |
| Z-01 | Médias M5/M15 vazam o fechamento do bucket aberto | P0 | P | **Concluído** |
| Z-02 | Candle de entrada não checado contra stop/alvo | P0 | P | **Concluído** |
| Z-03 | Gap além do stop (engine e trailing) | P1 | P | **Concluído** |
| Z-04 | Saída por EMA/sessão tem prioridade sobre o stop tocado | P1 | P | **Concluído** |
| Z-05 | Saída e nova entrada no mesmo candle | P1 | P | **Concluído** |
| Z-06 | `commission_per_lot` ignorado | P1 | P | **Concluído** |
| Z-07 | Sem risco mínimo: R explode | P1 | P | **Concluído** |
| Z-08 | Zonas não acompanhadas durante posição aberta | P2 | M | Pendente |
| Z-09 | Confirmação CHoCH usa candle seguinte; perde sinal em gaps | P2 | P | Pendente |
| Z-10 | Estado de limites vaza entre `run()`; off-by-one em breakers; hook com candle completo | P2 | P | **Concluído** |
| M-01 | Estratégia campeã escolhida pelo OOS | P0 | P | Pendente |
| M-02 | Walk-forward de verdade (otimiza no treino, testa na janela seguinte) | P0 | M | Pendente |
| M-03 | Recalcular e renomear todos os modelos oficiais | P0 | M | Pendente |
| M-04 | Anualização pelo período real dos dados | P1 | P | Pendente |
| M-05 | Métricas de portfólio realistas (sobreposição, % de equity) | P1 | M | Pendente |
| M-06 | Controle de múltiplos testes e robustez estatística | P1 | M | Pendente |
| M-07 | Spread real com candles bid **e** ask da Dukascopy | P1 | M | Pendente |
| M-08 | Baseline de entradas aleatórias e alarmes de sanidade | P1 | P | Pendente |
| M-09 | Versionar dados e reprodutibilidade dos relatórios | P2 | P | Pendente |
| L-01 | Modo `live` usa `MockMT5Client` | P0 | G | Pendente |
| L-02 | Live executa a estratégia de zonas, não a Fibo; params ignorados | P0 | G | Pendente |
| L-03 | Decisões tomadas no candle M1 ainda em formação | P0 | P | Pendente |
| L-04 | Sizing: `tick_value` por point e lote mínimo acima do risco | P0 | P | Pendente |
| L-05 | Limites diários não recebem stops/gains reais | P1 | P | Pendente |
| L-06 | Entrada a mercado no close em vez de ordem limite no nível | P1 | M | Pendente |
| L-07 | Estado só em memória; sem reconciliação nem idempotência | P1 | M | Pendente |
| L-08 | Ponte HTTP sem autenticação; EA frágil (FOK, JSON manual) | P1 | M | Pendente |
| L-09 | Trailing EMA não implementado no live; `should_exit` ignorado | P1 | P | Pendente |
| L-10 | Kill switch e limites de perda de conta | P1 | M | Pendente |
| L-11 | Observabilidade e diário de trades | P2 | M | Pendente |
| N-01 | Stop no NTSL não é ordem real (só `ClosePosition` no candle) | P0 | P | Pendente |
| N-02 | Entrada NTSL a mercado; preço de entrada registrado errado | P0 | P | Pendente |
| N-03 | Especificação única + teste de paridade NTSL/Python | P1 | M | Pendente |
| N-04 | Day trade B3: horário de zeragem e custos reais | P1 | P | Pendente |
| N-05 | Perna NTSL nunca expira; `.txt` duplicados | P2 | P | Pendente |
| D-01 | Ingestão de dados B3 (WIN/WDO) por CSV do Profit ou MT5 de corretora | P0 | M | Parcial |
| D-02 | Série contínua de WIN/WDO com rolagem de contrato | P0 | M | Pendente |
| D-03 | Histórico mais longo para os ativos Dukascopy (≥ 5 anos) | P1 | P | **Concluído** |
| D-04 | Validação de qualidade dos dados (buracos, duplicatas, fuso, sessão) | P1 | P | **Concluído** |
| D-05 | Custos e especificação dos contratos B3 por símbolo | P1 | P | **Concluído** |
| H-01 | Credenciais em `test.env` versionadas | P0 | P | Pendente |
| H-02 | Teste quebrado: instrumento DAX40 (`DEU.IDX/EUR`) | P1 | P | **Concluído** |
| H-03 | Documentação afirma "100% auditado" e métricas não reproduzíveis | P1 | P | Pendente |
| H-04 | CI com testes, lint e tipos | P1 | P | Pendente |
| H-05 | Arquivar relatórios gerados pelo motor enviesado | P2 | P | Pendente |
| H-06 | Pequenos ajustes (UI path check, nomes de scripts, imports) | P2 | P | Pendente |

---

## 3. Épico 0 — Fundação: motor único e testes

### B0-1 · Motor Fibo único (P0, M)
**Problema:** existem pelo menos 7 simuladores copiados em `scripts/` que já divergem entre si. Os números oficiais vêm de `simulate_audited` em [`scripts/recalibrate_all_variables_audited.py`](../scripts/recalibrate_all_variables_audited.py), e não de [`fibo_ote.py`](../src/smc_trader/strategies/fibo_ote.py). Divergências encontradas:
- o simulador do script cobra meio spread, o motor cobra spread inteiro;
- o script fixa R em +1/−1, o motor calcula pelo preço.

Scripts afetados:
- `test_fibo_partials.py`
- `test_fibo_breakeven.py`
- `test_fibo_pyramiding.py`
- `optimize_fibo_ote_grid.py`
- `test_fibo_ma_confluence_trailing.py`
- `test_smc_fibonacci_backtest.py`
- `recalibrate_all_variables_audited.py`

**Correção:**
- `FiboOTEStrategy` passa a ser a única implementação.
- Variações (parciais, breakeven, pirâmide) viram opções de config no motor.
- Os scripts apenas importam e orquestram.

**Aceite:** nenhum arquivo em `scripts/` contém loop de simulação próprio (`for i in range(k + 1, n - 1)`).

### B0-2 · Refatorar `fibo_ote.py` (P0, M)
**Problema:** são oito blocos quase idênticos de `FiboTrade(...)` (long/short × motivo de saída). Isso facilitou bugs assimétricos como o F-02. O estado está espalhado em variáveis soltas e num `dict` (`active_leg`).

**Correção:**
- Representar a direção como `d = +1/-1` e tratar long e short com o mesmo código.
- Usar dataclasses `Leg` e `Position`.
- Criar uma função única `_close(position, price, reason, bar)`.
- Separar `signal` (detecção de perna/entrada) de `fills` (modelo de execução e custos).

**Aceite:** os testes de B0-3 passam; o arquivo cai para cerca de metade do tamanho.

### B0-3 · Suíte de testes anti-viés (P0, M) — CONCLUÍDO
**Problema:** não existe nenhum teste para `fibo_ote.py`, o motor "oficial".

**Correção:** criar `tests/test_fibo_ote.py` com candles sintéticos construídos à mão, um teste por regra:
- [x] Barra do BOS que toca 70,5% não gera trade (F-01).
- [x] Short paga spread na entrada **e** na saída, em todos os motivos de saída (F-02).
- [x] Barra que toca +2R e o stop original resulta em −1R (F-03).
- [x] Nova máxima e toque na entrada na mesma barra não usam a máxima nova (F-04).
- [x] Gap de abertura além do stop sai no `open` (F-05).
- [x] Saída por MME sai no `open` da barra seguinte (F-06).
- [x] Posição aberta no fim dos dados aparece como `END_OF_DATA` e tempo máximo de posição (F-07).
- [x] Simetria: espelhar os preços (x → −x) produz os mesmos R para long e short.

**Status:** Implementado em `tests/test_fibo_ote.py` (18 testes passando em 0.8s).

### B0-4 · Teste de invariância de prefixo (P0, P) — CONCLUÍDO
**Ideia:** é o detector genérico de lookahead mais barato que existe.
- Rode o backtest com os dados completos e com os dados truncados em vários instantes *t*.
- Todo trade com `entry_time < t` precisa ter a mesma entrada nas duas execuções.
- Todo trade com `exit_time < t` precisa ser idêntico nas duas execuções.

Aplicar aos dois motores (Fibo e zonas SMC).

**Aceite:** o teste roda em CI com ≥ 20 cortes aleatórios sobre um ativo real.
**Status:** Implementado em `tests/test_prefix_invariance.py` (7 testes paramétricos sobre dados sintéticos e reais XAUUSD/NAS100, todos verdes).

---

## 4. Épico 1 — Motor Fibo OTE (`src/smc_trader/strategies/fibo_ote.py`)

### F-01 · Entrada na barra que confirma o BOS (P0, P)
**Onde:** [`fibo_ote.py:283-344`](../src/smc_trader/strategies/fibo_ote.py#L283-L344).

**Problema:**
- O BOS só é conhecido no **fechamento** da barra *i* (`closes[i] > last_sh_price`).
- Na mesma iteração, a entrada dispara com `lows[i] <= fibo_entry`, mínima que ocorreu **antes** desse fechamento.

**Impacto medido:** remove todo o resultado positivo (`estrutural`: +404R → −53R). O mesmo defeito existe em `simulate_audited`.

**Correção:** a perna só pode gerar entrada a partir da barra *i+1* (guardar `bos_idx` e exigir `i > bos_idx`).

### F-02 · Spread dos shorts não cobrado nas saídas (P0, P)
**Onde:** [`fibo_ote.py:229-230`](../src/smc_trader/strategies/fibo_ote.py#L229-L230), [`257-258`](../src/smc_trader/strategies/fibo_ote.py#L257-L258), [`392-394`](../src/smc_trader/strategies/fibo_ote.py#L392-L394).

**Problema:**
- Os dados são bid. O short entra na bid, o que está correto.
- Stop, alvo e MME são comparados com a **bid**, quando a recompra acontece no **ask**.
- O stop do short fica um spread mais folgado, e alvo e saída por MME não pagam spread.
- Em todos os ativos, os shorts rendem bem mais que os longs.

**Impacto medido:** ≈ 230R indevidos em 7 meses (o spread custa 0,15–0,30R por trade).

**Correção:** modelo de execução explícito:
- `ask = bid + spread`.
- Long: entra quando `ask_low <= limite` e sai na bid.
- Short: entra na bid e sai quando `ask_high >= stop`, `ask_low <= alvo` ou no `ask` de saída.

Depois de M-07, usar candles ask reais em vez de spread fixo.

### F-03 · Trava 2:1 assume máxima antes da mínima (P0, P)
**Onde:** [`fibo_ote.py:149-158`](../src/smc_trader/strategies/fibo_ote.py#L149-L158).

**Problema:** o stop é movido para +1R com `c_high` da barra e checado com `c_low` da **mesma** barra. Uma barra que tocou +2R e também o stop original é registrada como **+1R** (deveria ser −1R no modo conservador).

**Correção:**
1. Na barra *i*, checar o stop vigente no início da barra.
2. Só então avaliar o gatilho da trava; o stop novo vale a partir de *i+1*.

Alternativa melhor: resolver a ordem pelo caminho M1 (seção 10).

### F-04 · Expansão da perna e entrada na mesma barra (P0, P)
**Onde:** [`fibo_ote.py:328-344`](../src/smc_trader/strategies/fibo_ote.py#L328-L344).

**Problema:** a máxima da barra *i* atualiza o topo da perna (e portanto o nível de entrada), e a mínima da **mesma** barra é testada contra o nível novo. O código assume que a máxima veio antes da mínima.

**Correção:**
1. Testar a entrada contra os níveis calculados **até a barra *i−1***.
2. Só depois expandir a perna com a máxima/mínima de *i*.

### F-05 · Gap além do stop (P1, P)
**Onde:** [`fibo_ote.py:176-203`](../src/smc_trader/strategies/fibo_ote.py#L176-L203) e o bloco equivalente do short.

**Problema:** a saída é sempre em `sl_price`, mesmo quando a barra abre além dele (fim de semana, notícia, abertura de sessão).

**Correção:**
- Long: preço de saída = `min(open, sl)`.
- Short: preço de saída = `max(open_ask, sl)`.
- Registrar R < −1 quando acontecer.

### F-06 · Saída por MME no próprio fechamento (P1, P)
**Problema:** o sinal (close abaixo da MME) só existe no fechamento, mas a saída é registrada exatamente nesse close.

**Correção:** sair no `open` da barra *i+1* (ordem a mercado após o sinal). Se quiser manter a saída no close, documentar como suposição de ordem MOC e testar a sensibilidade.

### F-07 · Tempo de posição e trades abertos (P1, P)
**Onde:** [`fibo_ote.py:324`](../src/smc_trader/strategies/fibo_ote.py#L324).

**Problema:**
- `max_holding_candles` expira a **perna em espera**, não a posição.
- Com `trailing_only` e trailing só no lucro, uma posição pode ficar aberta indefinidamente.
- Posições abertas no fim dos dados são descartadas em silêncio (viés de sobrevivência).

**Correção:**
- Dividir em `max_leg_candles` e `max_position_candles`.
- Fechar a posição no fim dos dados com motivo `END_OF_DATA`.

### F-08 · Sessão e fim de semana (P1, P)
**Problema:** o motor Fibo não tem filtro de sessão nem fechamento forçado. Posições atravessam fim de semana e rollover.

**Correção:** reutilizar `SessionManager` do motor de zonas com:
- janela de entrada;
- horário de zeragem;
- zeragem antes do fechamento de sexta-feira.

### F-09 · R-múltiplo fixo (P2, P)
**Problema:** `INTRABAR_STOP_LOSS` usa `r_multiple=-1.0` fixo e o alvo `3R` usa `cfg.target_r` fixo. Com spread, slippage e gap, o R real é diferente.

**Correção:** calcular sempre `R = d × (saída − entrada) / risco_inicial`, já líquido de custos.

### F-10 · Custos hardcoded (P1, P)
**Onde:** [`cli.py`](../src/smc_trader/cli.py) (`_cmd_fibo_backtest`) e cada script.

**Correção:** tabela única de custos por símbolo em `config/` (spread típico, comissão por lote, slippage em pontos), com fonte e data. `FiboOTEConfig` recebe slippage e comissão.

### F-11 · Empate em swings (P2, P)
**Problema:**
- Python: `highs[i] == max(janela)`, ou seja, empates contam como swing.
- NTSL: comparações estritas.

Isso gera topos diferentes nas duas plataformas.

**Correção:** decidir a regra na especificação (N-03) e implementar igual nas duas.

---

## 5. Épico 2 — Motor de zonas SMC (`src/smc_trader/backtest/`)

O agente de revisão confirmou os itens Z-01 a Z-05 com scripts mínimos. Os detectores estão corretos e sem lookahead: pivôs, BOS/CHoCH, FVG, sweeps, OB/FVOB e breaker.

### Z-01 · Lookahead nas médias M5/M15 (P0, P)
**Onde:** [`engine.py:30-40`](../src/smc_trader/backtest/engine.py#L30-L40).

**Problema:**
- `resample_ohlc` rotula o bucket pela abertura (`label="left"`).
- O `ffill` para M1 entrega o fechamento do M15 a partir do 1º minuto do bucket.
- O `shift(1)` em M1 atrasa só 1 minuto.

**Correção:** indexar a média pelo `close_time` do bucket, ou aplicar `shift(1)` na série agregada **antes** do `ffill`.

### Z-02 · Candle de entrada não checado (P0, P)
**Onde:** [`engine.py:142-311`](../src/smc_trader/backtest/engine.py#L142-L311).

**Problema:** nos modos touch e hybrid, a posição abre intrabar e stop e alvo só são verificados a partir do candle seguinte. Caso confirmado: o trade deu +0,3R quando o correto era −1R.

**Correção:** checar o stop no candle de entrada, com a mesma regra conservadora de F-01/F-03.

### Z-03 · Gap além do stop (P1, P)
**Onde:** `engine.py:191-222` e `trailing.py` (saída em `current_stop`).

**Correção:** igual a F-05.

### Z-04 · Prioridade das saídas (P1, P)
**Onde:** `engine.py:145-185` e `trailing.py`.

**Problema:** a saída por EMA e o fechamento de sessão saem no `close`, mesmo quando a mínima do candle já tocou o stop.

**Correção:** ordem de avaliação: stop/gap → alvo → saídas por fechamento (EMA, sessão).

### Z-05 · Saída e reentrada no mesmo candle (P1, P)
**Problema:** no mesmo candle, a posição fecha pelo stop e uma nova abre no `open`, que aconteceu antes da saída. Na prática são duas posições simultâneas.

**Correção:** proibir nova entrada no candle em que houve saída, ou permitir só a partir de *i+1*.

### Z-06 · Comissão ignorada (P1, P)
**Onde:** `costs.py` e `config.py:64`.

**Problema:** o campo `commission_per_lot` existe na config, mas nenhum código o usa.

**Correção:** converter a comissão em pontos por lote e descontar do R.

### Z-07 · Risco mínimo (P1, P)
**Problema:** no modo confirmation com stop `ob`, o risco pode ficar igual a spread + slippage. Saídas sem teto viram dezenas de R e dominam as métricas.

**Correção:**
- Exigir `risco ≥ max(k × spread, m × ATR)`.
- Remover o fallback morto `risk = 0.0001`.

### Z-08 · Zonas durante posição aberta (P2, M)
**Problema:** zonas tocadas enquanto há posição continuam `UNTOUCHED` e depois geram "primeiro toque" já mitigado.

**Correção:** atualizar o estado das zonas a cada candle, independentemente de haver posição.

### Z-09 · Confirmação CHoCH (P2, P)
**Problema:**
- Busca por `t == open` do candle seguinte ao CHoCH, o que adiciona 1 candle de atraso.
- Se o minuto seguinte não existir no dado, o sinal se perde.

**Correção:** indexar o evento pelo candle que o confirma e usar o `close` dele.

### Z-10 · Pequenos vazamentos (P2, P)
- `limits_tracker` persiste entre chamadas de `run()`: recriar a cada execução.
- `compute_breaker_stats` testa `idx+1` em vez de `idx`, e os dois ramos do ternário são idênticos.
- `confluence_fn` recebe o candle M1 completo (inclusive o close) numa decisão intrabar. Passar só dados até *i−1*.

---

## 6. Épico 3 — Metodologia de validação

### M-01 · Seleção pelo OOS (P0, P)
**Onde:** [`attribution.py:66-68`](../src/smc_trader/backtest/attribution.py#L66-L68) e [`runner.py:151-152`](../src/smc_trader/backtest/runner.py#L151-L152).

**Problema:** a campeã (PF 7,36) foi a melhor expectativa OOS entre 234 variantes. Com essa escolha, o OOS deixa de ser fora da amostra.

**Correção:**
1. Ranquear e escolher **só pelo IS**.
2. Reportar o OOS apenas da escolhida, junto com a distribuição OOS de todas as variantes.

### M-02 · Walk-forward real (P0, M)
**Problema:** `train_df` nunca é usado em `split.py` e no runner. Hoje são só métricas por janela de teste. O STANDARDS exige WFE ≥ 0,70, e isso nunca foi medido.

**Correção:**
- Janelas rolantes (ex.: 6 meses de treino, 1 de teste).
- Em cada janela de treino, escolher os parâmetros e testar na janela seguinte.
- Concatenar os testes e calcular WFE = retorno anualizado OOS / retorno anualizado IS.

### M-03 · Recalcular e renomear os modelos (P0, M)
**Problema:** todos os YAMLs de `config/models/` e o `production.yaml` carregam métricas do motor enviesado no próprio nome (`_68pct_809R_1.48pf_30dd`). Quando a métrica muda, o nome passa a mentir.

**Correção:**
- Nomear pelo conceito + versão (`smc_fibo_estrutural_v3`).
- Manter as métricas dentro do YAML, geradas automaticamente pelo relatório, com data, hash dos dados e commit.
- Atualizar a convenção no STANDARDS.

**Aceite:** todos os modelos reexecutados após F-01..F-08 e M-01/M-02. Modelos sem vantagem OOS são arquivados.

### M-04 · Anualização (P1, P)
**Onde:** [`recalibrate_all_variables_audited.py:276`](../scripts/recalibrate_all_variables_audited.py#L276) (`r_total / 2.0`).

**Correção:** anualizar pelo intervalo real (`(t_fim − t_inicio) / 365,25 dias`).

### M-05 · Métricas de portfólio (P1, M)
**Problema:**
- O R é somado entre 7 ativos ordenados pela **entrada**, ignorando posições simultâneas e correlação (NAS100/US30, EURUSD/GBPUSD).
- "809R/ano" a 1% de risco implicaria +809% ao ano, número que precisa ser confrontado.

**Correção:** simulação de conta com:
- equity em % e sizing por risco;
- limite `max_open_trades_total`;
- drawdown em % ordenado por **saída**.

Reportar retorno anual %, max DD %, tempo em DD, Sharpe/Sortino diários, MAR, % de meses positivos e quebra por ativo e por direção.

### M-06 · Robustez estatística (P1, M)
- Registrar o **número de combinações testadas** em todo relatório.
- Aplicar Deflated Sharpe Ratio ou White's Reality Check (ou, no mínimo, Bonferroni na escolha).
- Rodar Monte Carlo da ordem dos trades para gerar uma distribuição de drawdown (percentil 95).
- Testar a sensibilidade de parâmetros vizinhos (ex.: 0,68 e 0,72 em vez de 0,705). Um pico isolado é sinal de overfit.
- Exigir ≥ 200 trades OOS por configuração.

### M-07 · Spread real bid/ask (P1, M)
**Problema:** o spread é fixo por símbolo, mas o real varia por horário (rollover, abertura, notícias). Como o spread custa 15–30% do R, isso é decisivo.

**Correção:** baixar também os candles **ask** da Dukascopy (o feed tem os dois lados), guardar como `{SYM}_M1_dukascopy_ask.parquet` e usar no modelo de execução de F-02.

### M-08 · Baseline aleatório e alarmes (P1, P)
- **Baseline:** entradas aleatórias nos mesmos horários, com a mesma distribuição de stop e as mesmas regras de saída. A estratégia precisa bater esse baseline com significância.
- **Alarmes automáticos no relatório:** PF > 2,5; acerto > 65% com payoff < 1; diferença long/short > 2× no mesmo ativo; mais de 20% dos trades com saída na barra de entrada. Cada alarme exige investigação antes de publicar o modelo.

### M-09 · Reprodutibilidade (P2, P)
**Problema:** os dados locais cobrem mar–out/2026, mas os modelos citam "2 anos / 4,95M candles" que não estão no repositório nem descritos.

**Correção:** todo relatório registra o hash SHA-256 de cada parquet, o período, o commit git e o hash da config. `out/backtests` já tem infraestrutura de exportação para isso.

---

## 7. Épico 4 — Execução ao vivo MT5

### L-01 · O modo `live` é mock (P0, G)
**Onde:** [`cli.py:381`](../src/smc_trader/cli.py#L381).

**Problema:** o modo bridge sobe `BridgeEAServer`, mas entrega `MockMT5Client()` ao motor. Nenhum comando chega ao EA, e não existe cliente que implemente `BaseMT5Client` sobre a ponte.

**Correção:**
- Implementar `BridgeMT5Client(BaseMT5Client)` (fila de comandos com `cmd_id`, espera pelo `order_result`, telemetria de candles/conta/posições), ou um cliente nativo `MetaTrader5`.
- O modo live **falha fechado**: não inicia se o cliente for mock.

### L-02 · Live roda a estratégia errada (P0, G)
**Onde:** [`cli.py:347`](../src/smc_trader/cli.py#L347) e [`live_engine.py`](../src/smc_trader/execution/live_engine.py).

**Problema:**
- `production.yaml` define modelos Fibo, mas o motor executa a estratégia de zonas OB/CHoCH.
- `fibo_entry`, `fibo_stop`, `pivot_k`, `trailing_exit_ma` e `profit_lock` são ignorados em silêncio.

**Correção:**
- Estratégia em formato **incremental** (`on_bar(bar) -> list[Order]`), compartilhada por backtest, paper e live (seção 10).
- Validar `production.yaml` com pydantic `extra="forbid"`.

**Aceite:** um teste de replay mostra que o live, alimentado barra a barra com dados históricos, gera exatamente os mesmos sinais do backtest.

### L-03 · Candle em formação (P0, P)
**Onde:** [`live_engine.py:139`](../src/smc_trader/execution/live_engine.py#L139) e [`184`](../src/smc_trader/execution/live_engine.py#L184).

**Problema:** `candles_m1.iloc[-1]` é o candle ainda aberto. Pivôs, CHoCH e toques são avaliados sobre dados que ainda vão mudar.

**Correção:** descartar a barra corrente e agir só quando uma barra nova fechar (guardar `last_processed_bar`).

### L-04 · Sizing (P0, P)
**Onde:** [`sizing.py:35`](../src/smc_trader/execution/sizing.py#L35) e [`49`](../src/smc_trader/execution/sizing.py#L49).

**Problema:**
- `tick_value` é tratado como valor por *point*, mas no MT5 ele é por *tick_size*. Em ativos com `tick_size ≠ point`, o risco é multiplicado.
- Quando o lote calculado é menor que `min_lot`, o código força `min_lot` e estoura o risco.
- `equity ≤ 0` também devolve `min_lot`.

**Correção:**
- `valor_por_preço = tick_value / tick_size`.
- Se `min_lot` exceder o risco permitido, **não operar** e registrar o motivo.
- `equity ≤ 0` resulta em lote 0.

Incluir `tick_size` em `SymbolInfo`.

### L-05 · Limites diários (P1, P)
**Onde:** [`live_engine.py:125`](../src/smc_trader/execution/live_engine.py#L125).

**Problema:**
- `record_trade` só é chamado no fechamento forçado. Stops e gains da corretora não contam, então "parar após 2 stops" nunca acontece.
- `max_open_trades_total` do YAML não é aplicado.

**Correção:** alimentar o tracker pelo histórico de negócios (deals) da conta e aplicar o limite global de posições.

### L-06 · Ordem limite no nível Fibo (P1, M)
**Problema:** a entrada é a mercado no `close`, enquanto o backtest assume fill exato no nível de retração.

**Correção:**
- Ordem **limite** pendente no nível, com expiração igual à da perna.
- SL e TP anexados no servidor.
- Cancelar a ordem se a perna for invalidada.

### L-07 · Estado e reconciliação (P1, M)
**Problema:** zonas consumidas e pernas ativas ficam só em memória. Depois de reiniciar, o motor pode reentrar nas mesmas zonas.

**Correção:**
- Persistir o estado (SQLite/JSON) a cada barra.
- Na inicialização, reconciliar com posições e ordens abertas da conta.
- Usar `cmd_id` idempotente para não duplicar ordens em retry.

### L-08 · Ponte e EA (P1, M)
**Problemas:**
- Bind em `0.0.0.0` sem autenticação.
- JSON parseado com `StringFind` no EA.
- `ORDER_FILLING_FOK` fixo ([EA:28](../mql5/SMC_Bridge_EA.mq5#L28)), rejeitado por muitas corretoras.
- O EA não confere retcodes.

**Correção:**
- Python: bind padrão `127.0.0.1`, token compartilhado em header, validação de payload.
- EA: modo de preenchimento lido de `SYMBOL_FILLING_MODE`, parser JSON robusto (`JAson.mqh` ou similar), log de retcode e **heartbeat**. Se o Python ficar silencioso por N segundos, o EA cancela pendentes e alerta.

### L-09 · Trailing no live (P1, P)
**Problema:** só o modo `bos` é tratado; `ema` é ignorado. O `should_exit` retornado por `check_and_update` é descartado.

**Correção:** coberta por L-02 (lógica única). Até lá, honrar `should_exit` e implementar o modo `ema`.

### L-10 · Kill switch (P1, M)
- Perda diária máxima em % do equity, que fecha tudo e bloqueia até o dia seguinte.
- Máximo de perdas consecutivas.
- Bloqueio se o spread corrente for maior que X vezes o típico.
- Bloqueio em janelas de notícia de alto impacto.
- Bloqueio se os dados estiverem atrasados (última barra mais velha que 2 minutos).

### L-11 · Observabilidade (P2, M)
- Logs estruturados (JSON) por decisão: sinal, ordem, fill e motivo de não operar.
- Diário de trades com o slippage real (preço pedido × preenchido).
- Alertas no Telegram (já previstos no backlog do STATUS).
- Relatório diário comparando o live com o backtest do mesmo dia.

---

## 8. Épico 5 — NTSL / Profit (`nelogica/`)

### N-01 · Stop real (P0, P)
**Problema:** o stop é `Se (Minima <= precoStop) Entao ClosePosition`, avaliado no candle. Não existe ordem de stop na bolsa:
- se a plataforma travar ou desconectar, a posição fica sem proteção;
- em backtest, a saída acontece após o candle, a um preço pior que o stop.

**Correção:** enviar a cada barra, enquanto posicionado, ordens de proteção (ex.: `SellToCoverStop(precoStop)` / `BuyToCoverStop(precoStop)`) e de alvo (`SellToCoverLimit(precoAlvo)` / `BuyToCoverLimit(precoAlvo)`). Conferir as assinaturas no manual NTSL da versão do Profit em uso.

### N-02 · Entrada a mercado (P0, P)
**Problema:**
- `BuyAtMarket` executa no preço corrente, não em `nivelEntrada`.
- `precoEntrada := nivelEntrada` registra um preço que não foi o executado.
- O filtro de trailing `Fechamento > precoEntrada` compara contra esse preço falso.

**Correção:**
- Ordem limite no nível (ex.: `BuyLimit(nivelEntrada)` / `SellShortLimit(nivelEntrada)`) enquanto a perna estiver ativa.
- `precoEntrada` passa a vir do preço médio da posição (ex.: `BuyPrice` / `SellPrice`).

### N-03 · Especificação única e paridade (P1, M)
**Problema:** o NTSL difere do Python em:
- fractal estrito;
- BOS exigindo cruzamento;
- filtro de perna por volatilidade, não por spread;
- perna sem expiração;
- saída por MME exigindo cruzamento;
- entrada a mercado;
- stop por fechamento.

Os resultados no Rico Trader (42–46% de acerto, 3 meses) não validam os 68% do Python.

**Correção:**
1. Escrever `docs/SPEC_SMC_FIBO.md` com cada regra em pseudocódigo.
2. Implementar a spec igual em Python, MQL5 e NTSL.
3. Teste de paridade: exportar a lista de operações do Profit para WIN/WDO num período e rodar o Python nos mesmos dados (importados via `import-csv`). Exigir ≥ 95% dos trades coincidentes em horário e direção.

### N-04 · Day trade B3 (P1, P)
- Horário limite de entrada e horário de zeragem obrigatórios (ex.: sem entradas após 17:00, zerar às 17:50; ajustar ao pregão vigente).
- Custos reais no backtest do Profit: corretagem, emolumentos e 1 tick de slippage por lado.

### N-05 · Limpeza (P2, P)
- Adicionar expiração da perna (equivalente a `max_leg_candles`).
- Remover os `.txt` duplicados dos `.ntsl`, ou gerá-los automaticamente.
- Extrair o código comum dos 4 scripts NTSL (hoje diferem só em parâmetros e trava); manter um só script parametrizado.

---

## 9. Épico 6 — Higiene do repositório

### H-01 · Credenciais versionadas (P0, P)
**Problema:** `test.env` tem login e senhas da conta MT5 demo (commit `0d627c5`) e o `.gitignore` faz exceção explícita para ele (`!test.env`).

**Correção:**
- Trocar as senhas da conta.
- Remover o arquivo e a exceção.
- Criar `test.env.example` sem valores.
- Antes de qualquer push para remoto, limpar o histórico com `git filter-repo`.

### H-02 · Teste quebrado (P1, P)
**Problema:** `tests/test_config.py::test_every_symbol_has_dukascopy_instrument` falha porque `DEU.IDX/EUR` (DAX40) não existe na biblioteca `dukascopy-python`. Resultado atual: 503 passaram, 1 falhou.

**Status (2026-11-07):** corrigido. `DAX40` agora usa `E_DAAX`, a constante oficial da biblioteca. Um download real de 2 dias com os dois nomes devolveu os mesmos 2.666 candles, então o dado não muda.

### H-03 · Documentação (P1, P)
**Problema:**
- HANDOFF, STANDARDS, PLAYBOOK e os cabeçalhos dos YAML/NTSL afirmam "100% auditado", "reproduz exatamente" e métricas não reproduzíveis.
- O STATUS.md está desatualizado (18/10).
- O caminho Windows citado (`D:\thiago\...`) não corresponde ao ambiente atual.

**Correção:** marcar as métricas atuais como "pré-correção, inválidas" até M-03. Depois, gerar a tabela de métricas automaticamente a partir dos relatórios.

### H-04 · CI e qualidade (P1, P)
- Pipeline rodando `uv run pytest`, `ruff check` e `mypy` em todo push.
- Hook de pre-commit com ruff.
- Os testes de B0-3, B0-4 e de paridade entram no pipeline.

### H-05 · Relatórios antigos (P2, P)
Mover `reports/*.csv` gerados pelo motor enviesado para `reports/archive/pre-correcao/`, para que ninguém tome decisões com base neles.

### H-06 · Ajustes menores (P2, P)
- UI: trocar `str(target).startswith(str(base_dir))` por `target.is_relative_to(base_dir)` em [`ui/server.py`](../src/smc_trader/ui/server.py). O check atual aceita diretórios irmãos como `out/backtests_x`.
- Renomear `scripts/test_*.py` para `scripts/exp_*.py`, para não confundir com testes do pytest.
- Remover imports não usados (`time`, `datetime` em `live_engine.py`).

---

## 9b. Épico 7 — Dados: B3 (WIN/WDO) e histórico mais longo

**Contexto:** o `dukascopy-python` não tem dados da B3, e `import-csv` só lê o CSV do MT5 (colunas `time` em epoch, `tick_volume`, `spread`). Hoje WIN e WDO só são testados no Profit, em 3 meses, e isso não valida o motor Python. Os dados locais cobrem só mar–out/2026 em 6 símbolos. Sem mais histórico e sem B3, o walk-forward (M-02) e o limite de ≥ 200 trades OOS (M-06) não são atingíveis.

### D-01 · Ingestão de dados B3 (P0, M)
**Fontes possíveis, da mais simples à mais cara:**
1. **Exportação do Profit/ProfitChart** (CSV ou ASCII): é o mesmo dado em que o NTSL roda, o que ajuda na paridade (N-03). Verificar na versão em uso até onde vai o histórico de M1 e como exportar.
2. **MT5 de corretora com B3** (várias corretoras brasileiras oferecem). O `scripts/wine/export_history.py` já exporta M1, mas a profundidade do histórico depende da corretora e precisa ser testada.
3. **Dados históricos pagos** (B3 ou fornecedores de tick). Só se as duas primeiras não tiverem profundidade suficiente.

**Correção:**
- Importador genérico `smc import-csv --format profit|mt5|generic`, com mapeamento de colunas configurável. O `import_mt5_csv` atual fica como um dos formatos.
- Fuso: o horário da B3 é `America/Sao_Paulo`. Converter para UTC na entrada e guardar em UTC, como o resto do projeto.
- Adicionar `WIN` e `WDO` em `symbols` do `config/default.yaml`, com `source: b3` no lugar de `dukascopy.instruments`, e ajustar `test_every_symbol_has_dukascopy_instrument` para só exigir instrumento nos símbolos com fonte Dukascopy.

**Status (2026-11-07):** importador do Profit implementado em `src/smc_trader/data/profit_import.py` (separador, decimal pt-BR e nomes de coluna detectados; fuso São Paulo para UTC; `--bar-label open|close`; barras inválidas rejeitadas), com 8 testes em `tests/test_profit_import.py`. A fonte `profit` foi registrada no store e o `fibo-backtest` lê `WIN`/`WDO` quando pedidos. **Pendente:** validar com um arquivo real exportado do Profit (nomes de coluna e rótulo do candle) e a primeira rodada em WIN/WDO.

**Aceite:** `smc import-csv ... --symbol WIN` grava `data/WIN_M1_*.parquet` e `smc fibo-backtest --symbol WIN` roda sem alterar código.

### D-02 · Série contínua com rolagem de contrato (P0, M)
**Problema:** WIN vence em meses pares e WDO todo mês. Uma série contínua mal montada cria gaps falsos na troca de contrato, e o motor trataria isso como BOS ou stop atingido. O `WDO$N` do Profit é uma série contínua com regras próprias de rolagem, que precisam ser conhecidas.

**Correção:**
- Montar a série por contrato, rolando na data em que o volume do contrato seguinte passa o do atual.
- Gravar uma coluna `roll` (booleana) na barra da troca.
- Os motores não podem calcular pivôs, BOS ou zonas atravessando uma barra com `roll`. Para estratégia intradiária isso quase não perde sinais, porque a troca pode ser feita no intervalo entre pregões.
- Preferir série **sem ajuste de preço** para o backtest intradiário. Se usar série ajustada, documentar o método.

### D-03 · Histórico mais longo para os ativos Dukascopy (P1, P)
**Problema:** o fetch atual puxa pouco histórico (mar–out/2026). Os scripts `fetch_1year_all_assets.py`, `fetch_2years_data.py` e `fetch_all_assets.py` fazem a mesma coisa com janelas diferentes.

**Status (2026-11-07):** implementado. `smc fetch SÍMBOLO --years N` (módulo `src/smc_trader/data/history.py`) baixa mês a mês, grava cada mês ao chegar, retoma pulando meses completos (refaz o último, que pode estar parcial), repete até 4 vezes por mês e sai com código 1 listando os meses que falharam. Testes em `tests/test_history.py`. Os scripts `fetch_1year_all_assets.py`, `fetch_2years_data.py` e `fetch_all_assets.py` ainda existem e podem ser removidos.

**Correção (original):**
- Unificar em `smc fetch --years N`, com download incremental por mês e retomada se cair no meio.
- Meta mínima: 5 anos, para cobrir regimes diferentes (alta, baixa, lateral, alta volatilidade).
- Os dados ficam no cache `data/` (já ignorado pelo git). Registrar período e hash dos arquivos (M-09).

### D-04 · Qualidade dos dados (P1, P)
**Status (2026-11-07):** implementado. `smc check-data SÍMBOLO|all` (módulo `src/smc_trader/data/quality.py`, 13 testes em `tests/test_quality.py`) separa **erros** (barra inválida, timestamp duplicado ou fora de ordem, horário incompatível com a sessão, que indica fuso errado) de **avisos** (buracos, picos, excesso de barras sem variação) e sai com código 1 se houver erro. A pausa diária recorrente do mercado é reconhecida e não polui o relatório. Nos 6 arquivos locais: nenhum erro; avisos restantes são 6 buracos por arquivo (o maior em 25/05, feriado nos EUA) e de 1 a 11 picos, que coincidem entre EURUSD e GBPUSD (10 de 11), ou seja, notícias reais e não corrupção. **Pendente:** integrar a checagem como etapa obrigatória antes de qualquer relatório de backtest.

Escopo original:
Rodar na importação e sempre que um relatório for gerado:
- buracos além do esperado (descontando fim de semana, feriados e intervalo de pregão);
- timestamps duplicados ou fora de ordem;
- barras com `high < low`, preço ≤ 0 ou saltos acima de N vezes o ATR;
- horário dentro da sessão esperada do ativo, para pegar erro de fuso;
- relatório resumido por símbolo (período, nº de barras, % de buracos).

### D-05 · Custos e especificação dos contratos (P1, P)
**Status (2026-11-07):** parcialmente implementado. Seção `contracts` em `config/default.yaml` (`ContractSpec` em `config.py`: spread, tick, valor do ponto, comissão, slippage) com os 8 ativos Dukascopy e WIN/WDO; o `fibo-backtest` lê o spread dali e **falha** se o ativo não tiver entrada (antes usava 1.0 em silêncio). Testes em `tests/test_contracts.py`. **Pendente, decisão sua:** ainda existem duas tabelas de spread. `backtest.costs.spread_pips` (motor SMC) usa XAUUSD 0,20 e EURUSD 0,00008; `contracts` (Fibo) usa 0,30 e 0,00015, valores que estavam fixos no código. Unificar muda o resultado de um dos motores, por isso não mexi. Comissão e slippage ainda não são aplicados pelo motor Fibo (F-10 e Z-06).

Escopo original:
Criar uma tabela por símbolo com tick size, valor do ponto, comissão e slippage típico. Para B3, os valores a conferir com a corretora são:

| Contrato | Tick | Valor do ponto |
|---|---|---|
| WIN | 5 pontos | R$ 0,20 |
| WDO | 0,5 ponto | R$ 10,00 |

Incluir corretagem, emolumentos e 1 tick de slippage por lado. Isso alimenta F-10 e Z-06, e permite expressar o resultado em reais, para comparar com o que o Profit mostra.

---

## 10. Sugestões para deixar o algoritmo mais realista e produtivo

As sugestões abaixo não são bugs. Valem depois que os P0 estiverem resolvidos.

### 10.1 Arquitetura orientada a eventos
- Interface `Strategy.on_bar(bar, state) -> list[Order]` e um `ExecutionModel` separado (fills, custos, gaps).
- O mesmo código roda em três modos: **backtest** (barras históricas), **paper** (barras ao vivo, fills simulados) e **live** (fills reais).
- Isso elimina, por construção, a divergência entre backtest e live (L-02) e boa parte do lookahead: a estratégia nunca vê uma barra que não fechou.

### 10.2 Resolver a ordem intrabar com M1
O projeto já tem dados M1, mas opera em M5. Quando uma barra M5 toca stop e alvo (ou gatilho de trava e stop), percorrer os 5 candles M1 dessa barra resolve a ordem real dos eventos.
- É mais realista que "assumir sempre o pior caso" e muito mais honesto que "assumir sempre o melhor".
- Se a ambiguidade persistir no próprio M1, aí sim usar o caso conservador.

### 10.3 Risco mínimo relativo ao custo
Hoje o stop de 70,5%→79% numa perna M5 é tão curto que o spread consome 15–30% do R. Testar, depois das correções:
- risco mínimo de 5–10× o spread, ou de 0,5–1× ATR(14) do timeframe;
- stops estruturais (100%) com entradas mais profundas;
- timeframes maiores (M15/H1) para a perna, com entrada refinada em M1/M5.

### 10.4 Filtros com hipótese prévia
Formular cada hipótese **antes** de testar, para não cair em garimpo de dados. Testar uma de cada vez em walk-forward:
- tendência de timeframe maior (perna a favor do BOS de H1/H4);
- sessão (Londres/NY) e exclusão de rollover;
- calendário econômico (sem entradas ±15 min de notícia de alto impacto);
- volatilidade (ATR em percentil intermediário).

### 10.5 Gestão de risco de portfólio
- Sizing por % de equity com teto de risco agregado (ex.: 3% somando todas as posições abertas).
- Agrupar ativos correlacionados (índices EUA, pares de USD) e limitar posições simultâneas no mesmo grupo.
- Fração de Kelly no máximo 0,25 e só após 200+ trades reais.

### 10.6 Produtividade da pesquisa
- Rastreamento de experimentos: cada execução salva config, hash dos dados, commit, métricas e lista de trades (estender o `exporter.py`).
- Acelerar o loop do motor com `numba` ou vetorização parcial, para grids grandes em walk-forward.
- Cache dos dados reamostrados por símbolo e timeframe.
- Notebook ou página da UI que, para qualquer trade, plota a perna, os níveis, as barras M1 e o motivo de saída, para auditoria visual por amostragem.

### 10.7 Promoção para dinheiro real em etapas
1. Backtest corrigido + walk-forward aprovado (WFE ≥ 0,7, ≥ 200 trades OOS, baseline aleatório superado).
2. Paper trading por ≥ 8 semanas, com diferença ≤ 15% entre o R real e o R do backtest no mesmo período.
3. Conta real com 0,25% de risco por trade durante 2 meses.
4. Aumentar o risco gradualmente se o drawdown real ficar dentro do percentil 95 do Monte Carlo.

---

## 11. Roadmap sugerido

| Sprint | Foco | Itens | Gate para seguir |
|---|---|---|---|
| 1 | Fundação + vieses P0 do Fibo | B0-1..B0-4, F-01..F-04, H-01, H-02, D-01..D-04 | Testes anti-viés e de prefixo passando em CI |
| 2 | Realismo do backtest | F-05..F-10, Z-01..Z-07, M-07, D-03, D-05 | Spread bid/ask real aplicado; testes passando |
| 3 | Revalidação honesta | M-01..M-06, M-08, M-09, M-03, H-03, H-05 | **Decisão go/no-go:** existe vantagem OOS após custos? Se não, voltar à pesquisa (seção 10.3–10.4) e não avançar para o live |
| 4 | Execução ao vivo | L-01..L-05, L-08, L-10 (com 10.1) | Teste de replay do live idêntico ao backtest |
| 5 | Operação assistida | L-06, L-07, L-09, L-11, N-01..N-05 | Paper trading 8 semanas dentro da tolerância; paridade NTSL ≥ 95% |
| 6 | Conta real reduzida | Seção 10.7, etapas 3–4 | Drawdown real dentro do Monte Carlo |

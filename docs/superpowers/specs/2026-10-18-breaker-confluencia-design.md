# Breaker Block, entrada híbrida e confluências — adendo ao design

Complementa `2026-10-18-smc-day-trade-design.md`. O que não for dito aqui continua valendo como está lá. O código existente (Plano 1) está na branch `feat/foundation`.

## Intenção

O Thiago quer um catálogo completo de estratégias e filtros SMC, **todos ligáveis por configuração**, e depois usar o backtest para **filtrar e refinar a melhor combinação**, fechando a estratégia no fim do mês. Este adendo acrescenta ao que já existe (OB e FVOB no M15) três coisas: o **Breaker Block**, a **entrada híbrida** (confirmação no M1, ou toque quando há confluência) e as **confluências** (EMA 80, SMA 200 e Fibonacci 61,8/79). Nada disso decide a estratégia: cada peça existe para ser comparada no backtest.

## Objetivos, não-objetivos e anti-objetivos

**Objetivos**
- Detectar Breaker Blocks no M15 sem look-ahead, com os mesmos contratos de tempo dos outros detectores.
- Permitir, no backtest, três modos de entrada por tipo de zona e confluências individuais ligáveis, para atribuir quanto cada uma melhora (ou não) o resultado.
- Produzir um relatório que ajude a escolher a estratégia e os filtros, com proteção contra ajuste excessivo ao passado.

**Não-objetivos**
- Execução automática de ordens (continua só alerta).
- OBs gerados por CHoCH (só BOS gera OB, como antes).
- RSI, Wyckoff e Elliott (Plano 3).

**Anti-objetivos (falha mesmo que "funcione")**
- Qualquer look-ahead: a zona, a confluência ou a confirmação não podem usar candles posteriores ao instante de decisão.
- Um relatório que escolha a "melhor" combinação olhando só o período em que ela foi ajustada.

## Decisões do Thiago (como ele disse)

- Breaker Block "precisa ser rompido com imbalance".
- "Todas essas estruturas ocorrem no macro M15; exige confirmação no micro."
- MME de 80 e MMA de 200: "se no micro o POI confluir com as MME ou MMA ou com Retração de Fibo 61.8/79.0, vale a entrada pelo toque."
- "A ideia é ter essas estratégias e, no momento do backtest, filtrarmos e refinarmos a melhor estratégia e filtros."
- Sobre o que já estava decidido: entrada por toque ou por confirmação no M1 é flag comparável; stop e alvo configuráveis; travas diárias só em produção (o backtest roda sem elas).

## Design

### 1. Breaker Block (Plano 1b — módulo de zonas)

Tudo no M15. Um breaker nasce de uma zona OB/FVOB que falhou.

- **Origem:** qualquer **candidata a OB**, isto é, as zonas construídas por `build_zones` com `require_discount=False` e `require_imbalance=False`, **independente** dos filtros das zonas de entrada (assim, mudar os filtros de OB não muda quais breakers existem, e a comparação no backtest fica limpa). O fim de vida da zona de origem (mitigada ou invalidada por CHoCH) **não** é condição: uma zona rompida depois de mitigada ou invalidada ainda conta. A **quebra** é o primeiro candle M15 `j`, com `open_time >= zone.created_at`, que **fecha além do lado oposto** da zona: zona de compra, `close < zone.low`; zona de venda, `close > zone.high`.
- **Idade:** só vira breaker se o candle `j` fecha até `breaker_max_age` candles M15 depois de `zone.created_at` (padrão 96; `None` desliga o limite).
- **Imbalance (obrigatório por padrão, flag `breaker_require_imbalance`):** o candle `j` precisa ser o candle **do meio** de um FVG na direção da quebra (queda, para zona de compra que falhou), isto é, `fvg.start_time == index[j-1]` e `direction` oposta à da zona. Se o primeiro candle que fecha além não é o candle do meio de um FVG, a zona **não** vira breaker (o OB falhou sem deslocamento; não se procura um candle posterior). Com a flag desligada, vale só o fechamento além.
- **CHoCH (flag `breaker_require_choch`, desligada por padrão):** com ela ligada, exige um evento `CHoCH` na direção da quebra com `zone.created_at < event.time <= breaker.created_at`.
- **Disponibilidade:** `created_at` = `formed_at` do FVG (fechamento do terceiro candle); sem a exigência de imbalance, `close_time` do candle `j`.
- **Zona do breaker:** mesmos `high`/`low` e `candle_time` da zona de origem; `direction` invertida (compra falhada → `short`); `kind = "BREAKER"`.
- **Perna da falha** (usada para premium/discount e Fibonacci): para um breaker de venda, `range_high` = maior máxima de `candle_time` até `j` (inclusive) e `range_low` = menor mínima dos candles `j` e `j+1` **quando o imbalance é exigido** (o breaker só existe depois do fechamento de `j+1`); com a flag de imbalance desligada, só o candle `j` (o breaker nasce no fechamento de `j`, e usar `j+1` seria look-ahead). O breaker de compra é o espelho. `in_discount` é calculado com essa perna (prêmio, para venda) e **não filtra** nada; só informa.
- **`swept_liquidity`:** um `Sweep` do lado contrário à nova direção (`"high"` para breaker de venda), com `sweep_time >= zone.candle_time` e `confirmed_at <= breaker.created_at`.
- **Vida:** termina no primeiro candle M15, a partir de `created_at`, que toca a zona (venda: `high >= zone.low`; compra: `low <= zone.high`), com `end_time` = `close_time` desse candle. O motivo é `invalidated` se esse mesmo candle **fecha além do lado de origem** (venda: `close > zone.high`; compra: `close < zone.low`), isto é, o preço atravessou o breaker sem reagir; caso contrário, `mitigated`. (Um fechamento além do lado de origem implica toque no mesmo candle, então não existe "invalidado antes do toque".) O breaker **não expira** por idade depois de formado (o limite de idade só vale na formação).
- **Unicidade:** cada zona de origem gera no máximo um breaker.
- **Configuração (`ZoneConfig`):** `breakers_enabled: bool = True`, `breaker_require_imbalance: bool = True`, `breaker_require_choch: bool = False`, `breaker_max_age: int | None = 96`.
- **Contrato de `Zone`:** o `kind` ganha o valor `"BREAKER"`, e `end_reason` continua `mitigated` ou `invalidated`. A docstring de `Zone` deve passar a descrever as duas vidas (OB/FVOB: mitigada pelo toque ou invalidada por CHoCH contra; BREAKER: mitigada pelo reteste ou invalidada por fechamento de volta além do lado de origem).
- **Integração:** função nova `build_breakers(candles, zones, events, fvgs, sweeps, cfg) -> list[Zone]` (o parâmetro `zones` recebe as candidatas a OB sem filtros, ver Origem); `Analysis` ganha o campo `breakers` (separado de `zones`); `analyze()` o preenche. O gráfico desenha breakers como retângulos **tracejados**, com cor própria e rótulo `BB` (mais ` sweep` quando houver). A propriedade de gating é a mesma do resto (`Zone.is_active_at`).
- **Zona de origem continua existindo:** o OB original segue na lista `zones` com o seu ciclo de vida atual; o breaker é uma zona adicional, não substitui a origem.
- **Testes:** um caso de compra falhada com FVG de baixa no candle de quebra (vira breaker de venda), o espelho, quebra sem imbalance (não vira; vira com a flag desligada), quebra tardia (acima de `breaker_max_age`), `breaker_require_choch`, vida (mitigated, invalidated, sem toque), e a propriedade de não-antecipação (breakers de um frame truncado iguais aos do frame completo, filtrados por `created_at`, com a regra de `end_time` já usada para zonas).

### 2. Modos de entrada (Plano 2)

O M15 define a zona (OB, FVOB ou Breaker); o M1 decide a entrada. Três modos, escolhidos por `entry_mode`:
- `touch`: entra no toque da zona.
- `confirmation`: após o toque, espera um CHoCH no M1, dentro da zona, na direção do trade; stop curto no swing do M1.
- `hybrid`: usa `confirmation`, **exceto** quando há confluência no momento do toque (seção 3), caso em que entra no toque.

**Semântica do motor M1 (minhas decisões):**
- O motor detecta o toque no **M1**, a partir de `created_at` da zona. Ele **não** usa o `end_time` de uma zona `mitigated` do M15 (esse é o fechamento do candle que tocou, tarde demais); usa apenas o `end_time` de uma zona `invalidated` como fim da armadilha.
- Vale só o **primeiro toque** de cada zona; toques seguintes não rearmam.
- `confirmation`: após o primeiro toque, a zona fica armada esperando um CHoCH no M1, dentro da zona (o fechamento do candle do CHoCH dentro de `[low, high]`, pivôs M1 com `pivot_k_ltf`), até a invalidação, o fim da sessão ou `confirmation_timeout_minutes` (configurável; padrão sem limite além dos dois primeiros).
- `hybrid`: a confluência é avaliada **apenas no primeiro toque**. Com confluência, entra no toque; sem, cai para `confirmation` (não há entrada por um toque posterior com confluência).
- **Uma posição aberta por símbolo:** enquanto há um trade aberto no símbolo, não entram novos (OB e breaker da mesma origem concorrem pela mesma vaga). Flag `max_open_per_symbol` (padrão 1) para testar outra regra.

Regras por tipo de zona: **OB e FVOB** aceitam os três modos (para comparação). **Breaker** aceita só `confirmation` e `hybrid` (toque puro não se aplica). O stop do toque (puro ou por confluência) é o da zona: além do OB/breaker (`stop_mode: ob`) ou além do swing da correção (`swing`); `m1_swing` só existe com confirmação. Alvo e condução como no design principal.

### 3. Confluências (Plano 2)

Indicadores, calculados sobre o M1 por padrão (`confluence.ma_timeframe` configurável: M1, M5 ou M15): **EMA** de período 80 (`ema_period`) e **SMA** de período 200 (`sma_period`).

**Há confluência** quando, no instante do toque, a zona (M15) coincide com ao menos `min_rules` (padrão 1) das regras ligadas:
- `ema80`: o valor da EMA está entre `zone.low` e `zone.high` (mais a tolerância).
- `sma200`: idem para a SMA.
- `fib618` e `fib790`: o nível de retração cai entre `zone.low` e `zone.high` (mais a tolerância). Retração da perna da zona: para zona de compra, `nível = range_high - r * (range_high - range_low)`; para venda, `nível = range_low + r * (range_high - range_low)`, com `r` em `confluence.fib_levels` (padrão `[0.618, 0.79]`). `range_low`/`range_high` vêm do evento BOS (OB/FVOB) ou da perna da falha (breaker).
- `confluence.tolerance`: distância em unidades de preço; padrão 0.

Regras de combinação: a confluência vale para `hybrid` em **todos os tipos de zona** (OB, FVOB e Breaker); o modo `touch` é puro e ignora confluência. `min_rules` conta só as regras **ligadas**; sem nenhuma regra ligada nunca há confluência, então `hybrid` equivale a `confirmation` (essa é a base de comparação). Durante o aquecimento dos indicadores (menos candles de histórico que o período) o valor é indefinido e a regra conta como "sem confluência"; o carregador de dados busca histórico extra antes do início do backtest (pelo menos 200 candles do `ma_timeframe`). Para `ma_timeframe` M5/M15, usa-se o último candle desse timeframe **fechado** antes do toque.

Sem look-ahead: a média usada é a do **último candle fechado** antes do toque (no M1, o último M1 fechado); o Fibonacci é fixo desde a criação da zona. As quatro regras são flags independentes, para o relatório atribuir o efeito de cada uma.

### 4. Refinamento (Plano 2 — relatório)

- O runner cruza `tipo de zona (OB, FVOB, BREAKER) × entry_mode × stop_mode × alvo × condução × regras de confluência`, por ativo e por mês, sem as travas diárias.
- Cada execução grava um identificador reprodutível (hash da configuração completa) junto com as métricas.
- Atribuição: acerto, R médio, expectativa, profit factor e drawdown em R **com e sem** cada filtro e cada tipo de zona.
- **Dados e divisão (minhas decisões):** pelo menos 6 meses de M1 por ativo. Divisão cronológica fixa: os primeiros 70% para escolher (amostra) e os 30% finais para confirmar (fora da amostra), por ativo e também agregada. Além disso, walk-forward rolante (treino de 2 meses, teste de 1 mês, avançando 1 mês). Piso de `min_trades` (padrão 30) por combinação e por período; combinações abaixo disso aparecem no relatório marcadas como "amostra insuficiente" e não entram no ranking.
- **Proteção contra ajuste excessivo:** os dados se dividem em amostra (para escolher) e fora da amostra (para confirmar), com walk-forward; o relatório sempre mostra o número de combinações testadas e a queda de desempenho entre amostra e fora da amostra. Uma combinação só entra no ranking final se mantiver expectativa positiva fora da amostra.

## Decisões minhas (para o Thiago conferir)

- Quebra do breaker = **primeiro** candle que fecha além, e ele precisa ser o candle do meio do FVG; sem busca por candles posteriores.
- CHoCH do breaker opcional e desligado; `breaker_max_age = 96` candles M15.
- Breakers numa lista própria (`Analysis.breakers`); o OB de origem permanece.
- Breaker não aceita toque puro; stop do toque é o da zona.
- Média e Fibonacci avaliados no M1 por padrão, com "coincide" = valor dentro da zona (tolerância 0).
- Fibonacci da perna do BOS (OB/FVOB) ou da perna da falha (breaker).
- Origem dos breakers = candidatas a OB sem filtros; a zona de origem pode ter terminado antes.
- Motor M1: primeiro toque apenas; `hybrid` avalia a confluência só nesse toque e, sem ela, cai para confirmação; uma posição aberta por símbolo.
- Divisão amostra/fora da amostra de 70/30, walk-forward 2+1 meses, `min_trades = 30`.
- Os dados do backtest precisam de meses de M1 por ativo (a Dukascopy fornece); o spread de custo vem da configuração por símbolo.

## Deixado ao construtor

Estrutura interna de `build_breakers` e dos indicadores, nomes de funções auxiliares, formato do arquivo de resultados do runner, estilo do relatório (HTML ou Markdown) e a escolha entre implementar os indicadores com `pandas` ou à mão.

## Ordem de execução

1. **Plano 1b:** Breaker Block (configuração, `build_breakers`, `analyze`, gráfico, testes), seguindo o processo de execução já usado.
2. **Plano 2:** primeiro a performance (vetorizar `find_pivots`/`find_fvgs`, `searchsorted` em `build_zones`/`_lifetime`, `analyze()` uma vez por série), depois engine M1 com os três modos de entrada, indicadores e confluências, travas desligáveis, custos, e o runner com o relatório de refinamento. `extra="forbid"` já vale na configuração.
3. **Plano 3:** RSI, Wyckoff e Elliott, scanner ao vivo e Telegram.

# Regras para agentes neste repositório

Leia antes de qualquer tarefa que mexa em estratégia, backtest, filtros, parâmetros ou modelos. Estas regras existem porque o mesmo erro já aconteceu várias vezes: resultados excelentes que vinham de viés do simulador e que foram promovidos a "modelo oficial".

Detalhes técnicos estão em `STANDARDS.md` (seção 4). Em caso de conflito, **este arquivo vence**.

## 1. Regra de ouro: a decisão só usa o que já era conhecido

Uma decisão tomada no instante `t` só pode usar informação disponível em `t`.

**O erro que mais se repetiu: usar a barra em que a ordem é executada.**

- Entradas por ordem limite ou stop são executadas **dentro** da barra `i`, no momento do toque. Nesse momento, `close[i]`, `high[i]`, `low[i]` e qualquer indicador calculado com eles (`ema[i]`, `sma[i]`, `atr[i]`) **ainda não existem**.
- Todo filtro que decide uma entrada executada dentro da barra `i` deve usar **`i - 1`** ou valores fixados antes da barra começar.
- **Exceção:** se a regra espera a barra `i` fechar (ex.: "candle de rejeição") e só **depois** envia a ordem para `i + 1` em diante, ela pode usar a barra `i` inteira. O fill tem que acontecer em `i + 1` ou depois.

| Errado | Certo |
|---|---|
| `if closes[i] <= ema80[i]: continue` para uma entrada limite executada na barra `i` | `if closes[i - 1] <= ema80[i - 1]: continue` |
| Testar stop e alvo da barra de entrada como se a ordem dos eventos fosse conhecida | A barra de entrada só pode ser estopada, nunca alvejada |
| `continue` logo após `if triggered:` ignorando o stop da própria barra `i` | Testar imediatamente `lows[i] <= stop` (long) ou `highs[i] + spread >= stop` (short) no momento do fill |
| `exit_price = pos["stop_price"]` mesmo quando `open[i]` abre além do stop por gap | `exit_price = min(pos["stop_price"], opens[i])` (long) ou `max(pos["stop_price"], opens[i] + spread)` (short) |
| Ordens a mercado / stop preenchidas no preço exato | Modelar slippage realista (mínimo 1.0 ponto em índices) |
| Somar trades de loops de gatilhos independentes no mesmo ativo/tempo (contagem dupla) | Em modo unificado/carteira, no máximo 1 posição por barra/evento de sinal |
| Entrar na barra que confirmou o BOS | Entrar a partir da barra seguinte (F-01) |
| Short comparando stop e alvo com o bid | Short sai pelo ask (bid + spread) |

**Caso real (2026-11-07):** o filtro `trend_ma` usava `closes[i]` e `trend_mas[i]` na barra do toque. A varredura reportou +150R, 35% de acerto e 6/6 ativos positivos com stop em 0,886. Com o filtro usando `i - 1`, o mesmo teste deu −103R e 0/6 ativos positivos. O resultado foi commitado em `production.yaml` e no NTSL antes de qualquer revisão.

**Caso real (2026-11-08): Falhas de simulação de Trend Follower (omissão de stop na barra de entrada, gaps ignorados e contagem dupla)**
1. **Omissão do stop na barra de entrada:** Ao simular a estratégia `TrendFollowerStrategy`, a ordem por rompimento era executada dentro da barra `i`. Logo após o disparo, o código executava um `continue`. Com isso, a barra `i` NUNCA era testada contra o `stop_price`! Se a barra rompia a máxima acionando a compra e em seguida despencava até a mínima do sinal, o trade sobrevivia no simulador. Pelo histórico em M1, isso aconteceu 110 vezes no NAS100 e US30, inflando o resultado em +40R de lucro fantasma.
2. **Gaps no stop loss:** Ordens de stop loss eram preenchidas no nível exato do stop (`exit_price = pos["stop_price"]`), ignorando que em gaps noturnos ou de fim de semana o mercado abre além do stop, devendo ser executado no `open` da barra.
3. **Contagem dupla no modo unificado:** Os gatilhos (Trap, Barra de Força, Engolfo) rodavam em laços independentes. Quando dois ou três gatilhos disparavam na mesma barra (167 casos, 360 trades), o simulador abria 2 ou 3 posições idênticas (mesma entrada, mesmo stop), concentrando 2R a 3R de risco no mesmo evento e inflando a contagem de trades e o retorno total.
4. **Ordens stop sem slippage:** Ordens de stop não continham slippage (mínimo de 1 ponto em índices).
5. **Atribuição falsa de alpha aos gatilhos:** O resultado foi anunciado com entusiasmo excessivo, atribuindo o mérito aos gatilhos gráficos. Uma entrada aleatória dentro do mesmo regime macro (ADX >= 25, MME 80/200, slope > 0.10, Sessão NY, saída na MME 20) rendeu praticamente o mesmo (+0,258R contra +0,303R), provando que os gatilhos gráficos não tinham vantagem estatística real. Além disso, a estratégia falhou catastroficamente em Forex e Commodities (XAUUSD −77R, EURUSD −135R, GBPUSD −59R, BRENT −31R).
- **Impacto corrigido no modelo configurado (Single-Position, slippage 1.0 pt):**
  - O retorno relatado de **+281,0R** (741 trades, PF 1.64) cai para **+54,7R em 457 trades** (+0,120 ± 0,112R/trade, PF 1.18, MaxDD 29.9R).
  - Com $t \approx 0,120 / 0,112 \approx 1,07$, esse resultado **não possui significância estatística** ($t < 2,0$).
  - Nos primeiros 3 anos (2021-2024), o retorno acumulado foi de apenas **+8,5R** (PF 1.05, praticamente nulo), com anos negativos em 2023 (−16,9R) e 2025 (−11,1R).
  - O número intermediário de "+141,6R em 562 trades" decorria de uma etapa em que posições sobrepostas de gatilhos distintos eram mantidas. No modo independente (com até 3 posições abertas simultaneamente), o resultado é +142,4R (+0,186 ± 0,087R/trade), decorrente puramente de triplicar a exposição ao regime direcional do índice, e não de qualquer vantagem dos gatilhos.

**Caso real (2026-11-08 - Parte 2): Sobrescrita de gatilho em Trend Following (Turtle transformado em "Sempre Comprado")**
1. **O bug de variável:** Nos scripts `test_higher_timeframe_trend_following.py` e `test_timeframe_decay_gradient.py`, a variável `trigger_price` foi usada tanto para compra quanto para venda. O bloco de venda sobrescrevia `trigger_price = dl20[i]` (fundo do canal). A checagem de compra `highs[i] >= trigger_price` virou `highs[i] >= dl20[i]`, que é verdadeira em praticamente 100% dos candles. Como o `open[i]` quase sempre é maior que a mínima de 20 barras, o simulador preenchia a compra no `open` imediatamente ao ficar desposicionado (746 compras contra 9 vendas no D1; 15.754 compras contra 46 vendas no H1; 100% das entradas saindo no `open`).
2. **Impacto mascarado:** Em um período de forte alta secular (2021-2026 nos índices e ouro), uma estratégia que fica permanentemente comprada no `open` colhe o drift positivo do mercado, gerando "+113R no D1" e "+1.168R no H1" falsos. O teste sintético de passeio aleatório deu 0.00R porque em um passeio sem tendência uma estratégia sempre comprada também dá zero, não detectando a falha de lógica.
3. **Resultado Corrigido (separando `long_trigger` e `short_trigger`):**
   - **No D1:** O retorno do Turtle 20/10 cai de +113.7R para **+13.8R em 396 trades** (+0.035 ± 0.069 R/trade, $t = 0.51$, PF 1.08), estatisticamente nulo. Compras dão +46R e vendas dão −32R (pura assimetria da alta dos mercados). Turtle 50/20 dá +0.1R ($t = 0.01$). Holdouts D1: SPX500 −0.9R, GER40 −9.3R, NAS100 pré-2021 +5.1R.
   - **No Intradiário:** Rompimentos de canal perdem maciçamente mesmo sem custo: H4 com custo −411.6R ($t = -6.30$, sem custo −321.6R); H1 com custo −2.167.5R ($t = -14.78$, sem custo −1.403.4R); M30 com custo −4.871.1R ($t = -20.44$, sem custo −2.221.4R). Rompimentos intradiários falham sistematicamente e revertem à média.

### Regras obrigatórias para qualquer simulação de estratégia:
- **Toda ordem executada dentro da barra `i` deve obrigatoriamente checar se a barra `i` atinge o stop loss.** A barra de entrada só pode ser estopada, nunca alvejada.
- **Todo stop loss atingido com gap na abertura deve ser executado no preço de abertura (`open`), acrescido de slippage.**
- **Toda ordem stop (entrada por rompimento ou stop loss) deve incluir parâmetro de slippage realista.**
- **Estratégias multi-gatilho devem operar com controle estrito de concorrência:** no máximo 1 trade por sinal, com prioridade determinística entre os gatilhos.
- **Nenhum gatilho pode ser creditado como produtor de alpha sem teste de controle de entrada aleatória** sob o mesmo regime macro e regra de saída. Se a diferença estiver dentro do desvio-padrão ($\sigma / \sqrt{N}$), a contribuição do gatilho é considerada estatisticamente nula.
- **Checagem obrigatória de simetria e preenchimento:** Estratégias bidirecionais de rompimento devem auditar a proporção de compras vs vendas e a porcentagem de entradas no preço do gatilho vs no Open. Se a assimetria for > 80% ou as entradas no Open forem > 50% em rompimento, o teste é considerado inválido por bug de sobrescrita.
- **Benchmark contra "Sempre Comprado" (Drift Macro):** Todo resultado positivo em ativos com viés de alta deve ser comparado contra uma entrada passiva sempre comprada com as mesmas saídas. Se o ganho não superar a compra passiva, não há alpha de timing.

## 2. Antes de afirmar que uma estratégia ou parâmetro "funciona"

Um resultado de backtest só pode ser apresentado como promissor se vier com **todos** os itens abaixo. Sem eles, apresente como "resultado preliminar, não validado".

1. **Revisão de causalidade:** liste, para cada filtro novo, qual índice de barra ele usa e por que a informação estava disponível no momento da decisão.
2. **Rodada sem custo:** se o R por trade sem custo é ~0, não há vantagem. Custo nunca cria vantagem.
3. **Comparação com entrada aleatória** com a mesma frequência, direção e regra de saída. Referência: com alvo de 3R e stop de 1R, um passeio aleatório acerta 25%.
4. **Separação dentro e fora da amostra:** parâmetros escolhidos só na primeira parte; resultado reportado na segunda, olhada uma única vez.
5. **Quantas variantes foram testadas.** Escolher o melhor de N stops ou filtros nos mesmos dados exagera o resultado; diga N.
6. **Tamanho da amostra e erro-padrão** do R por trade (≈ desvio-padrão / √trades).
7. **Os números precisam fechar entre si:** acerto × ganho médio − erro × perda média = R por trade. Confira o RR máximo possível pela geometria (ex.: entrada 0,618, stop 0,886 e alvo no extremo dão no máximo 0,382 / 0,268 ≈ 1,4R).

### Sinais de alerta (pare e revise antes de reportar)

- Melhora grande vinda de um filtro simples (ex.: de −100R para +150R).
- 100% dos ativos positivos.
- "Ponto ótimo" achado numa varredura.
- Taxa de acerto subindo e drawdown caindo ao mesmo tempo, sem custo maior.
- "No gráfico as operações parecem ótimas": o gráfico mostra barras fechadas, que é exatamente o viés da seção 1.

## 3. O que é proibido sem aprovação explícita do usuário

- Alterar `config/production.yaml`, os YAML em `config/models/` ou os scripts em `nelogica/` com base em resultado de backtest.
- Chamar um modelo de "oficial", "canônico", "calibrado" ou "auditado".
- Remover ou enfraquecer testes anti-viés, ou ajustar um teste para que ele passe com o comportamento novo.

Para propor um modelo novo, use um relatório com os 7 itens da seção 2 e peça aprovação. **Nunca** commite a mudança de produção junto com o experimento.

## 4. Ao criar ou alterar filtro, modo de entrada ou saída

- Escreva um **cenário sintético** em `tests/test_fibo_ote.py` em que a informação da barra de entrada mudaria a decisão. Exemplo: o toque acontece, a barra fecha do lado "bom" do filtro, e o teste exige que a entrada **não** dependa desse fechamento.
- Rode `tests/test_prefix_invariance.py` e os cenários anti-viés. Teste vermelho bloqueia o commit.
- **Backtest e live usam o mesmo código** (`FiboOTEStrategy.pending_setup`). Se o filtro olha uma barra no backtest e outra no live, um dos dois está errado.

## 5. Linguagem nos relatórios e documentos

- Não use "100%", "institucional", "auditado", "garantido", "extraordinário" para descrever resultado de backtest.
- Toda métrica informa a fonte (`backtest`, `paper`, `live`), o período, os custos usados e se é dentro ou fora da amostra.
- Resultado negativo é resultado; reporte-o com o mesmo destaque.

## 6. Referências

- `STANDARDS.md`, seção 4: protocolo anti-viés do motor.
- `docs/PESQUISA_ESTRATEGIAS_INTRADAY.md`, seção 8: protocolo de teste de estratégias.
- `docs/SPEC_PRODUTO.md`, seção 2: princípios do produto (P2 e P3).

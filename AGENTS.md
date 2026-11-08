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
| Entrar na barra que confirmou o BOS | Entrar a partir da barra seguinte (F-01) |
| Short comparando stop e alvo com o bid | Short sai pelo ask (bid + spread) |

**Caso real (2026-11-07):** o filtro `trend_ma` usava `closes[i]` e `trend_mas[i]` na barra do toque. A varredura reportou +150R, 35% de acerto e 6/6 ativos positivos com stop em 0,886. Com o filtro usando `i - 1`, o mesmo teste deu −103R e 0/6 ativos positivos. O resultado foi commitado em `production.yaml` e no NTSL antes de qualquer revisão.

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

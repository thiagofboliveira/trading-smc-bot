# Pesquisa: estratégias e filtros intraday com evidência

**Data:** 2026-11-07 · **Uso:** insumo da trilha de pesquisa (PQ) do [backlog do produto](BACKLOG_PRODUTO.md).
**Anexos (relatórios completos, tabelas e reprodução dos experimentos):** [PESQUISA_ESTRATEGIAS_INTRADAY_ANEXOS.md](PESQUISA_ESTRATEGIAS_INTRADAY_ANEXOS.md) · script: `scripts/research/exp_custo_timeframe_fibo.py`
**Método:** três frentes de pesquisa na web, cada uma com fontes primárias sempre que possível (artigos revisados, working papers, documentos da B3 e da CVM):

1. evidência acadêmica de estratégias intraday;
2. evidência sobre a tese SMC + Fibonacci;
3. particularidades da B3.

Somam-se dois testes com os dados locais. O que não foi conferido na fonte está marcado **(não verificado)**.

## 1. Resposta curta

- **Existem efeitos intraday com evidência séria, mas pequenos:** da ordem de poucos pontos-base por dia, antes dos custos. A maioria tem acerto acima de 50% com R:R perto de 1:1, o contrário do perfil 1:3 com 30–40% de acerto.
- **O candidato mais próximo do seu perfil é o momentum de rompimento da "noise area"**, com saída por trailing no VWAP: acerto de 37% a 43%, com o lucro vindo de poucos trades grandes. A evidência é moderada: um único grupo de autores e quase toda dentro da amostra.
- **Para Fibonacci, OTE, FVG e order block não há evidência a favor.** Os dois testes sistemáticos de SMC/ICT encontrados não acham vantagem contra entradas aleatórias.
- **O seu backtest tem a assinatura exata de ausência de vantagem.** Com alvo de 3R a taxa de acerto foi de 21% a 26%, e num passeio aleatório ela é 25%.
- **Psicologia não é o principal problema dos day traders.** Os estudos brasileiros mostram que o varejo perde no agregado **antes** dos custos (seção 4). Automatizar elimina o erro emocional, mas não cria vantagem.

## 2. A matemática do 1:3

### 2.1 Ponto de equilíbrio

Com R:R = 3 e custo médio `c`, medido em R por trade, a taxa de acerto de equilíbrio é:

```
p* = (1 + c) / (RR + 1)
```

| Custo por trade | Acerto de equilíbrio (1:3) | Expectativa com 30% | Com 40% |
|---|---|---|---|
| 0 | 25,0% | +0,20R | +0,60R |
| 0,10R | 27,5% | +0,10R | +0,50R |
| 0,17R | 29,3% | +0,03R | +0,43R |
| 0,22R | 30,5% | −0,02R | +0,38R |

No seu motor, em M5 com stop no 79%, o custo ficou entre 0,12R e 0,25R por trade. Por isso 30% de acerto não basta: com stop curto, o spread come o lucro.

### 2.2 Por que 25% é a referência

Num passeio aleatório sem tendência, a chance de o preço andar +3R antes de −1R é 1/(1+3) = 25%. Uma estratégia só tem vantagem se, **com alvo e stop fixos**, acertar acima disso, e com folga para pagar o custo.

### 2.3 Medição local

Seis ativos Dukascopy, mar–out/2026, motor corrigido:

| Timeframe | Modelo | Custo real (R/trade, acerto) | Sem custo (R/trade, acerto) |
|---|---|---|---|
| M5 | alvo fixo 3R, stop 100% | −0,068 · 23,1% | +0,013 · 25,2% |
| M15 | alvo fixo 3R, stop 100% | −0,047 · 24,2% | +0,016 · 25,7% |
| H1 | alvo fixo 3R, stop 100% | −0,168 · 21,1% | −0,103 · 22,7% |
| M5 | trailing EMA8 | −0,224 · 29,1% | +0,024 · 33,8% |
| M5 | estrutural | −0,119 · 58,7% | −0,017 · 63,6% |

Sem custo, o acerto com alvo de 3R gira em torno de 25% e o R por trade, em torno de zero, em todos os timeframes. **A entrada não se distingue do acaso.** Subir o timeframe não resolveu. São só 8 meses de dados, então a medição tem pouca precisão (cerca de ±0,05R por trade), mas nada aponta para uma vantagem escondida.

## 3. O que a evidência diz da tese SMC + Fibonacci

| Componente | Evidência | Resumo |
|---|---|---|
| "O preço anda em tendência" | **Forte** em meses (time-series momentum, mais de 100 anos de dados) e **moderada** no intraday, no nível da sessão | A parte da tese que se sustenta. |
| Níveis de Fibonacci | **Contra** | Batchelor & Ramyar (2006, DJIA 1914–2002): poucas razões significativas, em número compatível com o acaso. Tsinaslanidis et al. (2022, *Expert Systems with Applications*): o preço em zonas Fibonacci não se comporta diferente de zonas não-Fibonacci; o "bounce" cresce com a largura da zona, não com a razão. |
| SMC / ICT (BOS, OTE, FVG, order block) | **Sem evidência a favor** | Tangirala (SSRN, 2026, preprint): 44 detectores SMC no S&P 500 diário; contra entradas aleatórias pareadas e com correção para múltiplos testes, nenhum bate o acaso. Mahadzva (SSRN, 2026, preprint, FX intraday): "sem evidência de que os conceitos funcionem como ensinados". Os dois foram lidos só pelo resumo. |
| "Varredura de liquidez" (stop hunt) | **Existe, mas aponta o contrário** | Osler (2003, 2005): stops se acumulam além de números redondos, e cruzar esses níveis acelera o preço **na mesma direção** (continuação), com efeito menor que 1 ponto-base. Mahadzva também acha continuação depois do sweep, não reversão. |
| Suporte e resistência | **Efeito pequeno e real** | Osler (2000): 60,8% de repique em níveis publicados por bancos contra 56,2% em níveis aleatórios. Chung & Bellotti (2021): níveis com mais toques recentes repicam mais. |
| Entrar no pullback com ordem limite | **Contra** (seleção adversa) | A ordem limite é preenchida justamente quando o pullback vira reversão, e perde os trades que seguem sem retração (Handa & Schwartz 1996; Linnainmaa 2010). Goulding, Harvey & Mazzoleni (JFE 2023): no estado "correção dentro da tendência", o retorno piora e a volatilidade sobe. |
| Stop curto | **Contra** sem autocorrelação | Kaminski & Lo (2014) e Lo & Remorov (2017): sem tendência no curto prazo, o stop reduz o retorno esperado, e o custo de stops curtos pesa muito. |

**Veredito:** o conceito de "tendência" tem base, mas a forma de entrar (retração em nível de Fibonacci, com limite, depois de um BOS de M5) não tem. O que a literatura sugere é **operar a favor do movimento quando ele acontece** (momentum e rompimento), não esperar que ele volte.

## 4. Psicologia ou falta de vantagem?

| Estudo | Amostra | Resultado |
|---|---|---|
| Chague, De-Losso & Giovannetti, "Day trading for a living?" (FEA-USP/FGV, 2019) | Todas as pessoas físicas que começaram day trade no mini-índice entre 2013 e 2015 (dados da CVM) | Dos 1.551 que persistiram mais de 300 pregões, **97% perderam**. Só 1,1% ganhou mais que um salário mínimo e 0,4–0,5% mais que um caixa de banco. Sem sinal de aprendizado com o tempo. |
| Chague & Giovannetti (FGV, 2025) | Pessoas físicas no mercado futuro, 2017–2023 | Perdas **brutas** de R$ 9,9 bi desde a pandemia. O varejo perdeu no agregado em 95,8% a 96,4% dos dias, **antes** de corretagem e emolumentos. |
| Barber, Lee, Liu & Odean (2014) | Taiwan, 1992–2006 | Menos de 1% dos day traders lucra de forma previsível. |

Se o problema fosse só emocional, um robô que segue as regras ao pé da letra resolveria. A perda bruta agregada mostra que, na média, **as regras usadas pelo varejo não têm vantagem**. Automatizar é necessário (remove o erro de execução), mas não é suficiente.

## 5. Candidatos para testar, em ordem de evidência

Todos podem ser codificados com M1 OHLC. Os horários dependem do ativo: pregão do subjacente nos CFDs e sessão da B3 no WIN/WDO.

### H1. Rompimento da "noise area" com trailing no VWAP (o mais próximo do seu perfil)

**Fonte:** Zarattini, Aziz & Barbon (2024), "Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY)", SSRN 4824172. Working paper, não revisado.

**Regra:**
- Para cada horário `HH:MM`, calcule `σ(HH:MM)` = média dos últimos 14 dias de `|close(HH:MM) / open_do_dia − 1|`.
- Banda superior: `UB = max(open_hoje, close_ontem) × (1 + σ)`. Banda inferior: `LB = min(open_hoje, close_ontem) × (1 − σ)`.
- Decisões só às `HH:00` e `HH:30`: compra se o preço estiver acima de UB, vende se estiver abaixo de LB.
- Trailing stop: na compra, `max(UB, VWAP)`; na venda, `min(LB, VWAP)`. Zera tudo no fim da sessão.

**Resultado reportado** (2007–2024, líquido de comissão e slippage):

| Métrica | Valor |
|---|---|
| Sharpe | 1,24 (1,33 com dimensionamento por volatilidade) |
| Acerto diário | 43% |
| Acerto por trade | 37% |
| Sharpe médio por ativo em 33 futuros (FAQ do paper) | 0,60 |
| Sharpe no Nasdaq | 1,23 |

**Ressalvas:**
- Um único grupo de autores, sem período fora da amostra formal.
- No CFD, o spread pago em cada virada de posição pesa bem mais que o custo do paper.
- No Dukascopy, o "volume" usado no VWAP é contagem de ticks (aproximação). O WIN tem volume real.

**Evidência:** moderada. **Melhores ativos para testar:** NAS100, US30, DAX40 e WIN.

### H2. Momentum intraday de sessão (o dia prevê a última meia hora)

**Fontes:** Gao, Han, Li & Zhou (2018, *Journal of Financial Economics*, SPY 1993–2013); Baltussen, Da, Lammers & Martens (2021, *JFE*, mais de 60 futuros desde 1974).

**Regra:** se o retorno do fechamento anterior até 30 minutos antes do fim do pregão for positivo, compra nos últimos 30 minutos e zera no fechamento; se for negativo, vende.

**Resultado reportado:**

| Estudo | Sharpe | Acerto | Retorno |
|---|---|---|---|
| Gao et al. (SPY) | 1,08 | 54% | cerca de 6,5% ao ano, já com spread |
| Baltussen et al., índices (bruto) | 1,73 | 55% | — |
| Baltussen et al., moedas (bruto) | 0,87 | — | — |

No FX, o efeito não é significativo em 2000–2020.

**Ressalvas:**
- Rosa (2022) relata que a previsibilidade some fora da amostra. Li, Sakkas & Urquhart (2022) acham o contrário em 16 mercados.
- O efeito se concentra em dias de alta volatilidade.

**Perfil:** cerca de 1:1, não 1:3.

**Evidência:** forte de que o efeito existe; fraca a moderada de que dá lucro líquido. **Brasil:** nenhum estudo com dados locais encontrado. No WIN, o "fim" relevante é o call de fechamento das ações, que muda com o horário de verão americano (seção 7).

### H3. Rompimento de swing e "sweep" como continuação

**Fontes:** Osler (2003, 2005); Mahadzva (2026, preprint).

**Regra:**
- Gatilho: um candle M5 fecha além do swing high ou low das últimas N barras, ou de um número redondo (00/50).
- Entrada a mercado na direção do rompimento, com stop atrás do nível.
- Saída por tempo (15 a 120 minutos) ou por trailing.

É a inversão da leitura SMC: em vez de esperar a reversão depois da varredura, segue o rompimento.

**Ressalva:** o efeito bruto medido por Osler é menor que 1 ponto-base, então só sobrevive em ativos de spread muito baixo. Antes de qualquer otimização, meça o deslocamento favorável e o adverso máximos depois do sinal, já líquidos de custo.

**Evidência:** fraca a moderada. **Bom para testar** porque reaproveita o seu detector de BOS: muda só a forma de entrar.

### H4. Rompimento da faixa de abertura (ORB) com alvo longo

**Fonte:** Zarattini & Aziz (2023), "Can Day Trading Really Be Profitable?", SSRN 4416622 (QQQ 2016–2023).

**Regra:**
- A direção é a do primeiro candle de 5 minutos da sessão.
- Entrada na abertura do segundo candle, com stop no extremo oposto do primeiro.
- Alvo de 10R ou saída no fim do dia.

**Resultado:** acerto em torno de 24% e cerca de +0,13R por trade, com custo baixo.

**Ressalva:** uma replicação independente em CFDs (blog do MQL5, 2026, não revisada) reproduziu o resultado bruto, mas o líquido ficou entre zero e negativo: NQ +0,002R, DAX −0,038R.

**Evidência:** fraca para índices em CFD. Pode valer no WIN, onde o custo por contrato é baixo (seção 7). É o perfil de alvo longo que você quer.

### H5. Reação a dados macro americanos na B3

**Fonte:** Santos, Garcia & Medeiros (*Brazilian Review of Econometrics*, 2016; dados de 2008 a 2011). Anúncios **externos** dominam o dólar futuro e o Ibovespa futuro, com efeito por volta de 20 minutos.

**Regra:** continuação ou rompimento depois das 10:30 BRT (09:30 no horário de verão americano). Como filtro, não abrir posição nos minutos antes do dado.

**Evidência:** moderada, mas com amostra antiga. A versão com o sinal da surpresa exige dados de consenso, que você não tem.

### H6. Sazonalidade de sessão no FX

**Fonte:** Breedon & Ranaldo (2013, *Journal of Money, Credit and Banking*; dados de 1997 a 2007).

**Regra:** cada moeda tende a se desvalorizar no horário comercial do próprio país. No EUR/USD: vende na sessão europeia e compra na americana.

**Resultado:** Sharpe de 0,9 a 1,3 líquido do spread interbancário. Nos outros pares, quase tudo fica negativo depois dos custos.

**Evidência:** moderada até 2007. O desempenho depois disso não foi verificado. É um perfil 1:1.

### Controles (o que precisa perder para os candidatos)

- **C0. Entrada aleatória pareada:** sorteia o horário e a direção com a mesma frequência e a mesma regra de saída da estratégia.
- **C1. Fibo atual com níveis placebo:** troca 0,618 e 0,705 por razões sorteadas entre 0,4 e 0,9. Se o placebo empatar, Fibonacci não agrega nada.

## 6. Filtros com algum respaldo

Filtros não criam vantagem, mas podem concentrar uma vantagem fraca ou cortar custo. Cada um entra como hipótese no protocolo da seção 8.

| Filtro | Base | Regra testável |
|---|---|---|
| Tendência no timeframe maior | Time-series momentum (Moskowitz, Ooi & Pedersen 2012; Hurst, Ooi & Pedersen) | Só comprar se o retorno diário de 20 ou 60 dias for positivo (ou o fechamento estiver acima da média diária), e o inverso para vender. **Atenção:** Goulding et al. mostram que o pullback dentro da tendência é o estado de pior retorno; o filtro funciona melhor com entradas de momentum (H1 a H3) do que com retração. |
| Regime de volatilidade | Gao et al., Zarattini et al. e Baltussen et al.: o efeito intraday se concentra em dias voláteis | Operar só se a volatilidade da primeira meia hora (ou o ATR do dia) estiver acima da mediana dos últimos 20 dias. |
| Custo em relação ao stop | Lo & Remorov; nota de Mahadzva sobre stops curtos | Descartar o trade se `spread + slippage > 5–8%` da distância do stop, ou se o stop for menor que `m × ATR`. É o filtro que mais mexe no seu resultado: derruba o custo de cerca de 0,17R para menos de 0,08R. |
| Tamanho mínimo da perna | Mesmo raciocínio | Perna do BOS de pelo menos `k × ATR(14)`, com k ∈ {1,5; 2; 3}, em vez de 10 × spread. |
| Horário | Volatilidade em U (Andersen & Bollerslev 1997; Moreira & Lemgruber, BCB) | Operar na abertura, na sobreposição Londres–NY e depois do dado macro. Evitar o almoço. Normalizar o stop pelo horário. |
| Notícias | Santos et al.; Osler | Não abrir posição entre 15 minutos antes e 15 minutos depois de dado relevante. |
| Confluência com nível real | Osler (2000); Chung & Bellotti (2021) | Em vez da razão Fibonacci: número redondo ou swing com 2 ou mais toques recentes dentro da zona de entrada. |
| Saída por tempo | Gao e Zarattini usam | Testar saída no fim da sessão ou depois de N minutos contra alvo fixo de 3R e trailing EMA8. |

## 7. B3: custos e calendário (WIN e WDO)

| Item | WIN | WDO |
|---|---|---|
| Tick e valor | 5 pts = R$ 1,00 (R$ 0,20 por ponto) | 0,5 pt = R$ 5,00 (R$ 10 por ponto) |
| Tarifas B3 de day trade, ida e volta (estimativa) | cerca de R$ 0,50 ≈ 2,5 pts | cerca de R$ 2,1 ≈ 0,2 pt |
| Corretagem | zero em muitas corretoras | idem |
| Spread típico | 1 tick (não verificado) | 1 tick (não verificado) |
| Margem de day trade | R$ 155 (desde 02/02/2026) | R$ 140 |
| Imposto | 20% sobre o lucro mensal de day trade e IRRF de 1% sobre o resultado diário positivo | idem |

**Custos na prática:** o slippage de stop a mercado (5 a 10 pts no WIN; 1 tick = R$ 5 no WDO) pesa mais que as tarifas. Use slippage de pelo menos 1 tick nos backtests.

**Horários e vencimentos:**
- **WIN:** negocia das 09:00 às 18:25.
- **Fechamento das ações:** muda com o horário de verão americano.
  - De 09/03 a 02/11/2026, o call de fechamento era até as 17:00, com ajuste do WIN das 17:00 às 17:15.
  - Desde 03/11/2026, o call vai até as 18:00, com ajuste das 18:00 às 18:15.
  - Toda regra que dependa do "fim do pregão" precisa desse calendário.
- **Abertura americana:** 11:30 BRT de novembro a março e 10:30 BRT de março a novembro.
- **Vencimentos:**
  - **WIN:** meses pares, na quarta-feira mais próxima do dia 15.
  - **WDO:** todo mês, no 1º dia útil; a rolagem acontece nos últimos dias do mês anterior.
  - O motor já fecha a posição na rolagem (correção D-02).
- **RLP:** a corretora pode executar a sua ordem contra a própria carteira, o que muda a qualidade da execução. Vale medir o slippage real em conta simulada.

**Pesquisas com WIN/WDO:** não foi encontrada nenhuma dissertação ou artigo com estratégia intraday nesses contratos que seja fora da amostra, líquida de custos e positiva. Os trabalhos encontrados (UFMG 2022, com WIN em M5 e sem custos; UNIPAMPA 2025) foram negativos ou não bateram o buy & hold.

## 8. Protocolo de teste (obrigatório para qualquer candidato)

1. **Dados:** pelo menos 5 anos (item PQ-2 do backlog). Os 8 meses atuais não separam vantagem de ruído.
2. **Holdout:** separar o último período (por exemplo, os 12 meses mais recentes) e só olhá-lo uma vez, no final.
3. **Hipótese registrada antes:** regra, parâmetros e quantas variantes serão testadas. Nada de "mais uma variante" depois de ver o resultado.
4. **Comparação com os controles C0 e C1** em toda variante.
5. **Correção para múltiplos testes:** Benjamini-Hochberg ou o Sharpe deflacionado sobre todas as variantes testadas.
6. **Custos realistas:** spread dos dois lados, mais pelo menos 1 tick de slippage no stop. No WIN/WDO, as tarifas da seção 7.
7. **Medir o contrafactual das ordens limite não preenchidas** (seleção adversa), em qualquer estratégia que entre com limite.
8. **Walk-forward** nas variantes que passarem, e só então o período em paper (E3 do backlog).

## 9. Plano de execução sugerido

| Ordem | Teste | Por quê |
|---|---|---|
| 1 | C0 e C1 sobre o Fibo atual | Fecha a questão do Fibonacci com dados próprios. É barato e reaproveita o motor. |
| 2 | Filtro de custo em relação ao stop e perna mínima em ATR, aplicados ao Fibo atual | Mostra quanto do prejuízo é custo evitável. Não cria vantagem, mas é útil para qualquer estratégia. |
| 3 | H3 (BOS como continuação) | Reaproveita o detector de estrutura que você já tem; só muda a entrada. |
| 4 | H1 (noise area + VWAP) em NAS100, US30, DAX40 e WIN | O candidato mais forte com o perfil que você quer. |
| 5 | H4 (ORB) no WIN | Perfil de alvo longo; custo baixo por contrato. |
| 6 | H2 e H5 como filtros ou estratégias separadas | Perfil 1:1; valem como diversificação. |
| — | Filtro de tendência diária e de regime de volatilidade | Aplicados sobre o que passar nos passos 3 a 6. |

Cada teste roda primeiro **sem custo**. Se não houver vantagem bruta acima do controle C0, a ideia é descartada sem gastar tempo com otimização.

## 10. Fontes principais

**Estratégias intraday**
- Gao, Han, Li & Zhou (2018), *JFE* 129(2): https://econpapers.repec.org/RePEc:eee:jfinec:v:129:y:2018:i:2:p:394-414
- Baltussen, Da, Lammers & Martens (2021), *JFE* 142(1): https://www3.nd.edu/~zda/intramom.pdf
- Li, Sakkas & Urquhart (2022), *Journal of Financial Markets*: https://ideas.repec.org/a/eee/finmar/v57y2022ics138641812100001x.html
- Rosa (2022), *Journal of Futures Markets*: https://econpapers.repec.org/RePEc:wly:jfutmk:v:42:y:2022:i:12:p:2218-2234
- Zarattini, Aziz & Barbon (2024), noise area no SPY: https://www.sfi.ch/de/publications/n-24-97-beat-the-market-an-effective-intraday-momentum-strategy-for-s-p500-etf-spy
- Zarattini & Aziz (2023), ORB: https://papers.ssrn.com/abstract=4416622 · replicação (blog, não revisada): https://www.mql5.com/en/blogs/post/776235
- Breedon & Ranaldo (2013), sazonalidade de sessão no FX: https://www.snb.ch/en/publications/research/working-papers/2011/working_paper_2011_04

**Fibonacci, SMC e suporte/resistência**
- Batchelor & Ramyar (2006): https://openaccess.city.ac.uk/16276/
- Tsinaslanidis, Guijarro & Voukelatos (2022): https://riunet.upv.es/handle/10251/195083
- Tangirala (SSRN 2026, preprint): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7483658
- Mahadzva (SSRN 2026, preprint): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7430998
- Osler (2000), suporte e resistência: https://www.newyorkfed.org/research/epr/00v06n2/0007osle.html
- Osler (2003), *Journal of Finance*: https://ideas.repec.org/a/bla/jfinan/v58y2003i5p1791-1819.html
- Osler, stop-loss cascades: https://www.newyorkfed.org/research/staff_reports/sr150.html
- Chung & Bellotti (2021): https://arxiv.org/abs/2101.07410

**Análise técnica, stops e ordens limite**
- Marshall, Cahan & Cahan (2008): https://ideas.repec.org/a/eee/empfin/v15y2008i2p199-210.html
- Sullivan, Timmermann & White (1999): https://econpapers.repec.org/RePEc:bla:jfinan:v:54:y:1999:i:5:p:1647-1691
- Bajgrowicz & Scaillet (2012): https://econpapers.repec.org/RePEc:eee:jfinec:v:106:y:2012:i:3:p:473-491
- Park & Irwin (2007): https://ideas.repec.org/a/bla/jecsur/v21y2007i4p786-826.html
- Kaminski & Lo (2014): https://dspace.mit.edu/handle/1721.1/114876
- Lo & Remorov (2017): https://dspace.mit.edu/handle/1721.1/107017
- Handa & Schwartz (1996): https://econpapers.repec.org/RePEc:bla:jfinan:v:51:y:1996:i:5:p:1835-61
- Linnainmaa (2010): https://ideas.repec.org/a/bla/jfinan/v65y2010i4p1473-1506.html

**Tendência**
- Hurst, Ooi & Pedersen, um século de tendência: https://www.TrendFollowing.com/whitepaper/Century_Evidence_Trend_Following.pdf
- Goulding, Harvey & Mazzoleni (2023), *JFE*: https://econpapers.repec.org/RePEc:eee:jfinec:v:149:y:2023:i:3:p:378-406

**Brasil**
- Chague, De-Losso & Giovannetti (2019): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101
- Chague & Giovannetti (2025): https://portal.fgv.br/sites/default/files/uploads/eesp-pesquisa-day-trade-e-pandemia.pdf
- Barber, Lee, Liu & Odean (2014): https://ideas.repec.org/a/eee/finmar/v18y2014icp1-24.html
- Santos, Garcia & Medeiros (2016), anúncios macro: https://econpapers.repec.org/RePEc:sbe:breart:v:36:y:2016:i:2:a:46421
- B3, características do WIN/WDO: https://borainvestir.b3.com.br/tipos-de-investimentos/renda-variavel/day-trade/conheca-as-caracteristicas-dos-principais-produtos-de-day-trade/
- B3, horários desde 03/11/2026 (OC 055/2026-VNC): https://www.b3.com.br/data/files/BE/16/C1/59/2F881A10F75B881AAC094EA8/OC%20055-2026-VNC%20NOVOS%20HORARIOS%20DE%20NEGOCIACAO_PT.pdf
- B3, RLP em WIN e WDO (OC 038/2025-VNC): https://www.b3.com.br/data/files/17/B4/88/14/AEA99910F5D34899AC094EA8/OC%20038-2025-VNC%20NOVAS%20REGRAS%20DE%20FUNCIONAMENTO%20DE%20OFERTA%20RLP%20NO%20MERCADO%20DE%20ACOES%20E%20PARA%20OS%20MINICONTRATOS%20FUTUROS%20WIN%20E%20WDO_PT.pdf

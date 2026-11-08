# Anexos da pesquisa de estratégias intraday

**Data:** 2026-11-07 · **Documento principal:** [PESQUISA_ESTRATEGIAS_INTRADAY.md](PESQUISA_ESTRATEGIAS_INTRADAY.md)

Este anexo guarda na íntegra os três relatórios de pesquisa que alimentaram o documento principal, para não perder detalhes que ficaram de fora da síntese. Eles foram produzidos por agentes de pesquisa com busca na web, a partir de fontes primárias sempre que possível. O que não foi conferido na fonte está marcado **"não verificado"**.

**Antes de usar um número daqui numa decisão, confira a fonte.** Os preprints SSRN de 2026 (Tangirala, Mahadzva) foram lidos apenas pelo resumo.

Também está aqui o registro dos experimentos locais e como reproduzi-los.

- [Anexo A — Evidência acadêmica sobre estratégias intraday](#anexo-a)
- [Anexo B — Evidência sobre a tese SMC + Fibonacci](#anexo-b)
- [Anexo C — B3: WIN/WDO, custos, calendário e estudos brasileiros](#anexo-c)
- [Anexo D — Experimentos locais](#anexo-d)

---

<a id="anexo-a"></a>
## Anexo A — Evidência acadêmica sobre estratégias intraday

**Resumo:** existem efeitos intraday com respaldo acadêmico sólido, mas o ganho deles é pequeno, da ordem de 1 a 3 bp por dia antes dos custos. A maioria tem acerto acima de 50% com risco:retorno perto de 1:1, o contrário do perfil procurado.

O que chega perto de 1:3 com 30–40% de acerto é o momentum de rompimento de "noise area" com trailing stop. A evidência é moderada: vem de um único grupo de autores e é quase toda in-sample.

O resultado mais robusto da literatura é negativo: regras técnicas sem correção para data-snooping e sem custos realistas não sobrevivem.

### A.1 Ranking dos candidatos testáveis em OHLC M1

| # | Estratégia | Evidência | Perfil | Instrumentos do dataset |
|---|---|---|---|---|
| 1 | Noise area + trailing stop no VWAP (Zarattini, Aziz, Barbon 2024) | Moderada | Acerto 37–43%, cauda direita | NAS100, US30, DAX40, XAU, BRENT, WIN |
| 2 | Momentum intraday de mercado: retorno do dia até 30 min antes do fechamento prevê a última meia hora (Gao et al. 2018; Baltussen et al. 2021) | Forte para o efeito existir, fraca a moderada para lucro líquido | Acerto 53–56%, risco:retorno ~1:1 | NAS100, US30, DAX40, BRENT, XAU, WIN (fraco no FX) |
| 3 | Sazonalidade de sessão no FX (Breedon & Ranaldo 2013) | Moderada até 2007; depois, não verificado | ~1:1 | EURUSD (GBPUSD não lucra líquido) |
| 4 | ORB do primeiro candle de 5 min com alvo de 10R (Zarattini & Aziz 2023) | Fraca para índices | Acerto ~24%, R:R até 10 | NAS100, US30, DAX40, WIN |
| 5 | Overnight drift 02–03h ET (Boyarchenko et al. 2023) | Fraca hoje (perto de zero desde 2021) | — | NAS100, US30 |

### A.2 Noise area / intraday momentum no SPY

**Fonte:** Zarattini, Aziz & Barbon (2024), "Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY)". Working paper SSRN 4824172 / Swiss Finance Institute 24-97, não revisado por pares. Período: SPY, 2007 a abril de 2024. O PDF foi lido.

**Regra:**
- Para cada horário HH:MM, calcule σ como a média, nos últimos 14 dias, de |Close(HH:MM)/Open(9:30) − 1|.
- Banda superior: UB = max(Open_t, Close_{t−1})·(1+σ).
- Banda inferior: LB = min(Open_t, Close_{t−1})·(1−σ).
- Decisões só às HH:00 e HH:30. Compra se o preço estiver acima de UB e vende se estiver abaixo de LB.
- Trailing stop: na compra, max(UB, VWAP); na venda, min(LB, VWAP). Se o preço cruzar a banda oposta, a posição vira.
- Zera no fechamento.
- Dimensionamento: exposição para ter 2% de volatilidade diária, com alavancagem máxima de 4x.

**Resultados, líquidos de custos:**

| Versão | Retorno ao ano | Sharpe | Acerto diário | Drawdown máx. |
|---|---|---|---|---|
| Base (stop na banda oposta) | 6,2% | 0,61 | 53% | — |
| Banda + VWAP | 9,7% | 1,24 | 43% | — |
| Banda + VWAP com dimensionamento dinâmico | 19,6% | 1,33 | 43% | 25% |

- A versão com dimensionamento dinâmico acumulou 1.985% no período.
- Acerto por trade: 37%.
- Custo assumido: US$0,0035 por ação de comissão + US$0,001 por ação de slippage. Com o modelo de impacto I-Star, o Sharpe cai para 1,17.
- **Em 33 futuros** (FAQ do paper: 21 commodities e 12 índices, 2007–2024, mesmas regras):
  - Sharpe médio por ativo de 0,60.
  - Nasdaq 1,23, S&P 1,32.
  - Carteira diversificada 1,65.
  - Os custos usados nos futuros não foram verificados.
- Os autores dizem que lookback de 90 dias e multiplicador de 1,5 seriam melhores que os parâmetros publicados. Isso é argumento contra overfitting, mas não substitui um teste OOS independente.

**Críticas:**
- Tudo in-sample, de um único grupo de autores, sem holdout formal.
- O SPY é o mercado mais estudado, o que gera viés de sobrevivência.

**Testabilidade:** alta, com M1 por horário. O VWAP do Dukascopy usa volume de ticks (aproximação). O WIN tem volume real.

**Risco no CFD:** o spread pago a cada virada de posição pesa muito mais que US$0,0035 por ação.

### A.3 Momentum intraday de mercado (primeira → última meia hora)

**Fontes:**
- Gao, Han, Li & Zhou (2018), "Market intraday momentum", *JFE* 129(2). SPY, 1993–2013.
- Baltussen, Da, Lammers & Martens (2021), "Hedging demand and market intraday momentum", *JFE* 142(1). Mais de 60 futuros, 1974–2020.

**Regra:**
- Gao et al.: r1 é o retorno do fechamento anterior até as 10:00. Se r1 > 0, compra na penúltima meia hora (15:30) e zera no fechamento; se r1 < 0, vende.
- Baltussen et al.: o sinal mais forte é r_ROD, o retorno do fechamento anterior até 30 min antes do fechamento.

**Resultados:**
- **Gao et al. (SPY):** 6,67% ao ano, desvio de 6,19%, Sharpe 1,08, acerto de 54,37%. Pós-2005, descontado o spread (~1,2 bp), 6,52% ao ano contra 7,96% bruto.
- **Baltussen et al. (Sharpe bruto de η(r_ROD)):**

  | Classe | Sharpe | Acerto |
  |---|---|---|
  | Índices | 1,73 | 55% |
  | Juros | 1,62 | 55% |
  | Commodities | 1,42 | 56% |
  | Moedas | 0,87 | 53% |

  - Não há custos, exceto a afirmação de que no futuro do S&P, com custo de 1 tick, o Sharpe continua positivo.
  - No FX o efeito não é significativo em 2000–2020 (β = 0,33, t = 1,45).
  - O retorno anual nos índices (~6,9%) equivale a poucos bp por dia.

**Replicação e críticas:**
- Li, Sakkas & Urquhart (2022, *JFM*): o efeito aparece em 16 mercados desenvolvidos, in e out-of-sample, na maioria deles. Não foi verificado se a Alemanha está entre os significativos.
- Rosa (2022, *Journal of Futures Markets*): "the predictability disappears in the out-of-sample period". Limiares no sinal melhoram o resultado.
- O efeito se concentra em dias de volatilidade alta e de gamma negativo.

**Brasil:** nenhum estudo encontrado para WIN/Ibovespa.

**Testabilidade:** alta. Nos CFDs, usar o horário do pregão do ativo subjacente. O risco é o spread consumir 1–3 bp por dia de vantagem.

### A.4 Sazonalidade de sessão no FX

**Fonte:** Breedon & Ranaldo (2013), *Journal of Money, Credit and Banking* 45(5). EBS, 1997 a junho de 2007. O working paper do SNB foi lido.

**Regra:** a moeda tende a depreciar no horário do próprio país. No EUR/USD, vende na sessão europeia e compra na americana. Os horários exatos de corte não foram confirmados.

**Resultados:**
- Líquidos de bid/ask do EBS: Sharpe 1,3 na venda da manhã e 0,9 na compra da tarde.
- Nos outros pares, quase tudo fica negativo depois de custos, inclusive GBPUSD e USDJPY.
- A diferença entre sessões foi estável ano a ano, exceto em 2004.

**Não verificado:** desempenho pós-2007. O spread de varejo é maior que o do EBS.

### A.5 ORB do primeiro candle de 5 min com alvo de 10R

**Fonte:** Zarattini & Aziz (2023), "Can Day Trading Really Be Profitable?", SSRN 4416622. QQQ, 2016–2023.

**Regra:**
- A direção é a do primeiro candle de 5 min.
- Entrada na abertura do segundo candle.
- Stop no extremo oposto do primeiro candle.
- Alvo de 10R ou saída no fechamento.
- Risco de 1% por trade, alavancagem máxima de 4x.

**Resultados:** acerto de ~24%, ~+0,13R por trade, 1.484% no total. Custo: comissão de US$0,0005 por ação, sem slippage.

**Replicação independente** (blog MQL5, 2026, não revisado; CFDs de NQ, SPX, Dow, DAX e FTSE, 2015–2026):
- O resultado bruto se reproduz: NQ com +0,131R e 23% de acerto.
- Líquido de spread, fica em torno de zero ou negativo: NQ +0,002R, DAX −0,038R.
- No OOS de 2021–2026, no máximo +0,06R.
- Antes de custos, a vantagem sobre uma direção aleatória foi de ~0,1R.

**"Stocks in Play"** (Zarattini, Barbon & Aziz 2024, SSRN 4729284): Sharpe de 2,81 líquido, mas exige um universo de ações com volume relativo. Não é testável com os dados do projeto.

### A.6 Overnight drift

**Fonte:** Boyarchenko, Larsen & Whelan (2023), *Review of Financial Studies* 36(9).

**Resultado:** o futuro do S&P concentrou ~3,7% ao ano (~1,48 bp/dia) na janela das 02:00 às 03:00 ET, na abertura europeia, entre 1998 e 2019.

**Decaimento:** um post do NY Fed (Liberty Street, 2026) relata média perto de zero desde 2021. Visto apenas pelo resumo da busca.

### A.7 Tendência intraday e filtro de timeframe maior

- Não foi encontrado estudo acadêmico que valide especificamente "tendência no timeframe maior + entrada no menor".
- O condicionamento com suporte na literatura é o regime de volatilidade:
  - Gao et al.: no OOS, a estratégia rende muito mais no tercil de alta volatilidade da primeira meia hora, e tem Sharpe 2,10 em recessões.
  - Zarattini et al.: o Sharpe sobe com o VIX.
  - Baltussen et al.: o efeito é maior em dias de gamma negativo.
- Sugestão: tratar o filtro de timeframe maior como hipótese a testar com controle de múltiplos testes.

### A.8 Mean reversion, VWAP e sazonalidade

- **VWAP de tendência no QQQ** (Zarattini & Aziz 2023, SSRN 4631351): Sharpe de 2,1 em 2018–2023, líquido só de comissão. Replicações no QuantConnect relatam resultados bem piores (verificação secundária). Evidência fraca.
- **Reversão:** Baltussen et al. mostram que o momentum intraday reverte nos dias seguintes. Não foi achada estratégia de reversão intraday em índices ou FX com evidência líquida robusta (não verificado).
- **Sazonalidade de volatilidade** (Andersen & Bollerslev 1997, *JEF*): útil para normalizar stop/ATR por horário, não como sinal.

### A.9 O que a evidência diz que NÃO funciona

- **Regras técnicas intraday genéricas:** Marshall, Cahan & Cahan (2008, *Journal of Empirical Finance*) testaram 7.846 regras no SPDR de 5 min (2002–2003), com bootstrap. Nenhuma foi significativa.
- **Correção para data-snooping:**
  - Sullivan, Timmermann & White (1999, *JF*): no DJIA, a melhor regra perde significância no OOS de 1987–1996.
  - Bajgrowicz & Scaillet (2012, *JFE*): mesmo in-sample, custos baixos eliminam o desempenho, e não dá para escolher as melhores regras de antemão.
- **Revisões da literatura:**
  - Park & Irwin (2007, *Journal of Economic Surveys*): 56 de 95 estudos são positivos, mas os lucros se concentram até o início dos anos 1990, com data-snooping e custos mal tratados.
  - Lo, Mamaysky & Wang (2000, *JF*): os padrões gráficos têm informação incremental, mas não demonstram lucro líquido.
- **Pre-FOMC drift** (Lucca & Moench 2015): desapareceu depois de 2015 (Kurov, Wolfe & Gilbert, *Finance Research Letters*, 2020/21).
- **Day traders de varejo:**
  - Barber, Lee, Liu & Odean (2014, *JFM*), Taiwan 1992–2006: menos de 1% lucra de forma previsível, líquido de taxas.
  - Chague, De-Losso & Giovannetti ("Day Trading for a Living?", 2019/20, FGV), WIN 2013–2015: 97% de quem persistiu 300 dias ou mais perdeu, e 0,4% ganhou mais que um bancário (US$54/dia).

**Recomendações para o backtest:**
- Aplicar White Reality Check, Hansen SPA ou FDR sobre todo o espaço de parâmetros testado.
- Separar um período OOS (por exemplo, de 2021 em diante como holdout).
- Comparar com um benchmark de direção aleatória.
- Cobrar o spread real do Dukascopy, com o ask reconstruído, em toda entrada e saída.

### A.10 Fontes do Anexo A

**Momentum intraday**
- Gao et al. 2018, *JFE*: https://econpapers.repec.org/RePEc:eee:jfinec:v:129:y:2018:i:2:p:394-414 (versão de 2015, lida: https://c.mql5.com/forextsd/forum/173/intraday_momentum_-_the_first_half-hour_return_predicts_the_last_half-hour_return.pdf)
- Baltussen et al. 2021, *JFE* (lido): https://www3.nd.edu/~zda/intramom.pdf
- Li, Sakkas & Urquhart 2022, *JFM*: https://ideas.repec.org/a/eee/finmar/v57y2022ics138641812100001x.html
- Rosa 2022, *JFutM*: https://econpapers.repec.org/RePEc:wly:jfutmk:v:42:y:2022:i:12:p:2218-2234

**Noise area, ORB e VWAP**
- Zarattini, Aziz & Barbon 2024, SPY (lido): https://alexandria.unisg.ch/server/api/core/bitstreams/a99aba00-f967-49b3-aceb-f544dc386e0b/content ; https://www.sfi.ch/de/publications/n-24-97-beat-the-market-an-effective-intraday-momentum-strategy-for-s-p500-etf-spy
- Zarattini & Aziz 2023, ORB QQQ: https://papers.ssrn.com/abstract=4416622
- Replicação do ORB (blog, não revisado): https://www.mql5.com/en/blogs/post/776235
- Stocks in Play: https://ideas.repec.org/p/chf/rpseri/rp2498.html
- VWAP: https://concretumgroup.com/volume-weighted-average-price-vwap-the-holy-grail-for-day-trading-systems/
- Holmberg et al. 2013, ORB em petróleo (resultados não verificados): https://ideas.repec.org/a/eee/finlet/v10y2013i1p27-33.html

**Sazonalidade e anúncios**
- Breedon & Ranaldo 2013 (working paper lido): https://www.snb.ch/en/publications/research/working-papers/2011/working_paper_2011_04
- Boyarchenko et al. 2023: https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr917.pdf
- Kurov et al., pre-FOMC: https://www.skidmore.edu/economics/documents/KurovWolfeGilbert-TheDisappearingPre-FOMC-Announce-Drift-200914.pdf

**Análise técnica e data-snooping**
- Park & Irwin 2007: https://ideas.repec.org/a/bla/jecsur/v21y2007i4p786-826.html
- Sullivan, Timmermann & White 1999: https://bashtage.github.io/kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Sullivan_Timmermann_White.pdf
- Bajgrowicz & Scaillet 2012: https://econpapers.repec.org/RePEc:eee:jfinec:v:106:y:2012:i:3:p:473-491
- Marshall, Cahan & Cahan 2008: https://ideas.repec.org/a/eee/empfin/v15y2008i2p199-210.html

**Day traders de varejo**
- Barber et al. 2014: https://ideas.repec.org/a/eee/finmar/v18y2014icp1-24.html
- Chague et al., day trading no Brasil: https://ideas.repec.org/p/fgv/eesptd/525.html

**Citados sem verificação nesta pesquisa:** Lo, Mamaysky & Wang 2000 (*JF* 55(4)); White 2000 (*Econometrica*, Reality Check); Hansen 2005 (*JBES*, SPA); Andersen & Bollerslev 1997 (*JEF*).

---

<a id="anexo-b"></a>
## Anexo B — Evidência sobre a tese SMC + Fibonacci

### B.1 Veredito

**Resumo:** a evidência contra "Fibonacci/OTE/SMC" é moderada a forte. A favor de "existe tendência", ela é forte em meses e moderada intraday, no nível da sessão. A favor de "comprar o pullback na tendência" como fonte de vantagem, é fraca ou inexistente.

1. **Níveis de Fibonacci não se mostram especiais.**
   - Batchelor & Ramyar (2006, Cass), DJIA 1914–2002: pivôs identificados por métodos de ciclo econômico e testados com block bootstrap. Houve poucas razões "significativas", em número compatível com o acaso dado o número de testes.
   - Tsinaslanidis, Guijarro & Voukelatos (2022, *Expert Systems with Applications*), com detecção algorítmica de retrações em 3 mercados acionários: o comportamento em zonas Fibonacci não difere estatisticamente do comportamento em zonas não-Fibonacci. A probabilidade de "bounce" cresce com a largura da zona, ou seja, é efeito de tamanho e não da razão. Os autores alertam que isso não implica estratégia lucrativa. Mercados e período não foram verificados (só o abstract foi lido).
2. **SMC/ICT não tem evidência revisada por pares a favor.** Os dois testes sistemáticos encontrados são preprints SSRN de 2026, não revisados. Os PDFs não foram lidos; os dados abaixo vêm do abstract e de resumos de terceiros.
   - **Tangirala** (SSRN 7483658): 44 detectores SMC no S&P 500 diário, 2010–2026. Contra um nulo de retorno zero, 38 parecem significativos. Contra um nulo de entrada aleatória pareada, com correção Benjamini-Hochberg sobre 352 hipóteses, nenhum bate o acaso.
   - **Mahadzva** (SSRN 7430998): FX intraday (EURUSD, GBPUSD, AUDUSD, USDJPY), com walk-forward, permutação e holdout. Conclusão: "no evidence that ICT/SMC concepts work as literally taught". Dois achados relevantes:
     - O sweep de liquidez prevê continuação, não reversão (65 de 66 folds).
     - Uma regra teve vantagem por trade menor que a comissão imposta pelos stops curtos.
   - **StatOasis** (teste prático reproduzível; SPY/QQQ/DIA/IWM diário, sem custos): a OTE de 61,8–78,6% após quebra de estrutura bateu a entrada aleatória em 0% das variantes no SPY. Só 1 de 32 estatísticas t passou de 2.
   - **FVG e order block intraday:** nada rigoroso com custos foi encontrado. Status: sem evidência.
3. **Análise técnica intraday em geral morre nos custos.**
   - Marshall, Cahan & Cahan (2008): 7.846 regras em SPY de 5 min (2002–03), nenhuma lucrativa após correção de data-snooping, e isso antes dos custos.
   - Neely & Weller (2003): FX intraday sem excesso de retorno com custos e horários realistas.
   - Frömmel & Lampaert (2016): mais de 8.000 regras no RUB/USD; spreads reais apagam a maior parte do lucro.
   - Bajgrowicz & Scaillet (2012): DJIA 1897–2011; custos baixos zeram o desempenho, mesmo in-sample.
   - Sullivan, Timmermann & White (1999): as regras de Brock et al. (1992) não persistem em 1987–96.
4. **Suporte/resistência e stops existem, mas o efeito é pequeno** (números de Osler 2000 e 2002 verificados no PDF).
   - **Osler (2000):** em níveis publicados por 6 firmas de FX, o bounce foi de 60,8%, contra 56,2% em níveis aleatórios. São +4 a +5,6 pontos percentuais em 15 minutos, e o efeito dura cerca de 5 dias úteis.
   - **Osler (2002/2005):** stops se concentram logo além de números redondos (00/50). Depois de cruzar um número redondo, o DEM se move 0,061% em 15 minutos, contra 0,054% em números arbitrários: menos de 1 bp de diferença. O efeito é significativo por horas, não por dias.
   - **Kavajecz & Odders-White (2004):** níveis de suporte e resistência coincidem com picos de profundidade no livro.
   - **Chung & Bellotti (2021):** níveis com mais toques prévios rebatem mais, e o efeito decai com o tempo.
   - É o análogo acadêmico de "liquidez", mas a direção depois do rompimento é **continuação**, o oposto da narrativa de "stop hunt + reversão".
5. **Diagnóstico do resultado.** Num passeio aleatório sem drift, a probabilidade de atingir +3R antes de −1R é 1/(1+3) = 25%, o que dá expectativa bruta de 0R. O resultado de ~0R ±0,02 antes de custos é a assinatura de ausência de vantagem.
   - Com custo médio c (em R), o break-even exige p* = (1+c)/(RR+1). Com RR = 3: c = 0,10 → 27,5%; c = 0,17 → 29,3%; c = 0,22 → 30,5%.
   - A ordem limite em retração sofre **seleção adversa**: é preenchida mais vezes quando o pullback vira reversão e perde os trades que viram antes de chegar ao nível (Handa & Schwartz 1996; Linnainmaa 2010).
   - Kaminski & Lo (2014): sob passeio aleatório, stop-loss reduz o retorno esperado; só agrega quando há autocorrelação positiva.
   - Lo & Remorov (2017): stops curtos perdem para buy-and-hold por causa do custo.

### B.2 Variantes testáveis, em ordem de suporte (OHLC M1/M5)

1. **Filtro de tendência no timeframe maior (time-series momentum).** É a evidência mais forte: Hurst, Ooi & Pedersen (1880–2016) reportam Sharpe de carteira ~0,76 líquido e ~0,4 por mercado; ver também Moskowitz, Ooi & Pedersen (2012).
   - **Regra:** só comprar se o retorno D1 de 20 ou 60 dias for > 0, ou se o fechamento estiver acima da EMA de D1; o inverso para vender.
   - **Ressalva:** Goulding, Harvey & Mazzoleni (*JFE* 2023) mostram que no estado de "Correção" (tendência lenta positiva, rápida negativa), que é exatamente o pullback, os retornos pioram e a volatilidade sobe. Eles recomendam reduzir a exposição nesse estado, não aumentar.
   - **Teste:** setup com e sem o filtro, e com tamanho reduzido no estado de correção.
2. **Momentum intraday de sessão em vez de retração.**
   - Gao, Han, Li & Zhou (*JFE* 2018; SPY 1993–2013): o retorno da 1ª meia hora prevê o da última, com R² ~1,6%. A previsibilidade é maior com volatilidade e volume altos. Replicado em 12 de 16 mercados (Baltussen et al.); no FX, em Elaut et al. (2018) com RUB/USD.
   - Zarattini, Aziz & Barbon (2024, working paper SFI): rompimento de uma "noise area", definida como abertura × (1 ± movimento médio dos últimos 14 dias até aquele minuto), checado só a cada 30 minutos, com saída por VWAP ou no fim do dia. Sharpe de 1,33 líquido em 2007–2024. Sem replicação independente; ver o item 7.
   - **Regra M5:** entrar na direção do rompimento da banda de ruído e sair no fechamento da sessão.
3. **"Sweep"/rompimento como continuação, não reversão** (Osler 2005; Mahadzva 2026).
   - **Regra:** um candle M5 fecha além de um swing high/low de N barras, ou de um número redondo 00/50 → entrada a mercado na direção do rompimento, stop atrás do nível, saída por tempo (15–120 min).
   - Antes de otimizar, medir o MFE e o MAE líquidos. O efeito bruto de Osler é menor que 1 bp, então provavelmente só sobrevive em ativos com spread muito baixo.
4. **Confluência com níveis que têm evidência, em vez da razão Fibonacci:** números redondos (Osler 2000) e swings com 2 ou mais toques prévios recentes (Chung & Bellotti).
   - **Regra:** só manter a ordem limite se a zona 61,8–70,5% contiver um número redondo ou um swing anterior com ≥2 toques nos últimos X dias.
   - **Placebo:** trocar 0,618/0,705 por razões aleatórias em [0,4; 0,9] e comparar, no desenho de Batchelor & Ramyar e Tsinaslanidis. Se o placebo empatar, Fibonacci não agrega nada.
5. **Filtro de custo e de tamanho mínimo de perna e stop** (Lo & Remorov; nota de Mahadzva sobre stop mínimo). Isso não cria vantagem, mas reduz c de ~0,17R para menos de 0,08R.
   - Descartar o trade se spread + slippage > 5–8% da distância do stop.
   - Descartar se a perna do BOS for < k·ATR(14, M5 ou H1), com k ∈ {1,5; 2; 3}.
   - Descartar se o stop for < m·ATR.
6. **Filtros de janela e de volatilidade.** A previsibilidade intraday se concentra em períodos de alta liquidez e volatilidade (Gao et al.).
   - Operar só nas janelas de abertura e de sobreposição Londres–NY.
   - Exigir ATR(M5) dentro de uma faixa em relação à mediana de 20 dias.
   - Evitar ±15 min de notícias.
7. **Saída por tempo ou no fim do dia, em vez de alvo fixo de 3R.** Gao e Zarattini usam saída temporal.
   - **Teste:** alvo 3R contra trailing EMA8 contra saída por tempo, sempre comparado com uma entrada aleatória pareada em frequência e direção.
   - Uma replicação prática (blog no MQL5) do ORB de Zarattini & Aziz em 5 índices relata "gross reproduced, net zero" (não verificado).

**Protocolo mínimo para qualquer variante:**
- baseline de entrada aleatória pareada e de níveis placebo;
- walk-forward;
- deflated Sharpe ou Benjamini-Hochberg sobre todas as variantes testadas;
- medir o contrafactual dos trades em ordem limite que não foram preenchidos.

### B.3 Fontes do Anexo B

**Fibonacci**
- Batchelor & Ramyar 2006: https://openaccess.city.ac.uk/16276/
- Tsinaslanidis et al. 2022 (ESWA, DOI 10.1016/j.eswa.2021.115893): https://riunet.upv.es/handle/10251/195083

**Suporte, resistência e stops**
- Osler 2000, FRBNY EPR: https://www.newyorkfed.org/research/epr/00v06n2/0007osle.html
- Osler 2003, *JF*: https://ideas.repec.org/a/bla/jfinan/v58y2003i5p1791-1819.html ; SR125: https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr125.pdf
- Osler, stop-loss cascades (SR150): https://www.newyorkfed.org/research/staff_reports/sr150.html
- Kavajecz & Odders-White 2004, *RFS*: https://ideas.repec.org/a/oup/rfinst/v17y2004i4p1043-1071.html
- Chung & Bellotti 2021: https://arxiv.org/abs/2101.07410

**SMC/ICT**
- Tangirala (SSRN, preprint): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7483658
- Mahadzva (SSRN, preprint): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=7430998 ; resumo secundário: https://thortradecopier.com/blog/does-ict-smart-money-concepts-work
- StatOasis, backtest ICT (prático): https://statoasis.com/overfit/research/ict-backtest-what-survives

**Análise técnica e custos**
- Marshall, Cahan & Cahan 2008: https://ideas.repec.org/a/eee/empfin/v15y2008i2p199-210.html
- Neely & Weller 2003: https://econpapers.repec.org/RePEc:fip:fedlwp:1999-016
- Frömmel & Lampaert 2016: https://ideas.repec.org/a/eee/finlet/v18y2016icp177-183.html
- Bajgrowicz & Scaillet 2012: https://econpapers.repec.org/RePEc:eee:jfinec:v:106:y:2012:i:3:p:473-491
- Brock, Lakonishok & LeBaron 1992: https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1731-64.html
- Sullivan, Timmermann & White 1999: https://econpapers.repec.org/RePEc:bla:jfinan:v:54:y:1999:i:5:p:1647-1691

**Tendência e momentum**
- Hurst, Ooi & Pedersen: https://www.TrendFollowing.com/whitepaper/Century_Evidence_Trend_Following.pdf
- Goulding, Harvey & Mazzoleni 2023: https://econpapers.repec.org/RePEc:eee:jfinec:v:149:y:2023:i:3:p:378-406
- George & Hwang 2004 (52-week high): https://typeset.io/pdf/the-52-week-high-and-momentum-investing-4u9j16d52p.pdf
- AQR, "Hold the Dip" 2025: https://www.aqr.com/Insights/Research/Alternative-Thinking/Hold-the-Dip
- Gao et al. 2018: https://econpapers.repec.org/RePEc:eee:jfinec:v:129:y:2018:i:2:p:394-414
- Elaut, Frömmel & Lampaert 2018: https://ideas.repec.org/a/eee/finmar/v37y2018icp35-51.html

**Estratégias intraday**
- Zarattini, Aziz & Barbon 2024: https://www.sfi.ch/de/publications/n-24-97-beat-the-market-an-effective-intraday-momentum-strategy-for-s-p500-etf-spy
- Zarattini & Aziz, ORB: https://papers.ssrn.com/abstract=4416622 ; replicação (prática, não verificada): https://www.mql5.com/en/blogs/post/776235
- Holmberg, Lönnbark & Lundström 2013 (ORB, petróleo): https://econpapers.repec.org/RePEc:eee:finlet:v:10:y:2013:i:1:p:27-33

**Stops e ordens limite**
- Kaminski & Lo 2014: https://dspace.mit.edu/handle/1721.1/114876
- Lo & Remorov 2017: https://dspace.mit.edu/handle/1721.1/107017
- Handa & Schwartz 1996: https://econpapers.repec.org/RePEc:bla:jfinan:v:51:y:1996:i:5:p:1835-61
- Linnainmaa 2010: https://ideas.repec.org/a/bla/jfinan/v65y2010i4p1473-1506.html

**Não verificado neste anexo:**
- texto completo dos dois preprints SMC;
- mercados e período de Tsinaslanidis;
- números do "Hold the Dip" (196 variantes desde 1965, via fonte secundária);
- resultados de trading-range-break de Brock et al.

---

<a id="anexo-c"></a>
## Anexo C — B3: WIN/WDO, custos, calendário e estudos brasileiros

### C.1 Calibração de expectativas: quantos day traders lucram

**Chague, De-Losso & Giovannetti, "Day trading for a living?"** (WP FEA-USP 2019_47, 11/12/2019; revisão SSRN em jun/2020).
- Amostra: todas as pessoas físicas que começaram a fazer day trade no futuro de Ibovespa (na prática, WIN) entre 2013 e 2015, com dados da CVM.
- 19.646 começaram e só 1.551 (7,9%) persistiram mais de 300 pregões. Desses persistentes:
  - 97% perderam dinheiro;
  - 1,1% ganhou mais que o salário mínimo (~US$16/dia);
  - 0,4–0,5% ganhou mais que um caixa de banco (US$54/dia). As fontes divergem entre 0,4% e 0,5%.
- O melhor trader ganhou US$310/dia, com desvio-padrão de US$2.560.
- Não há evidência de aprendizado. Entre quem operou um único dia, 29,8% tiveram lucro (sorte).
- Confiabilidade alta: base censitária e autores sérios. Mas é working paper, e não foi verificado se o lucro é líquido ou bruto de taxas.

**Chague & Giovannetti, "As pandemias de COVID-19 e de day trade no Brasil"** (texto de 09/09/2025; segundo a imprensa, publicado na RBFin). Dados da CVM de 2017 a 2023, com foco no mercado futuro.
- Perdas brutas de R$ 9,9 bi desde o início da pandemia até dez/2023, média de R$ 10,2 mil por pessoa, antes de corretagem e emolumentos.
- O resultado agregado das pessoas físicas foi negativo em 95,8% dos dias antes da pandemia e em 96,4% depois de março de 2020.
- Confiabilidade alta: o PDF foi lido.

**Estudo encomendado pela CVM** (dados de 2012 a 2017, WIN+WDO): só foram achados relatos de imprensa. 19.696 iniciantes, 1.558 persistentes, cerca de 91% dos persistentes com prejuízo. Não verificado na fonte primária.

**Implicação:** o varejo perde no agregado antes dos custos, ou seja, a contraparte é sofisticada. Com R:R de 1:3, o break-even é 25% mais os custos; 30% de acerto dá +0,2R/trade e 40% dá +0,6R/trade. Qualquer vantagem precisa ser provada OOS e já com custos.

### C.2 Custos e especificações (B3)

| Item | WIN | WDO | Fonte e status |
|---|---|---|---|
| Tamanho | 0,2 × Ibovespa | US$ 10.000 | B3 Bora Investir, 22/10/2025 |
| Tick e valor | 5 pts = R$ 1,00 (R$0,20/pt) | 0,5 pt = R$ 5,00 (R$10/pt) | Confirmado nessa fonte |
| Tarifa única B3 (emolumentos + registro), faixa de ADV mais baixa | R$1,97 × fator 0,2 do contrato ≈ **R$0,39 por contrato por lado** | US$0,97 × fator 0,25 ≈ **US$0,24 por contrato por lado** | Páginas de tarifas da B3 (EN). Cálculo com o fator feito pelo agente; a página não tem data de vigência |
| Redução de day trade | 35% (ADV DT 1–5) e 40% (6–50) → ~R$0,24–0,26 por lado | 16% (1–20) e 25% (21–500) → ~US$0,20 por lado | Tabelas progressivas da B3 |
| Ida e volta em DT (estimativa) | ~R$0,50 ≈ 2,5 pts | ~R$2,1–2,2 ≈ 0,2 pt (câmbio de ~R$5,4, não verificado) | Coerente com o "custo máximo" de R$0,50 (WIN) e R$2,12 (WDO) da B3 Bora Investir |
| Programa PF da B3 (desde 08/09/2026) | tarifa R$0,21 × 0,15 | US$0,11 × 0,25 | OC 038/2026-PRE. Exige média ≥7.500 contratos/dia; não se aplica a operador pequeno |
| Tarifa de liquidação | R$0,30 | US$0,12 | Página da B3. Em tese incide sobre posição liquidada, não sobre DT zerado (não verificado) |
| Corretagem | Zero em muitas corretoras (ex.: Genial) | Idem | Corretoras. ISS/PIS/COFINS só incidem se houver corretagem |
| Spread típico | 1 tick (5 pts) | 1 tick (0,5 pt) | Não verificado (conhecimento de praticante) |
| Margem mínima DT | R$155 desde 02/02/2026 (antes R$100) | R$140 (antes R$150) | OC 059/2025-VPC, via Okai/InfoMoney |
| IR | 20% sobre o lucro líquido mensal de DT, DARF 6015, sem isenção | Idem | A MP 1.303/2025 (alíquota única de 17,5%) caducou em out/2025; os 20% continuam valendo |
| IRRF ("dedo-duro") | 1% sobre o resultado positivo diário | Idem | Amplamente citado (IN RFB 1.585/2015); não confirmado no texto primário |

**Na prática:** no WIN, o slippage de stops a mercado (5–10 pts) pesa mais que os emolumentos. No WDO, um tick de slippage (R$5) custa mais que o dobro das tarifas de ida e volta.

### C.3 Sessão e vencimentos

- **WIN/IND:** 09:00–18:25, com pré-abertura 5 minutos antes. Não muda com o horário de verão americano.
- **O que muda com o horário de verão americano é o fechamento das ações e o ajuste do WIN.** Fontes: OC 005/2026-PRE e OC 055/2026-VNC (texto dos PDFs lido).

  | Período | Ações à vista | Call de fechamento | Ajuste do WIN |
  |---|---|---|---|
  | 09/03 a 02/11/2026 | 10:00–16:55 | até 17:00 | 17:00–17:15 |
  | Desde 03/11/2026 | 10:00–17:55 | 17:55–18:00 | 18:00–18:15 |

  No dia do vencimento, o contrato que vence encerra às 18:00.
- **WDO:** 09:00–18:30. Os ofícios dizem apenas "inalterados" para os produtos não listados; o horário de 18:30 vem de fontes secundárias. A janela de ajuste do WDO não foi verificada.
- **Abertura dos EUA em horário de Brasília:** 11:30 de novembro a março e 10:30 de março a novembro. Os dados macro americanos das 8:30 ET saem às 10:30 e às 9:30 BRT, respectivamente. O Brasil continua sem horário de verão em 2026/27 (Decreto 9.772/2019; o MME manteve, segundo a imprensa).
- **Vencimento do WIN:** meses pares, na quarta-feira mais próxima do dia 15. As datas de 15/04 e 17/06/2026 caem em quartas-feiras, então a proposta da B3 de passar para a 3ª sexta não foi aplicada ao WIN.
- **Vencimento do WDO:** todo mês, no 1º dia útil; o último pregão é o dia útil anterior. A rolagem acontece nos últimos dias do mês, junto com a PTAX de fim de mês.
- **Série contínua:** a emenda de contratos gera saltos artificiais (no WIN, por causa da base de juros).
  - Recomendação: virar de contrato pelo cruzamento de volume, zerar a posição diariamente e não calcular indicadores atravessando a virada.
  - Não foi achada documentação da Nelogica sobre WIN$N/WINFUT; vale verificar se essas séries são ajustadas.
- **RLP (Retail Liquidity Provider):** a OC 038/2025-VNC traz novas regras de RLP para WIN e WDO. A corretora pode executar contra a própria carteira, o que afeta a qualidade de execução.

### C.4 Efeitos e estratégias da B3 para testar com M1

1. **Volatilidade após dados macro e abertura dos EUA.** Evidência **moderada**: é acadêmica, mas antiga, e a surpresa exige dados de consenso.
   - Fonte: Santos, Garcia & Medeiros (*Brazilian Review of Econometrics*, 2016), dados intraday de out/2008 a jan/2011. Anúncios externos dominam o dólar futuro e o Ibovespa futuro; os domésticos afetam sobretudo juros.
   - O efeito persiste cerca de 20 minutos (segundo o working paper). Uma estratégia condicionada ao sinal da surpresa acertou ~70% OOS, sem custos confirmados.
   - Teste: rompimento ou continuação após 10:30/9:30 BRT, com filtro de não operar antes do dado.
2. **Momentum intradiário** (retorno do dia prevê a última meia hora). Evidência **moderada por analogia**; o perfil esperado é acerto ~50%, não 1:3.
   - É forte lá fora (Gao et al., *JFE* 2018; Baltussen et al., *JFE* 2021, mais de 60 futuros), mas não foi achado estudo com dados do Brasil.
   - No WIN, o "fim" relevante é o call de fechamento das ações e a janela de ajuste, que mudam com o horário de verão americano.
3. **Liderança do WDO sobre o spot e ligação com DXY e juros americanos.** Evidência **fraca a moderada**.
   - Ventura & Garcia (RBE 2012, dados de 2006–07): o futuro lidera o spot. Rossi et al. (BID 2022): o futuro prevê o spot no horizonte de 1 minuto. Não foi achado estudo do WDO contra o DXY intraday.
   - Com M1 e execução de varejo, explorar defasagens de segundos é inviável; um filtro de regime pelo DXY é testável.
4. **Janelas da PTAX e disputa pela PTAX de fim de mês no WDO.** Evidência **fraca**; usar como filtro ou ajuste de stop.
   - As janelas são 10:00, 11:00, 12:00 e 13:00, de 10 minutos cada.
   - Há evidência de "briga por PTAX" em 2010–2012 (relatório do Senado) e comentários de mercado sobre aumento de volume e volatilidade (StoneX).
5. **Sazonalidade intradiária em U de volume e volatilidade.** Evidência **moderada**, mas como ferramenta de risco, não como fonte de lucro.
   - Moreira & Lemgruber (WP 61 do BCB) e uma dissertação da FGV de 2018 sobre ações.
   - Uso: normalizar o stop pelo horário e evitar 09:00–10:00, quando o WIN opera antes da abertura das ações.
6. **ORB às 10:00 no WIN e fechamento de gap.** Evidência **fraca**, mas a estratégia combina com o perfil 1:3.
   - Não há estudo acadêmico no Brasil. O WP 644 do BCB trata do risco de gap em ações.
   - Estatísticas de praticantes (por exemplo, "~85% dos gaps do IBOV fecham no dia", da Awake Trader) não têm metodologia publicada.
7. **Regras técnicas clássicas (MM, MACD, IFR, comitês de indicadores).** Evidência **negativa**.
   - Dissertação UFMG (Campolina, 2022), WIN M5 2015–2021, otimização walk-forward e **sem custos**: não bateu o buy & hold.
   - TCC UNIPAMPA (2025), WIN M5–M30 2023–24, com stop de 400 e alvo de 800 pts: −1,08% a −1,46% líquido.
   - Baptista & Pereira (RBFin 2008), dados tick do Ibovespa futuro: ganho bruto, que os custos "reduzem".
   - Nenhuma dissertação da FGV, Insper, USP ou UFRGS com WIN/WDO intraday OOS, líquida de custos e positiva foi encontrada.
   - Dia da semana e reversão à média intraday específicos da B3: nenhuma evidência encontrada.

### C.5 Fontes do Anexo C

**Day traders no Brasil**
- Chague, De-Losso & Giovannetti (2019): https://econpapers.repec.org/paper/spawpaper/2019wpecon47.htm ; https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3423101 ; https://quantpedia.com/retail-day-trading-is-an-uphill-battle/
- Chague & Giovannetti (2025): https://portal.fgv.br/sites/default/files/uploads/eesp-pesquisa-day-trade-e-pandemia.pdf ; https://monitormercantil.com.br/brasileiros-perderam-r-99-bi-com-day-trade-durante-a-covid-19/
- Estudo CVM 2012–17 (imprensa): https://www.suno.com.br/noticias/?p=17441

**Custos, contratos e regras da B3**
- Especificações e custos: https://borainvestir.b3.com.br/tipos-de-investimentos/renda-variavel/day-trade/conheca-as-caracteristicas-dos-principais-produtos-de-day-trade/
- Tarifas Ibovespa: https://www.b3.com.br/en_us/products-and-services/fee-schedules/listed-equities-and-derivatives/equities/ibovespa-and-brazil-index-50-fees/futures-and-structured-operations/
- Tarifas dólar: https://b3.com.br/en_us/products-and-services/fee-schedules/listed-equities-and-derivatives/exchange-rates/u-s-dollar-fees/u-s-dollar-futures/
- Programa PF da B3: https://www.b3.com.br/data/files/DB/A4/00/A7/C9940A105BF9020AAC094EA8/OC%20038-2026%20PRE%20PROGRAMA%20DE%20INCENTIVO%20PF_PT.pdf
- Margem: https://okai.com.br/documento/6c18a75e-1e9a-418b-ae1a-d62f17518843
- RLP: https://www.b3.com.br/data/files/17/B4/88/14/AEA99910F5D34899AC094EA8/OC%20038-2025-VNC%20NOVAS%20REGRAS%20DE%20FUNCIONAMENTO%20DE%20OFERTA%20RLP%20NO%20MERCADO%20DE%20ACOES%20E%20PARA%20OS%20MINICONTRATOS%20FUTUROS%20WIN%20E%20WDO_PT.pdf
- MP 1.303 caducada: https://coad.com.br/home/noticias-detalhe/134038/mp-sobre-tributacao-de-investimentos-e-retirada-de-pauta-e-perde-a-validade

**Horários e vencimentos**
- Horários desde 03/11/2026: https://www.b3.com.br/data/files/BE/16/C1/59/2F881A10F75B881AAC094EA8/OC%20055-2026-VNC%20NOVOS%20HORARIOS%20DE%20NEGOCIACAO_PT.pdf
- Horários no horário de verão dos EUA: https://www.b3.com.br/data/files/E3/B2/C2/12/BC09C910F37907C9AC094EA8/OC%20005-2026%20PRE%20NOVOS%20HORARIOS%20DE%20NEGOCIACAO_PT.pdf
- Vencimentos: https://www.b3.com.br/en_us/products-and-services/trading/equities/mini-ibovespa-futures.htm ; https://b3.com.br/en_us/products-and-services/trading/exchange-rates/mini-u-s-dollar-futures.htm ; https://clientes.b3.com.br/en/w/alteracao-da-data-de-vencimento-das-opcoes-e-futuros-de-ibovespa

**Efeitos intraday e câmbio**
- Anúncios macro: https://econpapers.repec.org/RePEc:sbe:breart:v:36:y:2016:i:2:a:46421
- Ventura & Garcia: https://ideas.repec.org/a/fgv/epgrbe/v66y2012i1a1907.html
- Rossi et al. (BID): https://publications.iadb.org/publications/english/document/Brazilian-Exchange-Rate-Forecasting-in-High-Frequency.pdf
- Momentum intradiário: https://www3.nd.edu/~zda/intramom.pdf ; https://c.mql5.com/forextsd/forum/173/intraday_momentum_-_the_first_half-hour_return_predicts_the_last_half-hour_return.pdf
- PTAX: https://legis.senado.leg.br/sdleg-getter/documento/download/bd073eca-5326-42a7-81d0-7b54c70154a3
- Sazonalidade intradiária: https://ideas.repec.org/p/bcb/wpaper/61.html ; https://repositorio.fgv.br/items/260f7c4e-dec9-4bd1-903f-4aafe4a0e242
- Gaps: https://www.bcb.gov.br/content/publicacoes/WorkingPaperSeries/WP644.pdf

**Regras técnicas no mercado brasileiro**
- Baptista & Pereira: https://econpapers.repec.org/RePEc:brf:journl:v:6:y:2008:i:2:p:205-234
- UFMG: https://repositorio.ufmg.br/bitstreams/59bdf474-78a6-4e7b-a080-2b1d0608e47b/download
- UNIPAMPA: https://repositorio.unipampa.edu.br/bitstreams/82706f83-804f-40c4-8d01-0d8bb372d1fa/download

---

<a id="anexo-d"></a>
## Anexo D — Experimentos locais

**Dados:** 6 ativos Dukascopy (BRENT, EURUSD, GBPUSD, NAS100, US30, XAUUSD), M1 bid, mar a out/2026.
**Motor:** `FiboOTEStrategy` com as correções F-01 a F-11, rolagem e expiração.
**Spreads:** seção `contracts` de `config/default.yaml`.

**Como reproduzir:**

```bash
uv run python scripts/research/exp_custo_timeframe_fibo.py
```

### D.1 Custo real × custo zero, por timeframe (pivot_k = 3)

| tf | modelo | custo | trades | R | R/trade | acerto% |
|---|---|---|---|---|---|---|
| 5min | trailing | real | 2154 | −483,1 | −0,224 | 29,1 |
| 5min | trailing | zero | 2327 | 56,3 | 0,024 | 33,8 |
| 5min | estrutural | real | 2273 | −270,7 | −0,119 | 58,7 |
| 5min | estrutural | zero | 2287 | −39,2 | −0,017 | 63,6 |
| 5min | alvo3R_estr | real | 1867 | −127,1 | −0,068 | 23,1 |
| 5min | alvo3R_estr | zero | 1872 | 23,8 | 0,013 | 25,2 |
| 15min | trailing | real | 855 | −210,6 | −0,246 | 29,1 |
| 15min | trailing | zero | 913 | −48,1 | −0,053 | 33,0 |
| 15min | estrutural | real | 892 | −64,1 | −0,072 | 58,4 |
| 15min | estrutural | zero | 894 | −0,2 | −0,000 | 61,9 |
| 15min | alvo3R_estr | real | 741 | −34,7 | −0,047 | 24,2 |
| 15min | alvo3R_estr | zero | 739 | 11,9 | 0,016 | 25,7 |
| 60min | trailing | real | 288 | −39,9 | −0,138 | 29,9 |
| 60min | trailing | zero | 297 | 28,4 | 0,096 | 34,0 |
| 60min | estrutural | real | 290 | −24,2 | −0,084 | 57,2 |
| 60min | estrutural | zero | 291 | −12,2 | −0,042 | 60,1 |
| 60min | alvo3R_estr | real | 251 | −42,2 | −0,168 | 21,1 |
| 60min | alvo3R_estr | zero | 251 | −26,0 | −0,103 | 22,7 |

Modelos:
- `trailing`: entrada 70,5%, stop 79%, saída pela EMA8.
- `estrutural`: entrada 70,5%, stop 100%, saída pela EMA8.
- `alvo3R_estr`: entrada 70,5%, stop 100%, alvo fixo de 3R, sem trailing.

### D.2 R total por ativo em M5 (custo real × zero)

| modelo | ativo | custo real | custo zero |
|---|---|---|---|
| estrutural | BRENT | −42,2 | 19,0 |
| estrutural | EURUSD | −32,7 | 7,2 |
| estrutural | GBPUSD | −36,7 | 4,9 |
| estrutural | NAS100 | −82,2 | −64,1 |
| estrutural | US30 | −44,7 | −2,2 |
| estrutural | XAUUSD | −32,2 | −4,0 |
| trailing | BRENT | −99,2 | 79,1 |
| trailing | EURUSD | −60,2 | −12,2 |
| trailing | GBPUSD | −51,9 | −0,8 |
| trailing | NAS100 | −133,5 | −39,2 |
| trailing | US30 | −77,0 | 13,7 |
| trailing | XAUUSD | −61,2 | 15,8 |

### D.3 Leitura

- **Com alvo fixo de 3R e sem custo, o acerto ficou em 22,7% a 25,7%.** Num passeio aleatório ele é 25%. A entrada não se distingue do acaso.
- **Sem custo, o R por trade fica entre −0,10 e +0,10** em todos os timeframes, dentro do ruído esperado para 250 a 2.300 trades (erro-padrão de ~0,03R a ~0,08R).
- **O custo tira de 0,08R a 0,25R por trade.** Subir o timeframe não reduziu esse dano de forma consistente.
- **Ativos positivos sem custo (BRENT, XAUUSD) não são sinal confiável.** Com 6 ativos × 2 modelos, é esperado que alguns pareçam positivos por acaso.
- **Limitação:** 8 meses de dados. A conclusão "sem vantagem demonstrada" é segura; a conclusão "nunca terá vantagem" não é. O próximo passo é o histórico de 5 anos (PQ-2).

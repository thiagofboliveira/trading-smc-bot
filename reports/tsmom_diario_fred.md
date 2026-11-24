# TSMOM diário diversificado: estudo com dados do FRED

**Fonte:** backtest. **Dados:** FRED, fechamento diário, 1990-01-02 a 2026-11-20. **Custos:** bps do nocional por ajuste (abaixo); execução no fechamento do pregão seguinte à decisão. **Resultado preliminar, não validado para conta real.**

Ativos e custo por ajuste (bps): NAS100 2.0, BRENT 5.0, EURUSD 1.5, GBPUSD 1.5, USDJPY 1.5, AUDUSD 1.5, USDCAD 1.5, USDCHF 1.5, USDMXN 5.0, USDBRL 5.0

## 1. Variante principal (lookback 252, fixada antes do teste)

- Amostra completa: +7.3% a.a.; vol 17.4%; Sharpe 0.49; t 2.97; MaxDD -43.0%; 36.3 anos
- Dentro da amostra (até 2012-12-31): +9.5% a.a.; vol 18.1%; Sharpe 0.59; t 2.81; MaxDD -43.0%; 22.6 anos
- **Fora da amostra (2013 em diante): +3.8% a.a.; vol 16.2%; Sharpe 0.31; t 1.16; MaxDD -34.4%; 13.7 anos**
- Sem custo, amostra completa: +7.6% a.a.; vol 17.4%; Sharpe 0.51; t 3.07; MaxDD -42.8%; 36.3 anos
- Sem custo, fora da amostra: +4.2% a.a.; vol 16.2%; Sharpe 0.33; t 1.24; MaxDD -33.6%; 13.7 anos
- Custo médio: 0.30% a.a.; giro médio 12.4x/ano
- Custo em dobro, amostra completa: +7.0% a.a.; vol 17.4%; Sharpe 0.47; t 2.86; MaxDD -43.1%; 36.3 anos

## 2. Controles (mesmo tamanho, frequência e custo)

- Comprado sempre: +8.2% a.a.; vol 11.0%; Sharpe 0.77; t 4.67; MaxDD -24.4%; 36.3 anos
- Comprado sempre, fora da amostra: +8.6% a.a.; vol 10.2%; Sharpe 0.86; t 3.18; MaxDD -16.1%; 13.7 anos
- Sinal aleatório (500 sorteios), Sharpe: média -0.06, desvio 0.18, p95 0.25, máx 0.54
- TSMOM (Sharpe 0.49) supera 99.8% dos sorteios na amostra completa
- Fora da amostra: aleatório média -0.08 (p95 0.39); TSMOM 0.31 supera 91.0%

## 3. Todas as variantes testadas (N = 3; nenhuma foi escolhida pelo resultado)

| Lookback | Amostra completa | Fora da amostra |
|---|---|---|
| 252 | +7.3% a.a.; vol 17.4%; Sharpe 0.49; t 2.97; MaxDD -43.0%; 36.3 anos | +3.8% a.a.; vol 16.2%; Sharpe 0.31; t 1.16; MaxDD -34.4%; 13.7 anos |
| 126 | +3.1% a.a.; vol 17.3%; Sharpe 0.26; t 1.57; MaxDD -50.6%; 36.3 anos | +2.7% a.a.; vol 16.1%; Sharpe 0.25; t 0.92; MaxDD -41.7%; 13.7 anos |
| 63 | +3.2% a.a.; vol 17.7%; Sharpe 0.27; t 1.62; MaxDD -63.3%; 36.3 anos | -2.3% a.a.; vol 16.7%; Sharpe -0.05; t -0.20; MaxDD -63.3%; 13.7 anos |

## 4. Por ano (variante principal, líquido)

| Ano | Retorno |
|---|---|
| 1990 | +0.0% |
| 1991 | -22.7% |
| 1992 | +9.9% |
| 1993 | +25.2% |
| 1994 | +33.0% |
| 1995 | +19.5% |
| 1996 | +9.1% |
| 1997 | +17.4% |
| 1998 | +33.8% |
| 1999 | +34.4% |
| 2000 | +3.3% |
| 2001 | +15.7% |
| 2002 | +35.1% |
| 2003 | +51.6% |
| 2004 | +3.5% |
| 2005 | -15.3% |
| 2006 | -13.8% |
| 2007 | +24.8% |
| 2008 | +16.0% |
| 2009 | -23.2% |
| 2010 | -1.2% |
| 2011 | -8.7% |
| 2012 | +6.8% |
| 2013 | +9.4% |
| 2014 | +16.3% |
| 2015 | +41.4% |
| 2016 | -7.3% |
| 2017 | +3.5% |
| 2018 | +0.1% |
| 2019 | -3.0% |
| 2020 | +28.3% |
| 2021 | -6.5% |
| 2022 | +4.6% |
| 2023 | -1.0% |
| 2024 | -2.2% |
| 2025 | -5.6% |
| 2026 | -12.8% |

Anos negativos: 13 de 37.

## 5. Por ativo (contribuição líquida, soma simples)

| Ativo | Total | Fora da amostra |
|---|---|---|
| NAS100 | +102.3% | +33.6% |
| BRENT | +22.3% | +22.1% |
| EURUSD | +4.6% | -0.7% |
| GBPUSD | -25.5% | -7.0% |
| USDJPY | +66.1% | +22.9% |
| AUDUSD | +29.2% | +3.2% |
| USDCAD | +18.5% | -3.8% |
| USDCHF | -12.8% | -20.5% |
| USDMXN | +35.4% | +0.7% |
| USDBRL | +70.4% | +18.8% |

## 6. Trades e conferência dos números (item 7)

- Trades (trechos de posição): 561; duração mediana 66 pregões
- Acerto 39.8%; ganho médio +3.277%; perda média -1.242% da conta
- Acerto × ganho − erro × perda = +0.5548%; média real +0.5548%
- Erro-padrão do resultado por trade: 0.1785% (t ≈ 3.11)
- Payoff (ganho médio / perda média): 2.64

## 7. Causalidade e limitações

- Sinal: retorno de `close[d - 252]` a `close[d]`; vol: EWMA de retornos até `d`. Decisão no fechamento do último pregão do mês, execução no fechamento do pregão seguinte, retorno a partir do outro. Teste: `tests/test_tsmom.py` (invariância de prefixo e atraso de execução).
- Câmbio spot sem diferencial de juros: um CFD real cobra/paga swap, que pode somar ou subtrair alguns % a.a. em USDMXN, USDBRL, USDJPY e AUDUSD.
- Brent spot (FRED) não é o futuro/CFD: falta o custo de rolagem.
- Ouro e DAX não estão no FRED; gás natural spot foi excluído (picos não negociáveis).
- Universo pesado em câmbio (8 de 10 ativos): o resultado depende disso.
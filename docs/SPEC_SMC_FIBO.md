# Especificação Canônica Oficial — SMC Fibonacci OTE

**Versão:** 3.0 · **Data:** 2026-11-07  
**Sistemas alvo:** Python (`src/smc_trader`), MetaTrader 5 (`mql5/SMC_Bridge_EA.mq5`), Nelogica Profit / Rico Trader (`nelogica/SMC_FIBO_CANONICO.ntsl`).

---

## 1. Princípios Fundamentais e Regras Anti-Viés

Esta especificação define matematicamente a estratégia institucional **SMC Fibonacci OTE (Optimal Trade Entry)**, garantindo equivalência exata entre backtest, paper trading e execução real em bolsa.

1. **Causalidade Estrita:** Nenhuma decisão é tomada sobre uma barra ainda em formação (`open_time` até `close_time`). O resample de M1 para M5 descarta caudas incompletas (`drop_incomplete_tail=True`).
2. **F-01 (Sem lookahead de BOS):** A quebra de estrutura (BOS) só existe no fechamento da barra `i`. A perna de retração só pode gerar ordens ou entradas a partir da barra `i+1`.
3. **F-02 / Custos Reais nos Dois Lados:** Compras entram no Ask e saem no Bid. Vendas entram no Bid e saem no Ask (`bid + spread`). Slippage e taxas de corretagem/emolumentos são debitados em ambas as pontas.
4. **F-03 (Trava de Lucro Causal):** O stop loss vigente no início da barra decide se a barra foi estopada. Uma trava 2:1 (ou breakeven) atingida na barra `j` só protege a posição a partir da barra `j+1`.
5. **F-04 (Expansão e Toque):** O toque no nível de retração é avaliado contra os níveis calculados até a barra `j-1`. Se não houver toque, a máxima/mínima de `j` pode expandir a perna para a barra `j+1`.
6. **F-11 (Desempate de Swings Fractais):** O topo fractal com janela `2k+1` desempata para a primeira ocorrência:
   $$\text{Topo}(chk) \iff \text{High}[chk] > \max(\text{High}[chk-k : chk]) \quad \land \quad \text{High}[chk] \ge \max(\text{High}[chk+1 : chk+k+1])$$
   Elimina topos duplicados consecutivos no mesmo preço mantendo estrita causalidade.
7. **N-01 (Ordens de Proteção Reais na Bolsa):** Posições abertas enviam imediatamente ordens de proteção OCO (`SellToCoverStop` / `BuyToCoverStop` e `SellToCoverLimit` / `BuyToCoverLimit`) ao servidor da bolsa, impedindo posições desprotegidas por desconexão.
8. **N-02 (Preço de Entrada Real):** O preço de entrada registrado no estado e usado no trailing é o preço médio preenchido na execução (`BuyPrice` / `SellPrice`), e não o nível teórico idealizado.
9. **N-04 (Day Trade B3):** Encerramento forçado às 17:45 BRT e bloqueio de novas entradas após as 17:00 BRT em contratos WIN e WDO.
10. **N-05 (Expiração de Perna):** Pernas não mitigadas expiram após 60 barras M5 ou na virada do pregão.

---

## 2. Parâmetros Canônicos

| Parâmetro | Descrição | Padrão Estrutural | Padrão Trailing | Padrão Blindado |
|---|---|---|---|---|
| `Timeframe` | Tempo gráfico operacional | M5 | M5 | M5 |
| `fibo_entry` | Nível de retração para entrada | 0.705 (70.5%) | 0.705 (70.5%) | 0.705 (70.5%) |
| `fibo_stop` | Nível de invalidação / Stop Loss | 1.000 (100.0%) | 0.790 (79.0%) | 0.790 (79.0%) |
| `target_mode` | Modo de Take Profit | `0_percent` (topo) | `0_percent` | `0_percent` |
| `pivot_k` | Raio do fractal de confirmação | 2 (ou 3 no macro) | 2 | 2 |
| `max_leg_candles`| Máximo de barras M5 de vida da perna | 60 | 60 | 60 |
| `trailing_exit_ma`| MME de condução de saída no lucro | `ema8` | `ema8` | `ema8` |
| `profit_lock` | Trava de proteção de capital | Desativada | Desativada | Disparo +2R, Trava +1R |
| `horario_limite` | Horário máximo para novas entradas | 17:00 BRT | 17:00 BRT | 17:00 BRT |
| `horario_zeragem`| Horário de liquidação forçada day trade | 17:45 BRT | 17:45 BRT | 17:45 BRT |

---

## 3. Pseudocódigo Universal

```pascal
// Executado a cada fechamento de barra M5 fechada (barra i)

// 1. Atualização dos Swings com Atraso k
chk := i - k;
Se chk >= k Entao
Inicio
  Se (High[chk] > Max(High[chk-k .. chk-1])) e (High[chk] >= Max(High[chk+1 .. chk+k])) Entao
  Inicio
    last_sh_price := High[chk];
    last_sh_idx := chk;
  Fim;
  
  Se (Low[chk] < Min(Low[chk-k .. chk-1])) e (Low[chk] <= Min(Low[chk+1 .. chk+k])) Entao
  Inicio
    last_sl_price := Low[chk];
    last_sl_idx := chk;
  Fim;
Fim;

// 2. Gerenciamento de Posição Aberta
Se Posicionado Entao
Inicio
  // A. Fechamento de sessão / Horário limite
  Se Time >= 17:45 Entao
  Inicio
    ClosePosition;
    Retorne;
  Fim;

  // B. Trava de Lucro 2:1 -> Stop em +1R (Blindado)
  Se (TemTrava2para1) e (Nao TravaAtivada) Entao
  Inicio
    favorable := (Long ? High[i] - EntryPrice : EntryPrice - Low[i]);
    Se favorable >= 2.0 * RiscoInicial Entao
    Inicio
      TravaAtivada := Verdadeiro;
      NovoStop := (Long ? EntryPrice + 1.0 * RiscoInicial : EntryPrice - 1.0 * RiscoInicial);
      ModificarStopLoss(NovoStop);
    Fim;
  Fim;

  // C. Saída por MME 8 no Lucro (Trailing)
  Se (UsaTrailingMME8) Entao
  Inicio
    mme8 := CalcularEMA(8, Close);
    Se Long e (Close[i] < mme8) e (Close[i] > EntryPrice) Entao
      ClosePosition;
    Se Short e ((Close[i] + Spread) > mme8) e ((Close[i] + Spread) < EntryPrice) Entao
      ClosePosition;
  Fim;

  Retorne;
Fim;

// 3. Detecção de Nova Perna por BOS (Só se não houver perna ativa)
Se (PernaAtiva = Nula) e (last_sh_price > 0) e (last_sl_price > 0) Entao
Inicio
  // BOS de Alta: Fechamento acima do topo prévio confirmado
  Se (last_sh_idx > last_sl_idx) e (Close[i] > last_sh_price) Entao
  Inicio
    span := High[i] - last_sl_price;
    Se span >= MinAmplitudePerna Entao
      PernaAtiva := CriarPerna(Direcao=+1, Origem=last_sl_price, Extremo=High[i], BosIdx=i);
  Fim
  // BOS de Baixa: Fechamento abaixo do fundo prévio confirmado
  Senao Se (last_sl_idx > last_sh_idx) e (Close[i] < last_sl_price) Entao
  Inicio
    span := last_sh_price - Low[i];
    Se span >= MinAmplitudePerna Entao
      PernaAtiva := CriarPerna(Direcao=-1, Origem=last_sh_price, Extremo=Low[i], BosIdx=i);
  Fim;
Fim

// 4. Avaliação de Perna Ativa (F-01: Exige i > BosIdx)
Senao Se (PernaAtiva <> Nula) e (i > PernaAtiva.BosIdx) Entao
Inicio
  PernaAtiva.Candles := PernaAtiva.Candles + 1;
  Se (PernaAtiva.Candles > 60) ou (Time >= 17:00) Entao
  Inicio
    CancelarOrdemLimiteSeExistir;
    PernaAtiva := Nula;
    Retorne;
  Fim;

  entry_level := PernaAtiva.Extremo - PernaAtiva.Direcao * FiboEntrada * PernaAtiva.Span;
  stop_level  := PernaAtiva.Extremo - PernaAtiva.Direcao * FiboStop * PernaAtiva.Span;
  target_level:= PernaAtiva.Extremo;

  // F-04: Teste de Toque antes de expandir
  touched := (PernaAtiva.Direcao = +1 ? Low[i] <= entry_level : High[i] >= entry_level);
  Se touched Entao
  Inicio
    EnviarOrdemEntrada(entry_level, stop_level, target_level);
    PernaAtiva := Nula;
  Fim
  Senao
  Inicio
    // Expande o extremo da perna se houver nova máxima/mínima sem tocar entrada
    Se (PernaAtiva.Direcao = +1) e (High[i] > PernaAtiva.Extremo) Entao
      PernaAtiva.Extremo := High[i];
    Se (PernaAtiva.Direcao = -1) e (Low[i] < PernaAtiva.Extremo) Entao
      PernaAtiva.Extremo := Low[i];
  Fim;
Fim;
```

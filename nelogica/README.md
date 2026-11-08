# Módulos NTSL (Nelogica / ProfitChart / Rico Trader / B3)

Esta pasta contém as estratégias desenvolvidas e validadas quantitativamente no projeto, traduzidas fielmente para a linguagem **NTSL** (Nelogica Trading System Language) para execução e acompanhamento visual no **ProfitChart**, **Rico Trader**, **Clear Trader** ou qualquer plataforma da Nelogica.

---

## 1. Estratégias Disponíveis

### A. `SMC_FIBO_REJEICAO_EMA80_PAVIO` (M5) — [Recomendada]
* **Arquivos:** [`SMC_FIBO_REJEICAO_EMA80_PAVIO.ntsl`](nelogica/SMC_FIBO_REJEICAO_EMA80_PAVIO.ntsl) e [`SMC_FIBO_REJEICAO_EMA80_PAVIO.txt`](nelogica/SMC_FIBO_REJEICAO_EMA80_PAVIO.txt)
* **Timeframe nativo:** 5 minutos (M5).
* **Conceito:**
  1. Identifica quebra estrutural (BOS) com fractal estrito ($k=2$).
  2. Aguarda retração na zona de desconto [50.0% a 79.0%] com toque simultâneo na **MME 80**.
  3. Exige candle de rejeição com pavio $\ge 50\%$ do range e fechamento a favor da média.
  4. Executa compra/venda a mercado na abertura da barra seguinte (`BuyAtMarket`/`SellShortAtMarket`).
  5. Stop loss técnico em **88,6%** da perna.
  6. Trava de proteção: ao atingir **`+1.618R`**, sobe o stop para **`+1.0R` garantido**.
  7. Alvo teto em **`4.0R`**.
  8. Travas diárias nativas: 1 gain bate meta e para; 2 stops seguidos encerra o dia; máx 3 trades/dia.

### B. `STORMER_TRAP_MME80_MME8` (M10 / M5 / M15)
* **Arquivos:** [`STORMER_TRAP_MME80_MME8.ntsl`](nelogica/STORMER_TRAP_MME80_MME8.ntsl) e [`STORMER_TRAP_MME80_MME8.txt`](nelogica/STORMER_TRAP_MME80_MME8.txt)
* **Timeframe recomendado:** 10 minutos (M10) ou 5 minutos (M5).
* **Conceito:**
  1. Tendência alinhada a favor da MME 80 e MME 8.
  2. Identifica pivô corretivo prévio que tem sua mínima/máxima violada pelo candle de Trap (captura de liquidez de stops).
  3. Arma ordem stop na superação da máxima do candle de Trap para compra (ou perda da mínima para venda).
  4. Stop loss no extremo oposto do candle de Trap e alvo em **`1.618R`**.
  5. Travas diárias nativas de risco.

---

## 2. Como Importar e Usar no ProfitChart

### Passo 1: Abrir o Editor de Estratégias
1. No Profit, clique no menu superior **Estratégias** $\to$ **Editor de Estratégias**.
2. Clique no ícone de **Novo** (folha em branco).
3. Abra o arquivo `.txt` da estratégia desejada no Bloco de Notas, copie todo o código e cole no editor do Profit.
4. Clique no ícone de **Salvar** (disquete) e salve com o nome da estratégia (ex.: `SMC_FIBO_PAVIO` ou `STORMER_TRAP`).
5. Clique no ícone de **Compilar** (engrenagem ou play verde). A mensagem na barra inferior deve indicar `Compilação concluída com sucesso`.

### Passo 2: Inserir como Regra de Coloração no Gráfico
1. No gráfico do ativo (ex.: `WIN$`, `WDO$`, `PETR4` em M5 ou M10), clique com o botão direito sobre os candles.
2. Selecione **Inserir Regra de Coloração...**
3. Procure pelo nome salvo (ex.: `SMC_FIBO_PAVIO`) e clique em **Inserir**.
4. **Cores sinalizadas:**
   * **Amarelo:** Barra que confirmou quebra de estrutura (BOS).
   * **Verde:** Candle de gatilho de compra confirmado (pavio $\ge 50\%$ + MME 80).
   * **Magenta / Fuchsia:** Candle de gatilho de venda confirmado.

### Passo 3: Execução / Módulo de Automação
1. Para rodar em simulação ou conta real via automação do Profit:
   * Menu **Estratégias** $\to$ **Automação de Estratégias**.
   * Clique em **Nova Automação**.
   * Selecione a estratégia salva, o ativo e o tempo gráfico (M5).
   * Defina a quantidade de contratos/lotes e marque para rodar em modo Simulação (Replay ou Paper) para validação.

# 📘 Playbook Operacional — Modelos Fechados (Institutional Trading Systems)

Este documento define os **dois modelos operacionais fechados** validados empiricamente pelo estudo quantitativo multi-ativo e multi-timeframe do ecossistema **SMC Trader**.

---

## 📊 Matriz Comparativa dos Modelos

| Característica | 🏛️ Modelo 1: `SMC-DayFlow` | 🎯 Modelo 2: `Wyckoff-Sniper` |
| :--- | :--- | :--- |
| **Timeframe Macro (HTF)** | **M15** (Estrutura e Zonas) | **H1** (Estrutura Macro e Extremos) |
| **Timeframe Micro (LTF)** | **M1** (CHoCH de Gatilho) | **M1** (CHoCH de Rejeição Imediata) |
| **Tipo de Operação** | Intraday / Continuação e Reação ao Fluxo | Reversão Institucional em Extremos de Liquidez |
| **Filtro de Blocos** | Order Blocks (OB) + Breaker Blocks (BB) | Order Blocks (OB) + Breaker Blocks (BB) |
| **Regra de Liquidez** | Inducement interno e desconto de zona | **Sweep Obrigatório** (Spring / UTAD Wyckoff) |
| **Risco : Retorno (R:R)**| **1 : 3.0 fixo** | **1 : 3.0 fixo** |
| **Taxa de Acerto Média** | **37.4% a 50.0%** | **60.0% a 75.0%** |
| **Frequência de Trades** | Alta (~2 a 4 trades por semana por ativo) | Baixa / Seletiva (~1 a 2 trades por semana) |
| **Expectativa Líquida (E)**| **+0.16R a +0.35R por trade** | **+0.60R a +1.68R por trade** |
| **Tag MetaTrader 5** | `[SMC-DayFlow]` | `[Wyckoff-Sniper]` |

---

## 🏛️ Modelo 1: `SMC-DayFlow` (M15 / M1)

### 1. Filosofia Operacional
Captura reações institucionais em níveis de Oferta e Demanda identificados no gráfico de **M15**, buscando surfar a expansão do ciclo intradiário nas sessões de Londres e Nova York.

### 2. Regras Mecânicas de Validação (HTF - M15)
1. **Identificação de Zonas:**
   - Detectar Order Blocks válidos com deslocamento.
   - Detectar Breaker Blocks (antigas zonas rompidas que se tornam suporte/resistência institucional).
   - **Exceção Brent:** No modelo `SMC-DayFlow-Brent`, utiliza exclusivamente **Order Blocks virgens (OB)**, desativando Breakers para evitar falsos retestes em momentos de forte tendência direcional.
2. **Equilíbrio de Preço (Premium / Discount):**
   - Compras autorizadas apenas abaixo de 50% do range (Discount).
   - Vendas autorizadas apenas acima de 50% do range (Premium).
3. **Inducement (Indução):**
   - O preço deve deixar uma indução interna de liquidez no M15 antes de atingir o bloco.

### 3. Regras Mecânicas de Gatilho (LTF - M1)
1. **Toque na Zona:** O preço toca a fronteira da zona M15. O estado da zona muda para `ARMED`.
2. **Mudança de Caráter (CHoCH):** Aguarda o candle de M1 romper a estrutura recente na direção oposta ao movimento de chegada.
3. **Entrada:** Disparo a mercado no fechamento do candle M1 que confirmou o CHoCH.
4. **Stop Loss:** Posicionado no swing estrutural recente (`stop_mode: swing`).
5. **Take Profit:** Posicionado a exatamente **$3.0 \times \text{Risco}$** (`target_r: 3.0`).

---

## 🛢️ Regra Fechada Especializada: `SMC-DayFlow-Brent`

* **Arquivo de Configuração:** `config/models/smc_dayflow_brent.yaml`
* **Particularidade:** Exclui estritamente os Breaker Blocks (`blocks_filter: ["OB"]`).
* **Justificativa Quantitativa:** No Petróleo Brent, o Breaker Block teve taxa de acerto de apenas 10% (-7.03R de perda), enquanto o **Order Block puro obteve 33.3% de acerto com +0.33R de expectativa e +5.00R de retorno positivo**.

---

## 🧪 Estudo Científico Global: [OB + BB] vs [Apenas OB]

Comparamos o impacto de remover o Breaker Block de **todos os 7 ativos simultaneamente** no mesmo período de mercado:

| Ativo | Com BB `[OB + BB]` (R Total) | Sem BB `[Apenas OB]` (R Total) | Impacto no Resultado | Diagnóstico |
| :--- | :---: | :---: | :---: | :--- |
| **XAUUSD** | +11.10R (Exp: +0.55R) | **+16.82R (Exp: +1.40R)** | <span style="color:#10b981; font-weight:bold;">+5.72R 🟢</span> | **Melhorou fortemente** (cortou ruído de falsos breakers) |
| **BRENT** | +2.20R (Exp: +0.09R) | **+5.00R (Exp: +0.33R)** | <span style="color:#10b981; font-weight:bold;">+2.80R 🟢</span> | **Melhorou fortemente** (evitou 9 stops no Brent) |
| **NAS100** | -1.62R (Exp: -0.04R) | **+2.55R (Exp: +0.11R)** | <span style="color:#10b981; font-weight:bold;">+4.17R 🟢</span> | **Virou de negativo para LUCRATIVO!** |
| **EURUSD** | -7.83R (Exp: -0.18R) | **-5.04R (Exp: -0.20R)** | <span style="color:#10b981; font-weight:bold;">+2.79R 🟢</span> | Reduziu o drawdown operacional |
| **DAX40** | **+13.40R** (Exp: +0.33R) | +7.55R (Exp: +0.38R) | -5.85R 🔴 | No DAX o Breaker é altamente respeitado |
| **GBPUSD** | -1.18R (Exp: -0.03R) | -2.90R (Exp: -0.12R) | -1.72R 🔴 | Leve recuo |
| **USDJPY** | +8.90R (Exp: +0.25R) | +7.66R (Exp: +0.32R) | -1.24R 🔴 | Praticamente equivalente (+0.32R/trade) |
| **CONSOLIDADO**| **+24.97R (239 trades)** | **+31.64R (144 trades)**| <span style="color:#10b981; font-weight:bold;">+6.67R 🟢</span> | **Aumento de +26.7% no lucro com 40% menos trades!** |

---

## 🎯 Modelo 2: `Wyckoff-Sniper` (H1 / M1)

### 1. Filosofia Operacional
Baseado nos princípios clássicos de Richard Wyckoff (Acumulação e Distribuição). O modelo busca identificar **Springs (Fase C)** e **Upthrusts After Distribution (UTAD)**, onde os grandes operadores institucionais realizam a captura maciça de liquidez dos participantes do varejo antes de disparar uma reversão direcional violenta.

### 2. Regras Mecânicas de Validação (HTF - H1)
1. **Estrutura Macro:** Mapeamento de Pivots e Swing Highs / Lows no gráfico de **H1**.
2. **Sweep Obrigatório (`require_sweep: true`):**
   - Para COMPRA (Spring): O preço DEVE romper a mínima de um swing anterior de H1 (varrendo ordens de stop) e retornar acima do nível.
   - Para VENDA (UTAD): O preço DEVE romper a máxima de um swing anterior de H1 (varrendo ordens de stop) e retornar abaixo do nível.
3. **Zonas de Reação:** O sweep deve ocorrer coincidindo com um Order Block ou Breaker Block institucional de H1.

### 3. Regras Mecânicas de Gatilho (LTF - M1)
1. **Confirmação Imediata:** Imediatamente após a varredura macro no H1, o gráfico de M1 deve apresentar rejeição com alto volume e reversão de caráter estrutural (Micro-CHoCH).
2. **Entrada:** A mercado na confirmação do CHoCH M1.
3. **Stop Loss:** Posicionado milimetricamente além do ponto extremo da manipulação (a ponta do pavio do Sweep).
4. **Take Profit:** Cravado em **1:3.0 fixo**.

---

## 🛡️ Gestão de Risco e Parâmetros Institucionais

| Parâmetro | Regra `SMC-DayFlow` | Regra `Wyckoff-Sniper` |
| :--- | :--- | :--- |
| **Risco por Operação** | 1.0% do Equity | 1.0% do Equity |
| **Limite de Perdas / Dia** | Pausa após 2 stops consecutivos (-2.0R) | Pausa após 1 stop no extremo (-1.0R) |
| **Meta de Ganho / Dia** | Pausa após 1 gain batido (+3.0R) | Pausa após 1 gain batido (+3.0R) |
| **Horários Permitidos** | Londres (07:00-15:30) / NY (13:00-20:00) | Londres (07:00-15:30) / NY (13:00-20:00) |
| **Encerramento Forçado**| 21:00 UTC (nenhuma posição aberta para swap)| 21:00 UTC |

---

## 💻 Mapeamento no MetaTrader 5

Quando o robô estiver conectado à ponte MT5:
* Ordens disparadas pelo modelo 1 recebem o comentário: `[SMC-DayFlow]`
* Ordens disparadas pelo modelo 2 recebem o comentário: `[Wyckoff-Sniper]`
* O número mágico (`magic_base: 888100`) permite controle independente de cada ativo e modelo pelo Expert Advisor.

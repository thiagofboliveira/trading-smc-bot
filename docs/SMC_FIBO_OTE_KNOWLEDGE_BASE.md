# 📚 BASE DE CONHECIMENTO OFICIAL: ESTRATÉGIA QUANTITATIVA SMC-FIBO-OTE

> [!WARNING]
> **AVISO CRÍTICO PÓS-AUDITORIA DE REALISMO (Novembro de 2026):**  
> Os retornos históricos citados originalmente nas seções preliminares deste documento (+809R a +2.101R no ano) foram decorrentes de vieses de antecipação intrabar no simulador legado (F-01: entrada na mesma barra do BOS; F-02: omissão de spread na saída de shorts).  
> Com o motor unificado e auditado (`FiboOTEStrategy`), a expectativa real na configuração padrão M5 mostrou-se negativa nos ativos testados. Consulte [`docs/BACKLOG_CORRECOES.md`](BACKLOG_CORRECOES.md) para o status completo das correções e novos direcionamentos quantitativos.

---

## 1. Contexto Histórico e Evolução do Projeto

O objetivo deste projeto é construir um sistema algorítmico automatizado e lucrativo para operar no MetaTrader 5 em ativos globais (Índices, Metais, Energia e Forex).

### Linha do Tempo das Descobertas:
1. **SMC Tradicional no M1 (SMC-DayFlow & Wyckoff-Sniper):**
   - *Resultado:* **-214,81 R** no ano (6 de 7 ativos negativos).
   - *Causa-Raiz (Autópsia de 105 stops):* No tempo gráfico M1, o ruído intradiário é violento e o custo de transação (spread de 1 a 2 pips) consumia mais de **0,208 R por operação** (mais de 250R de perda foram puras taxas da corretora).
2. **Opening Range Breakout (ORB) + VWAP + EMA20:**
   - *Resultado:* Excelente em Commodities (**+65.5 R** em Petróleo e Ouro no teste cego), porém negativo em Forex e Índices devido a *falsos rompimentos* (sweeps de liquidez).
3. **Pivô na Média M2 (1:1 com EMA20 + SMA200):**
   - *Resultado:* Excelente no DAX40 (+327 R), mas desastroso em Forex (-1.025 R) devido à armadilha matemática do alvo 1:1 com spread curto.
4. **SMC-Fibo-OTE (M5 / M15):**
   - *Resultado:* **A campeã absoluta e incontestável do projeto**. Fechou positiva em **100% dos ativos testados** e gerou entre **+1.232 R e +2.101 R** líquidos no ano, com teste cego Out-of-Sample superando o In-Sample.

---

## 2. Fundamento Teórico da Estratégia SMC-Fibo-OTE

A estratégia fundamenta-se no conceito institucional de **Optimal Trade Entry (OTE)** do Smart Money Concepts:

```
Topo Impulsivo (0.0% de Fibo) ─────────────────────── [Alvo Estrutural de TP]
                               ▲
                               │
61.8% Fibo              ───────┼────────────── [Zona de Desconto / OTE Inicial]
65.0% Fibo              ───────┼────────────── [Equilíbrio da Golden Zone]
70.5% Fibo (Sweet Spot) ───────┼────────────── [Entrada Institucional Profunda]
                               │  Risco Mínimo (apenas 8.5% da pernada!)
79.0% Fibo              ───────┴────────────── [Nível de Invalidação / Stop Loss]
                               │
100.0% Fibo (Fundo do BOS)───────────────────── [Origem da Estrutura]
```

### Por que a geometria da estratégia gera tanta assimetria?
1. **Quebra Estrutural (BOS):** O algoritmo só busca operações quando há uma perna impulsiva confirmada por quebra de topo (para alta) ou quebra de fundo (para baixa), validada por fractais.
2. **Retração em Desconto Profundo:** Em vez de comprar o rompimento no topo (onde o varejo é estopado), o algoritmo espera pacientemente o recuo nas zonas de 65.0% ou 70.5%.
3. **Stop Curto e Estruturado (79.0%):** Se o preço romper além de 79.0%, a tese institucional de continuação da perna foi invalidada. O stop fica posicionado exatamente no 79.0%, mantendo o risco financeiro extremamente pequeno.
4. **Payoff Gigantesco:** Como o risco mede apenas entre 8.5% e 14.0% da perna e o alvo busca o topo (ou 3R), a relação ganho/perda varia de **3:1 a 8.3:1**.

---

## 3. Padrão Oficial de Nomenclatura e os 3 Perfis Validados

### 📐 Regra Padrão de Nomenclatura das Estratégias
Para identificação imediata das características e métricas de cada modelo no código, nos relatórios, nos arquivos YAML e nos logs do MetaTrader 5, todas as estratégias devem seguir estritamente o formato:

> **`<nome_base>_<taxaacerto>_<retornoanual>_<profitfactor>_<maxdrawdown>`**

- **Campos:**
  1. `<nome_base>`: Identificador funcional da estratégia (ex: `smc_fibo_agressivo`).
  2. `<taxaacerto>`: Taxa de acerto percentual com sufixo `pct` (ex: `25pct`, `35pct`).
  3. `<retornoanual>`: Retorno líquido consolidado em R-múltiplos com sufixo `R` (ex: `2101R`, `1469R`).
  4. `<profitfactor>`: Profit Factor com sufixo `pf` (ex: `1.89pf`, `1.64pf`, `2.23pf`).
  5. `<maxdrawdown>`: Rebaixamento máximo da curva de capital com sufixo `dd` (ex: `43dd`, `56dd`, `25dd`).

---

### 👑 MODELO CAMPEÃO SUPREMO: `smc_fibo_trailing_44pct_2500R_2.23pf_32dd`
- **ID Oficial do Modelo:** `smc_fibo_trailing_44pct_2500R_2.23pf_32dd`
- **Arquivo de Configuração:** [`config/models/smc_fibo_trailing_44pct_2500R_2.23pf_32dd.yaml`](file:///D:/thiago/Projetos/trading-smc-bot/config/models/smc_fibo_trailing_44pct_2500R_2.23pf_32dd.yaml)
- **Inovação Técnica:** Entrada no 70.5% (Sweet Spot) com stop no 79.0% e saída dinâmica por **Trailing Stop na MME 8** (encerra quando o candle fecha contra a média móvel exponencial de 8 períodos).
- **Timeframe:** M5
- **Operações Anuais:** 4.217 (~16 trades/dia no portfólio completo)
- **Taxa de Acerto:** **44,0%** 🎯 *(Salto recorde de 24% para 44%)*
- **Profit Factor:** **2.23** 🚀
- **Retorno Total 12 Meses:** **+2.499,4 R** 🏆 *(Recorde Absoluto do Projeto)*
- **Out-of-Sample Cego (Mai/26 - Nov/26):** **+1.421,1 R** (Walk-Forward Efficiency: 1.32)
- **Max Drawdown Anual:** apenas **-32,3 R** *(Relação Retorno/Drawdown impressionante de 77 : 1)*
- **Desempenho por Ativo:**
  - Ouro (XAUUSD): **+877,0 R** (WR 48.1%)
  - Nasdaq (NAS100): **+716,9 R** (WR 42.1%)
  - DAX 40: **+463,5 R** (WR 42.7%)
  - Petróleo Brent: **+228,4 R** (WR 45.5%)
  - USD/JPY: **+106,1 R** (WR 41.7%)
  - EUR/USD: **+79,0 R** (WR 47.7%)
  - GBP/USD: **+28,4 R** (WR 37.7%)

---

### Perfil 1: `smc_fibo_agressivo_25pct_2101R_1.89pf_43dd` (Retorno Máximo sem Trailing)
- **ID Oficial do Modelo:** `smc_fibo_agressivo_25pct_2101R_1.89pf_43dd`
- **Arquivo de Configuração:** [`config/models/smc_fibo_agressivo_25pct_2101R_1.89pf_43dd.yaml`](file:///D:/thiago/Projetos/trading-smc-bot/config/models/smc_fibo_agressivo_25pct_2101R_1.89pf_43dd.yaml)
- **Foco:** Extração máxima de R-múltiplos no ano com relação risco:retorno média de **8.3 : 1**.
- **Timeframe:** M5
- **Nível de Entrada:** 70.5% da perna (Sweet Spot ICT)
- **Nível de Stop Loss:** 79.0% (Risco de apenas 8.5% da perna)
- **Alvo de Lucro:** Topo/Fundo prévio estrutural (0.0% de Fibo)
- **Horário:** 24 Horas
- **Operações Anuais:** 3.118 (~12 trades/dia no portfólio completo)
- **Taxa de Acerto:** 24,6% (`25pct`)
- **Profit Factor:** **1.89** (`1.89pf`)
- **Retorno Total 12 Meses:** **+2.101,3 R** (`2101R`)
- **In-Sample (Nov/25 - Abr/26):** +964,2 R
- **Out-of-Sample Cego (Mai/26 - Nov/26):** **+1.137,1 R** (Walk-Forward Efficiency: 1.18)
- **Max Drawdown Anual:** -42,8 R (`43dd`)
- **Indicação:** Para quem busca o maior crescimento patrimonial absoluto e compreende que a matemática do payoff de 8:1 compensa uma taxa de acerto de ~25%.

---

### Perfil 2: `smc_fibo_equilibrado_35pct_1469R_1.64pf_56dd` (Alta Taxa de Acerto)
- **ID Oficial do Modelo:** `smc_fibo_equilibrado_35pct_1469R_1.64pf_56dd`
- **Arquivo de Configuração:** [`config/models/smc_fibo_equilibrado_35pct_1469R_1.64pf_56dd.yaml`](file:///D:/thiago/Projetos/trading-smc-bot/config/models/smc_fibo_equilibrado_35pct_1469R_1.64pf_56dd.yaml)
- **Foco:** Equilíbrio perfeito entre retorno elevado e conforto psicológico (taxa de acerto superior a 35% com payoff de 3:1).
- **Timeframe:** M5
- **Nível de Entrada:** 65.0% da perna
- **Nível de Stop Loss:** 79.0% (Risco de 14.0% da perna)
- **Alvo de Lucro:** Fixo em 3.0 vezes o risco (3R / 1:3.0)
- **Horário:** 24 Horas
- **Operações Anuais:** 3.531 (~14 trades/dia no portfólio completo)
- **Taxa de Acerto:** **35,4%** 🎯 (`35pct`)
- **Profit Factor:** **1.64** (`1.64pf`)
- **Retorno Total 12 Meses:** **+1.469,0 R** (`1469R`)
- **In-Sample (Nov/25 - Abr/26):** +673,0 R
- **Out-of-Sample Cego (Mai/26 - Nov/26):** **+796,0 R** (Walk-Forward Efficiency: 1.18)
- **Max Drawdown Anual:** -56,0 R (`56dd`)
- **Indicação:** **Recomendado para início em conta real**, pois acerta mais de 1 a cada 3 operações e gera sequências de perdas menores.

---

### Perfil 3: `smc_fibo_conservador_27pct_1233R_2.23pf_25dd` (Maior Profit Factor)
- **ID Oficial do Modelo:** `smc_fibo_conservador_27pct_1233R_2.23pf_25dd`
- **Arquivo de Configuração:** [`config/models/smc_fibo_conservador_27pct_1233R_2.23pf_25dd.yaml`](file:///D:/thiago/Projetos/trading-smc-bot/config/models/smc_fibo_conservador_27pct_1233R_2.23pf_25dd.yaml)
- **Foco:** Máxima segurança institucional, trades mais longos, menor frequência e menor rebaixamento.
- **Timeframe:** M15
- **Nível de Entrada:** 70.5% da perna
- **Nível de Stop Loss:** 79.0%
- **Alvo de Lucro:** Topo/Fundo prévio estrutural (0.0% de Fibo)
- **Horário:** 24 Horas
- **Operações Anuais:** 1.366 (~5 trades/dia no portfólio completo)
- **Taxa de Acerto:** 26,7% (`27pct`)
- **Profit Factor:** **2.23** 🚀 *(Recorde Histórico do Projeto - `2.23pf`)*
- **Retorno Total 12 Meses:** **+1.232,9 R** (`1233R`)
- **In-Sample (Nov/25 - Abr/26):** +561,9 R
- **Out-of-Sample Cego (Mai/26 - Nov/26):** **+671,1 R** (Walk-Forward Efficiency: 1.19)
- **Max Drawdown Anual:** apenas **-24,9 R** *(Rebaixamento mínimo - `25dd`)*
- **Indicação:** Para contas de prop firms (mesas proprietárias) onde o limite de drawdown é rigoroso, ou para traders que preferem menor giro de ordens.

---

### Perfil 4: `smc_fibo_blindado_50pct_2278R_2.24pf_30dd` (Segurança Psicológica & Blindagem)
- **ID Oficial do Modelo:** `smc_fibo_blindado_50pct_2278R_2.24pf_30dd`
- **Arquivo de Configuração:** [`config/models/smc_fibo_blindado_50pct_2278R_2.24pf_30dd.yaml`](file:///D:/thiago/Projetos/trading-smc-bot/config/models/smc_fibo_blindado_50pct_2278R_2.24pf_30dd.yaml)
- **Inovação Técnica:** Entrada no 70.5% (Sweet Spot) com stop no 79.0% combinada com **Trava Automática de Lucro**: ao atingir **+2.0R a favor**, o stop loss é travado imediatamente em **+1.0R de lucro garantido**, e a MME 8 conduz o restante do movimento até a máxima.
- **Timeframe:** M5
- **Operações Anuais:** 4.240 (~16 trades/dia no portfólio completo)
- **Taxa de Acerto:** **49,6%** 🎯 *(Praticamente 1 em cada 2 trades fecha positivo!)*
- **Profit Factor:** **2.24** 🚀
- **Retorno Total 12 Meses:** **+2.278,5 R** (`2278R`)
- **Out-of-Sample Cego (Mai/26 - Nov/26):** **+1.297,5 R**
- **Max Drawdown Anual:** apenas **-29,5 R** (`30dd`) *(O menor drawdown entre todas as estratégias de M5!)*
- **Indicação:** **O perfil definitivo para tranquilidade mental e contas de mesas proprietárias**. Elimina a frustração de ver um trade ganhar 2R e voltar para o zero, garantindo que metade de todas as operações do ano fechem com lucro no bolso.

---

## 4. Comparativo de Desempenho por Ativo nos 3 Perfis

| Ativo | Classe | 🥇 Agressivo (+2.101 R) | 🥈 Equilibrado (+1.469 R) | 🥉 Conservador (+1.233 R) |
| :--- | :--- | :---: | :---: | :---: |
| **XAUUSD (Ouro)** | Metal | **+616,2 R** | **+449,0 R** | **+368,4 R** |
| **NAS100** | Índice US | **+582,6 R** | **+350,0 R** | **+312,1 R** |
| **DAX40** | Índice Europa | **+436,8 R** | **+317,0 R** | **+241,5 R** |
| **BRENT** | Energia | **+214,0 R** | **+161,0 R** | **+145,2 R** |
| **EURUSD** | Forex Principal | **+102,3 R** | **+88,0 R** | **+64,8 R** |
| **USDJPY** | Forex Cruzado | **+98,2 R** | **+83,0 R** | **+58,3 R** |
| **GBPUSD** | Forex Volátil | **+51,2 R** | **+21,0 R** | **+42,6 R** |
| **TOTAL DO PORTFÓLIO** | **Global** | **+2.101,3 R** 🏆 | **+1.469,0 R** 🏆 | **+1.232,9 R** 🏆 |

> [!IMPORTANT]
> Em todos os três perfis, **todos os 7 ativos fecharam lucrativos**, sem exceção. Isso comprova que a vantagem estatística é intrínseca à matemática da retração e não um ajuste de curva em um ativo isolado.

---

## 5. Auditoria Mensal Consolidada (1 Ano Real Dukascopy — 13 Meses)

Auditoria mês a mês de 01/11/2025 a 04/11/2026 em todos os 7 ativos combinados (dados reais sem lookahead):

### 📊 Comparativo Mensal de Lucro Líquido (em Risco $R$):

| Ano-Mês | 👑 Campeã Suprema (MME 8) | 🛡️ Blindada (Trava 2:1) | 🥇 Agressivo (Topo/Fundo) | 🥈 Equilibrado (3R) | 🥉 Conservador (M15) |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **2025-11** | **+310.2 R** | +282.8 R | +268.6 R | +149.0 R | +250.1 R |
| **2025-12** | **+286.0 R** | +253.0 R | +274.8 R | +197.0 R | +109.0 R |
| **2026-01** | **+340.1 R** | +320.4 R | +321.3 R | +250.0 R | +160.6 R |
| **2026-02** | +328.8 R | +325.8 R | **+350.2 R** | +267.0 R | +237.0 R |
| **2026-03** | +333.3 R | +319.3 R | **+395.5 R** | +296.0 R | +257.6 R |
| **2026-04** | **+453.2 R** | +440.8 R | +446.4 R | +258.0 R | +313.8 R |
| **2026-05** | +385.4 R | +391.8 R | **+419.3 R** | +273.0 R | +251.2 R |
| **2026-06** | **+364.9 R** | +336.6 R | +353.4 R | +191.0 R | +322.5 R |
| **2026-07** | +330.7 R | +322.9 R | **+339.0 R** | +212.0 R | +217.5 R |
| **2026-08** | +376.1 R | **+378.9 R** | +344.5 R | +220.0 R | +172.0 R |
| **2026-09** | **+496.5 R** | +460.0 R | +451.3 R | +271.0 R | +245.2 R |
| **2026-10** | +364.3 R | +332.4 R | **+391.8 R** | +213.0 R | +292.3 R |
| **2026-11\*** | +62.9 R | +60.6 R | **+71.4 R** | +35.0 R | +21.8 R |

> [!NOTE]
> **Consistência Perfeita:** Em todas as 5 estratégias, **100% dos meses fecharam positivos**. Não houve nenhum mês negativo no portfólio.
> Arquivos brutos de auditoria mensal: [`reports/monthly_comparison_all_strategies.csv`](file:///D:/thiago/Projetos/trading-smc-bot/reports/monthly_comparison_all_strategies.csv).

### 🛡️ Detalhamento do Perfil Blindado (`smc_fibo_blindado_50pct_2278R_2.24pf_30dd`):
* Média de ganho: **~330 R por mês**.
* Taxa de acerto mensal: sempre entre **49.8% e 61.0%**.
* Profit Factor mensal: sempre entre **2.68 e 4.98**.
* Pior rebaixamento intramês (Max DD): apenas **-10.2 R** após estabilização inicial.

---

## 6. Diretrizes de Gestão de Risco e Execução Real

Para operar qualquer um desses perfis em ambiente real no MetaTrader 5:

1. **Risco por Operação ($R$):**
   - Recomendado: **0.5% a 1.0% do patrimônio líquido** por operação.
   - Em mesas proprietárias (prop firms): **0.25% a 0.50% por operação** para manter o drawdown dentro das regras da mesa.
2. **Exposição Máxima Simultânea:**
   - Máximo de **3 a 4 operações abertas simultaneamente** na carteira para evitar sobre-alavancagem em momentos de notícias de alto impacto (CPI, NFP, FOMC).
3. **Reentrada no Nível 79% (Faca Caindo):**
   - **Regra Estrita:** A reentrada no 79% deve permanecer **DESATIVADA**. Nossos testes quantitativos comprovaram que tentar segurar a retração além do 79% devolve lucros (-13R), enquanto aceitar o stop no 79% e aguardar uma nova perna de BOS mantém a expectativa matemática no ápice.

---

## 7. Arquivos e Comandos do Sistema

- **Arquivo da Base de Dados da Otimização:** [`out/fibo_optimization/grid_results.csv`](file:///D:/thiago/Projetos/trading-smc-bot/out/fibo_optimization/grid_results.csv)
- **Planilha Excel Detalhada da Auditoria:** [`out/backtests/smc_fibo_ote_1ano/smc_fibo_ote_1ano_multiativo.xlsx`](file:///D:/thiago/Projetos/trading-smc-bot/out/backtests/smc_fibo_ote_1ano/smc_fibo_ote_1ano_multiativo.xlsx)
- **Código do Motor da Estratégia:** [`src/smc_trader/strategies/fibo_ote.py`](file:///D:/thiago/Projetos/trading-smc-bot/src/smc_trader/strategies/fibo_ote.py)
- **Configuração de Produção:** [`config/production.yaml`](file:///D:/thiago/Projetos/trading-smc-bot/config/production.yaml)

### Como rodar simulações no terminal a qualquer momento:
```powershell
# Executar backtest completo do perfil padrão nos 7 ativos:
uv run smc fibo-backtest --symbol all

# Executar backtest em um ativo específico (ex: Nasdaq):
uv run smc fibo-backtest --symbol NAS100

# Executar a suíte completa de auditoria com exportação Excel:
uv run python scripts/run_fibo_ote_suite.py
```

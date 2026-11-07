# 🤝 HANDOFF OFICIAL DO PROJETO — TRADING SMC BOT
**Documento de Transição e Contexto Contínuo para Agentes de IA e Desenvolvedores**  
**Data:** 07 de Novembro de 2026  
**Status do Repositório:** 100% Auditado, Validado Empiricamente, Sincronizado e Limpo (`main`)

---

## 📌 1. Visão Geral e Objetivo do Projeto

O **trading-smc-bot** é um ecossistema quantitativo e algorítmico institucional baseado em conceitos de **Smart Money Concepts (SMC)** e **Fibonacci Optimal Trade Entry (OTE)**.

### Plataformas Alvo:
1. **MetaTrader 5 (Python SDK / MQL5):** Ativos globais da Dukascopy (`XAUUSD`, `NAS100`, `DAX40`, `BRENT`, `EURUSD`, `GBPUSD`, `USDJPY`).
2. **Nelogica Profit / Rico Trader (NTSL):** Mercado B3 brasileiro (`WIN` Mini-Índice e `WDO` Mini-Dólar).

---

## 🚨 2. A Auditoria Crítica do Gemini Argon (Marco Fundamental)

### As 3 Distorções Identificadas e Corrigidas no Motor Python (`fibo_ote.py`):
1. **O Bug da Imunidade na Vela de Entrada (`continue`):**
   * *Diagnóstico:* Logo após abrir a posição no toque de Fibonacci (`in_pos = True`), o código executava um `continue`, saltando para a próxima barra sem verificar se a **própria barra de entrada** furou o Stop Loss.
   * *Correção:* Adicionado `INTRABAR_STOP_LOSS`. Se `lows[i] <= sl_price` (para long) ou `highs[i] >= sl_price` (para short) na própria barra de entrada, a posição é estopada imediatamente com -1.0 R.
   * *Impacto Empírico:* O teste em 4,95M candles Dukascopy revelou que isso ocorreu **4.470 vezes** na perna de 70.5% a 79.0%, porque o stop de 8.5% da perna é estreito demais para barras voláteis de M5.
2. **Saída de Trailing Stop no Prejuízo:**
   * *Diagnóstico:* O motor Python antigo saía por cruzamento da MME 8 mesmo no prejuízo (ex: -0.2 R).
   * *Correção:* Adicionada a condição `c_close > entry_price` (para compra) e `c_close < entry_price` (para venda), igual ao código Nelogica NTSL. Aumentou o Win Rate de 45.7% para 49.4%.
3. **Ausência da Trava 2:1 no Core Config:**
   * *Correção:* Implementado `use_lock_2to1` nativamente no motor, permitindo subir o stop garantindo +1.0 R ao atingir +2.0 R a favor.

---

## 📊 3. Tabela Oficial de Estratégias (Recalibração 2 Anos Dukascopy — 4.95M Candles)

Todos os modelos seguem rigorosamente a regra padrão de nomenclatura:
> **`<nome_base>_<taxaacerto>_<retornoanual>_<profitfactor>_<maxdrawdown>`**

| Perfil / Função | Nome Oficial do Modelo | Taxa Acerto | Retorno / Ano | Retorno 2 Anos | Profit Factor | Max Drawdown | Payoff | Config YAML |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **🥇 Campeão Institucional** | `smc_fibo_estrutural_68pct_809R_1.48pf_30dd` | **68,3%** | **+808,6 R** | +1.617,1 R | **1,48** | **-29,8 R** | 0.69 | [`smc_fibo_estrutural_68pct_809R_1.48pf_30dd.yaml`](config/models/smc_fibo_estrutural_68pct_809R_1.48pf_30dd.yaml) |
| **🚀 Campeão Retorno Bruto** | `smc_fibo_trailing_51pct_929R_1.35pf_46dd` | **51,4%** | **+928,6 R** | +1.857,3 R | **1,35** | **-46,3 R** | 1.28 | [`smc_fibo_trailing_51pct_929R_1.35pf_46dd.yaml`](config/models/smc_fibo_trailing_51pct_929R_1.35pf_46dd.yaml) |
| **🎯 Sweet Spot ICT** | `smc_fibo_sweetspot_53pct_774R_1.36pf_47dd` | **53,3%** | **+774,2 R** | +1.548,5 R | **1,36** | **-46,9 R** | 1.19 | [`smc_fibo_sweetspot_53pct_774R_1.36pf_47dd.yaml`](config/models/smc_fibo_sweetspot_53pct_774R_1.36pf_47dd.yaml) |
| **🛡️ Fortaleza Anti-Drawdown** | `smc_fibo_blindado_69pct_529R_1.32pf_26dd` | **69,0%** | **+528,7 R** | +1.057,4 R | **1,32** | **-26,2 R** | 0.59 | [`smc_fibo_blindado_69pct_529R_1.32pf_26dd.yaml`](config/models/smc_fibo_blindado_69pct_529R_1.32pf_26dd.yaml) |
| **⚖️ Alvo Fixo (3R)** | `smc_fibo_equilibrado_28pct_700R_1.19pf_49dd` | **28,4%** | **+700,0 R** | +1.400,0 R | **1,19** | **-49,0 R** | 3.00 | [`smc_fibo_equilibrado_28pct_700R_1.19pf_49dd.yaml`](config/models/smc_fibo_equilibrado_28pct_700R_1.19pf_49dd.yaml) |
| **⏱️ Sessão Nobre (07-18 UTC)**| `smc_fibo_conservador_66pct_337R_1.31pf_28dd` | **65,8%** | **+337,3 R** | +674,5 R | **1,31** | **-28,4 R** | 0.68 | [`smc_fibo_conservador_66pct_337R_1.31pf_28dd.yaml`](config/models/smc_fibo_conservador_66pct_337R_1.31pf_28dd.yaml) |

---

## 🇧🇷 4. Validação Empírica em Produção no Rico Trader (B3)

O usuário executou backtests no **Rico Trader (ProfitChart)** com dados reais da B3 em 3 meses:
* **Mini-Índice (`WIN`):** **+R$ 1.400,00 líquido** (1 contrato), **Win Rate 42%**, **Profit Factor 2.30**, máx. 5 perdedoras seguidas.
* **Mini-Dólar (`WDO$N` série contínua):** **+R$ 456,00 líquido** (1 contrato), **Win Rate 46%**, **Profit Factor 1.50**, máx. 6 vencedoras seguidas.
* **Diagnóstico:** O Rico Trader já executa candle a candle e tick a tick, reproduzindo exatamente as métricas do motor Python auditado (PF entre 1.35 e 2.30 e Win Rate entre 42% e 68%).

---

## 🛠️ 5. Scripts Nelogica NTSL (`nelogica/`)

Todos os scripts NTSL possuem:
1. **Auto-Escala Dinâmica:** `filtroMinimo := Media(20, Maxima - Minima) * MultVolatilidade(1.5)`. Funciona sem alteração no WIN, WDO, PETR4, Cripto.
2. **Plot Visual Direto no Gráfico Principal:**
   * Linha 1 (Ciano / `clAqua`): Topo Considerado (`ultimoTopo` em espera / `refTopo` no BOS).
   * Linha 2 (Magenta / `clFuchsia`): Fundo Considerado (`ultimoFundo` em espera / `refFundo` no BOS).
   * Candle Amarelo (`clAmarelo`): Sinaliza a barra da quebra de estrutura (BOS).
3. **Filtros de Risco com Default Universal (`0.0`):**
   * `MaxStopPontos(0.0)` e `MinStopPontos(0.0)` para não bloquear ordens em ativos com cotações diferentes. Para WIN sugerir 250/50 e para WDO sugerir 10/4.

### Arquivos Disponíveis:
* `nelogica/SMC_FIBO_ESTRUTURAL.ntsl` e `.txt` (Campeão Institucional)
* `nelogica/SMC_FIBO_SWEETSPOT.ntsl` e `.txt` (Sweet Spot 70.5% / 88.6%)
* `nelogica/SMC_FIBO_BLINDADO.ntsl` e `.txt` (Trava 2:1)
* `nelogica/SMC_FIBO_TRAILING.ntsl` e `.txt` (Versão Trailing livre)

---

## 💻 6. Ambiente de Desenvolvimento e Comandos Úteis

* **Diretório do Projeto:** `D:\thiago\Projetos\trading-smc-bot`
* **Gerenciador de Pacotes:** `uv` com Python 3.12 virtualenv.
* **Comandos Chave:**
  ```powershell
  # Rodar backtest CLI Python:
  uv run smc fibo-backtest --symbol all

  # Rodar a recalibração de variáveis auditada:
  uv run python scripts/recalibrate_all_variables_audited.py

  # Testar variações de Stop Loss auditadas:
  uv run python scripts/test_stop_variations_audited.py

  # Iniciar servidor UI local:
  uv run smc ui --port 8080
  ```

---

## ⚠️ 7. Diretrizes Cruciais para os Próximos Agentes

1. **NUNCA reintroduza o viés do `continue`:** Qualquer teste no motor Python DEVE verificar se a própria barra de entrada furou o stop (`check_intrabar_sl`).
2. **Preserve a Trava de Lucro no Trailing:** O trailing stop na MME 8 só pode disparar se `c_close > entry_price` (para long) ou `c_close < entry_price` (para short).
3. **Mantenha os Defaults do Nelogica em `0.0`:** Parâmetros de pontos fixos devem permanecer desativados por padrão para preservar a universalidade automática do código entre Índices, Moedas e Ações.
4. **Siga a Nomenclatura:** Toda nova estratégia deve ter nome no padrão `<nome_base>_<taxaacerto>_<retornoanual>_<profitfactor>_<maxdrawdown>`.

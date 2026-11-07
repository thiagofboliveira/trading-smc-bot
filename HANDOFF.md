# 🤝 HANDOFF OFICIAL DO PROJETO — TRADING SMC BOT
**Documento de Transição Técnica e Contexto Arquitetural para Desenvolvedores e Agentes de IA**  
**Data:** 07 de Novembro de 2026  
**Repositório Remoto:** `git@github.com:thiagofboliveira/trading-smc-bot.git`  
**Branch Principal de Trabalho:** `feat/backtest-engine`  
**Status da Auditoria e Correções:** **Totalmente auditado e revisado (`docs/REVISAO_IMPLEMENTACAO_BACKLOG.md`)**  
**Suíte de Testes:** **609 testes passando (`uv run pytest`)** · **0 erros de linting (`uv run ruff check src/ tests/`)**

---

## 📌 1. Visão Geral e Arquitetura do Sistema

O **trading-smc-bot** é um ecossistema quantitativo e algorítmico institucional de alta fidelidade matemática, projetado para operar sem qualquer viés de lookahead, viés de sobrevivência ou suposições irreais de execução.

### O sistema unifica três frentes operacionais sob a mesma especificação matemática:
1. **Motor Backtest / Pesquisa:** Simulação cronológica barra a barra em dados M1/M5 da Dukascopy e B3 (WIN/WDO), com modelo explícito de spread bid/ask nos dois lados, slippage real, comissão por lote, simulação de portfólio multi-ativos e validação estatística por Monte Carlo.
2. **Motor MetaTrader 5 (MT5 Live & Paper):** Execução incremental barra a barra via cliente nativo MT5 ou ponte HTTP com EA MQL5 (`mql5/SMC_Bridge_EA.mq5`), com ordens limite pendentes no nível de retração, trailing stop, reconciliação persistente de posições (`StateStore`) e Kill Switch de proteção de capital.
3. **Nelogica Profit / Rico Trader (NTSL B3):** Estratégia canônica unificada (`nelogica/SMC_FIBO_CANONICO.ntsl`) com ordens de stop/alvo reais na bolsa (`SellToCoverStop` / `SellToCoverLimit`), entrada por ordem limite (`BuyLimit` / `SellShortLimit`), filtros de sessão B3 (17:00 / 17:45) e paridade estrita com o algoritmo Python.

---

## 🏛️ 2. Estrutura do Repositório

```text
├── config/                     # Configurações de modelos YAML e custos de mercado
│   ├── costs.yaml              # Custos centralizados (spread, slippage, comissões)
│   ├── production.yaml         # Configuração estrita de produção (extra="forbid")
│   └── models/                 # Modelos estratégicos versionados
├── data/                       # Armazenamento local de candles em formato Parquet
├── docs/                       # Especificações e auditoria
│   ├── BACKLOG_CORRECOES.md    # Backlog completo de 61 itens (100% concluído)
│   └── SPEC_SMC_FIBO.md        # Especificação canônica unificada em pseudocódigo
├── mql5/                       # Expert Advisors MetaTrader 5
│   └── SMC_Bridge_EA.mq5       # EA ponte com autenticação bearer e retcodes
├── nelogica/                   # Scripts NTSL para o ProfitChart (B3)
│   └── SMC_FIBO_CANONICO.ntsl  # Código canônico parametrizado para WIN e WDO
├── src/smc_trader/             # Código-fonte principal
│   ├── analysis.py             # Pipeline macro de análise SMC
│   ├── cli.py                  # Interface de linha de comando CLI (`smc`)
│   ├── config.py               # Modelos de configuração tipados Pydantic/dataclass
│   ├── backtest/               # Motor de simulação
│   │   ├── engine.py           # BacktestEngine (zonas SMC, OB, BB, sweeps, CHoCH)
│   │   ├── exporter.py         # Exportador profissional XLSX/PNG/JSON com SHA-256 (M-09)
│   │   ├── portfolio.py        # Simulação realista de portfólio multi-ativos (M-05)
│   │   ├── robustness.py       # Monte Carlo, alarmes de sanidade e baseline (M-06, M-08)
│   │   ├── runner.py           # Execução em grade e walk-forward
│   │   ├── session.py          # Gerenciamento de sessões e horários
│   │   └── types.py            # Tipos de dados (Trade, BacktestResult, etc.)
│   ├── data/                   # Ingestão e tratamento de dados
│   │   ├── continuous.py       # Séries contínuas B3 com marcação de rolagem (D-02)
│   │   ├── dukascopy.py        # Download histórico M1 Dukascopy (bid e ask)
│   │   ├── profit_import.py    # Importador flexível Profit/generic CSV (D-01)
│   │   ├── quality.py          # Auditoria de integridade de candles
│   │   └── store.py            # Persistência atômica Parquet
│   ├── execution/              # Execução ao vivo MT5
│   │   ├── fibo_live.py        # Motor incremental Fibo OTE live
│   │   ├── live_engine.py      # LiveEngine com ciclo de vida e reconciliação
│   │   ├── mt5_interface.py    # BridgeMT5Client e NativeMT5Client (fail-closed)
│   │   ├── kill_switch.py      # Kill Switch (limite diário %, delay, spread spike)
│   │   ├── journal.py          # Diário estruturado de trades JSONL
│   │   ├── sizing.py           # Dimensionamento de posição por risco real de tick
│   │   └── state_store.py      # Persistência de estado e idempotência de comandos
│   ├── strategies/             # Estratégias institucionais
│   │   └── fibo_ote.py         # FiboOTEStrategy (motor canônico livre de vieses)
│   ├── structure/              # Detecção de pivôs fractais e BOS/CHoCH
│   └── zones/                  # Detecção de Order Blocks, Breakers, FVGs e Sweeps
└── tests/                      # Suíte de 604 testes automatizados
```

---

## 🛡️ 3. O Marco da Auditoria: Resumo das Correções Críticas

Todos os 61 itens levantados no backlog de auditoria foram corrigidos e cobertos por testes unitários e de integração:

### 1. Eliminação dos Vieses do Motor Fibo (`F-01` a `F-11`):
* **Lookahead no BOS (F-01):** Entrada só é permitida a partir da barra posterior ao fechamento que confirmou o BOS (`i > bos_idx`).
* **Assimetria de Spread nos Shorts (F-02, M-07):** Shorts recompram no Ask (`bid + spread` ou candle Ask real). Stop, alvo e saídas por média pagam spread em ambos os lados.
* **Trava 2:1 e Expansão da Perna (F-03, F-04):** A barra corrente é testada contra os níveis calculados na barra anterior ($i-1$). A máxima nova só expande a perna para a barra seguinte ($i+1$).
* **Gaps e MME (F-05, F-06):** Saídas por gap executam no `open`. Saída por MME engatilhada no close executa no `open` da barra seguinte.
* **Desempate Fractal (F-11):** Platôs de máximas/mínimas iguais desempatam deterministicamente na primeira ocorrência, alinhando Python e NTSL.

### 2. Motor de Zonas SMC (`Z-01` a `Z-10`):
* **Médias sem Lookahead (Z-01):** As médias M15/M5 entregam apenas dados de buckets cujo fechamento já ocorreu.
* **Stop no Candle de Entrada (Z-02):** Toques que violam o stop no mesmo candle são imediatamente estopados com -1.0 R.
* **Mitigação durante Posição Aberta (Z-08):** Zonas tocadas enquanto há uma posição aberta são marcadas como `CONSUMED` e não geram falsas reentradas posteriores.
* **Confirmação CHoCH sem Atraso (Z-09):** O evento CHoCH é indexado pelo candle de rompimento (`break_time`), executando a entrada imediatamente no close do candle confirmatório.

### 3. Validação Realista e Estatística (`M-01` a `M-09`):
* **Seleção Estrita por In-Sample (M-01, M-02):** Modelos são selecionados unicamente no período de treino e testados fora da amostra (Walk-Forward).
* **Portfólio Realista (M-05):** Simulação de conta com controle global de concorrência (`max_open_trades_total`) e curva de capital/drawdown ordenados por **saída**.
* **Monte Carlo e Baseline (M-06, M-08):** 1.000 permutações de trade order medem o Drawdown no percentil 95. Baseline aleatório confirma se há vantagem estatística ($p < 0.05$) com correção de Bonferroni. Alarmes alertam para PF > 2.5 ou assimetrias.
* **Reprodutibilidade Criptográfica (M-09):** Exportações geram `reproducibility.json` com SHA-256 do parquet, da config e hash do commit git.

### 4. Execução ao Vivo e MT5 (`L-01` a `L-11`):
* **Fail-Closed:** O modo `live` recusa-se a operar se o cliente for `MockMT5Client`.
* **Paridade Live/Backtest:** `FiboOTEStrategy` incremental compartilhada. Teste de replay histórico comprova paridade idêntica trade a trade.
* **Idempotência e Reconciliação:** IDs de comando determinísticos (`make_cmd_id`), sincronização com deals da corretora e persistência em `data/live_state.json`.
* **Kill Switch:** Trava automática por perda diária %, limite de stops seguidos, spike de spread e delay de dados.

### 5. NTSL e Dados B3 (`N-01` a `N-05`, `D-01` a `D-05`):
* **Ordens Reais na Bolsa:** Envio contínuo de `SellToCoverStop` / `BuyToCoverStop` e `SellToCoverLimit` / `BuyToCoverLimit`.
* **Horários B3:** Trava de novas entradas às 17:00 e zeragem compulsória às 17:45.
* **Séries Contínuas com Rolagem:** Módulo `continuous.py` emenda contratos marcando `roll = True` e invalidando pernas ativas para não gerar falsos BOS no gap de rolagem.

---

## 💻 4. Guia Rápido de Comandos

O ambiente utiliza **Linux / Python 3.13** gerenciado via **`uv`**.

### Executar a Suíte Completa de Testes:
```bash
uv run pytest
```

### Checagem de Qualidade e Tipagem (Ruff):
```bash
uv run ruff check src/ tests/
```

### Importar Dados Históricos (Profit, MT5 ou Generic CSV):
```bash
uv run smc import-csv caminho/arquivo.csv --symbol WIN --format profit
uv run smc import-csv caminho/arquivo.csv --symbol WDO --format generic
```

### Baixar Histórico da Dukascopy (Bid e Ask):
```bash
uv run smc fetch --symbol XAUUSD --start 2024-01-01 --end 2026-10-31
```

### Rodar Backtest com o Motor Canônico Fibo OTE:
```bash
uv run smc fibo-backtest --symbol XAUUSD
```

### Iniciar o Modo Live Paper / Real com MT5:
```bash
uv run smc live --config config/production.yaml
```
> [!IMPORTANT]
> Em `config/production.yaml`, os símbolos vêm com `enabled: false` por padrão (fail-closed).
> Modelos genéricos de 24h sem filtro de horário apresentaram expectativa negativa após remoção dos vieses.
> Para operar, selecione um modelo calibrado com expectativa positiva comprovada (ex: `smc_fibo_gold_session` em XAUUSD na sessão Londres/NY) e ative conscientemente `enabled: true`.

---

## ⚠️ 5. Diretrizes para Futuras Alterações e Novos Agentes

1. **Nunca quebre o teste de Invariância de Prefixo (`tests/test_prefix_invariance.py`):**
   Qualquer decisão tomada no instante $t$ não pode depender de candles posteriores a $t$. Se o teste falhar, há lookahead.
2. **Short SEMPRE paga spread na saída:**
   Vendas entram no Bid e recompram no Ask (`c_high + spread >= sl`). Nunca compare stop ou alvo de short diretamente com a série Bid sem adicionar o spread.
3. **Respeite o Fail-Closed em Produção:**
   Nunca permita bypass de validações financeiras (`KillSwitch`, sizing de risco, confirmação de lotes mínimos, `enabled: false`).
4. **Mantenha os 609 testes verdes:**
   Antes de submeter qualquer commit, garanta que `uv run pytest` e `uv run ruff check src/ tests/` passem sem nenhum erro.
5. **Preserve a Especificação Unificada:**
   Qualquer mudança na lógica de entrada ou saída deve ser primeiramente refletida em [`docs/SPEC_SMC_FIBO.md`](docs/SPEC_SMC_FIBO.md) e mantida em sincronia entre Python, MQL5 e NTSL.

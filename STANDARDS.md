# 📐 GUIA DE PADRÕES, ARQUITETURA E DIRETRIZES TÉCNICAS
**Documento Mestre para Desenvolvedores e Agentes de IA — Ecossistema Trading SMC Bot**  
**Versão:** 2.0 (Pós-Auditoria de Realismo)  
**Data:** Novembro de 2026  

---

## 🧭 Sumário Executivo

Este documento estabelece as **convenções, padrões arquiteturais, regras matemáticas e protocolos de simulação** que regem todo o código, modelos, scripts e testes deste projeto. Todos os desenvolvedores e agentes de IA que atuarem neste repositório devem seguir estas diretrizes para garantir consistência estatística, reprodutibilidade em conta real e rastreabilidade total.

---

## 🏷️ 1. Padrões de Nomenclatura (Naming Conventions)

### 1.1 Nomenclatura Oficial de Estratégias e Modelos
Toda estratégia validada que passar a compor o portfólio oficial DEVE seguir a taxonomia padrão:

$$\mathbf{<\!nome\_base\!>\_<\!taxaacerto\!>\_<\!retornoanual\!>\_<\!profitfactor\!>\_<\!maxdrawdown\!>}$$

* **Campos Obrigatórios:**
  1. `<nome_base>`: Identificador funcional e conceitual do modelo (ex: `smc_fibo_estrutural`, `smc_fibo_sweetspot`, `smc_fibo_blindado`).
  2. `<taxaacerto>`: Taxa de acerto percentual inteira com sufixo `pct` (ex: `68pct`, `53pct`, `51pct`).
  3. `<retornoanual>`: Retorno líquido consolidado anualizado em R-múltiplos com sufixo `R` (ex: `809R`, `929R`, `529R`).
  4. `<profitfactor>`: Profit Factor formatado com 2 casas decimais e sufixo `pf` (ex: `1.48pf`, `1.36pf`, `1.32pf`).
  5. `<maxdrawdown>`: Rebaixamento máximo histórico em R-múltiplos com sufixo `dd` (ex: `30dd`, `47dd`, `26dd`).

* **Exemplos Canônicos:**
  * `smc_fibo_estrutural_68pct_809R_1.48pf_30dd`
  * `smc_fibo_trailing_51pct_929R_1.35pf_46dd`
  * `smc_fibo_sweetspot_53pct_774R_1.36pf_47dd`
  * `smc_fibo_blindado_69pct_529R_1.32pf_26dd`

### 1.2 Nomenclatura de Arquivos e Pastas
* **Modelos YAML:** `config/models/<nome_oficial_da_estrategia>.yaml`
* **Scripts NTSL Nelogica:** `nelogica/<NOME_ESTRATEGIA_MAIUSCULO>.ntsl` e `.txt`
* **Scripts de Pesquisa/Teste:** `scripts/<verbo>_<finalidade>_<complemento>.py` (ex: `scripts/test_stop_variations_audited.py`)
* **Relatórios Quantitativos:** `reports/<tema>_<timeframe_ou_periodo>.<csv|md>`

### 1.3 Padrão de Commits Git (Conventional Commits)
* `feat:` Nova funcionalidade, novo modelo ou novo script.
* `fix:` Correção de lógica matemática, bug de simulação ou ajuste de plataforma.
* `docs:` Atualizações em documentações, markdowns, playbooks e handoffs.
* `test:` Novos testes quantitativos ou baterias de validação walk-forward.
* `refactor:` Melhoria de código que não altera o resultado dos cálculos.

---

## 🏛️ 2. Arquitetura do Repositório

```
trading-smc-bot/
├── config/
│   ├── models/                # Modelos oficiais fechados em YAML e PLAYBOOK.md
│   └── production.yaml        # Parâmetros operacionais para MetaTrader 5
├── data/                      # Dados históricos brutos em Parquet (M1 Dukascopy)
├── nelogica/                  # Códigos nativos NTSL para Nelogica Profit / Rico Trader
│   ├── *.ntsl                 # Arquivo importável no Editor do Profit
│   └── *.txt                  # Cópia em texto puro para inspeção rápida
├── reports/                   # Relatórios consolidados em CSV e Markdown
├── scripts/                   # Ferramentas de backtest, otimização e auditoria
├── src/
│   └── smc_trader/            # Pacote Python principal
│       ├── backtest/          # Motor de simulação, custos, limites e métricas
│       ├── execution/         # Conectores com MT5 e execução de ordens
│       ├── strategies/        # Implementação das lógicas (ex: fibo_ote.py)
│       ├── structure/         # Mapeamento de BOS, CHoCH, Swings e Liquidez
│       ├── ui/                # Servidor FastHTML/Dashboard analítico
│       └── cli.py             # Interface de linha de comando (CLI)
├── HANDOFF.md                 # Documento de continuidade e transição entre agentes
├── STANDARDS.md               # Este guia de padrões e diretrizes técnicas
└── pyproject.toml             # Gerenciamento de dependências via uv
```

---

## 📐 3. Fundamentos Matemáticos e Conceituais do SMC-Fibo-OTE

A estratégia é fundamentada na geometria institucional de **desconto profundo após quebra estrutural (BOS)**:

```
[0.0% / Topo Impulsivo]  ───────────────────────────────── (Alvo Estrutural Máximo)
                                       ▲
                                       │
[61.8% / Golden Ratio]   ──────────────┼────────────────── (Entrada Clássica SMC)
[70.5% / Sweet Spot ICT] ──────────────┼────────────────── (Entrada Profunda de Alta Assimetria)
                                       │
[79.0% / Invalidação Curta]────────────┼────────────────── (Stop Agressivo)
[88.6% / Harmonic Level] ──────────────┼────────────────── (Stop Deep Invalidation)
                                       │
[100.0% / Fundo do BOS]  ──────────────┴────────────────── (Stop Estrutural Oficial SMC)
```

### 3.1 Detecção de Swings Fractais sem Lookahead
* Para evitar viés de antecipação (lookahead bias), os topos e fundos fractais exigem atraso de confirmação:
  * Topo Fractal: $\text{Maxima}[k] > \text{Maxima}[k-1] \text{ e } \text{Maxima}[k] > \text{Maxima}[k-2] \dots$
  * No Profit NTSL e no Python: utiliza-se $k=2$ (comparando a barra de 2 períodos atrás com as barras vizinhas). A confirmação só ocorre no fechamento da barra atual.

### 3.2 Quebra de Estrutura (BOS - Break of Structure)
* **BOS de Alta:** Um candle fecha estritamente acima do último topo institucional confirmado ($\text{Fechamento} > \text{ultimoTopo}$).
* **BOS de Baixa:** Um candle fecha estritamente abaixo do último fundo institucional confirmado ($\text{Fechamento} < \text{ultimoFundo}$).
* **Filtro de Relevância:** A amplitude da pernada impulsiva ($\text{Máxima} - \text{Fundo}$) deve superar a volatilidade média:
  $$\text{diffPernada} \ge \text{Media}(20, \text{Maxima} - \text{Minima}) \times 1.5$$

### 3.3 Gestão e Condução por Trailing Stop na MME 8
* **Regra Fundamental de Proteção:** O trailing stop na MME 8 **SÓ PODE ATUAR NO LUCRO**.
  * Compra: encerra apenas se $(\text{Fechamento} < \text{MME}_8) \text{ E } (\text{Fechamento} > \text{precoEntrada})$.
  * Venda: encerra apenas se $(\text{Fechamento} > \text{MME}_8) \text{ E } (\text{Fechamento} < \text{precoEntrada})$.
* Essa regra impede que o ruído inicial da operação corte o trade em pequenas perdas artificiais antes do teste do stop técnico.

### 3.4 Trava de Lucro 2:1 (Blindagem de Capital)
* Quando o preço atinge $+2.0 R$ de lucro flutuante a favor:
  $$\text{Novo Stop Loss} = \text{precoEntrada} + (1.0 \times \text{Risco Inicial})$$
* Garante matematicamente $+1.0 R$ líquido no bolso se o mercado reverter violentamente.

---

## 🛡️ 4. Protocolo Rígido de Backtest e Simulação (Anti-Viés)

Qualquer código de backtest em Python neste repositório DEVE satisfazer as seguintes leis de auditoria:

### ⚠️ Regra 1: Proibição de Imunidade na Vela de Entrada (Intrabar SL)
* **O Erro Clássico:** Abrir a posição e executar `continue` para a próxima vela sem checar o Stop Loss da vela atual.
* **O Padrão Obrigatório:** Logo após marcar `in_pos = True` na barra `i`:
  ```python
  # OBRIGATÓRIO: Verificação imediata de Stop Loss na mesma barra
  if pos_dir == 1 and lows[i] <= sl_price:
      trades.append(FiboTrade(..., exit_reason="INTRABAR_STOP_LOSS", r_multiple=-1.0, win=False))
      in_pos = False
      active_leg = None
      continue
  elif pos_dir == -1 and highs[i] >= sl_price:
      trades.append(FiboTrade(..., exit_reason="INTRABAR_STOP_LOSS", r_multiple=-1.0, win=False))
      in_pos = False
      active_leg = None
      continue
  ```

### Regra 2: Simulação Realista de Ordem Limit e Custos
* A entrada ocorre exatamente no nível de retração de Fibonacci somando/subtraindo o spread da corretora.
* Spreads reais são aplicados em 100% das ordens (`data/` e tabelas de spreads oficiais).

### Regra 3: Validação Walk-Forward e Out-of-Sample
* Otimizações de parâmetros devem ser avaliadas em períodos *In-Sample* (ex: primeiros 12 meses) e validadas em períodos *Out-of-Sample* cegos (próximos 12 meses). Modelos com *Walk-Forward Efficiency* $< 0.70$ são rejeitados por sobre-ajuste (overfitting).

---

## 🌐 5. Padrões de Universalidade e Multi-Ativo

Para que o robô seja **agnóstico a ativo** e funcione com o mesmo código no Mini-Índice (`WIN`), Mini-Dólar (`WDO`), Ações (`PETR4`, `VALE3`) ou Criptomoedas:

### 5.1 Auto-Escala Dinâmica
* **Nunca utilize valores absolutos de pontos no código-fonte principal.**
* Toda verificação de amplitude mínima deve utilizar múltiplos do *Average Range* (tamanho médio das últimas 20 barras).

### 5.2 Filtros de Risco em Pontos nos Scripts NTSL
* Os parâmetros `MaxStopPontos` e `MinStopPontos` devem ter como padrão **`0.0` (desativado)**.
* Valores maiores que zero devem ser configurados pelo operador na interface gráfica do Profit de acordo com o ativo:
  * `WIN`: Stop Máx: 250 pts / Stop Mín: 50 pts
  * `WDO`: Stop Máx: 10 pts / Stop Mín: 3 pts
  * Ações / Outros: Manter `0.0` (universal automático)

---

## 🖥️ 6. Padrões Visuais no Nelogica Profit / Rico Trader

Para evitar que o Profit crie sub-janelas inferiores indesejadas e garantir máxima clareza gráfica:

1. **Inserção sobre os Preços:** O indicador deve ser inserido selecionando a janela principal de preços (clicando diretamente no candle) e não em "Nova Janela".
2. **Cores Padronizadas:**
   * **Linha 1 (Topo Considerado):** Ciano / Azul Claro (`clAqua`).
   * **Linha 2 (Fundo Considerado):** Magenta / Fúcsia (`clFuchsia`).
   * **Candle do BOS:** Amarelo (`clAmarelo`) para indicar o início da perna de retração.
   * **Posição Aberta:** Verde (`clVerde`) para compras e Vermelho (`clVermelho`) para vendas.
3. **Comportamento Dinâmico das Linhas:**
   * Em espera: mostram o topo e fundo institucionais ativos monitorados para rompimento.
   * No rompimento / operação: travam nos limites exatos da pernada impulsiva de referência do Fibonacci.

---

## 🚀 7. Guia Rápido de Comandos para Desenvolvedores e Agentes

Todos os comandos devem ser executados a partir da raiz do projeto (`D:\thiago\Projetos\trading-smc-bot`) utilizando o `uv`:

```powershell
# 1. Executar Backtest Oficial via CLI:
uv run smc fibo-backtest --symbol all

# 2. Executar a Grade Completa de Recalibração de Variáveis Auditada:
uv run python scripts/recalibrate_all_variables_audited.py

# 3. Testar Variações Específicas de Stop Loss:
uv run python scripts/test_stop_variations_audited.py

# 4. Iniciar o Painel de Controle e Visualização (Dashboard UI):
uv run smc ui --port 8080

# 5. Verificar Integridade e Sintaxe do Motor Python:
uv run python -c "from smc_trader.strategies.fibo_ote import FiboOTEStrategy; print('OK')"
```

---

## 📜 8. Glossário de Termos do Projeto

* **BOS (Break of Structure):** Quebra de topo ou fundo que confirma a continuidade direcional do fluxo institucional.
* **OTE (Optimal Trade Entry):** Região de desconto profundo da ferramenta de Fibonacci (entre 61.8% e 79.0%).
* **Sweet Spot (70.5%):** Nível médio entre 61.8% e 79.0%, considerado o ápice da assimetria risco:retorno.
* **Stop Estrutural (100.0%):** Posicionamento do stop loss na mínima absoluta (para compras) ou máxima absoluta (para vendas) da perna que originou o BOS.
* **R-Múltiplo ($R$):** Medida universal de lucro ou perda normalizada pelo risco inicial arriscado na operação ($1R = \text{risco inicial}$).
* **Profit Factor (PF):** Razão entre a soma de todos os ganhos e a soma de todas as perdas brutas ($\text{PF} = \frac{\sum \text{Gains}}{\sum \text{Losses}}$).

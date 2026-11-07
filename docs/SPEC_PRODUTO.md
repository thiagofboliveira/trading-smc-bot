# Spec do produto — SMC Trader

**Data:** 2026-11-07 · **Status:** proposta para validação · **Backlog:** [BACKLOG_PRODUTO.md](BACKLOG_PRODUTO.md)

## 1. Visão

**Produto principal: uma plataforma para o trader testar e acompanhar as próprias estratégias sem se enganar.** O usuário traz a estratégia (do catálogo ou escrita por ele), e a plataforma entrega:

1. **Backtest confiável:** sem viés, provado por teste, e reproduzível.
2. **Sinais semiautomáticos via Telegram:** o sistema detecta o setup da estratégia **do usuário**, manda a imagem com entrada, stop e alvo, e ele decide se entra.
3. **Painel gamificado "o escritório":** cada estratégia configurada é um funcionário numa mesa, e um telão mostra o resultado da empresa desde o dia 0.

O diferencial não é ter a melhor estratégia, e sim **ser honesto**: separar backtest, paper e live, mostrar o viés antes de o usuário perder dinheiro, e transformar disciplina em jogo.

**Complemento opcional: sinais próprios.** Se a trilha de pesquisa encontrar uma estratégia com vantagem comprovada em operação real, ela pode ser oferecida como um "funcionário pronto" dentro da plataforma (seção 9.2). O produto principal não depende disso.

O primeiro usuário é você, que também valida a plataforma usando as suas estratégias.

## 2. Princípios (valem para todas as entregas)

| # | Princípio | Consequência prática |
|---|---|---|
| P1 | **A estratégia existe em um lugar só** | Backtest, paper, Telegram e MT5 chamam o mesmo núcleo. Não há reimplementação em outra linguagem no caminho crítico. NTSL e EA ficam fora do produto, como experimentais. |
| P2 | **Sem viés, provado por teste** | Todo motor e toda estratégia passam pelo teste de invariância de prefixo e pelos cenários anti-viés. Um teste vermelho bloqueia a entrega. |
| P3 | **Todo número tem origem** | Cada resultado carrega a fonte (`backtest`, `paper` ou `live`), o período, o hash dos dados e da configuração e o commit. As fontes nunca são somadas entre si. |
| P4 | **Humano no comando** | O sistema sugere e você confirma. Execução automática total só por decisão explícita e por estratégia. |
| P5 | **Fail-closed** | Na dúvida (dado atrasado, spread anormal, limite diário, erro de corretora), o sistema não opera e avisa. |
| P6 | **Honestidade na gamificação** | O jogo nunca esconde perda nem embeleza resultado. Um funcionário que perde dinheiro aparece perdendo. |

## 3. Glossário

| Termo | Significado |
|---|---|
| **Usuário** | Quem usa a plataforma: traz estratégias, recebe sinais e decide. Na versão inicial é você. |
| **Estratégia** | O código da lógica (ex.: SMC Fibo OTE). Pode vir do catálogo ou ser escrita pelo usuário (seção 5.7). |
| **Catálogo** | Estratégias prontas e parametrizáveis que acompanham a plataforma, usadas sem programar. |
| **Funcionário** | Uma estratégia configurada: estratégia + parâmetros + ativo + timeframe + capital virtual. É a unidade que aparece no escritório. Ex.: "Fibo Trailing · XAUUSD · M5". |
| **Estágio** | Fase de vida do funcionário (seção 6.1): candidato, em experiência, contratado, afastado, desligado. |
| **Sinal** | Um setup detectado: direção, entrada, stop, alvo e validade. |
| **Decisão** | Sua resposta ao sinal: entrar, ignorar ou deixar expirar. |
| **Empresa** | O conjunto dos funcionários. O resultado dela é a soma dos funcionários em experiência e contratados. |
| **Dia 0** | A data em que a empresa começou a operar em paper. O telão conta a partir dela. |
| **R** | Resultado em múltiplos do risco inicial do trade. |

## 4. Arquitetura

```
              ┌──────────────── núcleo (puro, sem I/O) ────────────────┐
 candles ───▶ │ Strategy.evaluate(janela) → intenções                   │
              │ (armar limite, cancelar, mover stop, encerrar)          │
              └─────────────────────────────────────────────────────────┘
                     │                   │                     │
             ┌───────▼──────┐   ┌────────▼────────┐   ┌────────▼────────┐
             │ SimBroker    │   │ PaperBroker     │   │ MT5Broker       │
             │ (backtest)   │   │ (tempo real,    │   │ (execução real, │
             │              │   │  fills simulados)│   │  após confirmar)│
             └───────┬──────┘   └────────┬────────┘   └────────┬────────┘
                     └─────────── store (SQLite) ──────────────┘
                                         │
                   ┌─────────────────────┼──────────────────────┐
             relatórios          bot Telegram              API + escritório (web)
```

### 4.1 Núcleo da estratégia

- Interface única: recebe a janela de candles **fechados** e o estado da posição e devolve **intenções**, sem preço de execução.
- Quem transforma intenção em execução é o broker. O `SimBroker` concentra as regras de realismo de hoje: spread bid/ask nos dois lados, stop antes de alvo na mesma barra, gap preenchido no open, comissão e slippage.
- O `FiboOTEStrategy` atual é o primeiro a ser adaptado. O critério de aceite é produzir **exatamente os mesmos trades** do motor atual nos dados locais.

### 4.2 Dados

O que já existe: Dukascopy, importação do MT5 e do Profit, checagem de qualidade e série contínua de WIN/WDO.

Em tempo real, os candles vêm do MT5 (conta demo ou real da corretora). O Profit não tem API para isso, então WIN e WDO em tempo real dependem de uma corretora B3 com MT5.

### 4.3 Store

SQLite para um usuário. Postgres só quando for multiusuário. Tabelas principais:

| Tabela | Campos-chave |
|---|---|
| `strategy` | código, versão, hash do código |
| `employee` | estratégia, parâmetros, ativo, timeframe, capital virtual, estágio, nome, avatar, criado em |
| `signal` | funcionário, horário, direção, entrada, stop, alvo, validade, status, imagem |
| `decision` | sinal, usuário, ação, horário |
| `trade` | funcionário, fonte (backtest/paper/live), entrada, saída, R, PnL, motivo de saída |
| `equity` | funcionário, fonte, horário, patrimônio |
| `run` | relatório de backtest: período, hash dos dados, hash da config, commit, métricas |

### 4.4 Tecnologia

| Parte | Escolha | Por quê |
|---|---|---|
| Backtest e núcleo | código atual (Python) | É a parte mais testada; congelada, só recebe correção de bug. |
| API | FastAPI | Substitui o `http.server` atual; tem tipagem e WebSocket. |
| Telegram | `python-telegram-bot` | Botões inline, envio de imagem, comandos. |
| Gráfico do sinal | `mplfinance` (PNG) | Candles com faixas de entrada, stop e alvo. |
| Escritório | PixiJS (cena 2D em canvas) + HTML para popups e relatório | Sprites clicáveis, animação leve, sem engine de jogo pesada. |
| Gráficos do relatório | Plotly (já é dependência) | Interativo e reaproveita o código atual. |
| Execução | pacote oficial `MetaTrader5` | Substitui a ponte HTTP com EA, que não recebe candles nem posições. |

## 5. Funcionalidades

### 5.1 Backtest 100% funcional

"Funcional" significa todos os critérios abaixo verdes:

1. Invariância de prefixo e cenários anti-viés verdes para cada estratégia registrada.
2. Custos por contrato (spread, comissão, slippage) vêm de uma única tabela. Hoje há duas.
3. A checagem de qualidade dos dados roda antes de todo backtest; erro bloqueia.
4. O relatório traz IS e OOS separados, walk-forward, Monte Carlo do drawdown (p95), comparação com baseline aleatório e alarmes de sanidade.
5. O relatório registra hash dos dados, da config e o commit, e roda de novo com o mesmo resultado.
6. A suíte completa roda na CI.

### 5.2 Registro de funcionários

- **Um único arquivo de configuração por funcionário**, lido por todos os modos. Acaba a divergência atual entre `production.yaml`, `config/models/*.yaml` e a spec do NTSL.
- **Comandos de CLI:** `smc employee add|list|promote|suspend`.

### 5.3 Sinais em paper

- Um serviço acorda a cada barra fechada, roda o núcleo para cada funcionário em experiência ou contratado e grava os sinais.
- O `PaperBroker` simula os fills com as mesmas regras do `SimBroker`, sobre os candles reais que chegam depois.
- É daqui que sai o histórico a partir do dia 0.

### 5.4 Alertas no Telegram

**Mensagem de sinal:**
- **Imagem:** os últimos ~60 candles, com a perna, a faixa de entrada, a linha de stop (vermelha) e a de alvo (verde).
- **Texto:**
  - funcionário, ativo e direção;
  - entrada, stop, alvo, risco em pontos e em moeda, e R:R;
  - **validade** ("vale até 14:35 UTC ou até a perna expirar");
  - estágio e resultado recente do funcionário em paper.
- **Botões:** `Entrar`, `Ignorar` e `Detalhes`, este último com link para o relatório.

**Regras:**
- Só IDs de usuário autorizados podem decidir.
- Um clique repetido não gera duas ordens.
- Um sinal expirado não aceita mais `Entrar`.
- Toda decisão fica gravada.

**Relatórios:**
- **Diário**, no fechamento: resultado do dia por funcionário e da empresa.
- **Semanal:** curva de patrimônio e ranking dos funcionários.

**Comandos:** `/status`, `/hoje`, `/funcionarios` e `/pausar <funcionário>`.

### 5.5 Execução com confirmação (MT5)

- `Entrar` no Telegram vira uma ordem limite no MT5, com stop e alvo, usando o sizing pelo risco.
- O kill switch, os limites diários e a reconciliação após reinício têm estado persistido.
- Se a ordem não for executada dentro da validade, ela é cancelada e você é avisado.

### 5.6 O escritório (gamificação)

**A cena:**
- Um escritório em 2D com estilo próprio, com assets CC0 ou feitos para o projeto, sem copiar o visual de nenhum jogo existente.
- **Telão na parede:**
  - retorno da empresa desde o dia 0, em % e em moeda;
  - curva de patrimônio;
  - drawdown atual;
  - resultado de hoje;
  - um selo com a fonte (`PAPER` ou `LIVE`).
  - O backtest **nunca** aparece no telão, porque mostrá-lo como se fosse resultado da empresa violaria P3 e P6.
- **Mesas:** uma por funcionário. O personagem mostra o estado:
  - trabalhando: tem posição ou ordem armada;
  - esperando: sem setup;
  - comemorando: acabou de fechar um ganho;
  - abatido: fechou uma perda ou está em drawdown;
  - dormindo: mercado fechado;
  - afastado: kill switch ou pausa.
- **Balão sobre o personagem:** resultado de hoje e acumulado, na cor do sinal (verde ou vermelho), e um ícone se há sinal pendente.
- **Clique no personagem:** abre o relatório do funcionário:
  - curva de patrimônio e métricas, separadas por fonte;
  - lista de trades, últimos sinais e suas decisões;
  - o backtest, apresentado como o **currículo** dele.

**Ciclo de vida como carreira (6.1):**

| Estágio | Fonte do resultado | Como entra | Como sai |
|---|---|---|---|
| Candidato | backtest | é cadastrado | passa nos critérios de promoção do backtest (OOS, walk-forward, mínimo de trades) |
| Em experiência | paper | é promovido | após N semanas e M trades em paper, com métricas compatíveis com o backtest |
| Contratado | live (com confirmação) | é promovido por você | kill switch, drawdown acima do limite ou decisão sua |
| Afastado | — | kill switch ou pausa | é reativado por você |
| Desligado | — | reprovado ou desligado | fica no arquivo morto com o histórico |

Promoção para "em experiência" é automática se os critérios forem atendidos. Promoção para "contratado" é sempre manual.

**Capital:** cada funcionário recebe um capital virtual. O patrimônio da empresa é a soma dos funcionários em experiência e contratados, e o retorno do telão é calculado sobre o capital total alocado no dia 0, mais os aportes registrados.

**Atualização:** o servidor empurra eventos (sinal, fill, saída) por WebSocket, e a cena reage sem recarregar.

### 5.7 Estratégias do usuário

Esta é a peça que torna a plataforma um produto: o usuário não fica preso às estratégias do autor.

| Forma | Para quem | Como funciona |
|---|---|---|
| **Catálogo** | quem não programa | Estratégias prontas e parametrizáveis: SMC Fibo OTE, rompimento, médias móveis, seguimento de tendência. O usuário escolhe ativo, timeframe e parâmetros num formulário ou YAML. |
| **Plugin Python (SDK)** | quem programa | Uma classe que implementa a interface `Strategy` da seção 4.1. O SDK traz os testes anti-viés prontos: o usuário roda `smc strategy check minha_estrategia` e descobre se ela usa dado futuro antes de qualquer backtest. |
| **Construtor visual** | futuro | Montar regras por blocos. Só depois que o catálogo e o SDK estiverem estáveis. |

**Regras para qualquer estratégia do usuário:**
- Ela só vira funcionário se passar no `strategy check`: invariância de prefixo e cenários anti-viés.
- Ela não executa ordens diretamente. Devolve intenções, e o broker aplica custos e regras de realismo; não há como "pular" o spread.
- O resultado dela segue as mesmas regras de fonte e de promoção de qualquer outro funcionário.

**Segurança:** código de terceiros é risco. Enquanto a plataforma for instalada pelo próprio usuário (seção 9.1), o plugin roda na máquina dele. Numa versão hospedada, plugins só rodam em sandbox isolada, ou essa versão aceita apenas o catálogo.

## 6. Requisitos não funcionais

- **Tempo:** tudo em UTC internamente. A exibição usa o fuso do usuário (America/Sao_Paulo por padrão).
- **Segredos:** credenciais só por variável de ambiente ou cofre, nunca no repositório. Os segredos que já vazaram precisam ser trocados.
- **Logs:** cada sinal, decisão, ordem e fill fica num journal consultável.
- **Testes:** o núcleo e o `SimBroker` exigem cobertura anti-viés. O bot e a API, testes de contrato. A cena, um teste de fumaça que verifica que ela carrega com dados fictícios.
- **Desempenho:** o serviço de sinais avalia todos os funcionários em menos de 5 s após o fechamento da barra.

## 7. Fora de escopo (por enquanto)

- Execução automática sem confirmação.
- Versão hospedada multiusuário e app mobile nativo (o Telegram cumpre esse papel). A primeira distribuição é instalada pelo usuário (seção 9.1).
- NTSL e EA no caminho crítico (ficam como experimentais).
- Dados de tick ou de livro de ofertas.

## 8. Riscos

| Risco | Mitigação |
|---|---|
| Nenhuma estratégia própria ter vantagem real (é o caso hoje) | O produto principal não depende disso: o usuário traz as estratégias dele. A pesquisa segue como trilha paralela e só alimenta o complemento de sinais próprios. |
| Usuário confundir a ferramenta com promessa de lucro | A plataforma nunca recomenda operações por conta própria; os sinais são da estratégia do usuário. Termo de risco no primeiro uso. O backtest aparece sempre com o aviso de que não é resultado real. |
| Plugin malicioso ou com bug | Plugin roda na máquina do próprio usuário; na versão hospedada, só em sandbox ou só catálogo. Nenhuma estratégia acessa credenciais nem a corretora diretamente. |
| Paper divergir do backtest | O `PaperBroker` usa as mesmas regras do `SimBroker`. Um relatório semanal mede a divergência por funcionário. |
| Gamificação incentivar risco ("cassino gamificado") | Nada de "conquista" por lucro de curto prazo. As conquistas premiam disciplina: seguir os sinais, respeitar limites, cumprir a experiência. Limites diários e kill switch vêm ligados por padrão. |
| Sinal chegar tarde ao Telegram | A validade aparece na mensagem e a ordem nunca é enviada fora da validade. |

## 9. Caminho para produto

### 9.1 Plataforma (produto principal)

Pode ser oferecida assim que as entregas E0 a E5 estiverem estáveis e o catálogo e o SDK existirem. Não depende de você ter estratégia lucrativa.

| Fase | Distribuição | Por quê |
|---|---|---|
| 1 | **Instalada pelo usuário** (Docker ou instalador), com o MT5 e o bot de Telegram dele | Sem custódia de credenciais, sem rodar código de terceiros no seu servidor, custo de infraestrutura quase zero. Cobrança por licença. |
| 2 | **Hospedada (SaaS)**, com o catálogo apenas, ou plugins em sandbox | Mais fácil de vender, mas exige multiusuário, segurança e suporte. Só depois de a fase 1 ter usuários pagantes. |

Antes de cobrar:
- Consultar um advogado. Vender software de análise tende a ter risco regulatório menor que vender recomendações, mas o enquadramento precisa ser confirmado, principalmente se a plataforma trouxer estratégias prontas.
- Termo de uso e de risco, deixando claro que backtest não é promessa de resultado.
- Nunca guardar credenciais de corretora do usuário na versão hospedada.

### 9.2 Sinais próprios (complemento opcional)

Só existe se uma estratégia sua ficar **contratada por pelo menos 3 meses em live** com resultado compatível com o backtest. Nesse caso ela entra na plataforma como um "funcionário pronto" que o usuário pode contratar. Exige, além do item 9.1:
- Parecer jurídico específico sobre venda de sinais e recomendações (CVM).
- Resultados públicos só de live, com período completo, fonte e hash.
- Cada cliente executa na própria conta; nenhuma custódia.

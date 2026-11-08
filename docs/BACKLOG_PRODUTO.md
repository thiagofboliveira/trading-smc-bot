# Backlog do produto — SMC Trader

**Data:** 2026-11-07 · **Spec:** [SPEC_PRODUTO.md](SPEC_PRODUTO.md) · **Correções em aberto:** [REVISAO_IMPLEMENTACAO_BACKLOG.md](REVISAO_IMPLEMENTACAO_BACKLOG.md)

Cada entrega (E0 a E9) deixa algo utilizável e só depende das anteriores.

**Produto principal:** a plataforma, em que o usuário traz as próprias estratégias (E0 a E8). **Complemento opcional:** sinais próprios (E9), que só existem se a trilha de pesquisa (PQ) encontrar uma estratégia com vantagem comprovada em live. A PQ corre em paralelo a partir da E1.

**Tamanho:** P = até 1 dia · M = 2 a 4 dias · G = 1 a 2 semanas.

## Visão geral

| Entrega | Resultado utilizável | Depende de |
|---|---|---|
| E0 Fundação | repositório seguro, configuração única, CI completa | — |
| E1 Backtest 100% funcional | relatório confiável e reproduzível por funcionário | E0 |
| E2 Núcleo, SDK e funcionários | estratégia isolada, interface pública para estratégias do usuário, registro de funcionários e ciclo de vida | E1 |
| E3 Sinais em paper | serviço em tempo real gravando sinais e trades simulados; dia 0 | E2 |
| E4 Telegram | alertas com imagem, decisão por botão e relatórios | E3 |
| E5 Escritório v1 | telão, mesas, balões e relatório ao clicar | E3 (E4 opcional) |
| E6 Execução com confirmação | "Entrar" no Telegram vira ordem no MT5 | E4 |
| E7 Escritório v2 | animações, humor, conquistas de disciplina, eventos ao vivo | E5 |
| E8 Plataforma como produto | catálogo, SDK documentado, instalação pelo usuário, licença; depois versão hospedada | E5 (E6 recomendada) |
| E9 Sinais próprios (opcional) | sua estratégia oferecida como "funcionário pronto" | E8 + PQ aprovada + 3 meses em live |
| PQ Pesquisa | estratégia própria com vantagem fora da amostra | E1 (paralela) |

### Sequência e estimativa

```
E0 → E1 → E2 → E3 ─┬→ E4 ──→ E6 ─┐
                   └→ E5 ──→ E7 ─┴→ E8 → (E9, se houver estratégia aprovada)
          └──────── PQ (pesquisa, em paralelo desde a E1) ────────┘
```

Estimativas grosseiras (uma pessoa, com ajuda de agentes); variam muito com o ritmo.

| Entrega | Estimativa | Marco ao concluir |
|---|---|---|
| E0 | 3 a 5 dias | base limpa |
| E1 | 2 a 3 semanas | números do backtest confiáveis; a PQ pode começar |
| E2 | 2 a 3 semanas | estratégia num lugar só; SDK e `strategy check` |
| E3 | 1,5 a 2 semanas | **dia 0**: começa o histórico em paper |
| E4 | 1 a 1,5 semana | uso diário pelo celular |
| E5 | 3 a 4 semanas (pode correr junto com a E4) | o escritório; já dá para mostrar a outras pessoas |
| E6 | 2 a 3 semanas | ordem no MT5 testada em demo; dinheiro real depende da PQ |
| E7 | cerca de 2 semanas | escritório animado |
| E8 (fase 1) | 4 a 6 semanas | primeira versão vendável |

Até o sistema no celular (E0 a E4): cerca de 7 a 10 semanas.

---

## E0 — Fundação

**Objetivo:** parar de acumular dívida antes de construir em cima.

| ID | Item | Tam. | Critério de aceite |
|---|---|---|---|
| E0-1 | ~~Trocar a senha do MT5 demo~~ **Decidido (2026-11-07): mantida.** É conta de teste, sem dinheiro. Fica a regra: credencial de conta real nunca entra no repositório, só por variável de ambiente. | — | Decisão registrada. |
| E0-2 | Conferir quais pendências da revisão os commits `9193602` e `9124e8f` resolveram e atualizar o status em `REVISAO_IMPLEMENTACAO_BACKLOG.md` | P | Cada achado marcado como resolvido (com teste) ou aberto. |
| E0-3 | Uma única fonte de configuração de modelo: um loader lê `config/models/*.yaml` e alimenta backtest e live; `production.yaml` só referencia ids | M | Teste prova que backtest e live recebem o mesmo `FiboOTEConfig` para o mesmo id. |
| E0-4 | Uma única tabela de custos (spread, comissão, slippage) em `contracts`, usada pelos dois motores | P | `backtest.costs.spread_pips` removido; teste de config. |
| E0-5 | CI roda a suíte completa, `ruff` no repositório inteiro e `mypy` em `src/` (com baseline) | M | Pipeline verde; um teste vermelho bloqueia o merge. |
| E0-6 | NTSL e EA saem do caminho crítico: mover para `experimental/` com um README do status real | P | HANDOFF e README sem afirmações de "100% auditado" ou "paridade". |
| E0-7 | `production.yaml` sem símbolos ativos até existir funcionário aprovado | P | `smc live` recusa iniciar sem funcionário contratado. |

## E1 — Backtest 100% funcional

**Objetivo:** cumprir a definição da seção 5.1 da spec.

| ID | Item | Tam. | Critério de aceite |
|---|---|---|---|
| E1-1 | A checagem de qualidade dos dados é etapa obrigatória do backtest | P | Backtest falha com mensagem clara se `check-data` tiver erro. |
| E1-2 | Validar o importador do Profit com um arquivo real seu (colunas e rótulo do candle) e rodar WIN/WDO com série contínua | M | Teste com amostra anonimizada do arquivo real; primeira barra do pregão confere com o horário da B3. |
| E1-3 | Corrigir o motor de zonas: stop do short no ask, comissão por lote convertida em pontos, off-by-one dos breakers | M | Cada correção com teste que falhava antes. |
| E1-4 | Ligar Monte Carlo do drawdown, baseline aleatório (com entradas sorteadas, não troca de sinal) e alarmes de sanidade ao relatório | M | Relatório mostra DD p95, p-valor e alarmes; teste do alarme de payoff com métricas reais. |
| E1-5 | Corrigir métricas de portfólio: Sharpe em dias úteis, Sortino com downside deviation, drawdown com marcação a mercado | M | Testes com séries de resultado conhecido. |
| E1-6 | Relatório padrão por funcionário (HTML e JSON): IS, OOS, walk-forward, curva, trades, custos e hashes | G | O mesmo JSON alimenta depois o escritório e o Telegram; rodar duas vezes dá o mesmo hash. |
| E1-7 | Reprodutibilidade: hash do arquivo de dados real (não do recorte), da config e o commit | P | Teste com o caminho `{SYM}_M1_{source}.parquet`. |
| E1-8 | Teste de conformidade: portar a estratégia para uma biblioteca externa (vectorbt ou backtesting.py) e comparar os trades | M | Coincidência ≥ 95% de entradas; as diferenças são explicadas. Serve de segunda opinião sobre o motor. |

## E2 — Núcleo da estratégia e registro de funcionários

**Objetivo:** estratégia isolada (P1) e o conceito de funcionário com carreira.

| ID | Item | Tam. | Critério de aceite |
|---|---|---|---|
| E2-1 | Definir a interface `Strategy.evaluate(janela, posição) -> intenções` e os tipos de domínio | M | Documento curto e tipos em `src/smc_trader/core/`. |
| E2-2 | Extrair o `SimBroker` (regras de fill) do `fibo_ote.py` | G | Os trades nos 6 ativos locais são **idênticos** aos do motor atual (teste de regressão). |
| E2-3 | Adaptar o Fibo OTE à interface; o live passa a usar o mesmo caminho | M | Invariância de prefixo e cenários anti-viés verdes com o novo caminho. |
| E2-4 | Store SQLite com as tabelas da spec 4.3 e migrações | M | Testes de repositório; backup simples por arquivo. |
| E2-5 | CLI `smc employee add|list|show|promote|suspend|fire` | M | Funcionário criado a partir de um YAML de modelo, com estágio "candidato". |
| E2-6 | Critérios de promoção de candidato para "em experiência" (OOS, walk-forward, mínimo de trades, alarmes) configuráveis | P | Promoção recusada com o motivo exibido. |
| E2-7 | SDK: a interface `Strategy` vira pública e versionada; estratégias externas são carregadas de uma pasta de plugins | M | Uma estratégia de exemplo fora de `src/` roda no backtest sem alterar o código da plataforma. |
| E2-8 | `smc strategy check <estratégia>`: roda invariância de prefixo e cenários anti-viés em qualquer estratégia | M | Uma estratégia de exemplo que olha o fechamento futuro é reprovada com mensagem clara. Só estratégias aprovadas viram funcionário. |

## E3 — Sinais em paper (o dia 0)

**Objetivo:** histórico real, sem dinheiro, a partir de uma data.

| ID | Item | Tam. | Critério de aceite |
|---|---|---|---|
| E3-1 | Fonte de candles em tempo real via pacote `MetaTrader5` (demo), com detecção de atraso | M | Barra só é processada fechada; atraso acima do limite bloqueia e alerta. |
| E3-2 | Serviço `smc paper` que, a cada barra fechada, avalia todos os funcionários ativos e grava os sinais | M | Reinício não duplica sinal (idempotência por funcionário e barra). |
| E3-3 | `PaperBroker`: preenche ordens com as regras do `SimBroker` sobre os candles que chegam depois | M | Replay de um dia gravado bate com o backtest do mesmo dia. |
| E3-4 | Patrimônio por funcionário e da empresa; registrar o dia 0 e o capital virtual | P | `smc company status` mostra o retorno desde o dia 0. |
| E3-5 | Relatório semanal de divergência entre paper e backtest por funcionário | P | Alerta se a divergência passar de um limite configurável. |
| E3-6 | Rodar como serviço (systemd ou Docker), com reinício automático e journal | P | Instruções no README; teste de fumaça. |

## E4 — Telegram

**Objetivo:** você recebe o sinal com imagem e decide com um toque.

| ID | Item | Tam. | Critério de aceite |
|---|---|---|---|
| E4-1 | Bot com `python-telegram-bot`, token por variável de ambiente e lista de IDs autorizados | P | Mensagem de usuário não autorizado é ignorada e registrada. |
| E4-2 | Imagem do sinal (`mplfinance`): candles, perna, faixa de entrada, stop e alvo, com legenda | M | Teste gera o PNG a partir de um sinal fictício (snapshot). |
| E4-3 | Mensagem de sinal com texto (spec 5.4) e botões `Entrar`, `Ignorar` e `Detalhes` | M | A decisão é gravada; clique repetido não duplica. |
| E4-4 | Validade: o sinal expira, a mensagem é editada para "expirado" e o `Entrar` passa a ser recusado | P | Teste com relógio simulado. |
| E4-5 | Em paper, `Entrar` marca o trade como "seguido" para medir a sua disciplina contra o sistema | P | O relatório separa "sistema" de "seguido por você". |
| E4-6 | Relatório diário e semanal automáticos (texto e imagem da curva) | M | Enviados no horário configurado; conteúdo vem do JSON da E1-6. |
| E4-7 | Comandos `/status`, `/hoje`, `/funcionarios` e `/pausar` | P | Testes de contrato do bot. |

## E5 — Escritório v1

**Objetivo:** a tela da empresa, estática mas funcional.

| ID | Item | Tam. | Critério de aceite |
|---|---|---|---|
| E5-1 | API FastAPI (substitui o `http.server`): empresa, funcionários, trades, relatório | M | Endpoints documentados (OpenAPI); testes de contrato. |
| E5-2 | Direção de arte: paleta, mesa, personagem base e telão, com assets CC0 ou próprios | M | Folha de sprites versionada com a licença de cada asset. |
| E5-3 | Cena PixiJS: sala, telão e uma mesa por funcionário em grade automática | G | Cena carrega com 1 a 20 funcionários sem sobreposição; testada no celular. |
| E5-4 | Telão: retorno desde o dia 0 (% e moeda), curva, drawdown, resultado de hoje e selo `PAPER`/`LIVE` | M | Números iguais aos de `smc company status`; backtest nunca entra no telão. |
| E5-5 | Balão sobre cada personagem: resultado de hoje e acumulado, cor por sinal, ícone de sinal pendente | M | Atualiza a cada consulta (polling de 30 s nesta versão). |
| E5-6 | Clique no personagem abre o relatório do funcionário: curvas por fonte, métricas, trades, sinais e decisões, e o backtest como currículo | G | Reaproveita o JSON da E1-6; abas por fonte nunca somadas. |
| E5-7 | Estados visuais básicos: trabalhando, esperando, mercado fechado, afastado | P | Mapeados a partir do estado no store. |

## E6 — Execução com confirmação (MT5)

**Objetivo:** "Entrar" no Telegram vira ordem real, sempre com aprovação do usuário. A funcionalidade pode ser construída e testada em conta demo a qualquer momento. **Operar dinheiro real** com ela só é recomendado para funcionários que passaram pela experiência com resultado compatível com o backtest, e a plataforma avisa quando não for o caso.

| ID | Item | Tam. | Critério de aceite |
|---|---|---|---|
| E6-1 | `MT5Broker` com o pacote `MetaTrader5`: ordem limite com stop e alvo, modo de preenchimento do símbolo e horário do servidor convertido para UTC | G | Testes contra conta demo; ordem pendente respeita a validade. |
| E6-2 | `Entrar` no Telegram de um funcionário contratado envia a ordem; o resultado volta como mensagem | M | Idempotente por sinal; rejeição da corretora é avisada. |
| E6-3 | Kill switch e limites diários com estado persistido; reinício não zera o dia | M | Teste de reinício no meio do dia. |
| E6-4 | Reconciliação na partida: posições e ordens da corretora contra o store | M | Ordem órfã é cancelada ou adotada, com aviso. |
| E6-5 | Sizing por risco com `tick_value`, `tick_size` e lote mínimo reais | P | Ordem recusada se o lote mínimo passar do risco. |
| E6-6 | Relatório diário compara live, paper e backtest do mesmo funcionário | P | Divergência acima do limite afasta o funcionário automaticamente. |

## E7 — Escritório v2

**Objetivo:** dar vida à cena sem trair os números (P6).

| ID | Item | Tam. | Critério de aceite |
|---|---|---|---|
| E7-1 | Eventos em tempo real por WebSocket (sinal, fill, saída, promoção) | M | A cena reage em menos de 2 s. |
| E7-2 | Animações de humor: comemora no ganho, abatido na perda, inquieto com ordem armada, dorme fora do pregão | M | Humor deriva só do estado real; testes de mapeamento. |
| E7-3 | Carreira visível: crachá do estágio, cerimônia de promoção, mesa vazia quando desligado | M | Toda mudança de estágio gera evento e histórico. |
| E7-4 | Conquistas de disciplina (seguir sinais, respeitar limites, completar a experiência), nunca por lucro de curto prazo | P | Lista de conquistas revisada por você antes de entrar. |
| E7-5 | Linha do tempo da empresa (contratações, recordes, drawdowns) no telão | P | Dados vindos do journal. |

## E8 — Plataforma como produto

**Objetivo:** outra pessoa instala, traz as próprias estratégias e usa sem a sua ajuda. Não depende de você ter estratégia lucrativa.

**Fase 1: instalada pelo usuário**

| ID | Item | Tam. | Critério de aceite |
|---|---|---|---|
| E8-1 | Parecer jurídico sobre vender a plataforma (software de análise) e sobre trazer estratégias prontas no catálogo | — | Parecer por escrito antes de qualquer cobrança. |
| E8-2 | Catálogo inicial: SMC Fibo OTE, rompimento, cruzamento de médias e seguimento de tendência, todos parametrizáveis e aprovados no `strategy check` | G | Cada uma com relatório de exemplo e descrição honesta do resultado (inclusive negativo). |
| E8-3 | Configuração sem programar: escolher estratégia do catálogo, ativo, timeframe e parâmetros pela tela ou YAML | M | Um usuário cria um funcionário sem editar código. |
| E8-4 | Documentação do SDK com tutorial "escreva sua primeira estratégia" e exemplos de vieses comuns | M | Um desenvolvedor externo escreve e aprova uma estratégia seguindo só a documentação. |
| E8-5 | Instalação empacotada (Docker Compose ou instalador) e assistente de primeiro uso: dados, MT5, bot de Telegram, dia 0 | G | Instalação do zero em menos de 30 minutos numa máquina limpa. |
| E8-6 | Termo de uso e de risco no primeiro uso; avisos de "backtest não é resultado" em toda tela que mostra backtest | P | Revisado junto com o parecer da E8-1. |
| E8-7 | Licença e cobrança (chave de licença com validade), sem enviar dados do usuário para você | M | A plataforma funciona offline durante o período da licença. |
| E8-8 | Telemetria opcional e anônima (só com consentimento) para saber quais funcionalidades são usadas | P | Desligada por padrão. |

**Fase 2: versão hospedada** (só depois de a fase 1 ter usuários pagantes)

| ID | Item | Tam. | Critério de aceite |
|---|---|---|---|
| E8-9 | Multiusuário: autenticação, isolamento de dados e Postgres | G | Teste de isolamento entre contas. |
| E8-10 | Plugins só em sandbox isolada, ou versão hospedada só com o catálogo | G | Plugin não acessa rede, disco do servidor nem credenciais. |
| E8-11 | Conexão com a corretora fica na máquina do usuário (agente local) ou só sinais, sem guardar credenciais no servidor | G | Nenhuma credencial de corretora armazenada no servidor. |

## E9 — Sinais próprios (complemento opcional)

**Pré-requisito:** uma estratégia sua aprovada na PQ e contratada há pelo menos 3 meses em live, com resultado compatível com o backtest.

| ID | Item | Tam. | Critério de aceite |
|---|---|---|---|
| E9-1 | Parecer jurídico específico sobre venda de sinais e recomendações (CVM) | — | Parecer por escrito antes de oferecer. |
| E9-2 | A estratégia entra na plataforma como "funcionário pronto" que o usuário pode contratar | M | O usuário vê o histórico de live completo antes de contratar. |
| E9-3 | Página de resultados auditáveis: só live, período completo, fonte e hash | M | Nenhum número de backtest apresentado como resultado. |
| E9-4 | Cada cliente executa na própria conta | P | Nenhuma custódia nem credencial de cliente. |

---

## PQ — Trilha de pesquisa (paralela, a partir da E1)

**Objetivo:** encontrar pelo menos uma estratégia sua com vantagem fora da amostra. O produto principal não depende disso. A PQ alimenta o seu uso pessoal com dinheiro real e o complemento E9. Os controles da PQ-4 também viram estratégias do catálogo (E8-2).

| ID | Item | Tam. | Critério de aceite |
|---|---|---|---|
| PQ-1 | Protocolo de pesquisa por escrito: divisão IS/OOS fixa, walk-forward, número máximo de variantes testadas, correção para testes múltiplos | P | Documento aprovado por você antes de rodar a grade. |
| PQ-2 | Histórico longo (≥ 5 anos) dos ativos Dukascopy e, se possível, WIN/WDO | M | `smc fetch --years 5` concluído e checado. |
| PQ-3 | Testar os candidatos de [PESQUISA_ESTRATEGIAS_INTRADAY.md](PESQUISA_ESTRATEGIAS_INTRADAY.md) na ordem da seção 9: controles sobre o Fibo, filtros de custo, H3 (BOS como continuação), H1 (noise area + VWAP), H4 (ORB), H2/H5 | G | Cada candidato roda primeiro sem custo contra a entrada aleatória pareada; só os que superam o controle seguem para custos, walk-forward e holdout. |
| PQ-4 | Controles C0 (entrada aleatória pareada) e C1 (Fibo com níveis placebo) implementados como estratégias reutilizáveis | M | Todo relatório de candidato mostra a comparação com C0 e C1. |
| PQ-5 | Candidatos aprovados entram como funcionários "em experiência" | P | Critérios da E2-6 atendidos. |

## Ordem sugerida

1. **E0 e E1** primeiro, sem exceção.
2. **E2**, incluindo o SDK e o `strategy check`, enquanto a **PQ** começa.
3. **E3 → E4 → E5**: a parte visível do produto. Funciona mesmo com funcionários que perdem, e mostra isso de forma honesta.
4. **E6** construída e testada em demo. Dinheiro real só com funcionário que passou pela experiência.
5. **E7** quando a v1 estiver em uso diário.
6. **E8 fase 1** assim que você estiver usando a plataforma no dia a dia e o parecer jurídico sair. A fase 2 só com usuários pagantes.
7. **E9** apenas se a PQ aprovar uma estratégia e ela completar 3 meses em live.

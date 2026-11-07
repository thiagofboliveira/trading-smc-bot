# Revisão da implementação do backlog

**Data:** 2026-11-07 · **Escopo:** commits `8d22e19..ff8c294` (de `e62b98f` até `HEAD` em `feat/backtest-engine`), conferidos contra `docs/BACKLOG_CORRECOES.md`.
**Método:** leitura do código, suíte completa (`uv run pytest`: 604 passaram), reprodução dos bugs com casos mínimos e remedição dos modelos com os dados locais (6 ativos Dukascopy, mar a out/2026). Nenhum arquivo do projeto foi alterado por esta revisão.

## Veredito

**O backlog não está 100% concluído.** Pela contagem desta revisão, **29 dos 61 itens estão OK** (cerca de 48%). Os outros estão parciais, têm bug ou existem só como código que ninguém chama. A suíte passa porque vários testes confirmam o comportamento errado ou injetam à mão os dados que o código deveria produzir.

O que melhorou de verdade: o motor Fibo de backtest perdeu os vieses principais (F-01 a F-06), há teste de invariância de prefixo, e o motor de zonas não tem mais lookahead (Z-01 a Z-05, Z-08, Z-09).

O que é mais grave hoje:

1. **Os modelos de produção têm expectativa negativa** em todos os ativos, depois das correções, e `config/production.yaml` continua configurado para operá-los ao vivo.
2. **O modo live não abre nenhuma operação** com a janela de dados cheia, e na partida pode mandar ordens a mercado de sinais antigos.
3. **O NTSL canônico deixa a posição sem stop** depois da primeira barra.
4. **A senha da conta MT5 demo continua no GitHub** (commit `0d627c5` está em `origin/main` e `origin/feat/backtest-engine`).

## 1. Resultado dos modelos com o motor corrigido

`FiboOTEStrategy` com os parâmetros de `config/production.yaml` (pivot_k 3, MME 8) e o spread da seção `contracts`. Script: `scratchpad/remeasure.py`.

| Modelo | Trades | R total | R dos shorts |
|---|---|---|---|
| trailing (0,705 / 0,79) | 2154 | **−483,0** | −253,3 |
| blindado (0,705 / 0,79 / trava 2:1) | 2156 | **−478,7** | −249,6 |
| estrutural (0,705 / 1,0) | 2273 | **−270,7** | −151,8 |
| estrutural do YAML v3 (0,618 / 1,0 / k=2) | 2902 | **−303,1** | −163,7 |

Todos os 24 pares modelo × ativo são negativos. O backlog já registra isso na seção 1, mas:

- `config/production.yaml` chama esses três de "modelos canônicos" e liga o `trailing` em XAUUSD, NAS100, DAX40, BRENT, USDJPY etc.
- O `HANDOFF.md` descreve o sistema como "sem qualquer viés" e ensina a rodar `smc live --config config/production.yaml`.

**Recomendação:** marcar os modelos como reprovados no `production.yaml` (ou remover os símbolos) até existir um modelo com expectativa positiva fora da amostra.

## 2. Inconsistência entre as três definições de "modelo"

| Modelo | `config/production.yaml` (usado no live) | `config/models/*.yaml` v3 | `docs/SPEC_SMC_FIBO.md` / NTSL |
|---|---|---|---|
| estrutural | 0,705 / 1,0 / k=3 | 0,618 / 1,0 / k=2 | 0,705 |
| trailing | 0,705 / 0,79 / k=3 | 0,618 / 0,79 | 0,705 |
| blindado | 0,705 / 0,79 | 0,618 / 1,0 | 0,705 / 0,79 |
| zeragem | (não há) | `force_close_time: "21:30"` | 17:45 |

**Nenhum código lê `config/models/*.yaml`** para montar o `FiboOTEConfig`. Por isso `force_close_time`, `max_trades_per_day` e `max_stops_per_day` desses arquivos não têm efeito. O `smc fibo-backtest` só repassa `target_mode` (`cli.py:642`), então também ignora slippage e comissão.

## 3. Status por item

Legenda: OK · **P** = parcial · **B** = implementado com bug · **N** = não feito na prática.

| Grupo | OK | Parcial, com bug ou não feito |
|---|---|---|
| B0 (4) | B0-2, B0-3, B0-4 | B0-1 **P**: o live tem uma segunda implementação (`execution/fibo_live.py`) |
| F (11) | F-01 a F-06, F-09, F-11 | F-07 **B**, F-08 **P**, F-10 **P** |
| D (5) | D-03, D-04 | D-01 **P** (falta o teste com o arquivo real do Profit, combinado para o fim), D-02 **B**, D-05 **P** |
| Z (10) | Z-01 a Z-05, Z-08, Z-09 | Z-06 **P**, Z-07 **P**, Z-10 **P** |
| M (9) | M-01, M-02, M-04 | M-03 **P**, M-05 **P**, M-06 **N**, M-07 **P**, M-08 **P**, M-09 **P** |
| H (6) | H-02, H-05, H-06 | H-01 **P**, H-03 **P**, H-04 **P** |
| L (11) | L-03, L-04 | L-01 **P**, L-02 **B**, L-05 **N**, L-06 **N**, L-07 a L-11 **P** |
| N (5) | (nenhum) | N-01 **N**, N-02 a N-05 **P** |
| **Total** | **29** | **32** |

## 4. Bugs encontrados

### Críticos

| # | Onde | Bug | Cenário |
|---|---|---|---|
| 1 | `execution/fibo_live.py:115-125, 218, 239` | Índices posicionais (`last_sh_idx`, `bos_idx`) guardados entre chamadas numa janela deslizante. Com a janela cheia, toda barra nova recebe o mesmo índice. | Em produção (400 M1 ≈ 80 M5), `i > bos_idx` nunca fica verdadeiro e o live **nunca entra**. Num teste com 600 M1, o backtest fez 1 trade e o live, 0. |
| 2 | `execution/fibo_live.py:89-91` + `live_engine.py:189` | Na partida, o avaliador reprocessa a janela inteira como se não houvesse posição. | Uma perna de horas atrás vira `MARKET_ENTRY` no preço atual, com stop e alvo sem sentido. Pode sair mais de uma entrada no mesmo lote, com o mesmo `cmd_id`. |
| 3 | `nelogica/SMC_FIBO_CANONICO.ntsl:83-121, 176-185, 202-211` | Stop e alvo são enviados uma vez, junto com o `BuyLimit`, quando ainda não há posição, e nunca reenviados. No NTSL a ordem vale uma barra. | Posição perdedora fica sem stop até a zeragem das 17:45. A saída por MME exige lucro, então não protege. Fica pior que o script original. |
| 4 | `strategies/fibo_ote.py:381-385` (D-02) | Na barra de rolagem, o motor dá `continue` antes de gerenciar a posição aberta, e a série contínua não é ajustada (`data/continuous.py`). | A posição atravessa a rolagem e o PnL incorpora o salto entre vencimentos. Caso mínimo: **+381,7R** num trade com alvo de 3R. Também pula o teste de stop dessa barra. Os swings do contrato antigo ainda podem ser registrados depois do reset, porque a janela do fractal cruza a rolagem. |
| 5 | GitHub | `test.env` com senha no commit `0d627c5`, presente em `origin/main` e `origin/feat/backtest-engine`. `test.env.example` traz o login real. | Trocar a senha é o passo que resolve; reescrever o histórico vem depois. |

### Altos

| # | Onde | Bug |
|---|---|---|
| 6 | `strategies/fibo_ote.py:432-445` (F-07) | A expiração por tempo sai no **fechamento** da barra e pula o teste de stop dessa barra. Caso mínimo: a barra foi até abaixo do stop e fechou no alto; o trade saiu com **+6,0R** em vez de −1R. Deveria sair na abertura ou testar o stop antes. |
| 7 | `execution/fibo_live.py` (L-02) | Diverge do backtest: desempate de fractal `==max` (o backtest usa F-11), risco mínimo testado antes do toque (trava a expansão da perna), trailing e trava do short com outra série de preço, `trailing_only` com alvo, spread instantâneo em vez do de contrato. |
| 8 | `live_engine.py` / `fibo_live.py:276` (L-06) | Não existe ordem limite pendente no nível: a ordem sai depois que a barra fechou, sem expiração nem cancelamento. Pendentes não contam no limite de posições. |
| 9 | `cli.py:570` + `mql5/SMC_Bridge_EA.mq5` (L-01) | O modo bridge não recebe candles, posições nem deals. O equity é um valor fictício de 1000 e os dados do símbolo são padrões (bid 100, 2 casas). |
| 10 | `config.py:108`, `live_engine.py:140` (L-05) | Os limites diários ficam desligados (`LimitsConfig.enabled=False`) e `ProductionConfig` não tem seção para ligá-los. |
| 11 | NTSL canônico | A entrada fica uma barra atrasada: o `BuyLimit` sai depois do toque. A proteção `Fechamento > nivelStop` foi removida, então entra em setup já invalidado. A perna é descartada mesmo quando a ordem não executa. Faltam os filtros de perna mínima e risco mínimo. |
| 12 | `backtest/robustness.py`, `backtest/portfolio.py` (M-05, M-06, M-08) | Monte Carlo, baseline, Bonferroni, alarmes e portfólio não são chamados por nenhum relatório, CLI ou script. O HANDOFF diz que estão ativos. |

### Médios

- `live_engine.py:288-290`: o filtro de spread do kill switch compara o spread atual com ele mesmo, então nunca dispara.
- `kill_switch.py`: o estado fica só em memória, e um reinício zera a perda do dia. `check_consecutive_losses` nunca é chamado.
- `mt5_interface.py:478-488`: o comando que dá timeout continua na fila e é executado depois, sem deduplicação de `cmd_id`.
- `mt5_interface.py:699, 818, 849` (plausível): horários do servidor MT5 rotulados como UTC.
- `robustness.py:92-94`: o alarme de payoff lê chaves que `calculate_metrics` não devolve, então dispara sempre que o acerto passa de 65%. O teste injeta as chaves à mão.
- `runner.py:104-109`: o off-by-one de `compute_breaker_stats` continua, e `test_grid.py` fixa o comportamento errado.
- `backtest/engine.py:188, 337`: o motor de zonas testa o stop do short no bid (equivalente do F-02).
- `portfolio.py:271-283`: o Sharpe anualiza com √252 sobre dias corridos, o Sortino está errado e o drawdown ignora as posições abertas.
- `backtest/engine.py:582-584`: a comissão por lote é subtraída como pontos de preço.
- Os YAML `smc_fibo_agressivo`, `equilibrado` e `ote`, e o cabeçalho dos NTSL originais, ainda citam métricas do motor enviesado. O canônico diz "100% auditada e em paridade com Python".

### Baixos

- `strategies/fibo_ote.py:25-27`: o docstring diz que F-05 a F-10 não foram tratados, mas foram.
- `fibo_ote.py:582`: uma perna com risco pequeno demais fica marcada como tocada e bloqueia novos BOS até expirar.
- PF infinito vira `Infinity` no JSON. O hash do parquet (M-09) aponta para o arquivo errado. `scripts/exp_stop_variations_audited.py:86` chama uma função que não existe.

## 5. Testes e CI

- **CI** (`.github/workflows/ci.yml`): roda só 4 arquivos de teste, não roda mypy (109 erros em `src/`) e o `ruff check` cobre só `src/`. O repositório inteiro tem 255 erros de lint, e o HANDOFF diz "0 erros".
- **Paridade NTSL** (`tests/test_ntsl_parity.py`): não lê nem executa o `.ntsl`. Dois dos três testes calculam a mesma coisa dos dois lados. A paridade não está provada.
- **Replay live** (`tests/test_live_replay.py`): um único cenário curto, com tolerância maior que o spread. Não pega os bugs 1, 2 e 7.
- **Testes que confirmam o erro:** `test_compute_breaker_stats` (off-by-one), `test_z06` (comissão em pontos), `test_robustness.py:44` (payoff) e `test_z09` (monta à mão o índice que deveria testar).

## 6. Ordem sugerida de correção

1. **Agora, fora do código:** trocar a senha da conta MT5 demo e tirar o login real de `test.env.example`.
2. **Bloquear produção:** desligar os símbolos em `production.yaml` e corrigir o HANDOFF para dizer que não há modelo aprovado.
3. **Motor Fibo** (bugs 4 e 6): fechar a posição na rolagem e testar o stop antes da expiração. Escrever primeiro os testes dos dois casos mínimos desta revisão.
4. **Live:** trocar `FiboLiveEvaluator` por chamadas ao mesmo motor do backtest (o B0-1 de fato), com índices por timestamp. O replay deve comparar a janela deslizante cheia contra o backtest.
5. **NTSL:** reenviar stop e alvo a cada barra enquanto houver posição, e manter o `BuyLimit` armado enquanto a perna estiver ativa. Só depois, o protocolo de validação de `docs/REVISAO_NTSL.md`.
6. **Validação:** ligar Monte Carlo, baseline e alarmes ao relatório de backtest, e rodar a suíte completa na CI.
7. **Pesquisa:** com o simulador confiável, procurar um modelo com expectativa positiva fora da amostra. Os atuais não têm.

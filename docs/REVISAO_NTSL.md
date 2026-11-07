# Revisão dos modelos NTSL (Rico Trader / Profit)

**Data:** 2026-11-07 · **Escopo:** os 4 scripts existentes em `nelogica/` (`SMC_FIBO_ESTRUTURAL`, `SMC_FIBO_SWEETSPOT`, `SMC_FIBO_BLINDADO`, `SMC_FIBO_TRAILING`). Nenhum modelo novo foi criado e nenhum script foi alterado.
**Método:** leitura linha a linha dos 4 scripts e comparação com os YAML v3 em `config/models/`. Os `.txt` são idênticos aos `.ntsl` (verificado com `diff`).

## Veredito

**Os scripts não podem ser declarados 100% confiáveis.** Há 4 problemas críticos que dependem de como o Profit executa as ordens, e isso não dá para verificar daqui: não há Profit nesta máquina, então nada foi compilado nem executado. O que a revisão prova é o que o código faz; o que ele faz na plataforma real precisa do protocolo da seção 4.

Os 4 scripts são o mesmo programa com parâmetros diferentes (Blindado acrescenta a trava 2:1). Todos os achados valem para os quatro, salvo indicação.

## 1. Achados

### Críticos

| ID | Achado | Por que importa |
|---|---|---|
| C1 | **Preço de entrada fictício.** `BuyAtMarket` / `SellShortAtMarket` executam no preço corrente, mas `precoEntrada := nivelEntrada` grava o nível teórico do Fibonacci. | O risco inicial (Blindado), a trava +2R e o filtro `Fechamento > precoEntrada` da saída por MME usam um preço que não foi o executado. O resultado real pode ficar bem longe do que o script "acha" que está fazendo. |
| C2 | **Entrada na mesma barra do BOS.** O bloco de entrada roda na mesma execução em que o BOS é detectado, com `Minima <= nivelEntrada`. | A ordem sai a mercado no preço corrente (perto do topo da perna), não no nível de retração. Semântica diferente da do Python e sem relação com o resultado que ele reporta. Como se comporta depende de o script rodar no fechamento da barra ou a cada tick (não verificável daqui). |
| C3 | **O stop não é uma ordem.** É `Se (Minima <= precoStop) Entao ClosePosition`, avaliado pelo script. | Sem ordem na bolsa, uma queda de conexão ou travamento do Profit deixa a posição sem proteção. Mesmo conectado, a saída é a mercado depois do gatilho, com a perda acima de 1R em movimento rápido. |
| C4 | **Estado dessincronizado.** `emOperacao` é gravado na mesma linha em que a ordem é enviada, sem confirmar a execução. | Ordem rejeitada ou não executada deixa `emOperacao = ±1` sem posição, e o script não entra de novo até um stop, alvo ou cruzamento "limpar" o estado. O inverso também vale: posição zerada à mão não reseta o estado. |

### Altos

| ID | Achado |
|---|---|
| A1 | **Sem horário nem limites diários.** Não há horário limite de entrada, zeragem de fim de pregão, máximo de trades ou de stops por dia. Os YAML v3 pedem `force_close_time`, `max_trades_per_day: 5` e `max_stops_per_day: 2`. |
| A2 | **A perna nunca expira.** `pernadaAltaAtiva` fica ligada até um novo BOS ou uma entrada, inclusive de um dia para o outro; o Python expira em 60 candles. Uma perna de ontem pode disparar entrada hoje. |
| A3 | **Fractal com a barra corrente.** `Maxima[2] > Maxima[0]` usa a barra ainda em formação. Em modo tick o fractal pode aparecer e sumir, e `ultimoTopo` / `ultimoFundo` ficam gravados mesmo que a condição deixe de valer. O comentário "sem repintura" só é verdadeiro se o script roda no fechamento da barra. |
| A4 | **Trava 2:1 (Blindado) no mesmo candle.** O stop sobe para +1R com a máxima da barra e é testado já na mesma execução com a `Minima` da barra inteira, que pode ter ocorrido antes da máxima. Sai em +1R indevidamente (mesmo viés do F-03 do Python). |
| A5 | **Regras diferentes das do Python**, então os resultados de um não validam os do outro (detalhe na seção 2). |
| A6 | **Parâmetros divergentes do YAML v3 no modelo `trailing`:** o script usa entrada em 0,705; o YAML v3 usa 0,618. Os outros três coincidem em entrada e stop. |

### Médios

- **M1.** O comentário do `SMC_FIBO_TRAILING.ntsl` diz "Condução 100% Livre pela MME 8", mas o código também sai no alvo (`Maxima >= precoAlvo`). Não é condução livre.
- **M2.** Nenhum script define lote ou risco por trade; isso depende da configuração do Profit. Os YAML pedem 1% de risco.
- **M3.** Os cabeçalhos ainda citam as métricas dos modelos antigos (ex.: "68.3% Win Rate | PF 1.48"), que vieram do simulador enviesado e já estão em `config/models/legacy_biased/`.
- **M4.** São 4 arquivos de ~250 linhas quase idênticos, mais 4 `.txt` iguais. Qualquer correção tem que ser repetida 4 vezes.
- **M5.** Não verifiquei as funções específicas do Profit (`Alert`, `PaintBar`, constantes `clAmarelo` / `clVerde`, `HasPosition`, `IsBought`). Os scripts já rodaram no seu Rico Trader, então compilam, mas não confirmei que fazem o que o nome sugere.

## 2. Divergências NTSL × Python (A5)

| Regra | NTSL | Python (`fibo_ote.py`) |
|---|---|---|
| Fractal | estrito (`>`), 2 barras de cada lado | `==` máximo da janela (empate conta) |
| Ordem dos swings no BOS | não checa | exige topo mais recente que fundo (alta) |
| BOS | exige cruzamento (`Fechamento[1] <= ultimoTopo`) | basta `close > topo` |
| Filtro de perna | amplitude ≥ 1,5 × range médio de 20 barras | amplitude > 10 × spread |
| Execução da entrada | a mercado, no preço corrente | no nível de retração |
| Expiração da perna | nunca | 60 candles |
| Saída por MME | exige cruzamento de baixo para cima (`Fechamento[1] >= mme8[1]`) | qualquer fechamento do lado errado da MME, no lucro |
| Stop | `ClosePosition` por `Minima` | ordem implícita, preenchida no nível |
| Horário e limites | nenhum | nenhum no motor Fibo (só no YAML) |

A saída por MME merece destaque: como a entrada acontece após uma retração, o preço quase sempre já está abaixo da MME 8. No NTSL a saída só dispara depois que ele volta acima e cruza para baixo de novo, então haverá bem menos saídas por MME do que no Python.

## 3. Correções propostas (não aplicadas)

Ordenadas por impacto. As funções de ordem do Profit abaixo (`...Stop`, `...Limit`, preço médio da posição) são de memória e **precisam ser conferidas no manual NTSL da versão em uso** antes de escrever o código.

1. **C3:** enviar ordem de stop e ordem de alvo reais assim que a posição abrir, e movê-las (trava, MME) em vez de fechar a mercado.
2. **C1 e C2:** usar ordem limite no nível de retração, ou só armar a entrada a partir da barra seguinte à do BOS; gravar `precoEntrada` com o preço médio real da posição.
3. **C4:** a cada barra, se `emOperacao <> 0` e não há posição nem ordem pendente, zerar o estado.
4. **A4:** aplicar a trava só a partir da barra seguinte à que atingiu +2R.
5. **A2:** expirar a perna por número de barras e ao virar o dia.
6. **A1:** parâmetros de horário limite de entrada, horário de zeragem, máximo de trades e de stops por dia.
7. **A3:** calcular o fractal só com barras fechadas (deslocar um índice).
8. **A5 e A6:** alinhar com uma especificação única (item N-03 do backlog) e corrigir parâmetro, comentários e cabeçalhos (M1 e M3).
9. **M4:** consolidar os 4 scripts em um parametrizado e gerar os `.txt`.

**Por que não apliquei já:** (a) não consigo compilar nem rodar NTSL aqui, e uma edição de ordens sem teste num script que você já validou pode quebrá-lo ou, pior, mudar o comportamento sem aviso; (b) as correções 1 e 2 mudam a estratégia que foi validada (entrada e saída deixam de ser a mercado), então os resultados do Rico Trader deixam de valer e precisam ser refeitos.

## 4. Protocolo para tornar os scripts confiáveis

Nenhum item abaixo é possível sem o Profit; são o que falta para trocar "não verificado" por "verificado".

1. **Fixar e documentar o modo de cálculo** (a cada tick ou no fechamento da barra) e rodar o mesmo período nos dois modos. Se o resultado muda muito, o script depende de um comportamento que não está sob controle.
2. **Medir a diferença entre preço executado e `nivelEntrada`** em, no mínimo, 30 trades do backtest do Profit (em ticks e em R). Esse número quantifica o C1.
3. **Teste de paridade com o Python:** exportar a lista de operações de WIN e WDO e rodar o Python (depois das correções da sprint 1) sobre os mesmos dados. Meta: ≥ 95% de coincidência de horário e direção (item N-03).
4. **Testar o stop em conta simulada**, derrubando a conexão com posição aberta, para ver o que acontece com C3.
5. **Conta simulada por 2 a 4 semanas** antes de qualquer valor real, e depois 1 contrato.

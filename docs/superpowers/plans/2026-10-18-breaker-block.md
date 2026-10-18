# Breaker Block — Plano 1b

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detectar Breaker Blocks no M15 (OB/FVOB que falhou e foi rompido com imbalance), sem look-ahead, e exibi-los no gráfico.

**Architecture:** Um módulo novo `zones/breaker.py` com `build_breakers`, que consome as candidatas a OB (zonas sem filtros), os FVGs, os sweeps e os eventos. `analyze()` passa a devolver também `Analysis.breakers`, e o gráfico desenha breakers como retângulos tracejados. Nada do que já existe muda de comportamento.

**Tech Stack:** o mesmo do Plano 1 (Python 3.12, uv, pandas, pydantic, plotly, pytest).

**Spec:** `docs/superpowers/specs/2026-10-18-breaker-confluencia-design.md` (seção 1, Breaker Block), sobre o código da branch `feat/foundation`.

## Global Constraints

- **Sem look-ahead:** o breaker só vale a partir de `created_at` (fechamento do terceiro candle do FVG; sem a exigência de imbalance, fechamento do candle da quebra). O resultado em dados truncados no instante t deve ser igual ao da execução completa até t (com `end_time` só conhecido quando `t >= end_time`).
- Todo o detector roda sobre candles M15; horários UTC tz-aware.
- Compra e venda são espelhos exatos; cada comportamento tem teste espelhado.
- Origem do breaker = **candidatas a OB**: `build_zones` com `require_discount=False` e `require_imbalance=False`, independente dos filtros das zonas de entrada. O fim de vida da zona de origem não é condição.
- A quebra é o **primeiro** candle (com `open_time >= zone.created_at`) que **fecha estritamente além** do lado oposto da zona (origem de compra: `close < zone.low`; origem de venda: `close > zone.high`). Esse candle precisa ser o candle do meio de um FVG de direção oposta à da zona de origem (`start_time == index[j-1]`); sem busca por candles posteriores.
- Defaults de `ZoneConfig`: `breakers_enabled=True`, `breaker_require_imbalance=True`, `breaker_require_choch=False`, `breaker_max_age=96`.
- Cada commit termina com uma linha em branco e `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` (ou o modelo que escreveu o commit).
- Compatibilidade: nenhum teste existente muda de resultado; `Analysis(pivots, events, fvgs, sweeps, zones)` com 5 argumentos posicionais continua válido.

## Review Focus

1. **Quebra no último candle disponível:** com imbalance exigido e sem o candle `j+1`, não há breaker ainda (Task 2).
2. **Fechamento exatamente no limite da zona** não é quebra (comparação estrita) (Task 2).
3. **Frames vazios e listas vazias:** `build_breakers` e `analyze` devolvem listas vazias, sem exceção (Tasks 2 e 4).
4. **O candle de formação (o terceiro do FVG) pode tocar a zona** e isso **não** conta como mitigação: só candles com `open_time >= created_at` contam (Task 3).
5. **Origem filtrada fora de `zones`** (por desconto) ainda gera breaker, e `breakers_enabled=False` devolve lista vazia (Task 4).

---

## Mapa de arquivos

```
src/smc_trader/config.py              # + campos de breaker em ZoneConfig          (Task 1)
src/smc_trader/zones/orderblock.py    # Zone.kind ganha "BREAKER", docstring        (Task 1)
src/smc_trader/zones/breaker.py       # build_breakers                              (Tasks 2, 3)
src/smc_trader/analysis.py            # Analysis.breakers, analyze, docstring       (Task 4)
src/smc_trader/viz/chart.py           # retângulos tracejados dos breakers          (Task 5)
tests/helpers.py                      # constantes de séries do breaker             (Task 2)
tests/test_breaker.py, tests/test_analysis.py, tests/test_chart.py, tests/test_config.py
```

**Séries de teste.** Todas usam `SERIE_A_ROWS[0:6]` (candles 0 a 5, já em `tests/helpers.py`), que produz o BOS de alta no candle 5 e a zona de compra `[10, 12]` (candle do OB = posição 3, `created_at = close_time[5]`). Os candles seguintes ficam em `tests/helpers.py` (linhas `(open, high, low, close)`):

```
BREAKER_TAIL (6, 7, 8):          # quebra no candle 7 com FVG de baixa (6,7,8)
  6: (13.2, 14.0, 12.5, 12.8)
  7: (12.8, 12.9,  9.4,  9.5)
  8: ( 9.5, 10.0,  9.0,  9.2)

BREAKER_TAIL_NO_FVG (6, 7, 8):   # quebra no candle 7, sem FVG (high[8] > low[6])
  6: (13.2, 14.0, 12.5, 12.8)
  7: (12.8, 12.9,  9.4,  9.5)
  8: ( 9.5, 12.6,  9.0, 12.3)
```

Com `BREAKER_TAIL` (k=1, `ZoneConfig()`), as saídas dos detectores já conferidas à mão: um FVG de baixa `(10.0, 12.5)` com `start_time = index[6]` e `formed_at = close_time[8]`; um evento `CHoCH` de baixa em `close_time[7]` (nível 10); nenhum sweep; uma zona de origem de compra `[10, 12]`.

---

### Task 1: Configuração e contrato de `Zone`

**Files:**
- Modify: `src/smc_trader/config.py` (`ZoneConfig`), `src/smc_trader/zones/orderblock.py` (`Zone`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `ZoneConfig` ganha: `breakers_enabled: bool = True`, `breaker_require_imbalance: bool = True`, `breaker_require_choch: bool = False`, `breaker_max_age: int | None = Field(96, ge=1)`.
  - `Zone.kind: Literal["OB", "FVOB", "BREAKER"]`. A docstring de `Zone` passa a descrever as duas vidas: OB/FVOB (mitigada pelo toque ou invalidada por CHoCH contra) e BREAKER (termina no primeiro toque; `invalidated` se o candle do toque fecha além do lado de origem, senão `mitigated`).

- [ ] **Step 1: Escrever os testes que falham** em `tests/test_config.py`:
  - `test_breaker_defaults`: `ZoneConfig()` tem `breakers_enabled is True`, `breaker_require_imbalance is True`, `breaker_require_choch is False`, `breaker_max_age == 96`; `ZoneConfig(breaker_max_age=None).breaker_max_age is None`.
  - `test_breaker_max_age_must_be_positive`: `ZoneConfig(breaker_max_age=0)` levanta `ValidationError`.
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/test_config.py -v` → FAIL.
- [ ] **Step 3: Implementar** os campos e o `Literal` do `kind`, e reescrever a docstring de `Zone`. Não alterar comportamento de `build_zones`.
- [ ] **Step 4: Rodar a suíte inteira:** `uv run pytest -q` → todos PASS (72 anteriores + 2 novos).
- [ ] **Step 5: Commit** `feat: flags de breaker na configuração e kind BREAKER`.

---

### Task 2: Formação do breaker (`build_breakers`)

**Files:**
- Create: `src/smc_trader/zones/breaker.py`
- Modify: `tests/helpers.py` (acrescenta `BREAKER_TAIL` e `BREAKER_TAIL_NO_FVG` como listas de tuplas, valores acima)
- Test: `tests/test_breaker.py`

**Interfaces:**
- Consumes: `Zone` (Task 1), `StructureEvent`, `FVG`, `Sweep`, `ZoneConfig`, `in_discount` de `zones/premium_discount.py`.
- Produces: `build_breakers(candles: pd.DataFrame, zones: list[Zone], events: list[StructureEvent], fvgs: list[FVG], sweeps: list[Sweep], cfg: ZoneConfig) -> list[Zone]`. Cada zona de origem gera no máximo um breaker; resultado ordenado por `(created_at, candle_time)`.

Regras (posições são índices no frame de candles; `bos_pos` = posição do candle cujo `close_time == origem.created_at`; `n` = número de candles):
- **Quebra:** `j` = primeira posição `> bos_pos` com `close[j] < origem.low` (origem `long`) ou `close[j] > origem.high` (origem `short`). Sem `j` → sem breaker.
- **Idade:** se `cfg.breaker_max_age` não é `None` e `j - bos_pos > cfg.breaker_max_age` → sem breaker.
- **Imbalance:** exigido se `cfg.breaker_require_imbalance`. Procura um `FVG` com `direction == "down"` (origem `long`) ou `"up"` (origem `short`) e `start_time == index[j-1]` (exige `j >= 1`). Se `j + 1 >= n` o FVG ainda não pode existir → sem breaker. Sem FVG → sem breaker. `created_at = fvg.formed_at`. Com a flag desligada, `created_at = close_time[j]`.
- **CHoCH:** se `cfg.breaker_require_choch`, exige um evento `kind == "CHoCH"` com `direction == "down"` (origem `long`) ou `"up"` (origem `short`) e `origem.created_at < e.time <= created_at`.
- **Zona resultante:** `direction` invertida; `kind="BREAKER"`; `high`, `low`, `candle_time` copiados da origem; `end_time=None`, `end_reason=None` (a Task 3 preenche).
- **Perna da falha** (`last = j+1` se o imbalance é exigido, senão `j`; `c` = posição de `candle_time`): breaker de venda (origem `long`): `range_high = max(high[c..j])`, `range_low = min(low[j..last])`; breaker de compra (origem `short`): `range_low = min(low[c..j])`, `range_high = max(high[j..last])`.
- **`in_discount`** = `in_discount(nova_direção, low, high, range_low, range_high)` (informativo, não filtra).
- **`swept_liquidity`:** existe `Sweep` com `side == "high"` (breaker de venda) ou `"low"` (breaker de compra), `sweep_time >= origem.candle_time` e `confirmed_at <= created_at`.

- [ ] **Step 1: Escrever os testes que falham** em `tests/test_breaker.py`. Helper local `breakers_from(rows, cfg=None, k=1, events=None)`: monta `candles_from_ohlc(rows)`, roda `find_pivots` → `detect_structure` → `find_fvgs(candles, cfg.fvg_min_size)` → `find_sweeps`, constrói as candidatas com `build_zones(candles, events, fvgs, sweeps, cfg.model_copy(update={"require_discount": False, "require_imbalance": False}))` e chama `build_breakers` (com `events` substituído quando passado). Com `rows = SERIE_A_ROWS[0:6] + BREAKER_TAIL` e `ZoneConfig()`:
  - `test_failed_long_ob_becomes_short_breaker`: exatamente 1 breaker com `direction == "short"`, `kind == "BREAKER"`, `high == 12.0`, `low == 10.0`, `candle_time == index[3]`, `created_at == close_time[8]`, `range_high == 14.0`, `range_low == 9.0`, `in_discount is False`, `swept_liquidity is False`, `end_time is None`, `end_reason is None`.
  - `test_mirrored_failed_short_ob_becomes_long_breaker`: o `mirror` das mesmas linhas gera 1 breaker `long`, `high == 90.0`, `low == 88.0`, `range_low == 86.0`, `range_high == 91.0`, mesmo `candle_time` e `created_at`.
  - `test_no_imbalance_no_breaker`: com `SERIE_A_ROWS[0:6] + BREAKER_TAIL_NO_FVG` → lista vazia; com `breaker_require_imbalance=False` → 1 breaker com `created_at == close_time[7]` e `range_low == 9.4` (só o candle `j`).
  - `test_break_on_last_candle_waits_for_confirmation`: com `SERIE_A_ROWS[0:6] + BREAKER_TAIL[:2]` (sem o candle 8) → lista vazia.
  - `test_close_exactly_on_limit_is_not_a_break`: com `SERIE_A_ROWS[0:6] + BREAKER_TAIL_NO_FVG`, `breaker_require_imbalance=False`, e o candle 7 trocado por `(12.8, 12.9, 9.4, 10.0)` (fecha exatamente em `zone.low == 10.0`) → lista vazia (nenhum candle fecha abaixo de 10: o candle 8 fecha em 12.3); com o candle 7 em `(12.8, 12.9, 9.4, 9.9)` → 1 breaker.
  - `test_max_age`: `breaker_max_age=1` → vazio; `breaker_max_age=2` → 1 breaker; `breaker_max_age=None` → 1 breaker (a quebra está 2 candles depois do BOS: `j - bos_pos == 2`).
  - `test_require_choch`: com `breaker_require_choch=True` e os eventos reais da série → 1 breaker (o CHoCH de baixa em `close_time[7]` está na janela); com `events=[]` → vazio; com a flag desligada e `events=[]` → 1 breaker.
  - `test_empty_inputs`: `build_breakers` com frame de candles vazio, ou com `zones=[]`, devolve `[]` sem exceção.
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/test_breaker.py -v` → FAIL (módulo inexistente).
- [ ] **Step 3: Implementar `build_breakers`** em `zones/breaker.py`, uma única função com a direção como parâmetro das comparações (sem ramos de compra e venda copiados), mais helpers privados se necessário.
- [ ] **Step 4: Rodar e ver passar:** `uv run pytest tests/test_breaker.py -v` → PASS; depois `uv run pytest -q` → tudo PASS.
- [ ] **Step 5: Commit** `feat: formação de Breaker Block no M15`.

---

### Task 3: Vida do breaker

**Files:**
- Modify: `src/smc_trader/zones/breaker.py`
- Test: `tests/test_breaker.py`

**Interfaces:**
- Consumes: `build_breakers` da Task 2.
- Produces: `build_breakers` passa a preencher `end_time` e `end_reason`. Regra: considerando só candles com `open_time >= created_at`, o primeiro candle que toca a zona (breaker de venda: `high >= zone.low`; de compra: `low <= zone.high`) encerra o breaker, com `end_time = close_time` desse candle. `end_reason = "invalidated"` se esse mesmo candle fecha além do lado de origem (venda: `close > zone.high`; compra: `close < zone.low`), senão `"mitigated"`. Sem toque → ambos `None`. Não há expiração por idade depois de formado.

- [ ] **Step 1: Escrever os testes que falham** em `tests/test_breaker.py` (série base `SERIE_A_ROWS[0:6] + BREAKER_TAIL`, `created_at == close_time[8]`, mais um candle 9 por teste):
  - `test_mitigated_on_retest`: candle 9 `(9.2, 10.5, 9.1, 10.2)` → `end_reason == "mitigated"`, `end_time == close_time[9]`.
  - `test_invalidated_when_retest_candle_closes_beyond_origin_side`: candle 9 `(9.2, 12.6, 9.1, 12.4)` → `end_reason == "invalidated"`, `end_time == close_time[9]`.
  - `test_no_touch_keeps_breaker_open`: candle 9 `(9.2, 9.8, 9.0, 9.4)` → `end_time is None` e `end_reason is None`.
  - `test_formation_candle_touch_does_not_mitigate`: com só `BREAKER_TAIL` (o candle 8 tem `high == 10.0 >= zone.low` e é o candle de formação) → `end_time is None`.
  - `test_mirrored_lifetime`: o `mirror` da série com o candle 9 do primeiro teste → breaker `long`, `end_reason == "mitigated"`, `end_time == close_time[9]`.
  - `test_lifetime_without_imbalance_starts_at_candle_j_close`: com `BREAKER_TAIL_NO_FVG` e `breaker_require_imbalance=False` (`created_at == close_time[7]`), o candle 8 (`high 12.6`, `close 12.3 > 12`) toca e fecha além → `end_reason == "invalidated"`, `end_time == close_time[8]`.
- [ ] **Step 2: Rodar e ver falhar** → FAIL.
- [ ] **Step 3: Implementar** a vida em `build_breakers` (vetorizando sobre o trecho `candles[index >= created_at]`; um helper privado para o cálculo).
- [ ] **Step 4: Rodar e ver passar:** `uv run pytest tests/test_breaker.py -v` → PASS; `uv run pytest -q` → tudo PASS.
- [ ] **Step 5: Commit** `feat: vida do breaker (toque, mitigação e invalidação)`.

---

### Task 4: `analyze` com breakers e teste de não-antecipação

**Files:**
- Modify: `src/smc_trader/analysis.py`
- Test: `tests/test_analysis.py`

**Interfaces:**
- Consumes: `build_breakers` (Tasks 2 e 3), `build_zones`, `ZoneConfig`.
- Produces:
  - `Analysis` ganha o campo `breakers: list[Zone] = field(default_factory=list)` (último campo, com default, para manter a chamada posicional de 5 argumentos).
  - `analyze(candles, k, zones_cfg)` calcula as candidatas a OB com `zones_cfg.model_copy(update={"require_discount": False, "require_imbalance": False})`, e `breakers = build_breakers(candles, candidatas, events, fvgs, sweeps, zones_cfg)` quando `zones_cfg.breakers_enabled`, senão `[]`. `zones` continua sendo `build_zones(..., zones_cfg)` (filtrado). Frame vazio devolve `breakers=[]`.
  - A docstring do módulo ganha `breakers` no contrato de gating: por `created_at`, com fim por `end_time`.

- [ ] **Step 1: Escrever os testes que falham** em `tests/test_analysis.py`:
  - `test_breaker_end_to_end`: `analyze(candles_from_ohlc(SERIE_A_ROWS[0:6] + BREAKER_TAIL), 1, ZoneConfig())` → `len(zones) == 1`, `len(breakers) == 1`, o breaker `short`/`BREAKER` com `created_at == close_time[8]`; o OB de origem continua em `zones`.
  - `test_breaker_origin_filtered_out_of_zones_still_breaks`: linhas `0: (10,11,9,10.5)`, `1: (10.5,13,10,12.5)`, `2: (12.9,12.9,11.5,12.0)`, `3: (10.5,11.8,10,11.5)`, `4: (11.5,11.9,10.2,11.0)`, `5: (11,13.5,10.8,13.2)`, `6: (13.2,14,13.0,13.1)`, `7: (13.1,13.2,11.0,11.2)`, `8: (11.2,11.6,10.9,11.3)`. Com `ZoneConfig()`: `zones == []` (a candidata em `[11.5, 12.9]` está fora de desconto) e `len(breakers) == 1` com `direction == "short"`, `high == 12.9`, `low == 11.5`, `candle_time == index[2]`, `created_at == close_time[8]`.
  - `test_breakers_disabled`: a mesma série do primeiro teste com `ZoneConfig(breakers_enabled=False)` → `breakers == []`.
  - `test_empty_and_short_frames` (existente): acrescentar `breakers == []` nas asserções de frame vazio e de 3 candles.
  - `test_breakers_have_no_lookahead`: sobre `random_walk_candles(600, seed=…)`, `k=2`, cortes a cada 10 candles, mesma estrutura do teste de zonas: para cada corte `n`, os breakers do frame truncado devem ser iguais (campos: `direction, kind, high, low, candle_time, created_at, range_low, range_high, in_discount, swept_liquidity`) aos do frame completo com `created_at <= close_time[n-1]`, nos dois sentidos (listas iguais), e `end_time`/`end_reason` do truncado são `None` quando o `end_time` do completo é posterior a `close_time[n-1]`, e iguais caso contrário. O teste deve afirmar `len(full.breakers) >= 3`; se a semente/tamanho não gerarem 3 breakers com o `ZoneConfig()` padrão, aumentar o tamanho ou trocar a semente até gerar.
- [ ] **Step 2: Rodar e ver falhar** → FAIL.
- [ ] **Step 3: Implementar** a mudança em `analysis.py` (campo, `analyze`, docstring).
- [ ] **Step 4: Rodar e ver passar:** `uv run pytest tests/test_analysis.py -v` → PASS; `uv run pytest -q` → tudo PASS.
- [ ] **Step 5: Commit** `feat: analyze devolve breakers; teste de não-antecipação`.

---

### Task 5: Breakers no gráfico

**Files:**
- Modify: `src/smc_trader/viz/chart.py`
- Test: `tests/test_chart.py`

**Interfaces:**
- Consumes: `Analysis.breakers` (Task 4).
- Produces: `build_chart` desenha cada breaker como retângulo **tracejado** (`line.dash == "dash"`) de `created_at` até `end_time` (ou o último `close_time`), de `low` a `high`, com cor própria (âmbar para breaker de venda e violeta para o de compra, ambos distintos do verde/vermelho das zonas), e um rótulo `BB` (mais ` sweep` quando `swept_liquidity`). Os retângulos de breaker entram em `layout.shapes` junto com FVGs e zonas.

- [ ] **Step 1: Escrever os testes que falham** em `tests/test_chart.py`:
  - `test_breaker_rectangles_are_dashed`: com a análise de `SERIE_A_ROWS[0:6] + BREAKER_TAIL` (k=1): `len(fig.layout.shapes) == len(fvgs) + len(zones) + len(breakers)`; exatamente 1 shape com `line.dash == "dash"`; existe uma anotação cujo texto começa com `"BB"`.
  - `test_chart_without_breakers_unchanged`: com a análise do teste existente `test_build_chart_counts`, `len(fig.layout.shapes) == len(fvgs) + len(zones)` e nenhum shape tracejado.
- [ ] **Step 2: Rodar e ver falhar** → FAIL.
- [ ] **Step 3: Implementar** o desenho em `build_chart` (constantes de cor próximas às existentes, `layer="below"`, `xref/yref="x"/"y"`).
- [ ] **Step 4: Rodar e ver passar:** `uv run pytest tests/test_chart.py -v` → PASS; `uv run pytest -q` → tudo PASS.
- [ ] **Step 5: Verificação manual** (precisa dos dados baixados em `data/`): `uv run smc chart XAUUSD --tf M15 --from 2026-10-05 --to 2026-10-17 --out out/xauusd_bb.html` termina com código 0; contar os breakers com um script descartável (`analyze` sobre o mesmo período) e anotar o número no relatório da task. Este passo é do controlador, não do implementador.
- [ ] **Step 6: Commit** `feat: breakers tracejados no gráfico`.

---

## Autoavaliação

- **Cobertura da spec (seção 1):** origem sem filtros (Task 2 e 4), quebra com imbalance e candle do meio (Task 2), CHoCH opcional (Task 2), idade (Task 2), perna da falha sem look-ahead (Task 2), `swept_liquidity` (Task 2), vida (Task 3), `kind` e docstring de `Zone` (Task 1), `Analysis.breakers` e gating (Task 4), gráfico tracejado com `BB` (Task 5), testes espelhados e de não-antecipação (Tasks 2, 3 e 4). As seções 2 a 4 da spec (entradas, confluências, refinamento) ficam para o Plano 2.
- **Correção na spec:** a regra de vida do breaker foi reescrita (o desempate "mitigated antes de invalidated" tornava a invalidação impossível); a spec e este plano concordam.
- **Consistência de tipos:** `build_breakers` recebe as candidatas (`list[Zone]`) e devolve `list[Zone]` com `kind="BREAKER"`; `Analysis.breakers` usa o mesmo `Zone`; o gráfico lê os mesmos campos de `Zone` já usados para as zonas.

# Performance dos detectores — Plano 2a

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tornar `analyze()` rápido o bastante para meses de dados (meta: 12.000 candles M15 em menos de 1,5 s, contra 10,5 s hoje), **sem mudar nenhum resultado**.

**Architecture:** Primeiro congela-se o comportamento atual como oráculo: cópias literais das implementações de hoje em `tests/reference_impl.py` e testes que exigem igualdade exata contra elas, em dados aleatórios, com muitos empates e em dados reais. Depois otimizam-se as funções de `src/` (buscas por `searchsorted` e vetores numpy no lugar de varreduras lineares repetidas), com o oráculo como rede de segurança.

**Tech Stack:** o mesmo do projeto (Python 3.12, uv, pandas, numpy, pytest).

**Spec:** `docs/superpowers/specs/2026-10-18-breaker-confluencia-design.md` (ordem de execução: o Plano 2 começa pela performance) e `docs/superpowers/specs/2026-10-18-smc-day-trade-design.md`.

**Perfil de partida** (passeio aleatório, `scripts/bench.py` reproduz): em 12.000 candles M15 — `find_pivots` 0,32 s, `detect_structure` 0,45 s, `find_fvgs` 0,40 s, `find_sweeps` 0,09 s, `build_zones` 1,18 s, `build_breakers` 7,03 s, `analyze` 10,5 s. Em 30.000 candles M1 — `build_breakers` 60,9 s, `build_zones` 11,9 s. O custo vem de varreduras lineares repetidas por zona (`any()` sobre todos os FVGs e sweeps, cópia de DataFrame no ciclo de vida) e de laços Python com `iloc`.

## Global Constraints

- **Nenhum resultado muda.** Para toda entrada, as listas e DataFrames devolvidos pelas funções otimizadas são **exatamente iguais** (mesmos campos, mesma ordem, mesmos tipos) aos das implementações de referência. Assinaturas, dataclasses e contratos de tempo (sem look-ahead) ficam como estão.
- Os testes existentes continuam passando sem alteração de expectativas.
- `tests/reference_impl.py` é cópia **literal** do código de `HEAD` no início deste plano (obtida com `git show <commit>:<arquivo>`), só com os nomes prefixados por `ref_`; não é editado depois.
- Metas de tempo (medidas por `scripts/bench.py`, relatadas, **não** afirmadas em testes, para não criar testes instáveis): em 12.000 candles M15 (`random_walk_candles(12000, seed=5, tf="M15")`, k=3, `ZoneConfig()`): `find_pivots` < 0,1 s, `find_fvgs` < 0,1 s, `build_zones` < 0,4 s, `build_breakers` < 0,5 s, `analyze` < 1,5 s.
- Cada commit termina com uma linha em branco e `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` (ou o modelo que escreveu o commit). Não rodar formatadores sobre o repositório.

## Review Focus

1. **Empates:** preços repetidos (máximas e mínimas iguais, FVGs e sweeps com timestamps coincidentes) produzem o mesmo resultado que a referência (Task 1 gera quadros com preços arredondados para forçar empates).
2. **Entradas vazias e curtas:** frames vazios, de 1 a 4 candles, zonas/FVGs/sweeps vazios continuam devolvendo o mesmo que a referência, sem exceção (Task 1).
3. **`min_size` do FVG e tamanhos exatos** (gap igual a `min_size`, NaN) iguais à referência (Task 3).
4. **Quebra do breaker e idade:** o limite `breaker_max_age` (inclusive o valor 1 e `None`) e o CHoCH opcional iguais à referência (Task 2).
5. **Dados reais:** um quadro real de XAUUSD M15 dá resultado idêntico à referência quando os dados existem em `data/` (Task 1; o teste é ignorado quando não há dados).

---

### Task 1: Oráculo, testes de equivalência e benchmark

**Files:**
- Create: `tests/reference_impl.py`, `tests/test_equivalence.py`, `scripts/bench.py`

**Interfaces:**
- Produces:
  - `tests/reference_impl.py`: `ref_find_pivots(candles, k)`, `ref_find_fvgs(candles, min_size=0.0)`, `ref_build_zones(candles, events, fvgs, sweeps, cfg)`, `ref_build_breakers(candles, zones, events, fvgs, sweeps, cfg)` — cópias literais das funções de `src/smc_trader/structure/pivots.py` (`find_pivots`), `zones/fvg.py` (`find_fvgs`), `zones/orderblock.py` (`build_zones` com `_lifetime`) e `zones/breaker.py` (`build_breakers` com `_lifetime`), incluindo helpers privados necessários (renomeados com `_ref_`). As dataclasses (`Zone`, `FVG`) e `in_discount` são **importadas** de `src/`, não copiadas.
  - `scripts/bench.py`: imprime, para `random_walk_candles(n, seed=5, tf)` com `(2000, M15, k=3)`, `(12000, M15, k=3)` e `(30000, M1, k=2)`, o tempo de `analyze` e o de cada detector (`find_pivots`, `detect_structure`, `find_fvgs`, `find_sweeps`, `build_zones`, `build_breakers`). Execução: `uv run python scripts/bench.py` (precisa de `tests/` no `sys.path` para importar `helpers`; o script ajusta o caminho).

- [ ] **Step 1: Escrever `tests/reference_impl.py`** copiando as funções com `git show HEAD:<arquivo>` e renomeando; confirmar com `git diff --no-index` que o corpo é idêntico ao original (a menos dos nomes).
- [ ] **Step 2: Escrever `tests/test_equivalence.py`** (hoje deve passar de imediato, porque o código ainda é o mesmo; o valor aparece nas Tasks 2 e 3). Um gerador local `tied_candles(n, seed, tf)` cria passeio aleatório com `open/close` arredondados para múltiplos de 0,5 e `high`/`low` ajustados para cobrir o corpo (muitos empates). Testes parametrizados sobre `seed in (1, 2, 3)`, `n in (400, 1500)`, `k in (2, 3)` e sobre os dois geradores (`random_walk_candles` e `tied_candles`):
  - `test_find_pivots_equivalent`: `pd.testing.assert_frame_equal(find_pivots(c, k), ref_find_pivots(c, k))`.
  - `test_find_fvgs_equivalent`: listas iguais para `min_size = 0.0` e para `min_size` igual à mediana dos tamanhos dos gaps da referência (inclui gaps exatamente iguais ao limite).
  - `test_build_zones_equivalent`: listas iguais para `ZoneConfig()`, `require_discount=False`, `require_imbalance=True`, `use_body=True`, usando eventos, FVGs e sweeps calculados pelas funções de `src/`.
  - `test_build_breakers_equivalent`: listas iguais para `ZoneConfig()`, `breaker_require_imbalance=False`, `breaker_require_choch=True`, `breaker_max_age=None`, `breaker_max_age=1`, com as candidatas de `build_zones` (filtros de entrada desligados).
  - `test_edge_frames_equivalent`: para frames de 0, 1, 2, 3 e 4 candles, as quatro funções igualam a referência e não levantam exceção.
  - `test_real_data_equivalent`: se existir `data/XAUUSD_M1_dukascopy.parquet`, carrega duas semanas de M15 (`load_candles(Path("data"), "XAUUSD", "M15", start, end)`) e compara as quatro funções; senão, `pytest.skip`.
  Cada teste afirma também que a saída da referência **não é trivial** (por exemplo, `len(ref_zones) > 0` nos casos de 1.500 candles), para que a igualdade não seja vazia.
- [ ] **Step 3: Rodar:** `uv run pytest tests/test_equivalence.py -v` → todos PASS (e nenhum teste vazio).
- [ ] **Step 4: Escrever `scripts/bench.py`** e rodar `uv run python scripts/bench.py`; anotar a tabela de partida no relatório da task.
- [ ] **Step 5: Commit** `test: oráculo de referência, equivalência e benchmark dos detectores`.

---

### Task 2: `build_zones` e `build_breakers` com buscas ordenadas

**Files:**
- Modify: `src/smc_trader/zones/orderblock.py`, `src/smc_trader/zones/breaker.py`
- Test: `tests/test_equivalence.py` (já existe, não muda), suítes existentes

**Interfaces:**
- Produces: as mesmas funções públicas (`build_zones`, `build_breakers`, `Zone`) com a mesma assinatura e saída; internamente:
  - **FVG por direção em arrays ordenados:** `find_fvgs` entrega os FVGs em ordem crescente de `formed_at`, e `start_time` e `formed_at` crescem juntos. A pergunta "existe FVG da direção `d` com `start_time >= X` e `formed_at <= Y`?" vira: pega-se, por `searchsorted` em `start_time`, o primeiro FVG com `start_time >= X`; existe se o `formed_at` desse FVG é `<= Y`. Para o breaker, "existe FVG com `start_time == index[j-1]`" vira busca exata pelo mesmo array (ou dicionário `start_time → FVG`).
  - **Sweeps por lado em arrays ordenados:** `find_sweeps` entrega em ordem de `sweep_time`, e `confirmed_at` cresce junto. A pergunta "existe sweep do lado `s` com `sweep_time >= X` e `confirmed_at <= Y`?" vira: primeiro sweep do lado com `sweep_time >= X` (por `searchsorted`), existe se o seu `confirmed_at` é `<= Y`.
  - **CHoCH por direção:** os tempos de eventos `CHoCH` de cada direção ficam em arrays ordenados; "primeiro CHoCH contra com `time > created_at`" e "existe CHoCH com `created_at < time <= limite`" viram `searchsorted`.
  - **Ciclo de vida sem cópia de DataFrame:** `high`, `low`, `close` e `close_time` como arrays numpy criados uma vez; o primeiro toque a partir de `created_at` vem de `searchsorted` mais uma máscara vetorial sobre o trecho (ou um `argmax` sobre a máscara), sem `candles[candles.index >= ...]`.
  - **Quebra do breaker:** a procura do primeiro `close` além do lado oposto vira uma comparação vetorial sobre `close[bos_pos+1 : stop]` com `argmax`, mantendo o corte por `breaker_max_age`.
  - **Posição do candle do BOS** (`close_time == created_at`) por `searchsorted` sobre o array de `close_time` (que é crescente), com checagem de igualdade (origem sem candle correspondente continua sendo ignorada).

- [x] **Step 1: Rodar o oráculo antes de mexer** (`uv run pytest tests/test_equivalence.py -q` → PASS) e medir a linha de partida de `build_zones` e `build_breakers` com `scripts/bench.py`.
- [x] **Step 2: Implementar** as mudanças acima em `orderblock.py` e `breaker.py`, uma função privada por responsabilidade (preparar índices, primeiro toque, etc.); não alterar nenhuma assinatura pública nem dataclass.
- [x] **Step 3: Rodar:** `uv run pytest -q` → tudo PASS (equivalência inclusive, sem mudar nenhum teste).
- [x] **Step 4: Medir** com `scripts/bench.py` e registrar a tabela no relatório; metas: `build_zones` < 0,4 s e `build_breakers` < 0,5 s em 12.000 candles M15. Se uma meta não for atingida, relatar o gargalo restante com um perfil (`cProfile`) em vez de forçar.
- [x] **Step 5: Commit** `perf: buscas ordenadas em build_zones e build_breakers`.

---

### Task 3: `find_pivots` e `find_fvgs` vetorizados

**Files:**
- Modify: `src/smc_trader/structure/pivots.py`, `src/smc_trader/zones/fvg.py`
- Test: `tests/test_equivalence.py` (não muda), suítes existentes

**Interfaces:**
- Produces: as mesmas funções com a mesma saída.
  - `find_pivots(candles, k)`: comparações vetoriais com janelas deslizantes (por exemplo `numpy.lib.stride_tricks.sliding_window_view`) para as regras `high[i] > max(high[i-k:i])` e `high[i] >= max(high[i+1:i+k+1])` (e o espelho para fundos), mais a montagem do DataFrame de uma vez (colunas `time, kind, price, confirmed_at`, ordenado por `time`, mesmo `RangeIndex` e dtypes). `k < 1` continua levantando `ValueError`.
  - `find_fvgs(candles, min_size=0.0)`: máscara vetorial `high[i-2] < low[i]` (alta) e `low[i-2] > high[i]` (baixa) com o filtro `>= min_size`; a lista de `FVG` na mesma ordem (por `formed_at`) e com os mesmos campos; NaN continua não gerando FVG.

- [x] **Step 1: Rodar o oráculo** (`uv run pytest tests/test_equivalence.py -q` → PASS) e medir a partida de `find_pivots` e `find_fvgs` com `scripts/bench.py`.
- [x] **Step 2: Implementar** a vetorização.
- [x] **Step 3: Rodar:** `uv run pytest -q` → tudo PASS.
- [x] **Step 4: Medir** e registrar a tabela final de `analyze` e de cada detector no relatório; metas: `find_pivots` e `find_fvgs` < 0,1 s em 12.000 candles M15 e `analyze` < 1,5 s.
- [x] **Step 5: Commit** `perf: pivôs e FVG vetorizados`.

---

## Autoavaliação

- **Cobertura:** o oráculo e o benchmark (Task 1) cobrem a rede de segurança e a medição; os gargalos medidos — `build_breakers`, `build_zones`, depois pivôs e FVG — são as Tasks 2 e 3. `detect_structure` (0,45 s em 12.000 candles) e `find_sweeps` (0,09 s) ficam como estão: não são gargalo e já são lineares.
- **Risco principal:** mudar um resultado por engano. A mitigação é o oráculo literal com dados aleatórios, com empates e reais; nenhuma task altera `tests/reference_impl.py`.
- **Fora do plano:** o motor de backtest (Plano 2b em diante).

# SMC Day Trade — Plano 1: Base, Detectores e Visualização

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Baixar histórico M1 da Dukascopy (fonte primária; MT5 via Wine como fonte secundária), reamostrar para M15 e detectar estrutura (BOS/CHoCH), FVG, sweeps e zonas OB/FVOB sem look-ahead, com gráficos HTML para o Thiago validar contra a leitura manual.

**Architecture:** Pacote `smc_trader` (layout `src/`). Todo detector é função pura sobre um DataFrame de candles e devolve dataclasses ou DataFrames. M5/M15 são sempre reamostrados do M1 armazenado em Parquet. Um `analyze()` encadeia pivôs → estrutura → FVG → sweeps → zonas e alimenta o gráfico e, nos planos seguintes, o backtest.

**Tech Stack:** Python 3.12, uv, pandas, numpy, pyarrow, pydantic v2 + PyYAML, plotly, dukascopy-python, pytest, argparse.

**Spec:** `docs/superpowers/specs/2026-10-18-smc-day-trade-design.md`

**Este é o Plano 1 de 3.** Plano 2: engine de backtest, entradas touch/confirmation, stops, alvos, condução, travas, custos e grade de experimentos. Plano 3: confluência (RSI, Wyckoff, Elliott) e scanner ao vivo com Telegram. Os planos 2 e 3 só começam depois do checkpoint da Task 10.

## Global Constraints

- Python 3.12, gerenciado com `uv`; layout `src/smc_trader`; testes com `pytest`.
- Todos os horários internos em **UTC**, com `DatetimeIndex` tz-aware.
- M5/M15 **reamostrados a partir do M1** (nunca baixados separadamente).
- **Fonte primária de dados: Dukascopy** (M1 já em UTC, lado `bid` por padrão). O M1 da Dukascopy **não traz spread**: a coluna `spread` vem `0.0` e o custo de spread do backtest vem da configuração (Plano 2). MT5 via Wine é fonte secundária.
- `start`/`end` enviados ao `dukascopy_python.fetch` devem ser `datetime` **tz-aware em UTC** (o pacote usa `.timestamp()`, que interpreta datetimes ingênuos no fuso local da máquina).
- **Sem look-ahead:** pivô só é confirmado após `k` candles à direita fecharem (`confirmed_at` = `close_time` do k-ésimo candle à direita); OB/zona só é utilizável a partir do `close_time` do candle que confirma o BOS; resultado de qualquer detector em dados truncados no instante t deve ser idêntico ao da execução completa até t.
- Pivô do M15: `k = 3` (padrão, configurável); pivô do M1: `k = 2` (decisão minha, configurável).
- Zona só vale em desconto (compra) ou prêmio (venda) em relação ao range da perna; padrão `require_discount: true`, `require_imbalance: false` (aceita OB e FVOB), `use_body: false` (zona do pavio ao pavio).
- Símbolos iniciais, com nomes configuráveis por corretora: `XAUUSD, EURUSD, GBPUSD, US30, NAS100, BRENT`.
- Só candles de BOS geram zona (CHoCH não gera zona nesta versão).
- Compra e venda são espelhos exatos: cada detector deve ter teste espelhado.

## Review Focus

1. **Frames vazios ou curtos** (menos de `2k+1` candles): todo detector devolve resultado vazio, sem exceção (Tasks 4 e 9).
2. **Buracos no M1** (fim de semana, feriado, falha da corretora): a reamostragem não cria buckets vazios nem candles com NaN (Task 2).
3. **Horário do servidor do MT5** (fonte secundária; a Dukascopy já vem em UTC): conversão correta para UTC nas semanas em que o DST dos EUA e o da Europa divergem (ex.: 2024-03-20), e horas ambíguas do fim do DST não derrubam o import (Task 11).
4. **Dados sobrepostos, duplicados ou fora de ordem** (reexportação incremental, candle na fronteira dos blocos mensais do download da Dukascopy): índice final único e ordenado; a linha mais recente vence (Tasks 2, 3 e 11).
5. **Máximas/mínimas iguais e candles doji** (`open == close`): um único pivô por topo/fundo igual; doji não é candle de alta nem de baixa para o OB; nenhum erro (Tasks 4 e 8).

---

## Mapa de arquivos

```
pyproject.toml, .gitignore, config/default.yaml
src/smc_trader/__init__.py
src/smc_trader/config.py                 # modelos pydantic + load_config
src/smc_trader/cli.py                    # fetch, import-csv, chart
src/smc_trader/analysis.py               # Analysis + analyze()
src/smc_trader/data/candles.py           # TF_MINUTES, with_close_time
src/smc_trader/data/resample.py          # resample_ohlc
src/smc_trader/data/store.py             # save_m1, load_candles
src/smc_trader/data/dukascopy_source.py  # normalize_dukascopy, fetch_m1 (fonte primária)
src/smc_trader/data/mt5_bridge.py        # import_mt5_csv (fonte secundária)
src/smc_trader/structure/pivots.py       # find_pivots
src/smc_trader/structure/market_structure.py  # StructureEvent, detect_structure
src/smc_trader/zones/fvg.py              # FVG, find_fvgs
src/smc_trader/zones/liquidity.py        # Sweep, find_sweeps
src/smc_trader/zones/premium_discount.py # equilibrium, in_discount
src/smc_trader/zones/orderblock.py       # Zone, build_zones
src/smc_trader/viz/chart.py              # build_chart
scripts/wine/export_history.py           # roda no Python-Windows sob Wine
docs/wine-mt5.md
tests/helpers.py, tests/test_*.py
```

**Contrato do DataFrame de candles** (usado por todas as tasks): índice `time` (UTC, tz-aware, crescente, único = horário de abertura); colunas `open, high, low, close, volume` (float) e `close_time` (abertura + duração do timeframe). O M1 também tem `spread` (float).

---

### Task 1: Scaffold e configuração

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `config/default.yaml`, `src/smc_trader/__init__.py`, `src/smc_trader/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `class DataConfig(BaseModel)`: `root: Path = Path("data")`, `server_ny_offset_hours: int | None = 7`, `server_timezone: str | None = None`. Validador: **exatamente um** dos dois campos de fuso deve estar preenchido.
  - `class StructureConfig(BaseModel)`: `pivot_k_htf: int = Field(3, ge=1)`, `pivot_k_ltf: int = Field(2, ge=1)`
  - `class ZoneConfig(BaseModel)`: `require_discount: bool = True`, `require_imbalance: bool = False`, `use_body: bool = False`, `fvg_min_size: float = Field(0.0, ge=0)`
  - `class DukascopyConfig(BaseModel)`: `instruments: dict[str, str]` (símbolo do projeto → instrumento da Dukascopy), `offer_side: Literal["bid", "ask"] = "bid"`
  - `class Config(BaseModel)`: `data: DataConfig`, `symbols: list[str]`, `dukascopy: DukascopyConfig`, `structure: StructureConfig`, `zones: ZoneConfig`
  - `def load_config(path: Path = Path("config/default.yaml")) -> Config`

- [ ] **Step 1: Escrever os testes que falham** em `tests/test_config.py`:
  - `test_default_config_loads`: `cfg = load_config(Path("config/default.yaml"))`; `cfg.structure.pivot_k_htf == 3`, `cfg.structure.pivot_k_ltf == 2`, `cfg.zones.require_discount is True`, `cfg.zones.require_imbalance is False`, `cfg.symbols == ["XAUUSD","EURUSD","GBPUSD","US30","NAS100","BRENT"]`, `cfg.data.server_ny_offset_hours == 7`.
  - `test_pivot_k_must_be_positive`: `StructureConfig(pivot_k_htf=0)` levanta `ValidationError`.
  - `test_exactly_one_server_time_rule`: `DataConfig(server_timezone="Europe/Athens")` (com o offset padrão 7) levanta `ValidationError`; `DataConfig(server_timezone=None, server_ny_offset_hours=None)` levanta `ValidationError`; `DataConfig(server_timezone="Europe/Athens", server_ny_offset_hours=None)` é válido.
  - `test_every_symbol_has_dukascopy_instrument`: todo símbolo de `cfg.symbols` está em `cfg.dukascopy.instruments`; cada valor é igual ao valor de alguma constante string `INSTRUMENT_*` de `dukascopy_python.instruments`; `cfg.dukascopy.offer_side == "bid"`.
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/test_config.py -v` → FAIL (módulo inexistente).
- [ ] **Step 3: Criar o scaffold.** `pyproject.toml` com backend hatchling, `requires-python = ">=3.12"`, dependências `pandas>=2.2, numpy, pyarrow, pydantic>=2, pyyaml, plotly, dukascopy-python`, grupo dev `pytest`, e script `smc = "smc_trader.cli:main"`. `.gitignore` com `.venv/`, `__pycache__/`, `data/`, `out/`. `config/default.yaml` com os valores acima e o mapa da Dukascopy: `XAUUSD: "XAU/USD"`, `EURUSD: "EUR/USD"`, `GBPUSD: "GBP/USD"`, `BRENT: "E_Brent"`; para `US30` e `NAS100`, listar as constantes `INSTRUMENT_IDX_AMERICA_*` de `dukascopy_python.instruments` e usar as do Dow Jones e do Nasdaq 100. Implementar `config.py`. Rodar `uv sync`.
- [ ] **Step 4: Rodar e ver passar:** `uv run pytest tests/test_config.py -v` → PASS.
- [ ] **Step 5: Commit**

```bash
git add pyproject.toml .gitignore config src tests
git commit -m "feat: scaffold do projeto e configuração"
```

---

### Task 2: Contrato de candles, reamostragem e armazenamento

**Files:**
- Create: `src/smc_trader/data/__init__.py`, `data/candles.py`, `data/resample.py`, `data/store.py`, `tests/helpers.py`
- Test: `tests/test_resample.py`, `tests/test_store.py`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `TF_MINUTES: dict[str, int] = {"M1": 1, "M5": 5, "M15": 15}`
  - `with_close_time(df: pd.DataFrame, tf: str) -> pd.DataFrame` (copia e adiciona `close_time`)
  - `resample_ohlc(m1: pd.DataFrame, tf: str, drop_incomplete_tail: bool = True) -> pd.DataFrame` (agrega open=first, high=max, low=min, close=last, volume=sum; descarta buckets vazios; devolve `close_time`; sem `spread`)
  - `save_m1(root: Path, symbol: str, df: pd.DataFrame) -> None` (arquivo `{root}/{symbol}_M1.parquet`; une com o existente, remove índices duplicados mantendo o **mais recente**, ordena)
  - `load_candles(root: Path, symbol: str, tf: str = "M1", start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> pd.DataFrame` (filtra `start <= time < end`; para `tf != "M1"` reamostra do M1)
  - Em `tests/helpers.py`: `candles_from_ohlc(rows: list[tuple[float, float, float, float]], tf: str = "M15", start: str = "2024-01-02 00:00") -> pd.DataFrame` (candles contíguos, com `volume=1.0`, `close_time`), `mirror(df) -> pd.DataFrame` (preço `p` vira `100 - p`, trocando `high` e `low`) e `random_walk_candles(n: int, seed: int, tf: str = "M15") -> pd.DataFrame` (passeio aleatório com `numpy.random.default_rng(seed)`, high ≥ max(open, close), low ≤ min(open, close)).

- [ ] **Step 1: Escrever os testes que falham.**
  - `test_resample.py`:
    - `test_15_m1_become_one_m15`: 15 M1 de 10:00 a 10:14, com open do primeiro = 1, high máximo = 9, low mínimo = 0.5, close do último = 2 e volume 1 cada. Resultado: 1 linha em 10:00 com esses valores, `volume == 15`, `close_time == 10:15`.
    - `test_gaps_do_not_create_empty_buckets`: M1 em 10:00–10:14 e 10:45–10:59 → exatamente 2 linhas, nenhuma coluna com NaN.
    - `test_incomplete_tail_dropped_by_default`: M1 em 10:00–10:07 → frame vazio, com as colunas esperadas; com `drop_incomplete_tail=False` → 1 linha.
  - `test_store.py` (usando `tmp_path`):
    - `test_roundtrip_adds_close_time`: `save_m1` + `load_candles(..., "M1")` devolve as linhas e `close_time == index + 1min`.
    - `test_incremental_save_merges_and_newer_wins`: dois `save_m1` com sobreposição de 1 candle com valores diferentes → índice único, ordenado, valor do segundo save.
    - `test_load_m15_resamples_and_filters`: `load_candles(..., "M15", start, end)` devolve só candles `start <= time < end`.
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/test_resample.py tests/test_store.py -v` → FAIL.
- [ ] **Step 3: Implementar** os módulos acima. Para `drop_incomplete_tail`: descartar o último bucket quando o último M1 dele é anterior a `fim_do_bucket - 1min`.
- [ ] **Step 4: Rodar e ver passar** → PASS.
- [ ] **Step 5: Commit** `feat: candles, reamostragem M1→HTF e armazenamento Parquet`.

---

### Task 3: Fonte primária — Dukascopy e CLI `fetch`

**Files:**
- Create: `src/smc_trader/data/dukascopy_source.py`, `src/smc_trader/cli.py`
- Test: `tests/test_dukascopy_source.py`, `tests/test_cli_fetch.py`

**Interfaces:**
- Consumes: `Config`, `DukascopyConfig`, `load_config` (Task 1); `save_m1`, `load_candles` (Task 2).
- Produces:
  - `normalize_dukascopy(df: pd.DataFrame) -> pd.DataFrame`: recebe o DataFrame do `dukascopy_python.fetch` (índice `timestamp` UTC; colunas `open, high, low, close, volume`) e devolve o contrato do M1: índice `time` UTC, único e crescente (a última linha vence nos duplicados); colunas `open, high, low, close, volume, spread` com `spread = 0.0`; linhas com NaN descartadas.
  - `fetch_m1(instrument: str, start: datetime, end: datetime, offer_side: Literal["bid", "ask"], fetcher: Callable[..., pd.DataFrame] = dukascopy_python.fetch) -> pd.DataFrame`: baixa em blocos mensais com `interval=dukascopy_python.INTERVAL_MIN_1`, chamando `fetcher` só com argumentos nomeados (`instrument, interval, offer_side, start, end`), concatena e normaliza. `offer_side` vira `OFFER_SIDE_BID` ou `OFFER_SIDE_ASK`. `start`/`end` são tz-aware em UTC; sem conversão de fuso.
  - `cli.main(argv: list[str] | None = None) -> int` com o subcomando `fetch SYMBOL --from ISO --to ISO [--config PATH] [--data-root PATH]`. Símbolo sem mapeamento em `cfg.dukascopy.instruments` → mensagem em stderr e retorno `2`.

- [ ] **Step 1: Escrever os testes que falham.**
  - `test_dukascopy_source.py`:
    - `test_normalize_contract`: entrada com índice `timestamp` fora de ordem, 1 timestamp duplicado (valores diferentes) e 1 linha com NaN → saída com índice `time` UTC crescente e único, a linha duplicada com o valor da última ocorrência, sem NaN, colunas exatamente `["open","high","low","close","volume","spread"]` e `spread == 0.0`.
    - `test_fetch_m1_monthly_chunks`: um `fake_fetcher(**kw)` registra `kw["start"]` e `kw["end"]` e devolve 2 linhas M1 (nos instantes `start` e `end`). De 2024-01-15 a 2024-03-10 (UTC): 3 chamadas com `(start, end)` = `(01-15, 02-01)`, `(02-01, 03-01)`, `(03-01, 03-10)`; o resultado tem índice único e crescente (os candles nas fronteiras duplicam entre blocos); em todas as chamadas `kw["interval"] == dukascopy_python.INTERVAL_MIN_1`, `kw["start"].utcoffset()` é zero e `kw["offer_side"] == dukascopy_python.OFFER_SIDE_BID` (e `OFFER_SIDE_ASK` com `"ask"`).
  - `test_cli_fetch.py` (`tmp_path`, `monkeypatch.setattr("smc_trader.cli.fetch_m1", fake)` com `fake` devolvendo um M1 sintético):
    - `test_cli_fetch_saves_m1`: `main(["fetch","XAUUSD","--from","2024-06-03","--to","2024-06-04","--data-root",str(tmp_path)])` devolve 0 e `load_candles(tmp_path, "XAUUSD")` devolve as linhas do `fake`; o `fake` recebeu o instrumento `"XAU/USD"`.
    - `test_cli_fetch_unknown_symbol`: símbolo `FOO` → retorno `2` e nada gravado.
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/test_dukascopy_source.py tests/test_cli_fetch.py -v` → FAIL.
- [ ] **Step 3: Implementar** `normalize_dukascopy`, `fetch_m1` (blocos mensais `[início do mês seguinte]`, com o último bloco terminando em `end`) e o CLI com `argparse`, carregando a config e salvando via `save_m1`.
- [ ] **Step 4: Rodar e ver passar** → PASS.
- [ ] **Step 5: Verificação manual** (precisa de internet): `uv run smc fetch XAUUSD --from 2024-06-03 --to 2024-06-08` termina com código 0; `load_candles(Path("data"), "XAUUSD")` tem na ordem de milhares de linhas (cerca de 1.300 por dia útil) e nenhum candle no sábado.
- [ ] **Step 6: Commit** `feat: fonte Dukascopy e CLI fetch`.

---

### Task 11: Importação do MT5 via Wine (fonte secundária)

> Necessária só para o scanner ao vivo (Plano 3) ou se você quiser os dados exatos da sua corretora. Pode ser executada depois da Task 10.

**Files:**
- Create: `src/smc_trader/data/mt5_bridge.py`, `scripts/wine/export_history.py`, `docs/wine-mt5.md`
- Modify: `src/smc_trader/cli.py` (acrescenta o subcomando `import-csv`)
- Test: `tests/test_mt5_bridge.py`, `tests/test_cli_import.py`

**Interfaces:**
- Consumes: `DataConfig` (Task 1), `save_m1`, `load_candles` (Task 2).
- Produces:
  - `import_mt5_csv(path: Path, data_cfg: DataConfig) -> pd.DataFrame` (M1: colunas `open, high, low, close, volume, spread`, índice UTC único e ordenado; `volume` vem de `tick_volume`)
  - subcomando `import-csv CSV --symbol SYM [--config PATH] [--data-root PATH]` em `cli.main` (criado na Task 3)

CSV do MT5, cabeçalho: `time,open,high,low,close,tick_volume,spread,real_volume`, com `time` em segundos de época, **no horário do servidor** (não é UTC).

- [ ] **Step 1: Escrever os testes que falham.**
  - `test_server_time_ny_plus_7`: com `DataConfig()` e linhas em 2024-01-15 12:00, 2024-03-20 12:00 e 2024-07-15 12:00 (como época "ingênua"), o índice UTC é 10:00, 09:00 e 09:00 respectivamente (a de 03-20 distingue NY+7 de Europe/Athens).
  - `test_server_timezone_option`: com `DataConfig(server_timezone="Europe/Athens", server_ny_offset_hours=None)`, 2024-03-20 12:00 vira 10:00 UTC.
  - `test_duplicates_and_unsorted_rows`: linhas na ordem `t2, t1, t1'` (t1' com `close` diferente) → 2 linhas, ordem crescente, `close` de t1 igual ao de t1'.
  - `test_ambiguous_ny_time_is_dropped`: linha cujo horário corresponde a 2024-11-03 01:30 em Nova York (servidor 08:30) mais uma linha normal → só a normal permanece, sem exceção.
  - `test_cli_import_csv`: `main(["import-csv", str(csv), "--symbol", "XAUUSD", "--data-root", str(tmp_path)])` devolve 0 e `load_candles(tmp_path, "XAUUSD")` retorna as linhas.
- [ ] **Step 2: Rodar e ver falhar** → FAIL.
- [ ] **Step 3: Implementar `import_mt5_csv`.** Regra NY+7: subtrair `server_ny_offset_hours` do horário, localizar em `America/New_York` com `ambiguous="NaT"` e `nonexistent="NaT"`, converter para UTC e descartar NaT. Regra de fuso IANA: localizar no `server_timezone` com a mesma política e converter. Depois ordenar e remover duplicados mantendo a última linha do arquivo. Acrescentar o subcomando ao CLI da Task 3, carregando a config e salvando via `save_m1`.
- [ ] **Step 4: Rodar e ver passar** → PASS.
- [ ] **Step 5: Escrever `scripts/wine/export_history.py` e `docs/wine-mt5.md`** (não é testável automaticamente). O script roda no Python do Windows sob Wine, só com a biblioteca padrão e `MetaTrader5`. Argumentos: `--symbols`, `--from`, `--to`, `--out`. Chama `initialize()`, `symbol_select`, e `copy_rates_range` em blocos mensais para `TIMEFRAME_M1`, gravando `{SYMBOL}_M1.csv` com o cabeçalho acima. O doc explica: instalar o MT5 no Wine, instalar o Python do Windows no mesmo prefixo, `wine python -m pip install MetaTrader5`, comando de exportação, e como conferir o fuso do servidor da corretora (se o offset não for NY+7, usar `server_timezone`).
- [ ] **Step 6: Verificação manual** (precisa do MT5 do usuário): exportar 1 mês de XAUUSD. `head -2 XAUUSD_M1.csv` mostra o cabeçalho e uma linha; `uv run smc import-csv XAUUSD_M1.csv --symbol XAUUSD` termina com código 0.
- [ ] **Step 7: Commit** `feat: importação de histórico MT5 via Wine e CLI import-csv`.

---

### Task 4: Pivôs sem look-ahead

**Files:**
- Create: `src/smc_trader/structure/__init__.py`, `structure/pivots.py`
- Test: `tests/test_pivots.py`

**Interfaces:**
- Consumes: contrato de candles, `candles_from_ohlc` (Task 2).
- Produces: `find_pivots(candles: pd.DataFrame, k: int) -> pd.DataFrame` com colunas `time` (abertura do candle do pivô), `kind` (`"high"` ou `"low"`), `price`, `confirmed_at` (`close_time` do candle `i+k`), ordenado por `time`, `RangeIndex`. Topo: `high[i] > max(high[i-k:i])` **e** `high[i] >= max(high[i+1:i+k+1])`. Fundo: espelho com `<` e `<=`. Frame com menos de `2k+1` linhas devolve um DataFrame vazio com as mesmas colunas.

- [ ] **Step 1: Escrever os testes que falham** (usar `candles_from_ohlc` com `open=close=(high+low)/2`):
  - `test_pivots_k2`: `highs=[1,2,5,2,1,2,3,2,1]`, `lows = highs - 0.5`, `k=2`. Topos em `index[2]` (5) e `index[6]` (3); fundo só em `index[4]` (0.5); `confirmed_at` dos topos = `close_time[4]` e `close_time[8]`.
  - `test_equal_highs_single_pivot`: `highs=[1,2,5,5,2,1]`, `k=2` → exatamente 1 topo, em `index[2]`.
  - `test_short_or_empty_frame`: frame de 4 candles com `k=3`, e frame vazio → DataFrame vazio com as colunas `time, kind, price, confirmed_at`.
- [ ] **Step 2: Rodar e ver falhar** → FAIL.
- [ ] **Step 3: Implementar `find_pivots`** com `rolling` vetorizado ou laço simples sobre arrays numpy.
- [ ] **Step 4: Rodar e ver passar** → PASS.
- [ ] **Step 5: Commit** `feat: detecção de pivôs com confirmação sem look-ahead`.

---

### Task 5: Estrutura de mercado (BOS e CHoCH)

**Files:**
- Create: `src/smc_trader/structure/market_structure.py`
- Test: `tests/test_market_structure.py`

**Interfaces:**
- Consumes: `find_pivots` (Task 4).
- Produces:
  - `@dataclass(frozen=True) class StructureEvent`: `kind: Literal["BOS","CHoCH"]`, `direction: Literal["up","down"]`, `time` (`close_time` do candle que rompeu), `break_time` (abertura desse candle), `level: float`, `level_time` (abertura do pivô rompido), `leg_time` (abertura do candle do extremo da correção), `range_low: float`, `range_high: float`.
  - `detect_structure(candles: pd.DataFrame, pivots: pd.DataFrame) -> list[StructureEvent]`

Regras:
- Um pivô só fica ativo para candles com `open_time >= confirmed_at`.
- Mantém-se o **último pivô de topo** e o **último de fundo** confirmados, cada um com uma marca de "consumido".
- Um candle que **fecha** acima do último topo não consumido gera evento `up`; abaixo do último fundo não consumido gera `down`. O pivô rompido fica consumido.
- `kind` é `BOS` se a tendência atual for a mesma direção ou ainda indefinida, e `CHoCH` se for contrária. A tendência passa a ser a direção do evento.
- Perna do evento `up`: `range_low` = menor mínima nos candles de `level_time` (exclusive) até o candle do rompimento (inclusive), `leg_time` = abertura do candle da **última** ocorrência dessa mínima, `range_high` = maior máxima de `level_time` (inclusive) até o rompimento (inclusive). O evento `down` é o espelho: `range_high` = maior máxima na correção, `range_low` = menor mínima do mesmo intervalo.

- [ ] **Step 1: Escrever os testes que falham.** Série A (`k=1`, linhas `(open, high, low, close)`, posições 0 a 10):

```
0: (10, 11, 9, 10.5)      5: (11, 13.5, 10.8, 13.2)   9:  (12.0, 12.6, 11.9, 12.4)
1: (10.5, 13, 10, 12.5)   6: (13.2, 14, 12.8, 13.8)   10: (12.4, 12.5, 9.5, 9.8)
2: (12.5, 12.5, 11, 11.5) 7: (13.8, 13.9, 12.5, 12.6)
3: (11.5, 12, 10, 10.5)   8: (12.6, 13.0, 11.8, 12.0)
4: (10.5, 11.5, 10.2, 11)
```

  - `test_bos_then_choch`: a série A produz exatamente `[BOS up, CHoCH down]`. O BOS tem `time == close_time[5]`, `level == 13`, `level_time == index[1]`, `leg_time == index[3]`, `range_low == 10`, `range_high == 13.5`. O CHoCH tem `time == close_time[10]`, `level == 11.8`, `level_time == index[8]`.
  - `test_mirrored_series_gives_down_bos`: `mirror(série A)` produz `[BOS down, CHoCH up]`; o BOS tem `level == 87`, `leg_time == index[3]`, `range_high == 90`, `range_low == 86.5`.
  - `test_no_lookahead_truncation`: para cada `n` de 1 a 11 e para um `random_walk_candles(150, seed=7)` com `k=2` e cortes a cada 7 candles, os eventos calculados em `candles.iloc[:n]` são iguais aos eventos do frame completo com `time <= close_time[n-1]`.
  - `test_empty_inputs`: candles vazios ou menores que `2k+1` → lista vazia.
- [ ] **Step 2: Rodar e ver falhar** → FAIL.
- [ ] **Step 3: Implementar `detect_structure`** com um laço sobre os candles, fazendo a ativação dos pivôs por tempo.
- [ ] **Step 4: Rodar e ver passar** → PASS.
- [ ] **Step 5: Commit** `feat: BOS e CHoCH com perna corretiva`.

---

### Task 6: FVG (imbalance)

**Files:**
- Create: `src/smc_trader/zones/__init__.py`, `zones/fvg.py`
- Test: `tests/test_fvg.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class FVG`: `direction: Literal["up","down"]`, `low: float`, `high: float`, `start_time` (abertura do candle 1), `formed_at` (`close_time` do candle 3).
  - `find_fvgs(candles: pd.DataFrame, min_size: float = 0.0) -> list[FVG]`. Alta: `high[i-2] < low[i]`, com gap `(high[i-2], low[i])`. Baixa: `low[i-2] > high[i]`, com gap `(high[i], low[i-2])`. Só entram gaps com tamanho `>= min_size`.

- [ ] **Step 1: Escrever os testes que falham.**
  - `test_bullish_fvg`: `[(9.5,10,9,9.8), (9.9,13,9.8,12.8), (12.8,14,11,13.5)]` → 1 FVG `up`, `low=10`, `high=11`, `start_time=index[0]`, `formed_at=close_time[2]`.
  - `test_bearish_fvg`: `[(13.5,14,13,13.2), (13.1,13.2,10,10.5), (10.5,12,10.2,11)]` → 1 FVG `down`, `low=12`, `high=13`.
  - `test_min_size_filters`: nos dois casos acima, `min_size=1.5` → lista vazia.
  - `test_overlapping_candles_have_no_fvg_and_short_frames_are_empty`: candles sobrepostos e frame com 2 candles → lista vazia.
- [ ] **Step 2: Rodar e ver falhar** → FAIL.
- [ ] **Step 3: Implementar `find_fvgs`.**
- [ ] **Step 4: Rodar e ver passar** → PASS.
- [ ] **Step 5: Commit** `feat: detecção de FVG`.

---

### Task 7: Sweeps de liquidez

**Files:**
- Create: `src/smc_trader/zones/liquidity.py`
- Test: `tests/test_liquidity.py`

**Interfaces:**
- Consumes: `find_pivots` (Task 4).
- Produces:
  - `@dataclass(frozen=True) class Sweep`: `side: Literal["low","high"]` (`"low"` = liquidez de fundo varrida), `pivot_time`, `pivot_price`, `sweep_time` (abertura do candle), `extreme` (extremo do pavio).
  - `find_sweeps(candles: pd.DataFrame, pivots: pd.DataFrame) -> list[Sweep]`. Para cada pivô, olhando só candles com `open_time >= confirmed_at`: o **primeiro** candle que ultrapassa o preço do pivô decide. Se fechou de volta do lado original, é sweep; se fechou além, é rompimento e não gera sweep. Em ambos os casos o pivô fica consumido, então cada pivô gera no máximo 1 sweep.

- [ ] **Step 1: Escrever os testes que falham** (`k=1`):
  - `test_low_sweep`: `[(10,11,9,10.5), (10.5,10.8,8,9), (9,10,8.5,9.8), (9.8,10.5,9.5,10.2), (10.2,10.6,7.5,9.9), (9.9,10,7.2,9.5)]` → exatamente 1 Sweep `low`, `pivot_time=index[1]`, `pivot_price=8`, `sweep_time=index[4]`, `extreme=7.5` (o candle 5 não gera um segundo sweep).
  - `test_close_beyond_is_break_not_sweep`: mesma série, com o candle 4 trocado por `(10.2,10.6,7.5,7.8)` → lista vazia.
  - `test_high_sweep_mirrored`: `mirror` da série do primeiro teste → 1 Sweep `high`.
- [ ] **Step 2: Rodar e ver falhar** → FAIL.
- [ ] **Step 3: Implementar `find_sweeps`.**
- [ ] **Step 4: Rodar e ver passar** → PASS.
- [ ] **Step 5: Commit** `feat: sweeps de liquidez`.

---

### Task 8: Premium/discount e zonas OB/FVOB

**Files:**
- Create: `src/smc_trader/zones/premium_discount.py`, `src/smc_trader/zones/orderblock.py`
- Test: `tests/test_premium_discount.py`, `tests/test_orderblock.py`

**Interfaces:**
- Consumes: `StructureEvent` (Task 5), `FVG` (Task 6), `Sweep` (Task 7), `ZoneConfig` (Task 1).
- Produces:
  - `equilibrium(range_low: float, range_high: float) -> float`
  - `in_discount(direction: Literal["long","short"], zone_low: float, zone_high: float, range_low: float, range_high: float) -> bool` (compra: ponto médio da zona `<=` equilíbrio; venda: `>=`)
  - `@dataclass(frozen=True) class Zone`: `direction: Literal["long","short"]`, `kind: Literal["OB","FVOB"]`, `high: float`, `low: float`, `candle_time` (abertura do candle do OB), `created_at` (`close_time` do candle do BOS), `range_low: float`, `range_high: float`, `in_discount: bool` (prêmio, para venda), `swept_liquidity: bool`, `end_time: pd.Timestamp | None`, `end_reason: Literal["mitigated","invalidated"] | None`
  - `build_zones(candles, events: list[StructureEvent], fvgs: list[FVG], sweeps: list[Sweep], cfg: ZoneConfig) -> list[Zone]`

Regras de `build_zones`:
- Só eventos `kind == "BOS"` geram zona. BOS `up` gera zona `long`; BOS `down` gera zona `short`.
- **Candle do OB (compra):** o último candle de baixa (`close < open`; doji não conta) em posição `<= posição de leg_time` e `>= posição de level_time`. Venda: o último candle de alta. Se não houver, o evento não gera zona. Dois eventos com o mesmo `(direction, candle_time)` geram uma zona só (a primeira).
- **Limites:** `use_body=False` usa `low` e `high` do candle; `use_body=True` usa `min(open, close)` e `max(open, close)`.
- **FVOB:** existe um FVG de mesma direção com `start_time >= candle_time` e `formed_at <= event.time`. Se existir, `kind = "FVOB"`; senão `"OB"`. Com `require_imbalance=True`, o OB sem FVG é descartado.
- **Desconto:** `in_discount(...)` usa `range_low` e `range_high` do evento. Com `require_discount=True`, zonas fora de desconto (ou de prêmio, na venda) são descartadas; com `False` elas ficam com `in_discount=False`.
- **Sweep:** `swept_liquidity` é verdadeiro se existir um Sweep com `side == "low"` (compra) ou `"high"` (venda) e `candle_time <= sweep_time <= event.break_time`.
- **Vida da zona:** a zona fica em aberto a partir de `created_at`. Para candles com `open_time >= created_at`, ela é **mitigada** no primeiro candle que a toca (compra: `low <= zone.high`; venda: `high >= zone.low`), com `end_time = close_time` desse candle. Ela é **invalidada** pelo primeiro evento `CHoCH` contra a direção com `event.time > created_at` (`down` para compra, `up` para venda), com `end_time = event.time`. Vale o que acontecer primeiro por `end_time`; em empate, `mitigated`.

- [ ] **Step 1: Escrever os testes que falham.**
  - `test_premium_discount.py`: `equilibrium(10, 13.5) == 11.75`; `in_discount("long", 10, 12, 10, 13.5) is True`; `in_discount("long", 12.5, 13, 10, 13.5) is False`; `in_discount("short", 12.5, 13, 10, 13.5) is True`.
  - `test_orderblock.py`, usando `Série A[0:6]` (candles 0 a 5 da Task 5) com `k=1` e `analyze`-like encadeamento manual (`find_pivots` → `detect_structure` → `find_fvgs` → `find_sweeps` → `build_zones`):
    - `test_plain_ob`: 1 zona `long`, `kind="OB"`, `candle_time=index[3]`, `high=12`, `low=10`, `created_at=close_time[5]`, `range_low=10`, `range_high=13.5`, `in_discount=True`, `swept_liquidity=False`.
    - `test_fvob`: a mesma série com o candle 5 trocado por `(12.3, 13.5, 12.2, 13.2)` → `kind="FVOB"`, mesmos limites.
    - `test_use_body`: `use_body=True` → `high=11.5`, `low=10.5`.
    - `test_discount_filter`: série com os candles 0 e 1 iguais aos da Série A, `2: (12.9,12.9,11.5,12.0)`, `3: (10.5,11.8,10,11.5)`, `4: (11.5,11.9,10.2,11.0)`, `5: (11,13.5,10.8,13.2)`. O OB cai no candle 2 (o 3 é de alta), com ponto médio 12.2 acima do equilíbrio 11.75. Com `require_discount=True` → nenhuma zona; com `False` → 1 zona com `in_discount=False`.
    - `test_require_imbalance`: `require_imbalance=True` na série do `test_plain_ob` → nenhuma zona.
    - `test_swept_liquidity_window`: um `Sweep(side="low", ..., sweep_time=index[3])` à mão → `swept_liquidity=True`; com `sweep_time=index[0]` → `False`; `side="high"` em zona de compra → `False`.
    - `test_mitigated`: `Série A[0:6]` mais `6: (13.2,14,11.5,13.8)` → `end_reason="mitigated"`, `end_time=close_time[6]`.
    - `test_invalidated_before_touch`: `Série A[0:6]` mais `6: (13.2,14,13.5,13.9)`, `7: (13.9,14.2,13.2,14.0)`, `8: (14.0,14.5,13.4,14.4)`, `9: (14.4,14.4,12.8,12.9)` → `end_reason="invalidated"`, `end_time=close_time[9]`.
    - `test_mirrored_short_zone`: `mirror` da série do `test_fvob` → 1 zona `short`, `kind="FVOB"`, `high=90`, `low=88`.
    - `test_doji_is_not_ob_candle`: o candle 3 da série do `test_plain_ob` trocado por doji `(11,11,11,11)`, com os demais iguais, → o OB passa para o candle 2 (de baixa); sem exceção.
- [ ] **Step 2: Rodar e ver falhar** → FAIL.
- [ ] **Step 3: Implementar** `premium_discount.py` e `build_zones`.
- [ ] **Step 4: Rodar e ver passar** → PASS.
- [ ] **Step 5: Commit** `feat: zonas OB/FVOB com desconto, sweep e ciclo de vida`.

---

### Task 9: Pipeline `analyze` e teste de não-antecipação das zonas

**Files:**
- Create: `src/smc_trader/analysis.py`
- Test: `tests/test_analysis.py`

**Interfaces:**
- Consumes: `find_pivots`, `detect_structure`, `find_fvgs`, `find_sweeps`, `build_zones`, `ZoneConfig`.
- Produces:
  - `@dataclass class Analysis`: `pivots: pd.DataFrame`, `events: list[StructureEvent]`, `fvgs: list[FVG]`, `sweeps: list[Sweep]`, `zones: list[Zone]`
  - `analyze(candles: pd.DataFrame, k: int, zones_cfg: ZoneConfig) -> Analysis`

- [ ] **Step 1: Escrever os testes que falham.**
  - `test_end_to_end_sequence`: `Série A[0:6]` + candles 6 a 9 do `test_invalidated_before_touch`, `k=1`, `ZoneConfig()` → eventos `[BOS up, CHoCH down]`, 1 zona `long` com `kind="OB"` e `end_reason="invalidated"`.
  - `test_empty_and_short_frames`: `analyze` sobre frame vazio e sobre frame de 3 candles devolve `Analysis` com tudo vazio, sem exceção.
  - `test_zones_have_no_lookahead`: com `random_walk_candles(300, seed=11)`, `k=2` e cortes `n` a cada 10 candles: toda zona calculada no frame completo com `created_at <= close_time[n-1]` aparece no frame truncado com os mesmos `direction, kind, high, low, candle_time, created_at, range_low, range_high, in_discount, swept_liquidity`; e o `end_time` da zona truncada é `None` se `end_time` do frame completo for posterior a `close_time[n-1]`, ou igual a ele caso contrário. Se a série aleatória não gerar nenhuma zona, aumentar `n` ou trocar a seed até gerar ao menos 3; o teste deve afirmar `len(zones) >= 3`.
- [ ] **Step 2: Rodar e ver falhar** → FAIL.
- [ ] **Step 3: Implementar `analyze`** encadeando os detectores, com `fvg_min_size` vindo de `zones_cfg`.
- [ ] **Step 4: Rodar e ver passar** → PASS.
- [ ] **Step 5: Commit** `feat: pipeline de análise e teste de não-antecipação`.

---

### Task 10: Gráfico HTML e comando `chart`

**Files:**
- Create: `src/smc_trader/viz/__init__.py`, `viz/chart.py`
- Modify: `src/smc_trader/cli.py`
- Test: `tests/test_chart.py`

**Interfaces:**
- Consumes: `Analysis` (Task 9), `load_config`, `load_candles`, `analyze`.
- Produces:
  - `build_chart(candles: pd.DataFrame, analysis: Analysis, title: str) -> plotly.graph_objects.Figure`. Contém: candlestick; marcadores dos pivôs; uma anotação por evento (`BOS`/`CHoCH`) com linha no nível desde `level_time`; um retângulo por FVG; um retângulo por zona de `created_at` até `end_time` (ou o último `close_time`), com cor por direção e rótulo `OB`/`FVOB` (+ `sweep` se `swept_liquidity`).
  - Subcomando `chart SYMBOL [--tf M15] [--from ISO] [--to ISO] [--out out/chart.html] [--config PATH] [--data-root PATH]`. O `k` vem de `pivot_k_htf` para `M15` e de `pivot_k_ltf` para `M1`.

- [ ] **Step 1: Escrever os testes que falham.**
  - `test_build_chart_counts`: com a análise do `test_end_to_end_sequence`, o gráfico tem 1 trace `Candlestick`, `len(fig.layout.shapes) == len(fvgs) + len(zones)` e `len(fig.layout.annotations) >= len(events)`.
  - `test_cli_chart_writes_html`: gravar 3 dias de M1 sintético (passeio aleatório) com `save_m1` em `tmp_path`, rodar `main(["chart","XAUUSD","--data-root",str(tmp_path),"--out",str(tmp_path/"c.html")])` → código 0 e arquivo existente que contém `"plotly"`.
- [ ] **Step 2: Rodar e ver falhar** → FAIL.
- [ ] **Step 3: Implementar `build_chart` e o subcomando `chart`.**
- [ ] **Step 4: Rodar a suíte completa:** `uv run pytest -v` → todos PASS.
- [ ] **Step 5: Commit** `feat: gráficos HTML com estrutura, FVG e zonas`.
- [ ] **Step 6: Checkpoint com o Thiago (manual, fim do Plano 1).** Com dados reais baixados da Dukascopy (`uv run smc fetch XAUUSD --from <início> --to <fim>`, Task 3), gerar `uv run smc chart XAUUSD --tf M15 --from <semana> --out out/xauusd.html` para 2 a 3 semanas diferentes e para EURUSD. Ele compara as marcações com a leitura dele (BOS, OB, FVOB, desconto) e aponta divergências. Ajustar `pivot_k_htf` e as regras de zona conforme o retorno. Só depois disso escrever o Plano 2.

---

## Autoavaliação

- **Cobertura da spec (fases 1 a 4):** scaffold, config, fonte Dukascopy, store e reamostragem (Tasks 1–3); ponte Wine/MT5 secundária (Task 11); pivôs e BOS/CHoCH (4–5); OB/FVOB, FVG, sweep, premium/discount e mitigação/invalidação (6–8); visualização e checkpoint (10). Fases 5 a 8 ficam para os Planos 2 e 3.
- **Decisões minhas a sinalizar:** Dukascopy como fonte primária (lado `bid`; spread de custo vindo da configuração no Plano 2, porque o M1 da Dukascopy não traz spread); MT5/Wine como fonte secundária, com regra de fuso padrão NY+7 (comum em corretoras de Forex; configurável); só BOS gera zona; `k = 2` no M1; definição de `swept_liquidity` (sweep entre o candle do OB e o candle do BOS); `leg_time` como a última ocorrência do extremo da correção.
- **Consistência de tipos:** `StructureEvent.leg_time/range_low/range_high/break_time`, `Zone`, `FVG.start_time/formed_at` e `Sweep.side` são usados com os mesmos nomes nas Tasks 5 a 10.

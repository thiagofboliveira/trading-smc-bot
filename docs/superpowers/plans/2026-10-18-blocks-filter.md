# Filtro de tipos de bloco (`blocks_filter`) — plano curto

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir validar só um tipo de bloco (OB, FVOB ou BB) ou qualquer combinação, por uma lista na configuração, `zones.blocks_filter`, respeitada por `analyze()`, pelo gráfico e (no Plano 2) pelo backtest.

**Architecture:** O filtro vive em um só lugar, `analyze()`, que devolve apenas os tipos escolhidos; gráfico e motor leem `Analysis` e herdam o filtro. O CLI do gráfico ganha `--blocks` para sobrescrever a lista sem editar o yaml. A flag `breakers_enabled` (criada no Plano 1b e ainda sem uso fora dos testes) é removida: ligar o breaker passa a ser incluir `BB` na lista.

**Tech Stack:** o mesmo do projeto (Python 3.12, uv, pydantic, plotly, pytest).

**Spec:** `docs/superpowers/specs/2026-10-18-breaker-confluencia-design.md` (configuração do breaker e seção 4, grid do backtest).

## Global Constraints

- `ZoneConfig.blocks_filter: list[Literal["OB", "FVOB", "BB"]]`, padrão `["OB", "FVOB", "BB"]`. Lista vazia é rejeitada; valores repetidos são ignorados e a lista é devolvida na ordem canônica OB, FVOB, BB (assim a ordem digitada não importa e a configuração tem um único hash); valor fora de `OB`/`FVOB`/`BB` é rejeitado.
- Semântica: `OB` = zonas de `kind == "OB"` (sem imbalance); `FVOB` = zonas de `kind == "FVOB"`; `BB` = breakers (`kind == "BREAKER"`). `OB` e `FVOB` são excludentes; `[OB, FVOB]` devolve todas as zonas do tipo OB.
- O breaker continua nascendo das candidatas a OB **independente** do filtro e dos flags `require_discount`/`require_imbalance`: `[BB]` produz breakers mesmo sem nenhuma zona OB/FVOB na saída.
- O filtro só remove itens da **saída**; os resultados dos tipos mantidos não podem mudar em relação ao padrão (nenhum efeito sobre pivôs, eventos, FVGs, sweeps nem sobre o conteúdo de cada zona/breaker). `Analysis.pivots/events/fvgs/sweeps` não são filtrados.
- `breakers_enabled` deixa de existir (a configuração tem `extra="forbid"`, então usá-la passa a ser erro).
- Cada commit termina com uma linha em branco e `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>` (ou o modelo que escreveu o commit). Não rodar formatadores sobre o repositório; editar só os arquivos necessários.

## Review Focus

1. **Lista vazia, valor inválido e repetição** na configuração e no `--blocks` (Tasks 1 e 2).
2. **`[BB]` sem nenhuma zona OB/FVOB na saída** ainda devolve os breakers; `[OB, FVOB]` devolve zonas e nenhum breaker (Task 1).
3. **Reuso das candidatas:** o atalho de `analyze` que reaproveita a lista de zonas como candidatas quando os dois filtros de entrada estão desligados deve usar a lista **antes** do filtro por tipo, senão `[FVOB]` esconderia as origens de breakers (Task 1).
4. **`--blocks` inválido** no CLI termina com código 2 e mensagem, sem gerar arquivo (Task 2).

---

### Task 1: `blocks_filter` na configuração e em `analyze`

**Files:**
- Modify: `src/smc_trader/config.py` (`ZoneConfig`), `src/smc_trader/analysis.py`, `config/default.yaml`, `docs/superpowers/specs/2026-10-18-breaker-confluencia-design.md`
- Test: `tests/test_config.py`, `tests/test_analysis.py`

**Interfaces:**
- Produces:
  - `ZoneConfig.blocks_filter: list[Literal["OB", "FVOB", "BB"]]`, padrão `["OB", "FVOB", "BB"]`, com validador (não vazio, sem repetições, devolve na ordem canônica OB, FVOB, BB: assim a ordem digitada não importa e a configuração tem um único hash). O campo `breakers_enabled` é removido de `ZoneConfig`.
  - `analyze(candles, k, zones_cfg)` aplica o filtro: `Analysis.zones` contém só as zonas de `kind` em `blocks_filter` (`OB`/`FVOB`); `Analysis.breakers` é `[]` quando `"BB"` não está na lista. As candidatas a OB para os breakers vêm da lista de zonas **antes** do filtro por tipo (reaproveitada quando `require_discount` e `require_imbalance` já são ambos falsos; caso contrário, reconstruída com os dois filtros desligados).

- [ ] **Step 1: Escrever os testes que falham.**
  - `tests/test_config.py`: `test_blocks_filter_default` (`ZoneConfig().blocks_filter == ["OB", "FVOB", "BB"]`); `test_blocks_filter_validation` (`ZoneConfig(blocks_filter=[])` e `ZoneConfig(blocks_filter=["XX"])` levantam `ValidationError`; `ZoneConfig(blocks_filter=["OB", "OB", "BB"]).blocks_filter == ["OB", "BB"]`); `test_breakers_enabled_is_gone` (`ZoneConfig(breakers_enabled=False)` levanta `ValidationError`); em `test_default_config_loads`, trocar a asserção de `breakers_enabled` por `cfg.zones.blocks_filter == ["OB", "FVOB", "BB"]`; remover `breakers_enabled` de `test_breaker_defaults`.
  - `tests/test_analysis.py` (séries já existentes: `SERIE_A_ROWS[0:6] + BREAKER_TAIL` dá 1 zona `kind == "OB"` e 1 breaker; `SERIE_A_ROWS[0:5] + [(12.3, 13.5, 12.2, 13.2)]` com `k=1` dá 1 zona `kind == "FVOB"` e nenhum breaker): `test_blocks_filter_selects_kinds` com
    - `[OB]` na série do breaker → `zones` com 1 zona OB e `breakers == []`; `[BB]` → `zones == []` e `len(breakers) == 1` (a origem OB some da saída, mas o breaker existe); `[OB, FVOB]` → 1 zona e `breakers == []`; padrão → 1 zona e 1 breaker;
    - `[FVOB]` na série FVOB → 1 zona FVOB; `[OB]` na mesma série → `zones == []`;
    - `[FVOB, BB]` na série do breaker → `zones == []` e `len(breakers) == 1` (garante que o filtro por tipo não esconde as origens dos breakers).
  - Trocar `test_breakers_disabled` (usa `breakers_enabled=False`) por `ZoneConfig(blocks_filter=["OB", "FVOB"])` → `breakers == []`.
  - O resultado do padrão não pode mudar: as suítes existentes (inclusive os testes de não-antecipação) continuam passando sem alteração de expectativas.
- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/test_config.py tests/test_analysis.py -v` → FAIL.
- [ ] **Step 3: Implementar** o campo e o validador em `ZoneConfig`, remover `breakers_enabled` (e seu uso em `analyze`), aplicar o filtro em `analyze` (candidatas antes do filtro por tipo), atualizar `config/default.yaml` (trocar `breakers_enabled: true` por `blocks_filter: [OB, FVOB, BB]`), e atualizar a spec: na lista de configuração do breaker, trocar `breakers_enabled: bool = True` por `blocks_filter` e acrescentar um parágrafo curto "Filtro de tipos de bloco" (semântica de `OB`/`FVOB`/`BB` como nas Global Constraints; no Plano 2 cada valor de `blocks_filter` é uma execução do grid).
- [ ] **Step 4: Rodar e ver passar:** `uv run pytest -q` → todos PASS.
- [ ] **Step 5: Commit** `feat: blocks_filter escolhe os tipos de bloco (OB, FVOB, BB)`.

---

### Task 2: `--blocks` no `smc chart`

**Files:**
- Modify: `src/smc_trader/cli.py`
- Test: `tests/test_chart.py`

**Interfaces:**
- Consumes: `ZoneConfig.blocks_filter` e `analyze` (Task 1).
- Produces: o subcomando `chart` aceita `--blocks OB,FVOB,BB` (lista separada por vírgulas, maiúsculas ou minúsculas), que **sobrescreve** `cfg.zones.blocks_filter` apenas para essa execução. A sobrescrita passa pela validação de `ZoneConfig` (reconstruir o modelo, não `model_copy(update=...)`, que não valida). Valor inválido, lista vazia ou repetição só de lixo → mensagem em stderr, código 2, nenhum arquivo gerado.

- [ ] **Step 1: Escrever os testes que falham** em `tests/test_chart.py` (reaproveitar o padrão de `test_cli_chart_writes_html`, com M1 sintético em `tmp_path`):
  - `test_cli_chart_blocks_option_overrides_filter`: com `monkeypatch` envolvendo `smc_trader.cli.analyze` (grava o `zones_cfg` recebido e chama o original), `main(["chart", "XAUUSD", "--data-root", ..., "--out", ..., "--blocks", "fvob,bb"])` devolve 0 e o `zones_cfg.blocks_filter` recebido é `["FVOB", "BB"]`.
  - `test_cli_chart_blocks_invalid`: `--blocks XX` e `--blocks ""` devolvem 2, a mensagem em stderr cita `--blocks`, e o arquivo de saída não existe.
  - `test_cli_chart_without_blocks_uses_config`: sem `--blocks`, com `--config` apontando para uma cópia de `config/default.yaml` com `blocks_filter: [OB]`, o `zones_cfg.blocks_filter` recebido é `["OB"]`.
- [ ] **Step 2: Rodar e ver falhar** → FAIL.
- [ ] **Step 3: Implementar** a opção no parser do `chart`, a conversão (maiúsculas, divisão por vírgula, descarte de itens vazios) e a validação via `ZoneConfig`; capturar `ValidationError` para a mensagem e o código 2. O `cli.py` deve importar `analyze` pelo nome (`from smc_trader.analysis import analyze`) se ainda não o fizer.
- [ ] **Step 4: Rodar e ver passar:** `uv run pytest -q` → todos PASS.
- [ ] **Step 5: Verificação manual** (controlador): `uv run smc chart XAUUSD --tf M15 --from 2026-10-05 --to 2026-10-17 --blocks FVOB --out out/xauusd_fvob.html` e o mesmo com `--blocks BB`; contar com um script descartável as zonas de cada tipo.
- [ ] **Step 6: Commit** `feat: smc chart --blocks sobrescreve blocks_filter`.

---

## Autoavaliação

- **Cobertura:** campo e validação (Task 1), filtro em `analyze` com a regra das candidatas (Task 1), remoção de `breakers_enabled` (Task 1), `default.yaml` e spec (Task 1), `--blocks` (Task 2). A execução do grid por valor de `blocks_filter` é do Plano 2.
- **Consistência:** os nomes `OB`/`FVOB`/`BB` (configuração) mapeiam para os `kind` `"OB"`, `"FVOB"` e `"BREAKER"` (código); `Analysis` não muda de forma.

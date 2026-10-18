"""Equivalência dos detectores de `src/` com o oráculo congelado `reference_impl`."""

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from helpers import candles_from_ohlc, random_walk_candles
from reference_impl import (
    ref_build_breakers,
    ref_build_zones,
    ref_find_fvgs,
    ref_find_pivots,
)
from smc_trader.config import ZoneConfig
from smc_trader.data.store import load_candles
from smc_trader.structure.market_structure import detect_structure
from smc_trader.structure.pivots import find_pivots
from smc_trader.zones.breaker import build_breakers
from smc_trader.zones.fvg import find_fvgs
from smc_trader.zones.liquidity import find_sweeps
from smc_trader.zones.orderblock import build_zones

REAL_DATA = Path("data")
REAL_FILE = REAL_DATA / "XAUUSD_M1_dukascopy.parquet"


def tied_candles(n: int, seed: int, tf: str = "M15") -> pd.DataFrame:
    """Passeio aleatório com preços em múltiplos de 0,5 (muitos empates)."""
    rng = np.random.default_rng(seed)
    close = np.round((50 + np.cumsum(rng.normal(0, 1, n))) * 2) / 2
    open_ = np.concatenate([[50.0], close[:-1]])
    high = np.maximum(open_, close) + 0.5 * rng.integers(0, 2, n)
    low = np.minimum(open_, close) - 0.5 * rng.integers(0, 2, n)
    return candles_from_ohlc(list(zip(open_, high, low, close)), tf)


GENERATORS = {"walk": random_walk_candles, "tied": tied_candles}
CASES = [
    pytest.param(gen, seed, n, k, id=f"{gen}-s{seed}-n{n}-k{k}")
    for gen in GENERATORS
    for seed in (1, 2, 3)
    for n in (400, 1500)
    for k in (2, 3)
]

# Acumuladores de não trivialidade (conferidos por `test_reference_is_not_vacuous`).
SEEN = {"zones": 0, "breakers": 0, "breakers_choch": 0, "breakers_age1": 0}


def make(gen: str, seed: int, n: int) -> pd.DataFrame:
    return GENERATORS[gen](n, seed)


def pipeline(candles: pd.DataFrame, k: int, cfg: ZoneConfig | None = None):
    """Pivôs, eventos, FVGs e sweeps calculados pelas funções de `src/`."""
    pivots = find_pivots(candles, k)
    events = detect_structure(candles, pivots)
    fvgs = find_fvgs(candles, (cfg or ZoneConfig()).fvg_min_size)
    sweeps = find_sweeps(candles, pivots)
    return pivots, events, fvgs, sweeps


@pytest.mark.parametrize("gen,seed,n,k", CASES)
def test_find_pivots_equivalent(gen, seed, n, k):
    c = make(gen, seed, n)
    expected = ref_find_pivots(c, k)
    assert len(expected) > 0
    pd.testing.assert_frame_equal(find_pivots(c, k), expected)


@pytest.mark.parametrize("gen,seed,n,k", CASES)
def test_find_fvgs_equivalent(gen, seed, n, k):
    c = make(gen, seed, n)
    base = ref_find_fvgs(c)
    assert len(base) > 0
    assert find_fvgs(c) == base
    # Mediana inferior: sempre um tamanho que existe de fato entre os gaps.
    median = sorted(f.high - f.low for f in base)[(len(base) - 1) // 2]
    expected = ref_find_fvgs(c, median)
    # O limite é a mediana: gaps exatamente iguais a ele entram, os menores saem.
    assert 0 < len(expected) <= len(base)
    if gen == "walk":
        assert len(expected) < len(base)
    assert any(f.high - f.low == median for f in expected)
    assert find_fvgs(c, median) == expected


ZONE_CFGS = {
    "default": {},
    "no_discount": {"require_discount": False},
    "imbalance": {"require_imbalance": True},
    "body": {"use_body": True},
}


@pytest.mark.parametrize("gen,seed,n,k", CASES)
@pytest.mark.parametrize("cfg_name", ZONE_CFGS)
def test_build_zones_equivalent(gen, seed, n, k, cfg_name):
    c = make(gen, seed, n)
    cfg = ZoneConfig(**ZONE_CFGS[cfg_name])
    _, events, fvgs, sweeps = pipeline(c, k)
    expected = ref_build_zones(c, events, fvgs, sweeps, cfg)
    SEEN["zones"] += len(expected)
    if n == 1500 and cfg_name == "no_discount":
        assert len(expected) > 0
    assert build_zones(c, events, fvgs, sweeps, cfg) == expected


BREAKER_CFGS = {
    "default": {},
    "no_imbalance": {"breaker_require_imbalance": False},
    "choch": {"breaker_require_choch": True},
    "age_none": {"breaker_max_age": None},
    "age_1": {"breaker_max_age": 1},
}


@pytest.mark.parametrize("gen,seed,n,k", CASES)
@pytest.mark.parametrize("cfg_name", BREAKER_CFGS)
def test_build_breakers_equivalent(gen, seed, n, k, cfg_name):
    c = make(gen, seed, n)
    cfg = ZoneConfig(**BREAKER_CFGS[cfg_name])
    _, events, fvgs, sweeps = pipeline(c, k)
    # Candidatas com os filtros de entrada desligados, como em `analyze`.
    open_cfg = ZoneConfig(require_discount=False, require_imbalance=False)
    zones = build_zones(c, events, fvgs, sweeps, open_cfg)
    expected = ref_build_breakers(c, zones, events, fvgs, sweeps, cfg)
    SEEN["breakers"] += len(expected)
    if cfg_name == "choch":
        SEEN["breakers_choch"] += len(expected)
    if cfg_name == "age_1":
        SEEN["breakers_age1"] += len(expected)
    if n == 1500 and cfg_name in ("no_imbalance", "age_none"):
        assert len(expected) > 0
    assert build_breakers(c, zones, events, fvgs, sweeps, cfg) == expected


@pytest.mark.parametrize("n", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("gen", GENERATORS)
def test_edge_frames_equivalent(gen, n):
    c = make(gen, 1, 4).iloc[:n]
    assert len(c) == n
    for k in (1, 2, 3):
        pd.testing.assert_frame_equal(find_pivots(c, k), ref_find_pivots(c, k))
    assert find_fvgs(c) == ref_find_fvgs(c)
    assert find_fvgs(c, 0.1) == ref_find_fvgs(c, 0.1)
    cfgs = [ZoneConfig(), ZoneConfig(breaker_require_imbalance=False)]
    for k in (1, 2):
        _, events, fvgs, sweeps = pipeline(c, k)
        for cfg in cfgs:
            zones = ref_build_zones(c, events, fvgs, sweeps, cfg)
            assert build_zones(c, events, fvgs, sweeps, cfg) == zones
            assert build_breakers(c, zones, events, fvgs, sweeps, cfg) == (
                ref_build_breakers(c, zones, events, fvgs, sweeps, cfg)
            )
    # Zonas vazias com candles não vazios também devolvem o mesmo.
    for cfg in cfgs:
        assert build_breakers(c, [], [], [], [], cfg) == ref_build_breakers(
            c, [], [], [], [], cfg
        )


def test_real_data_equivalent():
    if not REAL_FILE.exists():
        pytest.skip("sem data/XAUUSD_M1_dukascopy.parquet")
    c = load_candles(
        REAL_DATA,
        "XAUUSD",
        "M15",
        pd.Timestamp("2026-09-21", tz="UTC"),
        pd.Timestamp("2026-10-05", tz="UTC"),
    )
    assert len(c) > 500
    for k in (2, 3):
        pivots = find_pivots(c, k)
        expected_pivots = ref_find_pivots(c, k)
        assert len(expected_pivots) > 0
        pd.testing.assert_frame_equal(pivots, expected_pivots)
        _, events, fvgs, sweeps = pipeline(c, k)
        expected_fvgs = ref_find_fvgs(c)
        assert len(expected_fvgs) > 0
        assert fvgs == expected_fvgs
        for cfg in (ZoneConfig(), ZoneConfig(breaker_require_imbalance=False)):
            zones = ref_build_zones(c, events, fvgs, sweeps, cfg)
            assert build_zones(c, events, fvgs, sweeps, cfg) == zones
            open_cfg = ZoneConfig(require_discount=False, require_imbalance=False)
            cands = ref_build_zones(c, events, fvgs, sweeps, open_cfg)
            assert len(cands) > 0
            breakers = ref_build_breakers(c, cands, events, fvgs, sweeps, cfg)
            assert build_breakers(c, cands, events, fvgs, sweeps, cfg) == breakers


def test_reference_is_not_vacuous():
    """Fecha o ciclo: a referência produziu zonas e breakers de cada variante."""
    if not SEEN["zones"] or not SEEN["breakers"]:
        pytest.skip("rode junto com os testes de zonas e breakers")
    assert SEEN["zones"] > 0
    assert SEEN["breakers"] > 0
    assert SEEN["breakers_choch"] > 0
    assert SEEN["breakers_age1"] > 0

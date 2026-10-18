"""Pipeline de análise SMC.

Contrato para o Plan 2: rode `analyze()` uma vez no frame completo e filtre cada
saída por tempo (pivôs por `confirmed_at`, eventos/zonas por `time`/`created_at`,
FVGs por `formed_at`, sweeps por `confirmed_at`, fim de zona por `end_time`).
Sob esse filtro o resultado não tem look-ahead (verificado por testes). Uso em
janela exige aquecimento: o primeiro rompimento da janela é rotulado BOS
(trend None).
"""
from dataclasses import dataclass

import pandas as pd

from smc_trader.config import ZoneConfig
from smc_trader.structure.market_structure import StructureEvent, detect_structure
from smc_trader.structure.pivots import find_pivots
from smc_trader.zones.fvg import FVG, find_fvgs
from smc_trader.zones.liquidity import Sweep, find_sweeps
from smc_trader.zones.orderblock import Zone, build_zones


@dataclass
class Analysis:
    pivots: pd.DataFrame
    events: list[StructureEvent]
    fvgs: list[FVG]
    sweeps: list[Sweep]
    zones: list[Zone]


def analyze(candles: pd.DataFrame, k: int, zones_cfg: ZoneConfig) -> Analysis:
    pivots = find_pivots(candles, k)
    if candles.empty:
        return Analysis(pivots, [], [], [], [])
    events = detect_structure(candles, pivots)
    fvgs = find_fvgs(candles, zones_cfg.fvg_min_size)
    sweeps = find_sweeps(candles, pivots)
    zones = build_zones(candles, events, fvgs, sweeps, zones_cfg)
    return Analysis(pivots, events, fvgs, sweeps, zones)

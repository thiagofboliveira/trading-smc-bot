from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from smc_trader.config import ZoneConfig
from smc_trader.structure.market_structure import StructureEvent
from smc_trader.zones.fvg import FVG
from smc_trader.zones.liquidity import Sweep
from smc_trader.zones.premium_discount import in_discount


@dataclass(frozen=True)
class Zone:
    """Zona OB, FVOB ou BREAKER.

    `end_time`/`end_reason` só são conhecidos quando `t >= end_time`; quem consome
    deve filtrá-los por tempo (ver `is_active_at`). O toque é julgado na resolução
    do timeframe da própria zona (M15), pelo `close_time` do primeiro candle que
    toca a zona, a partir de `created_at` (um toque entre o candle de origem e a
    criação não conta).

    Há duas vidas:
    - OB/FVOB: terminam `mitigated` no primeiro toque, ou `invalidated` por um
      CHoCH contra a zona.
    - BREAKER: termina no primeiro toque; `invalidated` se o candle do toque fecha
      além do lado de origem, senão `mitigated`.
    """

    direction: Literal["long", "short"]
    kind: Literal["OB", "FVOB", "BREAKER"]
    high: float
    low: float
    # OB/FVOB: abertura do candle do OB. BREAKER: abertura do candle do OB de origem.
    candle_time: pd.Timestamp
    # OB/FVOB: close_time do candle do BOS. BREAKER: instante em que o breaker passa a valer.
    created_at: pd.Timestamp
    range_low: float
    range_high: float
    in_discount: bool  # prêmio, para venda
    swept_liquidity: bool
    end_time: pd.Timestamp | None
    end_reason: Literal["mitigated", "invalidated"] | None

    def is_active_at(self, t: pd.Timestamp) -> bool:
        return self.created_at <= t and (self.end_time is None or self.end_time > t)


def _index_fvgs(fvgs: list[FVG]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    by_dir: dict[str, list[FVG]] = {"up": [], "down": []}
    for f in fvgs:
        if f.direction in by_dir:
            by_dir[f.direction].append(f)
    result = {}
    for d, items in by_dir.items():
        starts = np.array([f.start_time for f in items], dtype=object)
        forms = np.array([f.formed_at for f in items], dtype=object)
        result[d] = (starts, forms)
    return result


def _has_fvg(
    fvg_index: dict[str, tuple[np.ndarray, np.ndarray]],
    direction: str,
    candle_time: pd.Timestamp,
    event_time: pd.Timestamp,
) -> bool:
    starts, forms = fvg_index[direction]
    if starts.size == 0:
        return False
    idx = int(np.searchsorted(starts, candle_time, side="left"))
    n = starts.size
    for i in range(idx, n):
        if starts[i] > event_time:
            break
        if forms[i] <= event_time:
            return True
    return False


def _index_sweeps(sweeps: list[Sweep]) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    by_side: dict[str, list[Sweep]] = {"high": [], "low": []}
    for s in sweeps:
        if s.side in by_side:
            by_side[s.side].append(s)
    result = {}
    for side, items in by_side.items():
        times = np.array([s.sweep_time for s in items], dtype=object)
        confirms = np.array([s.confirmed_at for s in items], dtype=object)
        result[side] = (times, confirms)
    return result


def _has_sweep(
    sweep_index: dict[str, tuple[np.ndarray, np.ndarray]],
    side: str,
    candle_time: pd.Timestamp,
    event_time: pd.Timestamp,
) -> bool:
    times, confirms = sweep_index[side]
    if times.size == 0:
        return False
    idx = int(np.searchsorted(times, candle_time, side="left"))
    n = times.size
    for i in range(idx, n):
        if times[i] > event_time:
            break
        if confirms[i] <= event_time:
            return True
    return False


def _index_chochs(events: list[StructureEvent]) -> dict[str, np.ndarray]:
    by_dir: dict[str, list[pd.Timestamp]] = {"up": [], "down": []}
    for e in events:
        if e.kind == "CHoCH" and e.direction in by_dir:
            by_dir[e.direction].append(e.time)
    return {d: np.array(times, dtype=object) for d, times in by_dir.items()}


def _lifetime(
    index: pd.DatetimeIndex,
    close_time: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    choch_index: dict[str, np.ndarray],
    direction: str,
    zone_low: float,
    zone_high: float,
    created_at: pd.Timestamp,
) -> tuple[pd.Timestamp | None, Literal["mitigated", "invalidated"] | None]:
    start_idx = int(index.searchsorted(created_at, side="left"))
    n = len(index)
    if start_idx < n:
        if direction == "long":
            touched = low[start_idx:] <= zone_high
        else:
            touched = high[start_idx:] >= zone_low
        hits = np.flatnonzero(touched)
        mitigated = (
            pd.Timestamp(close_time[start_idx + int(hits[0])])
            if hits.size > 0
            else None
        )
    else:
        mitigated = None

    against = "down" if direction == "long" else "up"
    against_times = choch_index[against]
    if against_times.size > 0:
        c_idx = int(np.searchsorted(against_times, created_at, side="right"))
        invalidated = (
            pd.Timestamp(against_times[c_idx]) if c_idx < against_times.size else None
        )
    else:
        invalidated = None

    if mitigated is not None and (invalidated is None or mitigated <= invalidated):
        return mitigated, "mitigated"
    if invalidated is not None:
        return invalidated, "invalidated"
    return None, None


def build_zones(
    candles: pd.DataFrame,
    events: list[StructureEvent],
    fvgs: list[FVG],
    sweeps: list[Sweep],
    cfg: ZoneConfig,
) -> list[Zone]:
    """Zonas OB/FVOB geradas por BOS, sem look-ahead (válidas a partir de created_at)."""
    if candles.empty:
        return []
    index = candles.index
    open_ = candles["open"].to_numpy()
    high = candles["high"].to_numpy()
    low = candles["low"].to_numpy()
    close = candles["close"].to_numpy()
    close_time = candles["close_time"].to_numpy()

    fvg_index = _index_fvgs(fvgs)
    sweep_index = _index_sweeps(sweeps)
    choch_index = _index_chochs(events)

    zones: list[Zone] = []
    seen: set[tuple[str, pd.Timestamp]] = set()
    for event in events:
        if event.kind != "BOS":
            continue
        long = event.direction == "up"
        direction = "long" if long else "short"
        first, last = index.get_loc(event.level_time), index.get_loc(event.leg_time)
        pos = next(
            (
                i
                for i in range(last, first - 1, -1)
                if (close[i] < open_[i] if long else close[i] > open_[i])
            ),
            None,
        )
        if pos is None:
            continue
        candle_time = index[pos]
        if (direction, candle_time) in seen:
            continue
        seen.add((direction, candle_time))

        if cfg.use_body:
            o_pos, c_pos = open_[pos], close[pos]
            z_low, z_high = (o_pos, c_pos) if o_pos < c_pos else (c_pos, o_pos)
        else:
            z_low, z_high = low[pos], high[pos]
        z_low, z_high = float(z_low), float(z_high)

        has_fvg = _has_fvg(fvg_index, event.direction, candle_time, event.time)
        if cfg.require_imbalance and not has_fvg:
            continue
        discount = in_discount(
            direction, z_low, z_high, event.range_low, event.range_high
        )
        if cfg.require_discount and not discount:
            continue
        sweep_side = "low" if long else "high"
        swept = _has_sweep(sweep_index, sweep_side, candle_time, event.time)

        end_time, end_reason = _lifetime(
            index,
            close_time,
            high,
            low,
            choch_index,
            direction,
            z_low,
            z_high,
            event.time,
        )
        zones.append(
            Zone(
                direction=direction,
                kind="FVOB" if has_fvg else "OB",
                high=z_high,
                low=z_low,
                candle_time=candle_time,
                created_at=event.time,
                range_low=event.range_low,
                range_high=event.range_high,
                in_discount=discount,
                swept_liquidity=swept,
                end_time=end_time,
                end_reason=end_reason,
            )
        )
    zones.sort(key=lambda z: (z.created_at, z.candle_time))
    return zones

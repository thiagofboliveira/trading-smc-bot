from dataclasses import dataclass
from typing import Literal

import pandas as pd

from smc_trader.config import ZoneConfig
from smc_trader.structure.market_structure import StructureEvent
from smc_trader.zones.fvg import FVG
from smc_trader.zones.liquidity import Sweep
from smc_trader.zones.premium_discount import in_discount


@dataclass(frozen=True)
class Zone:
    direction: Literal["long", "short"]
    kind: Literal["OB", "FVOB"]
    high: float
    low: float
    candle_time: pd.Timestamp  # abertura do candle do OB
    created_at: pd.Timestamp  # close_time do candle do BOS
    range_low: float
    range_high: float
    in_discount: bool  # prêmio, para venda
    swept_liquidity: bool
    end_time: pd.Timestamp | None
    end_reason: Literal["mitigated", "invalidated"] | None


def build_zones(
    candles: pd.DataFrame,
    events: list[StructureEvent],
    fvgs: list[FVG],
    sweeps: list[Sweep],
    cfg: ZoneConfig,
) -> list[Zone]:
    """Zonas OB/FVOB geradas por BOS, sem look-ahead (válidas a partir de created_at)."""
    index = candles.index
    open_ = candles["open"].to_numpy()
    close = candles["close"].to_numpy()
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

        row = candles.iloc[pos]
        if cfg.use_body:
            low, high = min(row.open, row.close), max(row.open, row.close)
        else:
            low, high = row.low, row.high
        low, high = float(low), float(high)

        has_fvg = any(
            f.direction == event.direction
            and f.start_time >= candle_time
            and f.formed_at <= event.time
            for f in fvgs
        )
        if cfg.require_imbalance and not has_fvg:
            continue
        discount = in_discount(direction, low, high, event.range_low, event.range_high)
        if cfg.require_discount and not discount:
            continue
        sweep_side = "low" if long else "high"
        swept = any(
            s.side == sweep_side and candle_time <= s.sweep_time <= event.break_time
            for s in sweeps
        )
        end_time, end_reason = _lifetime(
            candles, events, direction, low, high, event.time
        )
        zones.append(
            Zone(
                direction=direction,
                kind="FVOB" if has_fvg else "OB",
                high=high,
                low=low,
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


def _lifetime(
    candles: pd.DataFrame,
    events: list[StructureEvent],
    direction: str,
    low: float,
    high: float,
    created_at: pd.Timestamp,
) -> tuple[pd.Timestamp | None, Literal["mitigated", "invalidated"] | None]:
    after = candles[candles.index >= created_at]
    touched = after["low"] <= high if direction == "long" else after["high"] >= low
    mitigated = after["close_time"][touched].iloc[0] if touched.any() else None
    against = "down" if direction == "long" else "up"
    invalidated = min(
        (
            e.time
            for e in events
            if e.kind == "CHoCH" and e.direction == against and e.time > created_at
        ),
        default=None,
    )
    if mitigated is not None and (invalidated is None or mitigated <= invalidated):
        return mitigated, "mitigated"
    if invalidated is not None:
        return invalidated, "invalidated"
    return None, None

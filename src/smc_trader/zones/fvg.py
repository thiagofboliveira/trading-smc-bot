from dataclasses import dataclass
from typing import Literal

import pandas as pd


@dataclass(frozen=True)
class FVG:
    direction: Literal["up", "down"]
    low: float
    high: float
    start_time: pd.Timestamp  # open time of candle 1
    formed_at: pd.Timestamp  # close_time of candle 3 (no look-ahead)


def find_fvgs(candles: pd.DataFrame, min_size: float = 0.0) -> list[FVG]:
    """Three-candle imbalances, ordered by formed_at."""
    fvgs: list[FVG] = []
    high = candles["high"].to_numpy()
    low = candles["low"].to_numpy()
    for i in range(2, len(candles)):
        if high[i - 2] < low[i]:
            direction, lo, hi = "up", float(high[i - 2]), float(low[i])
        elif low[i - 2] > high[i]:
            direction, lo, hi = "down", float(high[i]), float(low[i - 2])
        else:
            continue
        if hi - lo >= min_size:
            fvgs.append(
                FVG(direction, lo, hi, candles.index[i - 2], candles["close_time"].iloc[i])
            )
    return fvgs

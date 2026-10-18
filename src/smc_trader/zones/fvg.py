from dataclasses import dataclass
from typing import Literal

import numpy as np
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
    n = len(candles)
    if n < 3:
        return []
    high = candles["high"].to_numpy()
    low = candles["low"].to_numpy()
    h0 = high[:-2]
    l0 = low[:-2]
    h2 = high[2:]
    l2 = low[2:]

    is_up = (h0 < l2) & ((l2 - h0) >= min_size)
    is_down = (l0 > h2) & ((l0 - h2) >= min_size)
    is_fvg = is_up | is_down
    hits = np.flatnonzero(is_fvg)
    if hits.size == 0:
        return []

    index = candles.index
    close_time = candles["close_time"].to_numpy()

    fvgs: list[FVG] = []
    for idx in hits:
        i = idx + 2
        if is_up[idx]:
            direction, lo, hi = "up", float(h0[idx]), float(l2[idx])
        else:
            direction, lo, hi = "down", float(h2[idx]), float(l0[idx])
        fvgs.append(
            FVG(direction, lo, hi, index[idx], pd.Timestamp(close_time[i]))
        )
    return fvgs

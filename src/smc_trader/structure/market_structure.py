from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class StructureEvent:
    kind: Literal["BOS", "CHoCH"]
    direction: Literal["up", "down"]
    time: pd.Timestamp  # close_time do candle que rompeu
    break_time: pd.Timestamp  # abertura do candle que rompeu
    level: float
    level_time: pd.Timestamp  # abertura do candle do pivô rompido
    leg_time: pd.Timestamp  # abertura do candle do extremo da correção
    range_low: float
    range_high: float


class _Level:
    """Último pivô ativo de um lado, com marca de consumido."""

    def __init__(self, pivots: pd.DataFrame, index: pd.DatetimeIndex):
        ordered = pivots.sort_values(["confirmed_at", "time"])
        self._queue = [
            (row.confirmed_at, row.time, float(row.price), index.get_loc(row.time))
            for row in ordered.itertuples(index=False)
        ]
        self._next = 0
        self.current: tuple[pd.Timestamp, float, int] | None = None  # (time, price, pos)
        self.consumed = False

    def activate(self, open_time: pd.Timestamp) -> None:
        while self._next < len(self._queue) and self._queue[self._next][0] <= open_time:
            _, time, price, pos = self._queue[self._next]
            self._next += 1
            if self.current is None or time > self.current[0]:
                self.current = (time, price, pos)
                self.consumed = False

    def available(self) -> tuple[pd.Timestamp, float, int] | None:
        return None if self.consumed else self.current


def detect_structure(candles: pd.DataFrame, pivots: pd.DataFrame) -> list[StructureEvent]:
    """BOS/CHoCH por fechamento além do último pivô confirmado (sem look-ahead).

    Um pivô só fica ativo para candles com abertura >= `confirmed_at`.
    """
    if candles.empty or pivots.empty:
        return []
    index = candles.index
    high = candles["high"].to_numpy()
    low = candles["low"].to_numpy()
    close = candles["close"].to_numpy()
    close_time = candles["close_time"]
    tops = _Level(pivots[pivots["kind"] == "high"], index)
    bottoms = _Level(pivots[pivots["kind"] == "low"], index)

    events: list[StructureEvent] = []
    trend: str | None = None
    for j in range(len(candles)):
        tops.activate(index[j])
        bottoms.activate(index[j])
        top, bottom = tops.available(), bottoms.available()
        if top is not None and close[j] > top[1]:
            direction, (level_time, level, pos), side = "up", top, tops
        elif bottom is not None and close[j] < bottom[1]:
            direction, (level_time, level, pos), side = "down", bottom, bottoms
        else:
            continue
        side.consumed = True

        leg_high = high[pos + 1 : j + 1]
        leg_low = low[pos + 1 : j + 1]
        if direction == "up":
            extreme = leg_low.min()
            leg_pos = pos + 1 + int(np.flatnonzero(leg_low == extreme)[-1])
            range_low, range_high = float(extreme), float(high[pos : j + 1].max())
        else:
            extreme = leg_high.max()
            leg_pos = pos + 1 + int(np.flatnonzero(leg_high == extreme)[-1])
            range_low, range_high = float(low[pos : j + 1].min()), float(extreme)

        kind = "BOS" if trend in (None, direction) else "CHoCH"
        trend = direction
        events.append(
            StructureEvent(
                kind=kind,
                direction=direction,
                time=close_time.iloc[j],
                break_time=index[j],
                level=level,
                level_time=level_time,
                leg_time=index[leg_pos],
                range_low=range_low,
                range_high=range_high,
            )
        )
    return events

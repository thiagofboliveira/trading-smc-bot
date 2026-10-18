from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Sweep:
    side: Literal["low", "high"]  # "low" = liquidez de fundo varrida (contexto altista)
    pivot_time: pd.Timestamp
    pivot_price: float
    sweep_time: pd.Timestamp  # abertura do candle que varreu
    extreme: float  # extremo do pavio


def find_sweeps(candles: pd.DataFrame, pivots: pd.DataFrame) -> list[Sweep]:
    """Sweeps de liquidez sobre pivôs confirmados, sem look-ahead.

    Só candles com open_time >= confirmed_at são considerados. O primeiro candle
    cujo pavio ultrapassa o preço do pivô decide: fechou de volta do lado
    original => sweep; fechou além => rompimento. O pivô fica consumido.
    """
    if len(candles) == 0 or len(pivots) == 0:
        return []
    times = candles.index
    high = candles["high"].to_numpy()
    low = candles["low"].to_numpy()
    close = candles["close"].to_numpy()
    sweeps: list[Sweep] = []
    for p in pivots.itertuples(index=False):
        start = times.searchsorted(p.confirmed_at, side="left")
        if p.kind == "low":
            beyond = low[start:] < p.price
        else:
            beyond = high[start:] > p.price
        if not beyond.any():
            continue
        j = start + int(np.argmax(beyond))
        if p.kind == "low":
            swept, extreme = close[j] > p.price, low[j]
        else:
            swept, extreme = close[j] < p.price, high[j]
        if swept:
            sweeps.append(
                Sweep(p.kind, p.time, float(p.price), times[j], float(extreme))
            )
    sweeps.sort(key=lambda s: s.sweep_time)
    return sweeps

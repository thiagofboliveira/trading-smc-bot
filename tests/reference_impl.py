"""Implementações de referência (oráculo) dos detectores, congeladas.

Cópias LITERAIS do código de `HEAD` (commit 96a246c) das funções `find_pivots`,
`find_fvgs`, `build_zones` e `build_breakers` (com seus helpers), obtidas com
`git show 96a246c:<arquivo>` e alteradas apenas nos nomes (prefixo `ref_` /
`_ref_`). Este arquivo NÃO deve ser editado: ele é a definição de "mesmo
resultado" usada por `tests/test_equivalence.py` quando os detectores de `src/`
forem otimizados. Dataclasses (`Zone`, `FVG`) e `in_discount` são importadas de
`src/`, pois não são relevantes para desempenho.
"""

from typing import Literal

import numpy as np
import pandas as pd

from smc_trader.config import ZoneConfig
from smc_trader.structure.market_structure import StructureEvent
from smc_trader.zones.fvg import FVG
from smc_trader.zones.liquidity import Sweep
from smc_trader.zones.orderblock import Zone
from smc_trader.zones.premium_discount import in_discount

_REF_PIVOT_COLUMNS = ["time", "kind", "price", "confirmed_at"]


def ref_find_pivots(candles: pd.DataFrame, k: int) -> pd.DataFrame:
    """Pivôs de swing confirmados sem look-ahead.

    Topo em i: high[i] > max(high[i-k:i]) e high[i] >= max(high[i+1:i+k+1]).
    Fundo: espelho com < e <=. `confirmed_at` é o close_time do candle i+k.
    """
    if k < 1:
        raise ValueError("k must be >= 1")
    n = len(candles)
    records = []
    if n >= 2 * k + 1:
        high = candles["high"].to_numpy()
        low = candles["low"].to_numpy()
        times = candles.index
        close_times = candles["close_time"]
        for i in range(k, n - k):
            confirmed = close_times.iloc[i + k]
            if high[i] > high[i - k : i].max() and high[i] >= high[i + 1 : i + k + 1].max():
                records.append((times[i], "high", float(high[i]), confirmed))
            if low[i] < low[i - k : i].min() and low[i] <= low[i + 1 : i + k + 1].min():
                records.append((times[i], "low", float(low[i]), confirmed))
    if not records:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in _REF_PIVOT_COLUMNS}).astype(
            {"price": float}
        ).assign(
            time=pd.Series(dtype="datetime64[ns, UTC]"),
            confirmed_at=pd.Series(dtype="datetime64[ns, UTC]"),
        )[_REF_PIVOT_COLUMNS]
    return pd.DataFrame(records, columns=_REF_PIVOT_COLUMNS).reset_index(drop=True)



def ref_find_fvgs(candles: pd.DataFrame, min_size: float = 0.0) -> list[FVG]:
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



def _ref_zone_lifetime(
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



def ref_build_zones(
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
            s.side == sweep_side and s.sweep_time >= candle_time and s.confirmed_at <= event.time
            for s in sweeps
        )
        end_time, end_reason = _ref_zone_lifetime(
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



def _ref_breaker_lifetime(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    index: pd.DatetimeIndex,
    close_time: np.ndarray,
    created_at,
    zone_low: float,
    zone_high: float,
    origin_long: bool,
) -> tuple[pd.Timestamp | None, str | None]:
    """Primeiro candle com open_time >= created_at que toca a zona encerra o breaker.

    Breaker de venda (origem long): toque é `high >= zone_low`; de compra: `low <= zone_high`.
    Fecha além do lado de origem => "invalidated"; senão "mitigated". Sem expiração por idade.
    """
    start = int(index.searchsorted(created_at, side="left"))
    if origin_long:
        touched = high[start:] >= zone_low
        beyond = close[start:] > zone_high
    else:
        touched = low[start:] <= zone_high
        beyond = close[start:] < zone_low
    hits = np.flatnonzero(touched)
    if hits.size == 0:
        return None, None
    first = int(hits[0])
    reason = "invalidated" if beyond[first] else "mitigated"
    return pd.Timestamp(close_time[start + first]), reason



def ref_build_breakers(
    candles: pd.DataFrame,
    zones: list[Zone],
    events: list[StructureEvent],
    fvgs: list[FVG],
    sweeps: list[Sweep],
    cfg: ZoneConfig,
) -> list[Zone]:
    """Breaker Blocks no M15: zonas de origem rompidas no fechamento, sem look-ahead.

    A quebra é o primeiro candle após o BOS da origem que fecha estritamente além
    do lado oposto da zona; não há busca por candles posteriores. Com imbalance
    exigido, esse candle precisa ser o do meio de um FVG contra a origem, e o
    breaker só vale a partir do fechamento do terceiro candle do FVG. Cada origem
    gera no máximo um breaker; a vida termina no primeiro toque após `created_at`
    (ver `_ref_breaker_lifetime`).

    Duas origens rompidas pelo mesmo candle geram dois breakers com o mesmo
    `created_at` e a mesma direção; a ordem é determinística, por
    `(created_at, candle_time)`. Uma origem cujo `created_at` não coincide com o
    `close_time` de nenhum candle é ignorada, por contrato.
    """
    if candles.empty or not zones:
        return []
    index = candles.index
    close_time = candles["close_time"].to_numpy()
    high = candles["high"].to_numpy()
    low = candles["low"].to_numpy()
    close = candles["close"].to_numpy()
    n = len(candles)

    breakers: list[Zone] = []
    for origin in zones:
        long = origin.direction == "long"
        # sign > 0: origem de compra rompida para baixo; < 0: origem de venda para cima.
        sign = 1 if long else -1
        far = origin.low if long else origin.high
        against = "down" if long else "up"
        direction = "short" if long else "long"

        found = np.flatnonzero(close_time == origin.created_at)
        if found.size == 0:
            continue
        bos_pos = int(found[0])
        stop = n if cfg.breaker_max_age is None else min(n, bos_pos + cfg.breaker_max_age + 1)
        j = next((i for i in range(bos_pos + 1, stop) if sign * (far - close[i]) > 0), None)
        if j is None:
            continue

        if cfg.breaker_require_imbalance:
            if j + 1 >= n:
                continue
            fvg = next(
                (f for f in fvgs if f.direction == against and f.start_time == index[j - 1]),
                None,
            )
            if fvg is None:
                continue
            created_at = fvg.formed_at
            last = j + 1
        else:
            created_at = close_time[j]
            last = j

        if cfg.breaker_require_choch and not any(
            e.kind == "CHoCH" and e.direction == against and origin.created_at < e.time <= created_at
            for e in events
        ):
            continue

        c = index.get_loc(origin.candle_time)
        if long:
            range_high, range_low = high[c : j + 1].max(), low[j : last + 1].min()
        else:
            range_low, range_high = low[c : j + 1].min(), high[j : last + 1].max()
        range_low, range_high = float(range_low), float(range_high)

        sweep_side = "high" if long else "low"
        end_time, end_reason = _ref_breaker_lifetime(
            high,
            low,
            close,
            index,
            close_time,
            created_at,
            origin.low,
            origin.high,
            long,
        )
        swept = any(
            s.side == sweep_side
            and s.sweep_time >= origin.created_at
            and s.confirmed_at <= created_at
            for s in sweeps
        )
        breakers.append(
            Zone(
                direction=direction,
                kind="BREAKER",
                high=origin.high,
                low=origin.low,
                candle_time=origin.candle_time,
                created_at=pd.Timestamp(created_at),
                range_low=range_low,
                range_high=range_high,
                in_discount=in_discount(direction, origin.low, origin.high, range_low, range_high),
                swept_liquidity=swept,
                end_time=end_time,
                end_reason=end_reason,
            )
        )
    breakers.sort(key=lambda z: (z.created_at, z.candle_time))
    return breakers

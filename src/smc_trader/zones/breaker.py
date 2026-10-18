import numpy as np
import pandas as pd

from smc_trader.config import ZoneConfig
from smc_trader.structure.market_structure import StructureEvent
from smc_trader.zones.fvg import FVG
from smc_trader.zones.liquidity import Sweep
from smc_trader.zones.orderblock import Zone
from smc_trader.zones.premium_discount import in_discount


def _lifetime(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    index: pd.DatetimeIndex,
    close_time: np.ndarray,
    created_at: pd.Timestamp,
    zone_low: float,
    zone_high: float,
    origin_long: bool,
) -> tuple[pd.Timestamp | None, str | None]:
    """Primeiro candle com open_time >= created_at que toca a zona encerra o breaker.

    Breaker de venda (origem long): toque é `high >= zone_low`; de compra: `low <= zone_high`.
    Fecha além do lado de origem => "invalidated"; senão "mitigated". Sem expiração por idade.
    """
    start = int(index.searchsorted(created_at, side="left"))
    if start >= len(index):
        return None, None
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


def _index_chochs(events: list[StructureEvent]) -> dict[str, np.ndarray]:
    by_dir: dict[str, list[pd.Timestamp]] = {"up": [], "down": []}
    for e in events:
        if e.kind == "CHoCH" and e.direction in by_dir:
            by_dir[e.direction].append(e.time)
    return {d: np.array(times, dtype=object) for d, times in by_dir.items()}


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
    origin_created_at: pd.Timestamp,
    breaker_created_at: pd.Timestamp,
) -> bool:
    times, confirms = sweep_index[side]
    if times.size == 0:
        return False
    idx = int(np.searchsorted(times, origin_created_at, side="left"))
    n = times.size
    for i in range(idx, n):
        if times[i] > breaker_created_at:
            break
        if confirms[i] <= breaker_created_at:
            return True
    return False


def build_breakers(
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
    (ver `_lifetime`).

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

    fvg_lookup = {(f.direction, f.start_time): f for f in fvgs}
    choch_index = _index_chochs(events)
    sweep_index = _index_sweeps(sweeps)

    breakers: list[Zone] = []
    for origin in zones:
        long = origin.direction == "long"
        against = "down" if long else "up"
        direction = "short" if long else "long"

        pos = int(np.searchsorted(close_time, origin.created_at))
        if pos >= n or close_time[pos] != origin.created_at:
            continue
        bos_pos = pos

        stop = n if cfg.breaker_max_age is None else min(n, bos_pos + cfg.breaker_max_age + 1)
        if bos_pos + 1 >= stop:
            continue
        sub_close = close[bos_pos + 1 : stop]
        cond = (sub_close < origin.low) if long else (sub_close > origin.high)
        hits = np.flatnonzero(cond)
        if hits.size == 0:
            continue
        j = bos_pos + 1 + int(hits[0])

        if cfg.breaker_require_imbalance:
            if j + 1 >= n:
                continue
            fvg = fvg_lookup.get((against, index[j - 1]))
            if fvg is None:
                continue
            created_at = fvg.formed_at
            last = j + 1
        else:
            created_at = close_time[j]
            last = j

        if cfg.breaker_require_choch:
            against_times = choch_index[against]
            if against_times.size == 0:
                continue
            c_idx = int(np.searchsorted(against_times, origin.created_at, side="right"))
            if c_idx >= against_times.size or against_times[c_idx] > created_at:
                continue

        c = index.get_loc(origin.candle_time)
        if long:
            range_high = float(high[c : j + 1].max())
            range_low = float(low[j : last + 1].min())
        else:
            range_low = float(low[c : j + 1].min())
            range_high = float(high[j : last + 1].max())

        sweep_side = "high" if long else "low"
        end_time, end_reason = _lifetime(
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
        swept = _has_sweep(sweep_index, sweep_side, origin.created_at, created_at)
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

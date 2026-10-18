import numpy as np
import pandas as pd

from smc_trader.config import ZoneConfig
from smc_trader.structure.market_structure import StructureEvent
from smc_trader.zones.fvg import FVG
from smc_trader.zones.liquidity import Sweep
from smc_trader.zones.orderblock import Zone
from smc_trader.zones.premium_discount import in_discount


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
    gera no máximo um breaker; o fim de vida fica em aberto (`end_time=None`).
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
        j = next((i for i in range(bos_pos + 1, n) if sign * (far - close[i]) > 0), None)
        if j is None:
            continue
        if cfg.breaker_max_age is not None and j - bos_pos > cfg.breaker_max_age:
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
        swept = any(
            s.side == sweep_side
            and s.sweep_time >= origin.candle_time
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
                end_time=None,
                end_reason=None,
            )
        )
    breakers.sort(key=lambda z: (z.created_at, z.candle_time))
    return breakers

"""Fronteiras exatas (empates) dos detectores, com quadros e objetos feitos à mão."""

import pandas as pd
from helpers import BREAKER_TAIL, SERIE_A_ROWS, candles_from_ohlc

from smc_trader.config import ZoneConfig
from smc_trader.structure.market_structure import StructureEvent, detect_structure
from smc_trader.structure.pivots import find_pivots
from smc_trader.zones.breaker import build_breakers
from smc_trader.zones.fvg import find_fvgs
from smc_trader.zones.liquidity import Sweep
from smc_trader.zones.orderblock import build_zones

STEP = pd.Timedelta(minutes=15)
PLAIN = SERIE_A_ROWS[0:6]  # OB long [10, 12] criado no close_time do candle 5


def choch(direction: str, time: pd.Timestamp) -> StructureEvent:
    return StructureEvent(
        kind="CHoCH",
        direction=direction,
        time=time,
        break_time=time - STEP,
        level=0.0,
        level_time=time - 2 * STEP,
        leg_time=time - 2 * STEP,
        range_low=9.0,
        range_high=14.0,
    )


def bos_events(candles: pd.DataFrame) -> list[StructureEvent]:
    events = detect_structure(candles, find_pivots(candles, 1))
    return [e for e in events if e.kind == "BOS"]


def origin_zone(candles, events, sweeps=()):
    zones = build_zones(candles, events, [], list(sweeps), ZoneConfig())
    (z,) = [z for z in zones if z.candle_time == candles.index[3]]
    return z


# a) vida da zona: empate entre o toque e o CHoCH contra a zona
def test_zone_lifetime_touch_tie_with_choch_is_mitigated():
    # candle 6 não toca a zona (low > 12); candle 7 toca (low 11.5)
    c = candles_from_ohlc(PLAIN + [(13.2, 14, 12.5, 13.8), (13.8, 14, 11.5, 13.0)])
    events = bos_events(c)
    z = origin_zone(c, events + [choch("down", c["close_time"].iloc[7])])
    assert z.end_reason == "mitigated"
    assert z.end_time == c["close_time"].iloc[7]


def test_zone_lifetime_choch_one_candle_before_touch_is_invalidated():
    c = candles_from_ohlc(PLAIN + [(13.2, 14, 12.5, 13.8), (13.8, 14, 11.5, 13.0)])
    events = bos_events(c)
    z = origin_zone(c, events + [choch("down", c["close_time"].iloc[6])])
    assert z.end_reason == "invalidated"
    assert z.end_time == c["close_time"].iloc[6]


# b) sweep conhecido exatamente no instante do BOS conta; um candle depois, não
def _sweep(c, confirmed_at):
    return Sweep(
        side="low",
        pivot_time=c.index[0],
        pivot_price=9.0,
        sweep_time=c.index[3],
        confirmed_at=confirmed_at,
        extreme=8.5,
    )


def test_zone_sweep_confirmed_exactly_at_bos_counts():
    c = candles_from_ohlc(PLAIN)
    events = bos_events(c)
    assert origin_zone(c, events, [_sweep(c, events[0].time)]).swept_liquidity is True


def test_zone_sweep_confirmed_one_candle_after_bos_does_not_count():
    c = candles_from_ohlc(PLAIN)
    events = bos_events(c)
    sweep = _sweep(c, events[0].time + STEP)
    assert origin_zone(c, events, [sweep]).swept_liquidity is False


# c) janela do CHoCH do breaker: origin.created_at < e.time <= created_at
BREAKER_ROWS = SERIE_A_ROWS[0:6] + BREAKER_TAIL


def _breakers_with_choch(choch_offset: pd.Timedelta | None):
    c = candles_from_ohlc(BREAKER_ROWS)
    events = bos_events(c)
    candidates = build_zones(
        c, events, find_fvgs(c), [], ZoneConfig(require_discount=False)
    )
    cfg = ZoneConfig(breaker_require_choch=True)
    created_at = c["close_time"].iloc[8]  # fim do FVG, quando o breaker passa a valer
    extra = [] if choch_offset is None else [choch("down", created_at + choch_offset)]
    return build_breakers(c, candidates, events + extra, find_fvgs(c), [], cfg), created_at


def test_breaker_choch_exactly_at_created_at_counts():
    breakers, created_at = _breakers_with_choch(pd.Timedelta(0))
    assert [b.created_at for b in breakers] == [created_at]


def test_breaker_choch_one_candle_after_created_at_does_not_count():
    assert _breakers_with_choch(STEP)[0] == []


# d) tamanho do FVG exatamente igual a min_size é mantido
GAP_HALF = [(9.5, 10, 9, 9.8), (9.8, 11, 9.7, 10.8), (10.8, 11.5, 10.5, 11)]  # 10 -> 10.5
GAP_QUARTER = [(9.5, 10, 9, 9.8), (9.8, 11, 9.7, 10.8), (10.8, 11.5, 10.25, 11)]


def test_fvg_size_equal_to_min_size_is_kept():
    (f,) = find_fvgs(candles_from_ohlc(GAP_HALF), 0.5)
    assert (f.low, f.high) == (10.0, 10.5)
    assert len(find_fvgs(candles_from_ohlc(GAP_HALF), 0.0)) == 1


def test_fvg_size_just_below_min_size_is_dropped():
    c = candles_from_ohlc(GAP_QUARTER)
    assert len(find_fvgs(c, 0.25)) == 1
    assert find_fvgs(c, 0.5) == []

import dataclasses

import pandas as pd
from helpers import EXTRA_ROWS, SERIE_A_ROWS, candles_from_ohlc, mirror

from smc_trader.config import ZoneConfig
from smc_trader.structure.market_structure import detect_structure
from smc_trader.structure.pivots import find_pivots
from smc_trader.zones.fvg import find_fvgs
from smc_trader.zones.liquidity import Sweep, find_sweeps
from smc_trader.zones.orderblock import build_zones

PLAIN = SERIE_A_ROWS[0:6]
FVOB = PLAIN[:5] + [(12.3, 13.5, 12.2, 13.2)]
DISCOUNT_FAIL = PLAIN[:2] + [
    (12.9, 12.9, 11.5, 12.0),
    (10.5, 11.8, 10, 11.5),
    (11.5, 11.9, 10.2, 11.0),
    (11, 13.5, 10.8, 13.2),
]


def _zones(candles, cfg=None, sweeps=None):
    pivots = find_pivots(candles, 1)
    events = detect_structure(candles, pivots)
    fvgs = find_fvgs(candles)
    if sweeps is None:
        sweeps = find_sweeps(candles, pivots)
    return build_zones(candles, events, fvgs, sweeps, cfg or ZoneConfig())


def test_plain_ob():
    c = candles_from_ohlc(PLAIN)
    zones = _zones(c)
    assert len(zones) == 1
    z = zones[0]
    assert z.direction == "long"
    assert z.kind == "OB"
    assert z.candle_time == c.index[3]
    assert z.high == 12
    assert z.low == 10
    assert z.created_at == c["close_time"].iloc[5]
    assert z.range_low == 10
    assert z.range_high == 13.5
    assert z.in_discount is True
    assert z.swept_liquidity is False
    assert z.end_time is None
    assert z.end_reason is None


def test_fvob():
    c = candles_from_ohlc(FVOB)
    zones = _zones(c)
    assert len(zones) == 1
    z = zones[0]
    assert z.kind == "FVOB"
    assert z.candle_time == c.index[3]
    assert (z.high, z.low) == (12, 10)


def test_use_body():
    c = candles_from_ohlc(PLAIN)
    (z,) = _zones(c, ZoneConfig(use_body=True))
    assert z.high == 11.5
    assert z.low == 10.5


def test_discount_filter():
    c = candles_from_ohlc(DISCOUNT_FAIL)
    assert _zones(c, ZoneConfig(require_discount=True)) == []
    zones = _zones(c, ZoneConfig(require_discount=False))
    assert len(zones) == 1
    z = zones[0]
    assert z.candle_time == c.index[2]
    assert (z.high, z.low) == (12.9, 11.5)
    assert z.in_discount is False


def test_require_imbalance():
    c = candles_from_ohlc(PLAIN)
    assert _zones(c, ZoneConfig(require_imbalance=True)) == []


def test_swept_liquidity_window():
    c = candles_from_ohlc(PLAIN)

    def sweep(side, pos):
        return Sweep(
            side=side,
            pivot_time=c.index[0],
            pivot_price=9.0,
            sweep_time=c.index[pos],
            confirmed_at=c["close_time"].iloc[pos],
            extreme=8.5,
        )

    (z,) = _zones(c, sweeps=[sweep("low", 3)])
    assert z.swept_liquidity is True
    (z,) = _zones(c, sweeps=[sweep("low", 0)])
    assert z.swept_liquidity is False
    (z,) = _zones(c, sweeps=[sweep("high", 3)])
    assert z.swept_liquidity is False


def test_mitigated():
    c = candles_from_ohlc(PLAIN + [(13.2, 14, 11.5, 13.8)])
    (z,) = _zones(c)
    assert z.end_reason == "mitigated"
    assert z.end_time == c["close_time"].iloc[6]


def test_invalidated_before_touch():
    c = candles_from_ohlc(
        PLAIN + EXTRA_ROWS
    )
    (z,) = _zones(c)
    assert z.end_reason == "invalidated"
    assert z.end_time == c["close_time"].iloc[9]


def test_mirrored_short_zone():
    c = mirror(candles_from_ohlc(FVOB))
    zones = _zones(c)
    assert len(zones) == 1
    z = zones[0]
    assert z.direction == "short"
    assert z.kind == "FVOB"
    assert z.high == 90
    assert z.low == 88
    assert z.candle_time == c.index[3]
    assert z.in_discount is True


def test_doji_is_not_ob_candle():
    rows = list(PLAIN)
    rows[3] = (11, 11, 11, 11)
    c = candles_from_ohlc(rows)
    zones = _zones(c)
    assert len(zones) == 1
    assert zones[0].candle_time == c.index[2]
    assert zones[0].direction == "long"


def test_zone_is_active_at():
    c = candles_from_ohlc(PLAIN + [(13.2, 14, 11.5, 13.8)])
    (z,) = _zones(c)
    assert z.end_time is not None
    assert z.is_active_at(z.created_at - pd.Timedelta(minutes=1)) is False
    assert z.is_active_at(z.created_at) is True
    assert z.is_active_at(z.end_time - pd.Timedelta(minutes=1)) is True
    assert z.is_active_at(z.end_time) is False
    assert z.is_active_at(z.end_time + pd.Timedelta(days=1)) is False
    open_ended = dataclasses.replace(z, end_time=None, end_reason=None)
    assert open_ended.is_active_at(z.created_at - pd.Timedelta(minutes=1)) is False
    assert open_ended.is_active_at(z.created_at + pd.Timedelta(days=365)) is True

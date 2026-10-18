import pandas as pd
from helpers import SERIE_A_ROWS, candles_from_ohlc, random_walk_candles

from smc_trader.analysis import Analysis, analyze
from smc_trader.config import ZoneConfig

EXTRA_ROWS = [
    (13.2, 14, 13.5, 13.9),
    (13.9, 14.2, 13.2, 14.0),
    (14.0, 14.5, 13.4, 14.4),
    (14.4, 14.4, 12.8, 12.9),
]


def test_end_to_end_sequence():
    c = candles_from_ohlc(SERIE_A_ROWS[0:6] + EXTRA_ROWS)
    a = analyze(c, 1, ZoneConfig())
    assert [(e.kind, e.direction) for e in a.events] == [("BOS", "up"), ("CHoCH", "down")]
    (z,) = a.zones
    assert z.direction == "long"
    assert z.kind == "OB"
    assert z.end_reason == "invalidated"


def test_empty_and_short_frames():
    full = candles_from_ohlc(SERIE_A_ROWS)
    for c in (full.iloc[:0], full.iloc[:3]):
        a = analyze(c, 2, ZoneConfig())
        assert isinstance(a, Analysis)
        assert a.pivots.empty
        assert list(a.pivots.columns) == list(analyze(full, 2, ZoneConfig()).pivots.columns)
        assert a.events == [] and a.fvgs == [] and a.sweeps == [] and a.zones == []


def test_zones_have_no_lookahead():
    c = random_walk_candles(300, seed=11)
    cfg = ZoneConfig()
    full = analyze(c, 2, cfg).zones
    assert len(full) >= 3
    fields = (
        "direction kind high low candle_time created_at range_low range_high "
        "in_discount swept_liquidity"
    ).split()
    for n in range(10, 301, 10):
        t = c["close_time"].iloc[n - 1]
        part = analyze(c.iloc[:n], 2, cfg).zones
        for z in (z for z in full if z.created_at <= t):
            matches = [
                p for p in part
                if all(getattr(p, f) == getattr(z, f) for f in fields)
            ]
            assert len(matches) == 1, (n, z)
            expected_end = None if z.end_time is not None and z.end_time > t else z.end_time
            assert matches[0].end_time == expected_end, (n, z)

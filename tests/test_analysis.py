from dataclasses import replace

from helpers import EXTRA_ROWS, SERIE_A_ROWS, candles_from_ohlc, random_walk_candles

from smc_trader.analysis import Analysis, analyze
from smc_trader.config import ZoneConfig


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


def test_analysis_has_no_lookahead_both_directions():
    c = random_walk_candles(300, seed=11)
    cfg = ZoneConfig()
    full = analyze(c, 2, cfg)
    assert len(full.zones) >= 3
    assert full.events and full.fvgs and full.sweeps
    for n in range(10, 301, 10):
        t = c["close_time"].iloc[n - 1]
        part = analyze(c.iloc[:n], 2, cfg)
        assert part.zones == [
            replace(z, end_time=None, end_reason=None) if z.end_time is not None and z.end_time > t else z
            for z in full.zones
            if z.created_at <= t
        ], n
        assert part.events == [e for e in full.events if e.time <= t], n
        assert part.fvgs == [f for f in full.fvgs if f.formed_at <= t], n
        assert part.sweeps == [s for s in full.sweeps if s.confirmed_at <= t], n


def test_exact_minimum_lengths():
    c = candles_from_ohlc(SERIE_A_ROWS)
    four = analyze(c.iloc[:4], 2, ZoneConfig())
    assert four.pivots.empty
    analyze(c.iloc[:5], 2, ZoneConfig())

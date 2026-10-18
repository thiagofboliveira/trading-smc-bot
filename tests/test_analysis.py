from dataclasses import replace

from helpers import BREAKER_TAIL, EXTRA_ROWS, SERIE_A_ROWS, candles_from_ohlc, random_walk_candles

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
        assert a.breakers == []


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


def test_breaker_end_to_end():
    c = candles_from_ohlc(SERIE_A_ROWS[0:6] + BREAKER_TAIL)
    a = analyze(c, 1, ZoneConfig())
    assert len(a.zones) == 1
    (b,) = a.breakers
    assert (b.direction, b.kind) == ("short", "BREAKER")
    assert b.created_at == c["close_time"].iloc[8]


def test_breaker_origin_filtered_out_of_zones_still_breaks():
    rows = [
        (10, 11, 9, 10.5),
        (10.5, 13, 10, 12.5),
        (12.9, 12.9, 11.5, 12.0),
        (10.5, 11.8, 10, 11.5),
        (11.5, 11.9, 10.2, 11.0),
        (11, 13.5, 10.8, 13.2),
        (13.2, 14, 13.0, 13.1),
        (13.1, 13.2, 11.0, 11.2),
        (11.2, 11.6, 10.9, 11.3),
    ]
    c = candles_from_ohlc(rows)
    a = analyze(c, 1, ZoneConfig())
    assert a.zones == []
    (b,) = a.breakers
    assert b.direction == "short"
    assert (b.high, b.low) == (12.9, 11.5)
    assert b.candle_time == c.index[2]
    assert b.created_at == c["close_time"].iloc[8]


def test_breakers_disabled():
    c = candles_from_ohlc(SERIE_A_ROWS[0:6] + BREAKER_TAIL)
    assert analyze(c, 1, ZoneConfig(blocks_filter=["OB", "FVOB"])).breakers == []


_BREAKER_FIELDS = (
    "direction", "kind", "high", "low", "candle_time", "created_at",
    "range_low", "range_high", "in_discount", "swept_liquidity",
)


def _key(z):
    return tuple(getattr(z, f) for f in _BREAKER_FIELDS)


def test_breakers_have_no_lookahead():
    c = random_walk_candles(600, seed=11)
    cfg = ZoneConfig()
    full = analyze(c, 2, cfg)
    assert len(full.breakers) >= 3
    for n in range(10, 601, 10):
        t = c["close_time"].iloc[n - 1]
        part = analyze(c.iloc[:n], 2, cfg)
        expected = [z for z in full.breakers if z.created_at <= t]
        assert [_key(z) for z in part.breakers] == [_key(z) for z in expected], n
        for p, f in zip(part.breakers, expected):
            if f.end_time is not None and f.end_time > t:
                assert p.end_time is None and p.end_reason is None, n
            else:
                assert (p.end_time, p.end_reason) == (f.end_time, f.end_reason), n


def test_blocks_filter_selects_kinds():
    bb = candles_from_ohlc(SERIE_A_ROWS[0:6] + BREAKER_TAIL)
    fv = candles_from_ohlc(SERIE_A_ROWS[0:5] + [(12.3, 13.5, 12.2, 13.2)])

    def run(c, blocks):
        return analyze(c, 1, ZoneConfig(blocks_filter=blocks))

    a = run(bb, ["OB"])
    assert [z.kind for z in a.zones] == ["OB"] and a.breakers == []
    a = run(bb, ["BB"])
    assert a.zones == [] and len(a.breakers) == 1
    a = run(bb, ["OB", "FVOB"])
    assert len(a.zones) == 1 and a.breakers == []
    a = run(bb, ["OB", "FVOB", "BB"])
    assert len(a.zones) == 1 and len(a.breakers) == 1
    a = run(fv, ["FVOB"])
    assert [z.kind for z in a.zones] == ["FVOB"]
    assert run(fv, ["OB"]).zones == []
    a = run(bb, ["FVOB", "BB"])
    assert a.zones == [] and len(a.breakers) == 1

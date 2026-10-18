from helpers import BREAKER_TAIL, BREAKER_TAIL_NO_FVG, SERIE_A_ROWS, candles_from_ohlc, mirror

from smc_trader.config import ZoneConfig
from smc_trader.structure.market_structure import detect_structure
from smc_trader.structure.pivots import find_pivots
from smc_trader.zones.breaker import build_breakers
from smc_trader.zones.fvg import find_fvgs
from smc_trader.zones.liquidity import find_sweeps
from smc_trader.zones.orderblock import build_zones

ROWS = SERIE_A_ROWS[0:6] + BREAKER_TAIL
NO_FVG_ROWS = SERIE_A_ROWS[0:6] + BREAKER_TAIL_NO_FVG


def _run(candles, cfg=None, k=1, events=None):
    cfg = cfg or ZoneConfig()
    pivots = find_pivots(candles, k)
    real_events = detect_structure(candles, pivots)
    fvgs = find_fvgs(candles, cfg.fvg_min_size)
    sweeps = find_sweeps(candles, pivots)
    candidates = build_zones(
        candles,
        real_events,
        fvgs,
        sweeps,
        cfg.model_copy(update={"require_discount": False, "require_imbalance": False}),
    )
    used_events = real_events if events is None else events
    return build_breakers(candles, candidates, used_events, fvgs, sweeps, cfg)


def breakers_from(rows, cfg=None, k=1, events=None):
    return _run(candles_from_ohlc(rows), cfg, k, events)


def test_failed_long_ob_becomes_short_breaker():
    c = candles_from_ohlc(ROWS)
    breakers = breakers_from(ROWS)
    assert len(breakers) == 1
    b = breakers[0]
    assert b.direction == "short"
    assert b.kind == "BREAKER"
    assert b.high == 12.0
    assert b.low == 10.0
    assert b.candle_time == c.index[3]
    assert b.created_at == c["close_time"].iloc[8]
    assert b.range_high == 14.0
    assert b.range_low == 9.0
    assert b.in_discount is False
    assert b.swept_liquidity is False
    assert b.end_time is None
    assert b.end_reason is None


def test_mirrored_failed_short_ob_becomes_long_breaker():
    c = mirror(candles_from_ohlc(ROWS))
    breakers = _run(c)
    assert len(breakers) == 1
    b = breakers[0]
    assert b.direction == "long"
    assert b.kind == "BREAKER"
    assert b.high == 90.0
    assert b.low == 88.0
    assert b.range_low == 86.0
    assert b.range_high == 91.0
    assert b.candle_time == c.index[3]
    assert b.created_at == c["close_time"].iloc[8]


def test_no_imbalance_no_breaker():
    c = candles_from_ohlc(NO_FVG_ROWS)
    assert breakers_from(NO_FVG_ROWS) == []
    breakers = breakers_from(NO_FVG_ROWS, ZoneConfig(breaker_require_imbalance=False))
    assert len(breakers) == 1
    assert breakers[0].created_at == c["close_time"].iloc[7]
    assert breakers[0].range_low == 9.4


def test_break_on_last_candle_waits_for_confirmation():
    assert breakers_from(SERIE_A_ROWS[0:6] + BREAKER_TAIL[:2]) == []


def test_close_exactly_on_limit_is_not_a_break():
    cfg = ZoneConfig(breaker_require_imbalance=False)
    on_limit = NO_FVG_ROWS[:7] + [(12.8, 12.9, 9.4, 10.0)] + NO_FVG_ROWS[8:]
    assert breakers_from(on_limit, cfg) == []
    below = NO_FVG_ROWS[:7] + [(12.8, 12.9, 9.4, 9.9)] + NO_FVG_ROWS[8:]
    assert len(breakers_from(below, cfg)) == 1


def test_max_age():
    assert breakers_from(ROWS, ZoneConfig(breaker_max_age=1)) == []
    assert len(breakers_from(ROWS, ZoneConfig(breaker_max_age=2))) == 1
    assert len(breakers_from(ROWS, ZoneConfig(breaker_max_age=None))) == 1


def test_require_choch():
    cfg = ZoneConfig(breaker_require_choch=True)
    assert len(breakers_from(ROWS, cfg)) == 1
    assert breakers_from(ROWS, cfg, events=[]) == []
    assert len(breakers_from(ROWS, ZoneConfig(), events=[])) == 1


def test_empty_inputs():
    c = candles_from_ohlc(ROWS)
    cfg = ZoneConfig()
    pivots = find_pivots(c, 1)
    events = detect_structure(c, pivots)
    fvgs = find_fvgs(c)
    sweeps = find_sweeps(c, pivots)
    candidates = build_zones(
        c, events, fvgs, sweeps, cfg.model_copy(update={"require_discount": False})
    )
    assert candidates
    assert build_breakers(c.iloc[:0], candidates, events, fvgs, sweeps, cfg) == []
    assert build_breakers(c, [], events, fvgs, sweeps, cfg) == []

from helpers import candles_from_ohlc, mirror

from smc_trader.structure.pivots import find_pivots
from smc_trader.zones.liquidity import Sweep, find_sweeps

LOW_SWEEP = [
    (10, 11, 9, 10.5),
    (10.5, 10.8, 8, 9),
    (9, 10, 8.5, 9.8),
    (9.8, 10.5, 9.5, 10.2),
    (10.2, 10.6, 7.5, 9.9),
    (9.9, 10, 7.2, 9.5),
]


def test_low_sweep():
    c = candles_from_ohlc(LOW_SWEEP)
    sweeps = find_sweeps(c, find_pivots(c, 1))
    assert sweeps == [
        Sweep(
            side="low",
            pivot_time=c.index[1],
            pivot_price=8.0,
            sweep_time=c.index[4],
            extreme=7.5,
        )
    ]


def test_close_beyond_is_break_not_sweep():
    rows = list(LOW_SWEEP)
    rows[4] = (10.2, 10.6, 7.5, 7.8)
    c = candles_from_ohlc(rows)
    assert find_sweeps(c, find_pivots(c, 1)) == []


def test_high_sweep_mirrored():
    c = mirror(candles_from_ohlc(LOW_SWEEP))
    sweeps = find_sweeps(c, find_pivots(c, 1))
    assert len(sweeps) == 1
    s = sweeps[0]
    assert s.side == "high"
    assert s.pivot_time == c.index[1]
    assert s.pivot_price == 92.0
    assert s.sweep_time == c.index[4]
    assert s.extreme == 92.5

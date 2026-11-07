
from helpers import candles_from_ohlc, mirror

from smc_trader.zones.fvg import FVG, find_fvgs

BULL = [(9.5, 10, 9, 9.8), (9.9, 13, 9.8, 12.8), (12.8, 14, 11, 13.5)]
BEAR = [(13.5, 14, 13, 13.2), (13.1, 13.2, 10, 10.5), (10.5, 12, 10.2, 11)]


def test_bullish_fvg():
    df = candles_from_ohlc(BULL)
    assert find_fvgs(df) == [
        FVG("up", 10.0, 11.0, df.index[0], df["close_time"].iloc[2])
    ]


def test_bearish_fvg():
    df = candles_from_ohlc(BEAR)
    assert find_fvgs(df) == [
        FVG("down", 12.0, 13.0, df.index[0], df["close_time"].iloc[2])
    ]


def test_min_size_filters():
    for rows in (BULL, BEAR):
        assert find_fvgs(candles_from_ohlc(rows), min_size=1.5) == []


def test_overlapping_candles_have_no_fvg_and_short_frames_are_empty():
    df = candles_from_ohlc([(10, 12, 9, 11), (11, 13, 10, 12), (12, 13, 10.5, 11)])
    assert find_fvgs(df) == []
    assert find_fvgs(candles_from_ohlc(BULL[:2])) == []


def test_mirror_of_bullish_gives_bearish():
    df = candles_from_ohlc(BULL)
    (f,) = find_fvgs(mirror(df))
    assert (f.direction, f.low, f.high) == ("down", 89.0, 90.0)
    assert f.start_time == df.index[0]
    assert f.formed_at == df["close_time"].iloc[2]

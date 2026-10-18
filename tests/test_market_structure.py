import pandas as pd
import pytest
from helpers import SERIE_A_ROWS as SERIE_A
from helpers import candles_from_ohlc, mirror, random_walk_candles

from smc_trader.structure.market_structure import detect_structure
from smc_trader.structure.pivots import find_pivots


def _events(candles, k):
    return detect_structure(candles, find_pivots(candles, k))


def test_bos_then_choch():
    c = candles_from_ohlc(SERIE_A)
    events = _events(c, 1)
    assert [(e.kind, e.direction) for e in events] == [("BOS", "up"), ("CHoCH", "down")]
    bos, choch = events
    assert bos.time == c["close_time"].iloc[5]
    assert bos.break_time == c.index[5]
    assert bos.level == 13
    assert bos.level_time == c.index[1]
    assert bos.leg_time == c.index[3]
    assert bos.range_low == 10
    assert bos.range_high == 13.5
    assert choch.time == c["close_time"].iloc[10]
    assert choch.break_time == c.index[10]
    assert choch.level == 11.8
    assert choch.level_time == c.index[8]


def test_mirrored_series_gives_down_bos():
    c = mirror(candles_from_ohlc(SERIE_A))
    events = _events(c, 1)
    assert [(e.kind, e.direction) for e in events] == [("BOS", "down"), ("CHoCH", "up")]
    bos = events[0]
    assert bos.time == c["close_time"].iloc[5]
    assert bos.level == 87
    assert bos.level_time == c.index[1]
    assert bos.leg_time == c.index[3]
    assert bos.range_high == 90
    assert bos.range_low == 86.5
    assert events[1].level == pytest.approx(100 - 11.8)
    assert events[1].level_time == c.index[8]


@pytest.mark.parametrize(
    "candles,k,cuts",
    [
        (candles_from_ohlc(SERIE_A), 1, range(1, 12)),
        (random_walk_candles(150, seed=7), 2, range(7, 151, 7)),
    ],
    ids=["serie_a", "random_walk"],
)
def test_no_lookahead_truncation(candles, k, cuts):
    full = _events(candles, k)
    assert full, "série de teste deveria gerar eventos"
    for n in cuts:
        cut = candles.iloc[:n]
        expected = [e for e in full if e.time <= candles["close_time"].iloc[n - 1]]
        assert _events(cut, k) == expected, f"divergência no corte n={n}"


def test_empty_inputs():
    c = candles_from_ohlc(SERIE_A)
    assert _events(c.iloc[:0], 1) == []
    assert _events(c.iloc[:2], 1) == []
    assert _events(c.iloc[:4], 2) == []


def test_event_times_are_utc_timestamps():
    c = candles_from_ohlc(SERIE_A)
    for e in _events(c, 1):
        for t in (e.time, e.break_time, e.level_time, e.leg_time):
            assert isinstance(t, pd.Timestamp)
            assert str(t.tz) == "UTC"

import pandas as pd
import pytest
from helpers import candles_from_ohlc

from smc_trader.structure.pivots import find_pivots

COLS = ["time", "kind", "price", "confirmed_at"]


def _candles(highs):
    rows = []
    for h in highs:
        low = h - 0.5
        mid = (h + low) / 2
        rows.append((mid, h, low, mid))
    return candles_from_ohlc(rows)


def test_pivots_k2():
    c = _candles([1, 2, 5, 2, 1, 2, 3, 2, 1])
    p = find_pivots(c, 2)
    assert list(p.columns) == COLS
    assert isinstance(p.index, pd.RangeIndex)
    tops = p[p.kind == "high"]
    assert list(tops["time"]) == [c.index[2], c.index[6]]
    assert list(tops["price"]) == [5, 3]
    assert list(tops["confirmed_at"]) == [c["close_time"].iloc[4], c["close_time"].iloc[8]]
    lows = p[p.kind == "low"]
    assert list(lows["time"]) == [c.index[4]]
    assert list(lows["price"]) == [0.5]
    assert p["time"].is_monotonic_increasing


def test_equal_highs_single_pivot():
    c = _candles([1, 2, 5, 5, 2, 1])
    p = find_pivots(c, 2)
    tops = p[p.kind == "high"]
    assert list(tops["time"]) == [c.index[2]]


def test_short_or_empty_frame():
    for c in (_candles([1, 2, 3, 2]), _candles([1, 2, 3, 2]).iloc[:0]):
        p = find_pivots(c, 3)
        assert p.empty
        assert list(p.columns) == COLS


@pytest.mark.parametrize("k", [0, -1])
def test_k_must_be_positive(k):
    with pytest.raises(ValueError, match="k must be >= 1"):
        find_pivots(_candles([1, 2, 3]), k)

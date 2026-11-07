from datetime import datetime, timezone

import dukascopy_python
import numpy as np
import pandas as pd

from smc_trader.data.dukascopy_source import fetch_m1, normalize_dukascopy


def test_normalize_contract():
    idx = pd.DatetimeIndex(
        [
            "2024-01-02 00:02",
            "2024-01-02 00:00",
            "2024-01-02 00:01",
            "2024-01-02 00:01",
            "2024-01-02 00:03",
        ],
        tz="UTC",
        name="timestamp",
    )
    df = pd.DataFrame(
        {
            "open": [3.0, 1.0, 2.0, 20.0, np.nan],
            "high": [3.5, 1.5, 2.5, 20.5, 4.5],
            "low": [2.5, 0.5, 1.5, 19.5, 3.5],
            "close": [3.2, 1.2, 2.2, 20.2, 4.2],
            "volume": [10.0, 11.0, 12.0, 22.0, 13.0],
        },
        index=idx,
    )
    out = normalize_dukascopy(df)
    assert out.index.name == "time"
    assert str(out.index.tz) == "UTC"
    assert out.index.is_monotonic_increasing and out.index.is_unique
    assert list(out.columns) == ["open", "high", "low", "close", "volume", "spread"]
    assert not out.isna().any().any()
    assert len(out) == 3
    assert out.loc["2024-01-02 00:01", "open"] == 20.0
    assert (out["spread"] == 0.0).all()


def _run(offer_side):
    calls = []

    def fake_fetcher(**kw):
        calls.append(kw)
        idx = pd.DatetimeIndex([kw["start"], kw["end"]], name="timestamp")
        return pd.DataFrame(
            {"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0}, index=idx
        )

    utc = timezone.utc
    out = fetch_m1(
        "XAU/USD",
        datetime(2024, 1, 15, tzinfo=utc),
        datetime(2024, 3, 10, tzinfo=utc),
        offer_side,
        fetcher=fake_fetcher,
    )
    return calls, out


def test_fetch_m1_monthly_chunks():
    calls, out = _run("bid")

    def d(m, day):
        return datetime(2024, m, day, tzinfo=timezone.utc)

    assert [(c["start"], c["end"]) for c in calls] == [
        (d(1, 15), d(2, 1)),
        (d(2, 1), d(3, 1)),
        (d(3, 1), d(3, 10)),
    ]
    assert out.index.is_unique and out.index.is_monotonic_increasing
    assert len(out) == 4
    for c in calls:
        assert c["interval"] == dukascopy_python.INTERVAL_MIN_1
        assert c["start"].utcoffset().total_seconds() == 0
        assert c["offer_side"] == dukascopy_python.OFFER_SIDE_BID
        assert c["instrument"] == "XAU/USD"


def test_fetch_m1_ask_side():
    calls, _ = _run("ask")
    assert all(c["offer_side"] == dukascopy_python.OFFER_SIDE_ASK for c in calls)

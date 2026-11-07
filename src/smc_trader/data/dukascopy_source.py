from collections.abc import Callable
from datetime import datetime
from typing import Literal

import dukascopy_python
import pandas as pd

_OFFER_SIDES = {
    "bid": dukascopy_python.OFFER_SIDE_BID,
    "ask": dukascopy_python.OFFER_SIDE_ASK,
}


def normalize_dukascopy(df: pd.DataFrame) -> pd.DataFrame:
    out = df[["open", "high", "low", "close", "volume"]].dropna().copy()
    out.index = pd.DatetimeIndex(out.index, name="time")
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out["spread"] = 0.0
    return out


def _next_month_start(t: datetime) -> datetime:
    year, month = (t.year + 1, 1) if t.month == 12 else (t.year, t.month + 1)
    return t.replace(
        year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0
    )


def fetch_m1(
    instrument: str,
    start: datetime,
    end: datetime,
    offer_side: Literal["bid", "ask"],
    fetcher: Callable[..., pd.DataFrame] = dukascopy_python.fetch,
) -> pd.DataFrame:
    side = _OFFER_SIDES[offer_side]
    frames = []
    chunk_start = start
    while chunk_start < end:
        chunk_end = min(_next_month_start(chunk_start), end)
        frames.append(
            fetcher(
                instrument=instrument,
                interval=dukascopy_python.INTERVAL_MIN_1,
                offer_side=side,
                start=chunk_start,
                end=chunk_end,
            )
        )
        chunk_start = chunk_end
    if not frames:
        raise ValueError("intervalo vazio: --from deve ser anterior a --to")
    return normalize_dukascopy(pd.concat(frames))

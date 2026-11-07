import numpy as np
import pandas as pd

from smc_trader.data.candles import TF_MINUTES, with_close_time

SERIE_A_ROWS: list[tuple[float, float, float, float]] = [
    (10, 11, 9, 10.5),
    (10.5, 13, 10, 12.5),
    (12.5, 12.5, 11, 11.5),
    (11.5, 12, 10, 10.5),
    (10.5, 11.5, 10.2, 11),
    (11, 13.5, 10.8, 13.2),
    (13.2, 14, 12.8, 13.8),
    (13.8, 13.9, 12.5, 12.6),
    (12.6, 13.0, 11.8, 12.0),
    (12.0, 12.6, 11.9, 12.4),
    (12.4, 12.5, 9.5, 9.8),
]

EXTRA_ROWS: list[tuple[float, float, float, float]] = [
    (13.2, 14, 13.5, 13.9),
    (13.9, 14.2, 13.2, 14.0),
    (14.0, 14.5, 13.4, 14.4),
    (14.4, 14.4, 12.8, 12.9),
]


def _frame(o, h, lo, c, tf: str, start: str) -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(o), freq=f"{TF_MINUTES[tf]}min", tz="UTC", name="time")
    df = pd.DataFrame(
        {"open": o, "high": h, "low": lo, "close": c, "volume": 1.0}, index=idx
    ).astype(float)
    return with_close_time(df, tf)


def candles_from_ohlc(
    rows: list[tuple[float, float, float, float]],
    tf: str = "M15",
    start: str = "2024-01-02 00:00",
) -> pd.DataFrame:
    o, h, lo, c = (list(col) for col in zip(*rows))
    return _frame(o, h, lo, c, tf, start)


def mirror(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["open"] = 100 - df["open"]
    out["close"] = 100 - df["close"]
    out["high"] = 100 - df["low"]
    out["low"] = 100 - df["high"]
    return out


def random_walk_candles(n: int, seed: int, tf: str = "M15") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 50 + np.cumsum(rng.normal(0, 1, n))
    open_ = np.concatenate([[50.0], close[:-1]])
    high = np.maximum(open_, close) + rng.uniform(0, 0.5, n)
    low = np.minimum(open_, close) - rng.uniform(0, 0.5, n)
    return _frame(open_, high, low, close, tf, "2024-01-02 00:00")


BREAKER_TAIL: list[tuple[float, float, float, float]] = [
    (13.2, 14.0, 12.5, 12.8),
    (12.8, 12.9, 9.4, 9.5),
    (9.5, 10.0, 9.0, 9.2),
]

BREAKER_TAIL_NO_FVG: list[tuple[float, float, float, float]] = [
    (13.2, 14.0, 12.5, 12.8),
    (12.8, 12.9, 9.4, 9.5),
    (9.5, 12.6, 9.0, 12.3),
]

BREAKER_TAIL_DEEP: list[tuple[float, float, float, float]] = [
    (13.2, 14.0, 12.5, 12.8),
    (12.8, 12.9, 9.4, 9.5),
    (9.5, 10.0, 7.0, 9.2),
]

import numpy as np
import pandas as pd

from smc_trader.data.candles import TF_MINUTES, with_close_time


def _frame(o, h, l, c, tf: str, start: str) -> pd.DataFrame:
    idx = pd.date_range(start, periods=len(o), freq=f"{TF_MINUTES[tf]}min", tz="UTC", name="time")
    df = pd.DataFrame(
        {"open": o, "high": h, "low": l, "close": c, "volume": 1.0}, index=idx
    ).astype(float)
    return with_close_time(df, tf)


def candles_from_ohlc(
    rows: list[tuple[float, float, float, float]],
    tf: str = "M15",
    start: str = "2024-01-02 00:00",
) -> pd.DataFrame:
    o, h, l, c = (list(col) for col in zip(*rows))
    return _frame(o, h, l, c, tf, start)


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

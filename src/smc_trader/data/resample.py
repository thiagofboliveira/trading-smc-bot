import pandas as pd

from smc_trader.data.candles import tf_minutes, with_close_time

_OHLC_COLS = ["open", "high", "low", "close", "volume"]
_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def resample_ohlc(
    m1: pd.DataFrame, tf: str, drop_incomplete_tail: bool = True
) -> pd.DataFrame:
    """Agrega M1 em `tf`; buckets vazios são descartados."""
    minutes = tf_minutes(tf)
    if m1.index.tz is None:
        raise ValueError(
            "O índice de candles deve ser tz-aware (UTC); recebido índice sem fuso"
        )
    m1 = m1[~m1.index.duplicated(keep="last")].sort_index()
    grouped = m1[_OHLC_COLS].resample(f"{minutes}min", label="left", closed="left")
    out = grouped.agg(_AGG)
    last_m1 = m1.index.to_series().resample(f"{minutes}min").max()
    out = out[last_m1.notna()]
    if drop_incomplete_tail and not out.empty:
        bucket_end = out.index[-1] + pd.Timedelta(minutes=minutes)
        if last_m1.iloc[-1] < bucket_end - pd.Timedelta(minutes=1):
            out = out.iloc[:-1]
    out.index.name = "time"
    return with_close_time(out, tf)

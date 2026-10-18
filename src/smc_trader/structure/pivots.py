import numpy as np
import pandas as pd

COLUMNS = ["time", "kind", "price", "confirmed_at"]


def find_pivots(candles: pd.DataFrame, k: int) -> pd.DataFrame:
    """Pivôs de swing confirmados sem look-ahead.

    Topo em i: high[i] > max(high[i-k:i]) e high[i] >= max(high[i+1:i+k+1]).
    Fundo: espelho com < e <=. `confirmed_at` é o close_time do candle i+k.
    """
    if k < 1:
        raise ValueError("k must be >= 1")
    n = len(candles)
    records = []
    if n >= 2 * k + 1:
        high = candles["high"].to_numpy()
        low = candles["low"].to_numpy()
        times = candles.index
        close_times = candles["close_time"]
        for i in range(k, n - k):
            confirmed = close_times.iloc[i + k]
            if high[i] > high[i - k : i].max() and high[i] >= high[i + 1 : i + k + 1].max():
                records.append((times[i], "high", float(high[i]), confirmed))
            if low[i] < low[i - k : i].min() and low[i] <= low[i + 1 : i + k + 1].min():
                records.append((times[i], "low", float(low[i]), confirmed))
    if not records:
        return pd.DataFrame({c: pd.Series(dtype="object") for c in COLUMNS}).astype(
            {"price": float}
        ).assign(
            time=pd.Series(dtype="datetime64[ns, UTC]"),
            confirmed_at=pd.Series(dtype="datetime64[ns, UTC]"),
        )[COLUMNS]
    return pd.DataFrame(records, columns=COLUMNS).reset_index(drop=True)

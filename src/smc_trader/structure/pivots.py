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
    if n >= 2 * k + 1:
        high = candles["high"].to_numpy()
        low = candles["low"].to_numpy()
        high_win = np.lib.stride_tricks.sliding_window_view(high, window_shape=k)
        low_win = np.lib.stride_tricks.sliding_window_view(low, window_shape=k)

        max_l = high_win[0 : n - 2 * k].max(axis=1)
        max_r = high_win[k + 1 : n - k + 1].max(axis=1)
        c_h = high[k : n - k]
        is_high = (c_h > max_l) & (c_h >= max_r)

        min_l = low_win[0 : n - 2 * k].min(axis=1)
        min_r = low_win[k + 1 : n - k + 1].min(axis=1)
        c_l = low[k : n - k]
        is_low = (c_l < min_l) & (c_l <= min_r)

        h_idx = np.flatnonzero(is_high)
        l_idx = np.flatnonzero(is_low)
        if h_idx.size > 0 or l_idx.size > 0:
            n_h, n_l = h_idx.size, l_idx.size
            total = n_h + n_l
            pos_all = np.empty(total, dtype=np.int64)
            pos_all[:n_h] = h_idx + k
            pos_all[n_h:] = l_idx + k

            kind_all = np.empty(total, dtype=object)
            kind_all[:n_h] = "high"
            kind_all[n_h:] = "low"

            price_all = np.empty(total, dtype=np.float64)
            price_all[:n_h] = high[h_idx + k]
            price_all[n_h:] = low[l_idx + k]

            tag_all = np.empty(total, dtype=np.int8)
            tag_all[:n_h] = 0
            tag_all[n_h:] = 1

            order = np.lexsort((tag_all, pos_all))
            pos_sorted = pos_all[order]

            return pd.DataFrame(
                {
                    "time": candles.index[pos_sorted],
                    "kind": kind_all[order],
                    "price": price_all[order],
                    "confirmed_at": candles["close_time"]
                    .iloc[pos_sorted + k]
                    .to_numpy(),
                },
                columns=COLUMNS,
            )

    return (
        pd.DataFrame({c: pd.Series(dtype="object") for c in COLUMNS})
        .astype({"price": float})
        .assign(
            time=pd.Series(dtype="datetime64[ns, UTC]"),
            confirmed_at=pd.Series(dtype="datetime64[ns, UTC]"),
        )[COLUMNS]
    )

from pathlib import Path

import pandas as pd

from smc_trader.data.candles import tf_minutes, with_close_time
from smc_trader.data.resample import resample_ohlc


def _path(root: Path, symbol: str) -> Path:
    return Path(root) / f"{symbol}_M1.parquet"


def save_m1(root: Path, symbol: str, df: pd.DataFrame) -> None:
    path = _path(root, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        df = pd.concat([pd.read_parquet(path), df])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    df.to_parquet(path)


def load_candles(
    root: Path,
    symbol: str,
    tf: str = "M1",
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    path = _path(root, symbol)
    if not path.exists():
        raise FileNotFoundError(f"Sem dados M1 para {symbol}: arquivo não encontrado em {path}")
    tf_minutes(tf)
    m1 = pd.read_parquet(path)
    out = m1 if tf == "M1" else resample_ohlc(m1, tf)
    if tf == "M1":
        out = with_close_time(out, "M1")
    if start is not None:
        out = out[out.index >= start]
    if end is not None:
        out = out[out.index < end]
    return out

import os
from pathlib import Path

import pandas as pd

from smc_trader.data.candles import tf_minutes, with_close_time
from smc_trader.data.resample import resample_ohlc

SOURCES = ("dukascopy", "mt5", "profit")


def _path(root: Path, symbol: str, source: str) -> Path:
    if source not in SOURCES:
        raise ValueError(
            f"source deve ser um de {sorted(SOURCES)}, recebido: {source!r}"
        )
    return Path(root) / f"{symbol}_M1_{source}.parquet"


def save_m1(
    root: Path, symbol: str, df: pd.DataFrame, source: str = "dukascopy"
) -> None:
    path = _path(root, symbol, source)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        df = pd.concat([pd.read_parquet(path), df])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    tmp = path.with_name(path.name + ".tmp")
    try:
        df.to_parquet(tmp)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def existing_months(root: Path, symbol: str, source: str = "dukascopy") -> set[str]:
    """Meses ("AAAA-MM", UTC) que têm ao menos um candle M1 gravado."""
    path = _path(root, symbol, source)
    if not path.exists():
        return set()
    index = pd.read_parquet(path, columns=["close"]).index
    return set(index.strftime("%Y-%m"))


def load_candles(
    root: Path,
    symbol: str,
    tf: str = "M1",
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
    source: str = "dukascopy",
) -> pd.DataFrame:
    path = _path(root, symbol, source)
    if not path.exists():
        raise FileNotFoundError(
            f"Sem dados M1 para {symbol} (fonte {source}): arquivo não encontrado em {path}"
        )
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

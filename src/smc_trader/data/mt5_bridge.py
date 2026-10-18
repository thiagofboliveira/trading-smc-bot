from pathlib import Path

import pandas as pd

from smc_trader.config import DataConfig

_OUT_COLUMNS = ["open", "high", "low", "close", "volume", "spread"]


def import_mt5_csv(path: Path, data_cfg: DataConfig) -> pd.DataFrame:
    """Lê o CSV exportado do MT5 (horário do servidor) e devolve M1 em UTC."""
    raw = pd.read_csv(path)
    server = pd.to_datetime(raw["time"], unit="s")  # relógio do servidor, ingênuo
    if data_cfg.server_timezone is not None:
        local = server.dt.tz_localize(
            data_cfg.server_timezone, ambiguous="NaT", nonexistent="NaT"
        )
    else:
        shifted = server - pd.Timedelta(hours=data_cfg.server_ny_offset_hours)
        local = shifted.dt.tz_localize(
            "America/New_York", ambiguous="NaT", nonexistent="NaT"
        )
    df = pd.DataFrame(
        {
            "open": raw["open"].astype(float),
            "high": raw["high"].astype(float),
            "low": raw["low"].astype(float),
            "close": raw["close"].astype(float),
            "volume": raw["tick_volume"].astype(float),
            "spread": raw["spread"].astype(float),
        }
    )
    df.index = pd.DatetimeIndex(local.dt.tz_convert("UTC"), name="time")
    df = df[df.index.notna()]
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df[_OUT_COLUMNS]

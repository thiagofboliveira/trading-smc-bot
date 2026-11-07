import pandas as pd

TF_MINUTES: dict[str, int] = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}


def tf_minutes(tf: str) -> int:
    if tf not in TF_MINUTES:
        raise ValueError(f"Timeframe desconhecido {tf!r}; válidos: {sorted(TF_MINUTES)}")
    return TF_MINUTES[tf]


def with_close_time(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    out = df.copy()
    out["close_time"] = out.index + pd.Timedelta(minutes=tf_minutes(tf))
    return out

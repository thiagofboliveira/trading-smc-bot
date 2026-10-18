import pandas as pd


def calculate_sma(series: pd.Series, period: int) -> pd.Series:
    """Calcula Média Móvel Simples (SMA) com min_periods = period (sem valor antes do warmup)."""
    return series.rolling(window=period, min_periods=period).mean()


def calculate_ema(series: pd.Series, period: int) -> pd.Series:
    """Calcula Média Móvel Exponencial (EMA) com min_periods = period."""
    return series.ewm(span=period, min_periods=period, adjust=False).mean()

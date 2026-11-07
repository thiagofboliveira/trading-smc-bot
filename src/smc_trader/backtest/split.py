from dataclasses import dataclass
import pandas as pd


@dataclass(frozen=True)
class WalkForwardWindow:
    window_id: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    train_df: pd.DataFrame
    test_df: pd.DataFrame


def split_is_oos(
    df: pd.DataFrame, is_ratio: float = 0.7
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Divide a série temporal estritamente em In-Sample (70%) e Out-of-Sample (30%)."""
    if df.empty:
        return df.copy(), df.copy()

    split_idx = int(len(df) * is_ratio)
    # Garante pelo menos 1 item em cada se len >= 2
    split_idx = max(1, min(split_idx, len(df) - 1)) if len(df) > 1 else split_idx

    is_df = df.iloc[:split_idx]
    oos_df = df.iloc[split_idx:]
    return is_df, oos_df


def generate_walk_forward_windows(
    df: pd.DataFrame,
    train_days: int = 60,
    test_days: int = 30,
    step_days: int = 30,
) -> list[WalkForwardWindow]:
    """Gera janelas de walk-forward rolante (ex: 2 meses treino + 1 mês teste, avançando 1 mês)."""
    if df.empty or len(df) < 100:
        return []

    windows: list[WalkForwardWindow] = []
    first_time = df.index[0]
    last_time = df.index[-1]

    curr_start = first_time
    window_id = 1

    train_delta = pd.Timedelta(days=train_days)
    test_delta = pd.Timedelta(days=test_days)
    step_delta = pd.Timedelta(days=step_days)

    while curr_start + train_delta + test_delta <= last_time + pd.Timedelta(days=1):
        train_start = curr_start
        train_end = curr_start + train_delta
        test_start = train_end
        test_end = test_start + test_delta

        train_mask = (df.index >= train_start) & (df.index < train_end)
        test_mask = (df.index >= test_start) & (df.index < test_end)

        train_sub = df.loc[train_mask]
        test_sub = df.loc[test_mask]

        if not train_sub.empty and not test_sub.empty:
            windows.append(
                WalkForwardWindow(
                    window_id=window_id,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    train_df=train_sub,
                    test_df=test_sub,
                )
            )
            window_id += 1

        curr_start += step_delta

    return windows

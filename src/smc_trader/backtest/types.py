from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from smc_trader.config import BacktestConfig


@dataclass(frozen=True)
class Position:
    """Posição em aberto no mercado."""

    symbol: str
    direction: Literal["long", "short"]
    zone_kind: Literal["OB", "FVOB", "BREAKER"]
    entry_mode: Literal["touch", "confirmation", "hybrid"]
    entry_time: pd.Timestamp
    entry_price: float
    stop_loss: float
    take_profit: float | None
    initial_risk: float
    zone_created_at: pd.Timestamp


@dataclass(frozen=True)
class Trade:
    """Operação encerrada no backtest."""

    id: str
    symbol: str
    direction: Literal["long", "short"]
    zone_kind: Literal["OB", "FVOB", "BREAKER"]
    entry_mode: Literal["touch", "confirmation", "hybrid"]
    entry_time: pd.Timestamp
    entry_price: float
    stop_loss: float
    take_profit: float | None
    exit_time: pd.Timestamp
    exit_price: float
    exit_reason: Literal["tp", "sl", "session_close", "trailing"]
    r_multiple: float
    pnl: float
    costs: float
    zone_created_at: pd.Timestamp


@dataclass
class DailyStats:
    """Estatísticas de um dia de negociação para controle de limites."""

    date: str
    trades_count: int = 0
    stops_count: int = 0
    gains_count: int = 0
    locked: bool = False


@dataclass(frozen=True)
class BacktestResult:
    """Resultado completo da execução de backtest."""

    trades: list[Trade]
    metrics: dict[str, Any]
    config: BacktestConfig

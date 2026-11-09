"""Núcleo de domínio e SDK da plataforma SMC Trader."""

from smc_trader.core.strategy import BaseStrategy
from smc_trader.core.types import (
    DecisionRecord,
    Employee,
    EmployeeStage,
    EquityPoint,
    OrderIntent,
    OrderIntentType,
    RunRecord,
    SignalRecord,
    TradeRecord,
)

__all__ = [
    "BaseStrategy",
    "DecisionRecord",
    "Employee",
    "EmployeeStage",
    "EquityPoint",
    "OrderIntent",
    "OrderIntentType",
    "RunRecord",
    "SignalRecord",
    "TradeRecord",
]

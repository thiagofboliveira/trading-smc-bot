"""Tipos fundamentais do domínio (Fase E2 da spec do produto).

Define as entidades de funcionários, ciclo de vida, intenções de ordens,
sinais, decisões, operações e patrimônio.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class EmployeeStage(StrEnum):
    """Estágios do ciclo de vida de um funcionário (SPEC_PRODUTO.md seção 6.1)."""

    CANDIDATE = "candidato"
    PROBATION = "em_experiencia"
    HIRED = "contratado"
    SUSPENDED = "afastado"
    FIRED = "desligado"


class OrderIntentType(StrEnum):
    """Tipos de intenção emitidos por uma estratégia isolada."""

    PLACE_LIMIT = "place_limit"
    PLACE_STOP = "place_stop"
    CANCEL = "cancel"
    MODIFY_STOP = "modify_stop"
    CLOSE_MARKET = "close_market"


@dataclass(frozen=True)
class OrderIntent:
    """Intenção emitida pelo núcleo da estratégia sem acoplamento a corretora."""

    intent_type: OrderIntentType
    direction: Literal["long", "short"]
    price: float
    stop_loss: float
    take_profit: float | None = None
    expiry_bars: int | None = None
    comment: str = ""


@dataclass
class Employee:
    """Representação de um funcionário (estratégia configurada na empresa)."""

    id: str
    name: str
    strategy_id: str
    symbol: str
    timeframe: str
    stage: EmployeeStage = EmployeeStage.CANDIDATE
    virtual_capital: float = 10000.0
    params: dict[str, Any] = field(default_factory=dict)
    avatar: str = "💼"
    created_at: str = ""
    updated_at: str = ""
    notes: str = ""


@dataclass
class SignalRecord:
    """Registro de setup/sinal detectado por um funcionário."""

    id: str
    employee_id: str
    timestamp: str
    direction: Literal["long", "short"]
    entry_price: float
    stop_loss: float
    take_profit: float | None
    valid_until: str
    status: Literal["pending", "executed", "ignored", "expired", "cancelled"] = "pending"
    image_path: str | None = None


@dataclass
class DecisionRecord:
    """Decisão humana sobre um sinal (P4 - Humano no comando)."""

    id: str
    signal_id: str
    user: str
    action: Literal["enter", "ignore", "timeout"]
    timestamp: str


@dataclass
class TradeRecord:
    """Operação fechada com rastreabilidade da fonte (P3)."""

    id: str
    employee_id: str
    source: Literal["backtest", "paper", "live"]
    direction: Literal["long", "short"]
    entry_time: str
    entry_price: float
    exit_time: str
    exit_price: float
    r_multiple: float
    pnl: float
    exit_reason: str
    costs: float = 0.0


@dataclass
class EquityPoint:
    """Ponto temporal da curva de patrimônio por funcionário e fonte."""

    employee_id: str
    source: Literal["backtest", "paper", "live"]
    timestamp: str
    equity: float
    id: int | None = None


@dataclass
class RunRecord:
    """Auditoria reproduzível de backtest ou homologação."""

    id: str
    employee_id: str
    period_start: str
    period_end: str
    data_hash: str
    config_hash: str
    git_commit: str
    metrics: dict[str, Any]
    created_at: str

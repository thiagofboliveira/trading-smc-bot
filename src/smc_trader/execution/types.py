"""Tipos e estruturas de dados para execução ao vivo em produção no MetaTrader 5."""

from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd


@dataclass
class AccountInfo:
    balance: float
    equity: float
    margin: float
    free_margin: float
    currency: str = "USD"
    leverage: int = 100
    server: str = ""
    login: int = 0


@dataclass
class SymbolInfo:
    symbol: str
    bid: float
    ask: float
    point: float
    digits: int
    spread: float
    min_lot: float = 0.01
    max_lot: float = 100.0
    lot_step: float = 0.01
    tick_value: float = 1.0  # Valor financeiro de 1 tick por 1 lote
    tick_size: float = 0.0   # Tamanho do tick (0.0 = fallback para point)
    trade_contract_size: float = 100.0


@dataclass
class LivePosition:
    ticket: int
    symbol: str
    direction: Literal["long", "short"]
    volume: float
    open_price: float
    current_price: float
    stop_loss: float
    take_profit: float
    open_time: pd.Timestamp
    initial_risk: float
    magic: int = 888111
    comment: str = "SMC-Auto"
    cmd_id: str = ""
    custom_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class OrderRequest:
    symbol: str
    direction: Literal["long", "short"]
    volume: float
    order_type: Literal["market", "limit", "stop"]
    price: float
    stop_loss: float
    take_profit: float
    magic: int = 888111
    comment: str = "SMC-Auto"
    deviation: int = 20  # Max slippage em pontos
    cmd_id: str = ""


@dataclass
class ClosedTradeInfo:
    ticket: int
    symbol: str
    direction: Literal["long", "short"]
    volume: float
    open_price: float
    close_price: float
    open_time: pd.Timestamp
    close_time: pd.Timestamp
    pnl: float
    r_multiple: float
    magic: int
    comment: str = ""


@dataclass
class OrderResult:
    success: bool
    ticket: int = 0
    price: float = 0.0
    volume: float = 0.0
    comment: str = ""
    error_code: int = 0
    cmd_id: str = ""

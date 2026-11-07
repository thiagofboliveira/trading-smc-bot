"""Diário estruturado de ordens, sinais e execuções em JSONL (L-11).

Registra de forma imutável e auditável cada evento operacional:
- Detecção de sinal institucional (BOS, Fibo, Zonas)
- Envio de ordem (a mercado ou pendente limite)
- Confirmação de execução / retcode / slippage real
- Modificação de stop protetor (trailing, break-even, trava 2:1)
- Encerramento de posição com PnL, R-múltiplo e motivo
- Bloqueios operacionais (limite diário, kill switch, spread alto)
"""

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger("smc.journal")


class TradeJournal:
    """Diário de operações em arquivo JSONL para auditoria e observabilidade contínua."""

    def __init__(self, log_path: Path = Path("logs/live_trade_journal.jsonl")) -> None:
        self.log_path = log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def log_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Grava uma entrada JSON estruturada no diário."""
        entry = {
            "timestamp": pd.Timestamp.now(tz="UTC").isoformat(),
            "event": event_type,
            **data,
        }
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.error(f"Erro ao gravar no diário de trades: {exc}")

    def log_signal(
        self,
        symbol: str,
        strategy: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.log_event(
            "SIGNAL",
            {
                "symbol": symbol,
                "strategy": strategy,
                "direction": direction,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "details": details or {},
            },
        )

    def log_order_dispatch(
        self,
        symbol: str,
        order_type: str,
        direction: str,
        volume: float,
        price: float,
        stop_loss: float,
        take_profit: float,
        magic: int,
        cmd_id: str,
    ) -> None:
        self.log_event(
            "ORDER_DISPATCH",
            {
                "symbol": symbol,
                "order_type": order_type,
                "direction": direction,
                "volume": volume,
                "price": price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "magic": magic,
                "cmd_id": cmd_id,
            },
        )

    def log_order_fill(
        self,
        symbol: str,
        ticket: int,
        requested_price: float,
        filled_price: float,
        volume: float,
        cmd_id: str,
    ) -> None:
        slippage = abs(filled_price - requested_price)
        self.log_event(
            "ORDER_FILL",
            {
                "symbol": symbol,
                "ticket": ticket,
                "requested_price": requested_price,
                "filled_price": filled_price,
                "slippage": slippage,
                "volume": volume,
                "cmd_id": cmd_id,
            },
        )

    def log_trade_close(
        self,
        symbol: str,
        ticket: int,
        close_price: float,
        pnl: float,
        r_multiple: float,
        reason: str,
    ) -> None:
        self.log_event(
            "TRADE_CLOSE",
            {
                "symbol": symbol,
                "ticket": ticket,
                "close_price": close_price,
                "pnl": pnl,
                "r_multiple": r_multiple,
                "reason": reason,
            },
        )

    def log_block(self, symbol: str, reason: str, details: dict[str, Any] | None = None) -> None:
        self.log_event(
            "OPERATION_BLOCKED",
            {
                "symbol": symbol,
                "reason": reason,
                "details": details or {},
            },
        )

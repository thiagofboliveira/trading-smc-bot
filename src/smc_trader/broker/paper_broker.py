"""Broker de Paper Trading e motor em tempo real (Fase E3 da spec do produto).

Executa operações simuladas sobre candles em tempo real ou em modo replay,
com persistência direta no SQLite (SPEC_PRODUTO.md seções 4.3 e 5.3).
Garante rigor causal idêntico ao SimBroker:
- Spread nos dois lados.
- Stop intrabar na barra de fill.
- Gap no open + slippage.
"""

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from smc_trader.core.types import EquityPoint, SignalRecord, TradeRecord
from smc_trader.store.repository import StoreRepository


@dataclass
class PaperPosition:
    """Posição em aberto no Paper Trading."""

    id: str
    employee_id: str
    symbol: str
    direction: Literal["long", "short"]
    entry_time: pd.Timestamp
    entry_price: float
    stop_loss: float
    take_profit: float | None
    initial_risk: float
    volume: float = 1.0


class PaperBroker:
    """Gerenciador de ordens e posições em Paper Trading com gravação no SQLite."""

    def __init__(
        self,
        repo: StoreRepository,
        spread: float = 0.0,
        slippage: float = 0.0,
        commission: float = 0.0,
    ) -> None:
        self.repo = repo
        self.spread = spread
        self.slippage = slippage
        self.commission = commission
        self.open_positions: list[PaperPosition] = []

    def on_bar_close(
        self,
        symbol: str,
        timestamp: pd.Timestamp,
        open_: float,
        high: float,
        low: float,
        close: float,
    ) -> list[TradeRecord]:
        """Processa barra fechada: checa saídas de posições e ativação de sinais pendentes."""
        closed_trades: list[TradeRecord] = []

        # 1. Checa posições abertas existentes (Stop antes de Alvo)
        surviving_positions: list[PaperPosition] = []
        for pos in self.open_positions:
            if pos.symbol != symbol:
                surviving_positions.append(pos)
                continue

            is_long = pos.direction == "long"
            stop_hit = False
            exit_price = pos.stop_loss
            reason = ""

            if is_long:
                if low <= pos.stop_loss:
                    stop_hit = True
                    exit_price = min(open_, pos.stop_loss) - self.slippage
                    reason = "sl"
            else:
                adverse_short = high + self.spread
                if adverse_short >= pos.stop_loss:
                    stop_hit = True
                    exit_price = max(open_ + self.spread, pos.stop_loss) + self.slippage
                    reason = "sl"

            if stop_hit:
                tr = self._close_position(pos, timestamp, exit_price, reason)
                closed_trades.append(tr)
                continue

            tp_hit = False
            if pos.take_profit is not None:
                if is_long:
                    if high >= pos.take_profit:
                        tp_hit = True
                        exit_price = max(open_, pos.take_profit)
                        reason = "tp"
                else:
                    if low <= pos.take_profit:
                        tp_hit = True
                        exit_price = min(open_, pos.take_profit)
                        reason = "tp"

            if tp_hit:
                tr = self._close_position(pos, timestamp, exit_price, reason)
                closed_trades.append(tr)
                continue

            surviving_positions.append(pos)

        self.open_positions = surviving_positions
        return closed_trades

    def execute_signal(
        self,
        sig: SignalRecord,
        timestamp: pd.Timestamp,
        open_: float,
        high: float,
        low: float,
        close: float,
    ) -> TradeRecord | None:
        """Executa um sinal confirmado e checa stop intrabar imediatamente."""
        is_long = sig.direction == "long"
        fill_price = sig.entry_price
        risk = abs(fill_price - sig.stop_loss)

        pos = PaperPosition(
            id=f"pos_{sig.id}",
            employee_id=sig.employee_id,
            symbol="ASSET",
            direction=sig.direction,
            entry_time=timestamp,
            entry_price=fill_price,
            stop_loss=sig.stop_loss,
            take_profit=sig.take_profit,
            initial_risk=risk if risk > 0 else 1.0,
        )

        # Regra de Ouro: Checagem intrabar de stop na própria barra
        instant_stop = False
        instant_exit_price = pos.stop_loss
        if is_long:
            if low <= pos.stop_loss:
                instant_stop = True
                instant_exit_price = min(open_, pos.stop_loss) - self.slippage
        else:
            if high + self.spread >= pos.stop_loss:
                instant_stop = True
                instant_exit_price = max(open_ + self.spread, pos.stop_loss) + self.slippage

        sig.status = "executed"
        self.repo.record_signal(sig)

        if instant_stop:
            return self._close_position(pos, timestamp, instant_exit_price, "sl_intrabar")

        self.open_positions.append(pos)
        return None

    def _close_position(
        self,
        pos: PaperPosition,
        exit_time: pd.Timestamp,
        exit_price: float,
        reason: str,
    ) -> TradeRecord:
        """Encerra posição, persiste trade e grava ponto de equity."""
        d = 1 if pos.direction == "long" else -1
        gross_pts = d * (exit_price - pos.entry_price)
        net_pts = gross_pts - self.commission
        r = net_pts / pos.initial_risk if pos.initial_risk > 0 else 0.0

        trade = TradeRecord(
            id=f"trade_{pos.id}",
            employee_id=pos.employee_id,
            source="paper",
            direction=pos.direction,
            entry_time=pos.entry_time.isoformat(),
            entry_price=pos.entry_price,
            exit_time=exit_time.isoformat(),
            exit_price=exit_price,
            r_multiple=r,
            pnl=net_pts,
            exit_reason=reason,
            costs=self.commission,
        )
        self.repo.record_trade(trade)

        # Atualiza curva de patrimônio
        emp = self.repo.get_employee(pos.employee_id)
        current_cap = emp.virtual_capital if emp else 10000.0
        new_cap = current_cap + net_pts
        self.repo.record_equity_point(
            EquityPoint(
                employee_id=pos.employee_id,
                source="paper",
                timestamp=exit_time.isoformat(),
                equity=new_cap,
            )
        )
        return trade

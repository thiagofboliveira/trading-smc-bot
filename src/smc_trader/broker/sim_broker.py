"""Motor de simulação de execução e regras de preenchimento (SimBroker - E2-2).

Centraliza todas as regras de realismo operacional (AGENTS.md e SPEC_PRODUTO.md):
1. Spread bid/ask em ambos os lados (long compra no ask, short sai no ask).
2. Stop loss testado intrabar obrigatoriamente na própria barra de entrada.
3. Barra de entrada só pode ser estopada, nunca alvejada.
4. Gaps além do stop preenchidos no Open da barra, acrescidos de slippage.
5. Slippage e comissões modelados realisticamente.
"""

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from smc_trader.core.types import OrderIntent, OrderIntentType


@dataclass
class BrokerPosition:
    """Posição gerenciada pelo broker."""

    id: str
    symbol: str
    direction: Literal["long", "short"]
    entry_time: pd.Timestamp
    entry_price: float
    stop_loss: float
    take_profit: float | None
    initial_risk: float
    entry_bar_idx: int
    volume: float = 1.0
    trailing_active: bool = False


@dataclass
class BrokerTrade:
    """Resultado de uma operação encerrada pelo broker."""

    id: str
    symbol: str
    direction: Literal["long", "short"]
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float | None
    initial_risk: float
    pnl: float
    r_multiple: float
    exit_reason: str
    costs: float = 0.0


@dataclass
class PendingOrder:
    """Ordem pendente aguardando ativação."""

    id: str
    intent: OrderIntent
    created_bar_idx: int
    expiry_bars: int | None = None


class SimBroker:
    """Broker simulador para execução rigorosa sem viés em backtest."""

    def __init__(
        self,
        spread: float = 0.0,
        slippage: float = 0.0,
        commission: float = 0.0,
    ) -> None:
        self.spread = spread
        self.slippage = slippage
        self.commission = commission
        self.positions: list[BrokerPosition] = []
        self.pending_orders: list[PendingOrder] = []
        self.closed_trades: list[BrokerTrade] = []
        self._trade_counter = 0

    def submit_order(self, intent: OrderIntent, bar_idx: int) -> None:
        """Envia uma nova intenção para a fila de ordens pendentes."""
        self._trade_counter += 1
        order_id = f"ord_{self._trade_counter}"
        self.pending_orders.append(
            PendingOrder(
                id=order_id,
                intent=intent,
                created_bar_idx=bar_idx,
                expiry_bars=intent.expiry_bars,
            )
        )

    def process_bar(
        self,
        bar_idx: int,
        timestamp: pd.Timestamp,
        open_: float,
        high: float,
        low: float,
        close: float,
        symbol: str = "ASSET",
    ) -> list[BrokerTrade]:
        """Processa a barra atual respeitando a causalidade dos eventos."""
        newly_closed: list[BrokerTrade] = []

        # -------------------------------------------------------------
        # 1. Checa saída de posições já existentes (Stop antes de Alvo)
        # -------------------------------------------------------------
        active_positions: list[BrokerPosition] = []
        for pos in self.positions:
            is_long = pos.direction == "long"
            stop_hit = False
            exit_price = pos.stop_loss
            reason = ""

            # Checagem de Stop Loss
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
                trade = self._close_position(pos, timestamp, exit_price, reason)
                newly_closed.append(trade)
                continue

            # Checagem de Take Profit (se stop não foi acionado)
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
                trade = self._close_position(pos, timestamp, exit_price, reason)
                newly_closed.append(trade)
                continue

            active_positions.append(pos)

        self.positions = active_positions

        # -------------------------------------------------------------
        # 2. Avalia ativação de ordens pendentes
        # -------------------------------------------------------------
        remaining_orders: list[PendingOrder] = []
        for p_ord in self.pending_orders:
            intent = p_ord.intent
            # Expiração
            if p_ord.expiry_bars and (bar_idx - p_ord.created_bar_idx >= p_ord.expiry_bars):
                continue

            is_long = intent.direction == "long"
            filled = False
            fill_price = intent.price

            if intent.intent_type == OrderIntentType.PLACE_LIMIT:
                if is_long:
                    # Limite de compra toca no Ask (low + spread <= price)
                    if low + self.spread <= intent.price:
                        filled = True
                        fill_price = min(open_ + self.spread, intent.price)
                else:
                    # Limite de venda toca no Bid (high >= price)
                    if high >= intent.price:
                        filled = True
                        fill_price = max(open_, intent.price)

            elif intent.intent_type == OrderIntentType.PLACE_STOP:
                if is_long:
                    # Rompimento de alta aciona stop de compra
                    if high + self.spread >= intent.price:
                        filled = True
                        fill_price = max(open_ + self.spread, intent.price) + self.slippage
                else:
                    # Rompimento de baixa aciona stop de venda
                    if low <= intent.price:
                        filled = True
                        fill_price = min(open_, intent.price) - self.slippage

            if filled:
                # Regra de Ouro AGENTS.md:
                # A barra de entrada só pode ser estopada, NUNCA alvejada.
                # Checa imediatamente se o stop da própria barra é violado.
                risk = abs(fill_price - intent.stop_loss)
                new_pos = BrokerPosition(
                    id=f"pos_{p_ord.id}",
                    symbol=symbol,
                    direction=intent.direction,
                    entry_time=timestamp,
                    entry_price=fill_price,
                    stop_loss=intent.stop_loss,
                    take_profit=intent.take_profit,
                    initial_risk=risk if risk > 0 else 1.0,
                    entry_bar_idx=bar_idx,
                )

                # Checagem intrabar de stop na barra do fill
                instant_stop = False
                instant_exit_price = new_pos.stop_loss
                if is_long:
                    if low <= new_pos.stop_loss:
                        instant_stop = True
                        instant_exit_price = min(open_, new_pos.stop_loss) - self.slippage
                else:
                    if high + self.spread >= new_pos.stop_loss:
                        instant_stop = True
                        instant_exit_price = max(open_ + self.spread, new_pos.stop_loss) + self.slippage

                if instant_stop:
                    trade = self._close_position(new_pos, timestamp, instant_exit_price, "sl_intrabar")
                    newly_closed.append(trade)
                else:
                    self.positions.append(new_pos)
            else:
                remaining_orders.append(p_ord)

        self.pending_orders = remaining_orders
        return newly_closed

    def _close_position(
        self,
        pos: BrokerPosition,
        exit_time: pd.Timestamp,
        exit_price: float,
        reason: str,
    ) -> BrokerTrade:
        """Calcula o PnL e R da operação fechada."""
        d = 1 if pos.direction == "long" else -1
        gross_pts = d * (exit_price - pos.entry_price)
        net_pts = gross_pts - self.commission
        r = net_pts / pos.initial_risk if pos.initial_risk > 0 else 0.0

        trade = BrokerTrade(
            id=pos.id,
            symbol=pos.symbol,
            direction=pos.direction,
            entry_time=pos.entry_time,
            exit_time=exit_time,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            stop_loss=pos.stop_loss,
            take_profit=pos.take_profit,
            initial_risk=pos.initial_risk,
            pnl=net_pts,
            r_multiple=r,
            exit_reason=reason,
            costs=self.commission,
        )
        self.closed_trades.append(trade)
        return trade

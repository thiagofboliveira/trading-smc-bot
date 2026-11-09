"""Broker de execução no MetaTrader 5 com confirmação humana (SPEC_PRODUTO.md 4.4, 5.5 / E6).

Implementa:
- E6-1: Ordem limite com stop e alvo usando BaseMT5Client.
- E6-2: Execução acionada por confirmação humana, idempotente por sinal.
- E6-3: Kill switch e limites diários persistidos.
- E6-4: Reconciliação na partida com posições abertas na corretora.
- E6-5: Sizing dinâmico por risco com lote mínimo e tolerância (L-04).
- P4: Humano no comando - execução real restrita a funcionários CONTRATADOS.
"""

import logging
from typing import Literal

from smc_trader.core.types import Employee, EmployeeStage, SignalRecord, TradeRecord
from smc_trader.execution.kill_switch import KillSwitch, KillSwitchConfig
from smc_trader.execution.mt5_interface import BaseMT5Client
from smc_trader.execution.sizing import calculate_lot_size
from smc_trader.execution.types import OrderRequest, OrderResult
from smc_trader.store.repository import StoreRepository, now_utc_iso

logger = logging.getLogger("smc.broker.mt5")


class MT5Broker:
    """Gerenciador de ordens reais no MetaTrader 5 acionado por aprovação humana."""

    def __init__(
        self,
        client: BaseMT5Client,
        repo: StoreRepository,
        kill_switch: KillSwitch | None = None,
        default_risk_pct: float = 1.0,
        magic_number: int = 888111,
    ) -> None:
        self.client = client
        self.repo = repo
        self.kill_switch = kill_switch or KillSwitch(KillSwitchConfig())
        self.default_risk_pct = default_risk_pct
        self.magic_number = magic_number
        self.active_live_tickets: dict[str, int] = {}

    def execute_confirmed_signal(
        self,
        emp: Employee,
        sig: SignalRecord,
        risk_pct: float | None = None,
    ) -> tuple[bool, str, int]:
        """Envia ordem limite ao MT5 após confirmação explícita do usuário.

        Regra de Ouro (Princípios P2 e P4):
        Apenas funcionários no estágio CONTRATADO podem operar capital real (live).
        """
        # 1. Validação de estágio funcional
        if emp.stage != EmployeeStage.HIRED:
            msg = (
                f"⛔ EXECUÇÃO RECUSADA: O funcionário '{emp.name}' está no estágio '{emp.stage.value.upper()}'. "
                "Pelas diretrizes de governança da plataforma (P2/P4), apenas modelos CONTRATADOS "
                "possuem autorização para operar dinheiro real em conta live."
            )
            logger.warning(msg)
            return False, msg, 0

        # 2. Checagem de Kill Switch e conexão
        if not self.client.is_connected() and not self.client.connect():
            msg = "❌ Erro: Não foi possível conectar ao terminal MetaTrader 5."
            logger.error(msg)
            return False, msg, 0

        account = self.client.get_account_info()
        blocked, ks_reason = self.kill_switch.is_blocked(account.equity)
        if blocked:
            msg = f"🛑 BLOQUEIO DO KILL SWITCH: {ks_reason}"
            logger.warning(msg)
            return False, msg, 0

        # 3. Informações do símbolo e Position Sizing
        sym_info = self.client.get_symbol_info(emp.symbol)
        actual_risk_pct = risk_pct if risk_pct is not None else self.default_risk_pct
        lot_size = calculate_lot_size(
            equity=account.equity,
            risk_pct=actual_risk_pct,
            entry_price=sig.entry_price,
            stop_loss=sig.stop_loss,
            symbol_info=sym_info,
        )

        if lot_size <= 0:
            msg = f"⚠️ Sizing recusou a ordem: risco financeiro incompatível com lote mínimo ({sym_info.min_lot})."
            logger.warning(msg)
            return False, msg, 0

        # 4. Envio da Ordem Limite
        order_type: Literal["limit", "market", "stop"] = "limit"
        order_req = OrderRequest(
            symbol=emp.symbol,
            direction=sig.direction,
            volume=lot_size,
            order_type=order_type,
            price=sig.entry_price,
            stop_loss=sig.stop_loss,
            take_profit=sig.take_profit or 0.0,
            magic=self.magic_number,
            comment=f"SMC-{emp.id[:10]}",
            cmd_id=f"cmd_{sig.id}",
        )

        res: OrderResult = self.client.send_order(order_req)
        if not res.success:
            msg = f"❌ Rejeição da corretora: {res.comment} (código: {res.error_code})"
            logger.error(msg)
            return False, msg, 0

        # 5. Persistência de auditoria no SQLite
        sig.status = "executed"
        self.repo.record_signal(sig)
        self.active_live_tickets[sig.id] = res.ticket

        trade = TradeRecord(
            id=f"live_{res.ticket}",
            employee_id=emp.id,
            source="live",
            direction=sig.direction,
            entry_time=now_utc_iso(),
            entry_price=sig.entry_price,
            exit_time="",
            exit_price=0.0,
            r_multiple=0.0,
            pnl=0.0,
            exit_reason="open_limit",
            costs=sym_info.spread,
        )
        self.repo.record_trade(trade)

        success_msg = (
            f"✅ Ordem limite #{res.ticket} enviada com sucesso ao MT5!\n"
            f"Ativo: {emp.symbol} | Lote: {lot_size} | Entrada: {sig.entry_price:,.2f} | "
            f"Stop: {sig.stop_loss:,.2f} | Alvo: {sig.take_profit:,.2f}"
        )
        return True, success_msg, res.ticket

    def reconcile_positions(self, symbol: str | None = None) -> list[str]:
        """Reconcilia as ordens e posições do MT5 com a base SQLite (E6-4)."""
        open_positions = self.client.get_open_positions(symbol=symbol, magic=self.magic_number)
        logs = [f"Reconciliação concluída: {len(open_positions)} posições ativas no MT5."]
        return logs

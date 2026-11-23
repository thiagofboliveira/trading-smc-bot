"""Módulo de Kill Switch e Proteção de Risco de Conta em Produção (L-10).

Monitora e aplica bloqueios imediatos:
1. Perda diária máxima (% do equity) -> fecha todas as posições e bloqueia até o dia seguinte.
2. Máximo de perdas consecutivas -> bloqueia novas operações no dia.
3. Spread anômalo / pico de spread -> bloqueia novas entradas.
4. Latência de dados / candle atrasado -> bloqueia ordens até normalização.
"""

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from smc_trader.config import KillSwitchConfig
from smc_trader.execution.mt5_interface import BaseMT5Client

logger = logging.getLogger("smc.kill_switch")


@dataclass
class KillSwitchStatus:
    triggered: bool = False
    reason: str = ""
    emergency_stopped: bool = False


class KillSwitch:
    """Guarda e executor de proteções de capital."""

    def __init__(
        self,
        config: KillSwitchConfig | None = None,
        state_file: Path | None = None,
    ) -> None:
        self.config = config or KillSwitchConfig()
        self.is_active = False
        self.trigger_reason = ""
        self.starting_equity_day: float | None = None
        self.last_reset_day: pd.Timestamp | None = None
        # Com `state_file`, o saldo base do dia e o estado de parada sobrevivem a um
        # reinício do processo. Sem ele, reiniciar zerava a perda diária acumulada.
        self.state_file = state_file
        self._load_state()

    def _load_state(self) -> None:
        if self.state_file is None or not self.state_file.exists():
            return
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            day = data.get("last_reset_day")
            self.last_reset_day = pd.Timestamp(day) if day else None
            eq = data.get("starting_equity_day")
            self.starting_equity_day = float(eq) if eq is not None else None
            self.is_active = bool(data.get("is_active", False))
            self.trigger_reason = str(data.get("trigger_reason", ""))
        except Exception as exc:  # estado corrompido: parte do zero, mas avisa
            logger.error(f"[KillSwitch] Falha ao ler estado de {self.state_file}: {exc}")

    def _save_state(self) -> None:
        if self.state_file is None:
            return
        data = {
            "last_reset_day": (
                self.last_reset_day.isoformat() if self.last_reset_day is not None else None
            ),
            "starting_equity_day": self.starting_equity_day,
            "is_active": self.is_active,
            "trigger_reason": self.trigger_reason,
        }
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.state_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            tmp.replace(self.state_file)
        except Exception as exc:
            logger.error(f"[KillSwitch] Falha ao salvar estado em {self.state_file}: {exc}")

    def reset_daily_equity_if_new_day(
        self, current_equity: float, now_utc: pd.Timestamp
    ) -> None:
        """Reinicia o equity base diário no início de cada pregão UTC."""
        today = now_utc.floor("D")
        if self.last_reset_day != today:
            self.starting_equity_day = current_equity
            self.last_reset_day = today
            self.is_active = False
            self.trigger_reason = ""
            self._save_state()
            logger.info(
                f"🛡️ [KillSwitch] Novo dia {today.strftime('%Y-%m-%d')}. Saldo base inicial: ${current_equity:.2f}"
            )

    def check_daily_loss(self, current_equity: float) -> tuple[bool, str]:
        """Verifica se a perda diária acumulada excedeu o limite %."""
        if self.starting_equity_day is None or self.starting_equity_day <= 0:
            return False, ""
        loss_pct = (
            (self.starting_equity_day - current_equity) / self.starting_equity_day
        ) * 100.0
        if loss_pct >= self.config.max_daily_loss_pct:
            return (
                True,
                f"Perda diária acumulada de {loss_pct:.2f}% excedeu o teto de {self.config.max_daily_loss_pct:.1f}%",
            )
        return False, ""

    def check_consecutive_losses(self, consecutive_stops: int) -> tuple[bool, str]:
        """Verifica se o número de stops consecutivos atingiu o limite."""
        if consecutive_stops >= self.config.max_consecutive_losses:
            return (
                True,
                f"Atingido limite de {consecutive_stops} stops consecutivos no dia (máx: {self.config.max_consecutive_losses})",
            )
        return False, ""

    def check_spread(
        self, current_spread: float, typical_spread: float
    ) -> tuple[bool, str]:
        """Verifica se o spread atual está anômalo (ex: notícias, baixa liquidez)."""
        if typical_spread <= 0:
            return False, ""
        ratio = current_spread / typical_spread
        if ratio > self.config.max_spread_multiplier:
            return (
                True,
                f"Spread anômalo de {current_spread:.5f} ({ratio:.1f}x o típico {typical_spread:.5f})",
            )
        return False, ""

    def check_data_delay(
        self, last_bar_time: pd.Timestamp, now_utc: pd.Timestamp
    ) -> tuple[bool, str]:
        """Verifica se a série temporal de cotações está atrasada / desconectada."""
        delta_sec = (now_utc - last_bar_time).total_seconds()
        if delta_sec > self.config.max_data_delay_seconds:
            return (
                True,
                f"Dados de mercado atrasados em {delta_sec:.0f}s (tolerância máxima: {self.config.max_data_delay_seconds}s)",
            )
        return False, ""

    def execute_emergency_shutdown(
        self,
        client: BaseMT5Client,
        magics: Iterable[int] | None = None,
        pending_tickets: Iterable[int] = (),
    ) -> None:
        """Cancela as ordens pendentes e encerra as posições do robô.

        `magics`: números mágicos do robô. Só posições e pendentes com esses números são
        tocados (posições manuais e de outros robôs ficam intactas). None = todos.
        `pending_tickets`: pendentes que o motor conhece; somam-se às que o cliente lista.
        As pendentes são canceladas ANTES de fechar as posições, para que nenhuma seja
        executada depois da parada.
        """
        self.is_active = True
        self._save_state()
        magic_set = set(magics) if magics is not None else None
        logger.warning(
            f"🚨 [KillSwitch] PARADA DE EMERGÊNCIA ATIVADA: {self.trigger_reason}. Encerrando todas as operações!"
        )
        to_cancel: set[int] = {int(t) for t in pending_tickets if t}
        try:
            if magic_set is None:
                to_cancel.update(client.get_pending_orders())
            else:
                for m in magic_set:
                    to_cancel.update(client.get_pending_orders(magic=m))
        except Exception as exc:
            logger.error(f"Erro ao listar ordens pendentes na parada de emergência: {exc}")
        for ticket in sorted(to_cancel):
            try:
                if client.cancel_order(ticket):
                    logger.info(f"🚨 [KillSwitch] Ordem pendente #{ticket} cancelada.")
                else:
                    logger.error(f"🚨 [KillSwitch] Falha ao cancelar a ordem pendente #{ticket}.")
            except Exception as exc:
                logger.error(f"Erro ao cancelar a ordem #{ticket}: {exc}")
        try:
            positions = client.get_open_positions()
            for p in positions:
                if magic_set is not None and p.magic not in magic_set:
                    continue
                if client.close_position(p.ticket):
                    logger.info(f"🚨 [KillSwitch] Posição #{p.ticket} ({p.symbol}) encerrada emergencialmente.")
                else:
                    logger.error(f"🚨 [KillSwitch] Falha ao encerrar a posição #{p.ticket} ({p.symbol}).")
        except Exception as exc:
            logger.error(f"Erro ao encerrar posições na parada de emergência: {exc}")

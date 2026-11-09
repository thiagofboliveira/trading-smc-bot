"""Módulo de Kill Switch e Proteção de Risco de Conta em Produção (L-10).

Monitora e aplica bloqueios imediatos:
1. Perda diária máxima (% do equity) -> fecha todas as posições e bloqueia até o dia seguinte.
2. Máximo de perdas consecutivas -> bloqueia novas operações no dia.
3. Spread anômalo / pico de spread -> bloqueia novas entradas.
4. Latência de dados / candle atrasado -> bloqueia ordens até normalização.
"""

import logging
from dataclasses import dataclass

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

    def __init__(self, config: KillSwitchConfig | None = None) -> None:
        self.config = config or KillSwitchConfig()
        self.is_active = False
        self.trigger_reason = ""
        self.starting_equity_day: float | None = None
        self.last_reset_day: pd.Timestamp | None = None

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

    def is_blocked(self, current_equity: float | None = None) -> tuple[bool, str]:
        """Informa se novas operações estão bloqueadas pelo Kill Switch."""
        if self.is_active:
            return True, self.trigger_reason
        if current_equity is not None:
            tripped, reason = self.check_daily_loss(current_equity)
            if tripped:
                self.is_active = True
                self.trigger_reason = reason
                return True, reason
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

    def execute_emergency_shutdown(self, client: BaseMT5Client) -> None:
        """Executa fechamento de emergência de todas as posições abertas e cancela ordens."""
        self.is_active = True
        logger.warning(
            f"🚨 [KillSwitch] PARADA DE EMERGÊNCIA ATIVADA: {self.trigger_reason}. Encerrando todas as operações!"
        )
        try:
            positions = client.get_open_positions()
            for p in positions:
                client.close_position(p.ticket)
                logger.info(f"🚨 [KillSwitch] Posição #{p.ticket} ({p.symbol}) encerrada emergencialmente.")
        except Exception as exc:
            logger.error(f"Erro ao encerrar posições na parada de emergência: {exc}")

import pandas as pd

from smc_trader.config import SessionConfig


class SessionManager:
    """Validador de sessões de negociação e fechamento forçado diário."""

    def __init__(self, config: SessionConfig) -> None:
        self.config = config

    def is_trade_allowed(self, t: pd.Timestamp) -> bool:
        """Verifica se o timestamp UTC atual está dentro de alguma janela de sessão ativa."""
        if not self.config.windows:
            return True
        time_str = t.strftime("%H:%M")
        for window in self.config.windows:
            if window.start <= time_str < window.end:
                return True
        return False

    def should_force_close(self, t: pd.Timestamp) -> bool:
        """Verifica se o timestamp atingiu ou ultrapassou o horário limite de fechamento forçado."""
        if self.config.force_close_time is None:
            return False
        time_str = t.strftime("%H:%M")
        return time_str >= self.config.force_close_time

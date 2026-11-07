import pandas as pd

from smc_trader.backtest.types import DailyStats
from smc_trader.config import LimitsConfig


class DailyLimitsTracker:
    """Rastreador de limites operacionais diários (travas de produção)."""

    def __init__(self, config: LimitsConfig) -> None:
        self.config = config
        self._current_date: str | None = None
        self._stats: DailyStats | None = None

    def _ensure_date(self, t: pd.Timestamp) -> DailyStats:
        date_str = t.strftime("%Y-%m-%d")
        if self._current_date != date_str or self._stats is None:
            self._current_date = date_str
            self._stats = DailyStats(date=date_str)
        return self._stats

    def can_trade(self, t: pd.Timestamp) -> bool:
        """Verifica se novos trades são permitidos no momento t."""
        if not self.config.enabled:
            return True
        stats = self._ensure_date(t)
        return not stats.locked

    def record_trade(self, t: pd.Timestamp, r_multiple: float) -> None:
        """Registra o desfecho de um trade encerrado e atualiza travas."""
        stats = self._ensure_date(t)
        stats.trades_count += 1
        if r_multiple <= 0:
            stats.stops_count += 1
        else:
            stats.gains_count += 1

        if not self.config.enabled:
            return

        if stats.trades_count >= self.config.max_trades_per_day or stats.stops_count >= self.config.max_stops_per_day or stats.gains_count >= self.config.max_gains_per_day:
            stats.locked = True

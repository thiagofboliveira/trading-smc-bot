import math
from typing import Any, Literal
import pandas as pd

from smc_trader.backtest.types import Position
from smc_trader.config import TrailingConfig
from smc_trader.structure.market_structure import StructureEvent


class TrailingManager:
    """Gerenciador do ciclo de vida de condução e trailing stop para uma posição aberta."""

    def __init__(self, config: TrailingConfig, initial_stop: float) -> None:
        self.config = config
        self.activated: bool = False
        self.current_stop: float = initial_stop

    def check_and_update(
        self,
        pos: Position,
        c_open: float,
        c_high: float,
        c_low: float,
        c_close: float,
        t: pd.Timestamp,
        trailing_ema_val: float | None = None,
        bos_events: list[StructureEvent] | None = None,
    ) -> tuple[bool, float, Literal["trailing", "sl"] | None]:
        """Avalia se a condução foi ativada e se houve disparo de saída por trailing.

        Retorna: (should_exit, exit_price, reason)
        """
        if self.config.mode == "none":
            return False, 0.0, None

        long = pos.direction == "long"

        # 1. Checa condição de ativação se ainda não ativado
        if not self.activated:
            current_gain_r = (
                (c_high - pos.entry_price) / pos.initial_risk
                if long
                else (pos.entry_price - c_low) / pos.initial_risk
            )
            has_new_bos = False
            if bos_events:
                needed_dir = "up" if long else "down"
                for e in bos_events:
                    if e.kind == "BOS" and e.direction == needed_dir and e.time > pos.entry_time:
                        has_new_bos = True
                        break

            if self.config.activation == "r_multiple":
                if current_gain_r >= self.config.r_threshold:
                    self.activated = True
            elif self.config.activation == "on_new_bos":
                if has_new_bos:
                    self.activated = True
            elif self.config.activation == "either":
                if current_gain_r >= self.config.r_threshold or has_new_bos:
                    self.activated = True

        # 2. Executa lógica de trailing após ativação
        if self.activated:
            if self.config.mode == "ema":
                if trailing_ema_val is not None and not math.isnan(trailing_ema_val):
                    # Long: candle fechou abaixo da EMA
                    if long and c_close < trailing_ema_val:
                        return True, c_close, "trailing"
                    # Short: candle fechou acima da EMA
                    elif not long and c_close > trailing_ema_val:
                        return True, c_close, "trailing"

            elif self.config.mode == "bos":
                if bos_events:
                    needed_dir = "up" if long else "down"
                    for e in bos_events:
                        if (
                            e.kind == "BOS"
                            and e.direction == needed_dir
                            and e.time > pos.entry_time
                        ):
                            if long and e.range_low > self.current_stop:
                                self.current_stop = e.range_low
                            elif not long and e.range_high < self.current_stop:
                                self.current_stop = e.range_high

                # Verifica se o preço violou o novo stop
                if long and c_low <= self.current_stop:
                    return True, self.current_stop, "trailing"
                elif not long and c_high >= self.current_stop:
                    return True, self.current_stop, "trailing"

        return False, 0.0, None

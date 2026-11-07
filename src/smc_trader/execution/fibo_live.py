"""Avaliador da estratégia SMC Fibo OTE para execução ao vivo (L-02, L-06, L-09).

Não reimplementa a estratégia. A decisão de entrada vem de `FiboOTEStrategy.pending_setup`,
o mesmo código do backtest, rodado sobre a janela de candles atual:

* Sem posição: devolve `PLACE_LIMIT` com a entrada que o backtest executaria na próxima
  barra (ordem limite armada no nível, com validade da perna). Se o setup deixou de valer
  (perna expirada, tocada, invalidada), não devolve nada e o engine cancela a pendente.
* Com posição: trava de lucro e saída por média móvel sobre a última barra fechada, com as
  mesmas séries de preço do backtest (short compara com o ask na trava e no lucro da saída).

Como o estado é recalculado da janela a cada barra, não há índices guardados entre chamadas
(que quebravam com a janela deslizante) nem replay de sinais antigos na partida.
"""

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy


@dataclass
class FiboLiveAction:
    action_type: Literal[
        "PLACE_LIMIT",
        "MARKET_ENTRY",
        "CANCEL_ORDER",
        "MODIFY_STOP",
        "CLOSE_POSITION",
        "EXPAND_LEG",
        "NONE",
    ]
    direction: Literal["long", "short"] | None = None
    price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk: float = 0.0
    ticket: int = 0
    reason: str = ""


class FiboLiveEvaluator:
    """Avalia a última barra fechada de um símbolo e devolve as ações a despachar."""

    def __init__(self, config: FiboOTEConfig, spread: float = 0.0) -> None:
        self.config = config
        self.spread = spread
        self.k = config.pivot_k
        self.profit_lock_applied = False
        self.profit_lock_ticket: int | None = None
        self.last_processed_m5_time: pd.Timestamp | None = None
        self.evaluated = False  # True quando a última chamada avaliou uma barra nova
        self._strategy = FiboOTEStrategy(config)

    def process_closed_m5(
        self,
        df_m5: pd.DataFrame,
        is_positioned: bool,
        current_pos_direction: str | None = None,
        current_pos_open_price: float = 0.0,
        current_pos_stop_loss: float = 0.0,
        current_pos_ticket: int = 0,
        current_pos_open_time: pd.Timestamp | None = None,
    ) -> list[FiboLiveAction]:
        """Avalia a última barra fechada de `df_m5` (candles já resampleados, só fechados)."""
        self.evaluated = False
        if len(df_m5) < 2 * self.k + 1:
            return []
        last_time = df_m5.index[-1]
        if self.last_processed_m5_time == last_time:
            return []
        self.last_processed_m5_time = last_time
        self.evaluated = True

        if is_positioned and current_pos_direction:
            return self._manage_position(
                df_m5,
                current_pos_direction,
                current_pos_open_price,
                current_pos_stop_loss,
                current_pos_ticket,
                current_pos_open_time,
            )

        self.profit_lock_applied = False
        self.profit_lock_ticket = None
        setup = self._strategy.pending_setup(df_m5, self.spread)
        if setup is None:
            return []
        return [
            FiboLiveAction(
                action_type="PLACE_LIMIT",
                direction=setup.direction,
                price=setup.entry_price,
                stop_loss=setup.stop_loss,
                take_profit=setup.take_profit,
                risk=setup.risk,
                reason=f"FIBO_OTE_LIMIT leg_bos={setup.bos_time.isoformat()} "
                f"left={setup.candles_left}",
            )
        ]

    def _manage_position(
        self,
        df_m5: pd.DataFrame,
        direction: str,
        open_price: float,
        stop_loss: float,
        ticket: int,
        open_time: pd.Timestamp | None,
    ) -> list[FiboLiveAction]:
        cfg = self.config
        last = df_m5.iloc[-1]

        # F-08: controle de sessão / fim de semana (zeragem compulsória no fechamento da barra)
        if cfg.session_filter:
            if "close_time" in df_m5.columns:
                close_ts = df_m5["close_time"].iloc[-1]
            else:
                bar_mins = (
                    15
                    if cfg.timeframe in ("M15", "15min", "15m")
                    else (60 if cfg.timeframe in ("H1", "1h", "60min") else 5)
                )
                close_ts = df_m5.index[-1] + pd.Timedelta(minutes=bar_mins)
            is_friday = close_ts.weekday() == 4
            t_str = close_ts.strftime("%H:%M")
            force_close = False
            if (
                is_friday
                and cfg.close_on_friday
                and t_str >= cfg.friday_close_time
            ) or (cfg.force_close_time and t_str >= cfg.force_close_time):
                force_close = True
            if force_close:
                return [
                    FiboLiveAction(
                        action_type="CLOSE_POSITION",
                        ticket=ticket,
                        reason="SESSION_CLOSE",
                    )
                ]

        # a barra que contém a entrada só pode estopar (tratado pela corretora)
        if open_time is not None and df_m5.index[-1] <= open_time:
            return []

        if self.profit_lock_ticket is not None and self.profit_lock_ticket != ticket:
            self.profit_lock_applied = False
            self.profit_lock_ticket = None

        d = 1 if direction == "long" else -1
        risk = abs(open_price - stop_loss)
        c_high, c_low, c_close = float(last["high"]), float(last["low"]), float(last["close"])
        adj = self.spread if d == -1 else 0.0  # short recompra no ask
        actions: list[FiboLiveAction] = []

        trigger_r = cfg.profit_lock_trigger_r or (
            cfg.lock_trigger_r if cfg.use_lock_2to1 else None
        )
        lock_r = (
            cfg.profit_lock_guarantee_r
            if cfg.profit_lock_trigger_r
            else (cfg.lock_guarantee_r if cfg.use_lock_2to1 else 0.0)
        )
        if trigger_r is not None and not self.profit_lock_applied and risk > 0:
            favorable = c_high if d == 1 else c_low + adj
            if d * (favorable - (open_price + d * risk * trigger_r)) >= 0:
                self.profit_lock_applied = True
                self.profit_lock_ticket = ticket
                actions.append(
                    FiboLiveAction(
                        action_type="MODIFY_STOP",
                        stop_loss=open_price + d * lock_r * risk,
                        ticket=ticket,
                        reason=f"PROFIT_LOCK_{trigger_r:g}to{lock_r:g}",
                    )
                )

        if cfg.trailing_exit_ma:
            prepared = self._strategy.resample_data(df_m5)
            ma = prepared["trailing_ma"].iloc[-1]
            if pd.notna(ma) and d * (c_close - ma) < 0:
                in_profit = (not cfg.trailing_profit_only) or d * (
                    c_close + adj - open_price
                ) > 0
                if in_profit:
                    return [
                        FiboLiveAction(
                            action_type="CLOSE_POSITION",
                            ticket=ticket,
                            reason=f"TRAILING_{cfg.trailing_exit_ma.upper()}",
                        )
                    ]
        return actions

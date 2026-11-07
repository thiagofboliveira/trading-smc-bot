"""Avaliador incremental da estratégia SMC Fibo OTE para execução ao vivo (L-02).

Processa barras de M5 mantendo o estado causal estrito idêntico ao FiboOTEStrategy:
- Swings fractais com atraso de confirmação k barras (sem lookahead)
- Quebra de estrutura (BOS): leg is None and last_sh_idx > last_sl_idx and close > last_sh
- Formação e expansão de perna OTE
- Ordem limite no nível Fibo de entrada ou entrada no toque (L-06)
- Saída por Trailing EMA8 / médias móveis (L-09)
- Trava de lucro 2:1 / Break-even (F-03)
- Expiração de pernas após max_holding_candles
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from smc_trader.strategies.fibo_ote import FiboOTEConfig


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


@dataclass
class _LiveLeg:
    d: int  # +1 long, -1 short
    origin: float
    extreme: float
    bos_time: pd.Timestamp
    bos_idx: int
    candles: int = 0
    pending_ticket: int | None = None

    def level(self, ratio: float) -> float:
        span = self.d * (self.extreme - self.origin)
        return self.extreme - self.d * ratio * span


class FiboLiveEvaluator:
    """Mantém o estado incremental da estratégia Fibo OTE para um símbolo específico."""

    def __init__(self, config: FiboOTEConfig, spread: float = 0.0) -> None:
        self.config = config
        self.spread = spread
        self.k = config.pivot_k
        self.last_sh_price: float | None = None
        self.last_sh_idx: int | None = None
        self.last_sh_time: pd.Timestamp | None = None
        self.last_sl_price: float | None = None
        self.last_sl_idx: int | None = None
        self.last_sl_time: pd.Timestamp | None = None
        self.active_leg: _LiveLeg | None = None
        self.profit_lock_applied = False
        self.last_processed_m5_time: pd.Timestamp | None = None

    def process_closed_m5(
        self,
        df_m5: pd.DataFrame,
        is_positioned: bool,
        current_pos_direction: str | None = None,
        current_pos_open_price: float = 0.0,
        current_pos_stop_loss: float = 0.0,
        current_pos_ticket: int = 0,
    ) -> list[FiboLiveAction]:
        """Avalia barras M5 fechadas ainda não processadas e retorna ações a despachar."""
        min_bars = 2 * self.k + 1
        if len(df_m5) < min_bars:
            return []

        # Determina o índice a partir do qual processar
        if self.last_processed_m5_time is None:
            start_idx = self.k
        else:
            if self.last_processed_m5_time in df_m5.index:
                loc = df_m5.index.get_loc(self.last_processed_m5_time)
                start_idx = (loc if isinstance(loc, int) else loc.stop) + 1
            else:
                start_idx = len(df_m5) - 1

        if start_idx >= len(df_m5):
            return []

        highs = df_m5["high"].to_numpy()
        lows = df_m5["low"].to_numpy()
        closes = df_m5["close"].to_numpy()
        ts = df_m5.index
        actions: list[FiboLiveAction] = []

        for i in range(start_idx, len(df_m5)):
            c_high = float(highs[i])
            c_low = float(lows[i])
            c_close = float(closes[i])
            now_time = ts[i]

            # 1. Swings fractais confirmados com atraso de k barras
            chk = i - self.k
            if chk >= self.k and chk + self.k + 1 <= len(df_m5):
                window_h = highs[chk - self.k : chk + self.k + 1]
                window_l = lows[chk - self.k : chk + self.k + 1]
                if highs[chk] == np.max(window_h):
                    self.last_sh_price = float(highs[chk])
                    self.last_sh_idx = chk
                    self.last_sh_time = ts[chk]
                if lows[chk] == np.min(window_l):
                    self.last_sl_price = float(lows[chk])
                    self.last_sl_idx = chk
                    self.last_sl_time = ts[chk]

            # 2. Gerenciamento de posição aberta
            if is_positioned and current_pos_direction:
                d = 1 if current_pos_direction == "long" else -1
                risk = abs(current_pos_open_price - current_pos_stop_loss)

                # A. Trava de Lucro / Break-even
                trigger_r = self.config.profit_lock_trigger_r or (
                    self.config.lock_trigger_r if self.config.use_lock_2to1 else None
                )
                lock_r = (
                    self.config.profit_lock_guarantee_r
                    if self.config.profit_lock_trigger_r
                    else (self.config.lock_guarantee_r if self.config.use_lock_2to1 else 0.0)
                )

                if trigger_r is not None and not self.profit_lock_applied and risk > 0:
                    favorable = (
                        (c_high - current_pos_open_price)
                        if d == 1
                        else (current_pos_open_price - c_low)
                    )
                    if favorable >= trigger_r * risk:
                        self.profit_lock_applied = True
                        new_sl = current_pos_open_price + d * lock_r * risk
                        actions.append(
                            FiboLiveAction(
                                action_type="MODIFY_STOP",
                                stop_loss=new_sl,
                                ticket=current_pos_ticket,
                                reason=f"PROFIT_LOCK_{trigger_r:.0f}to{lock_r:.0f}",
                            )
                        )

                # B. Saída por Trailing MME (L-09)
                if self.config.trailing_exit_ma == "ema8":
                    ema8 = (
                        pd.Series(closes[: i + 1])
                        .ewm(span=8, adjust=False)
                        .mean()
                        .iloc[-1]
                    )
                    if d == 1:
                        crossed_ma = c_close < ema8
                        in_profit = (
                            c_close > current_pos_open_price
                            if self.config.trailing_profit_only
                            else True
                        )
                        if crossed_ma and in_profit:
                            actions.append(
                                FiboLiveAction(
                                    action_type="CLOSE_POSITION",
                                    ticket=current_pos_ticket,
                                    reason="TRAILING_EMA8",
                                )
                            )
                            self.active_leg = None
                            self.last_processed_m5_time = now_time
                            return actions
                    else:
                        ask_close = c_close + self.spread
                        crossed_ma = ask_close > ema8
                        in_profit = (
                            ask_close < current_pos_open_price
                            if self.config.trailing_profit_only
                            else True
                        )
                        if crossed_ma and in_profit:
                            actions.append(
                                FiboLiveAction(
                                    action_type="CLOSE_POSITION",
                                    ticket=current_pos_ticket,
                                    reason="TRAILING_EMA8",
                                )
                            )
                            self.active_leg = None
                            self.last_processed_m5_time = now_time
                            return actions

            else:
                self.profit_lock_applied = False

                # 3. Nova perna por BOS (idêntico a FiboOTEStrategy.run: leg is None)
                if (
                    self.active_leg is None
                    and self.last_sh_price is not None
                    and self.last_sl_price is not None
                    and self.last_sh_idx is not None
                    and self.last_sl_idx is not None
                ):
                    cand = None
                    if self.last_sh_idx > self.last_sl_idx and c_close > self.last_sh_price:
                        cand = _LiveLeg(
                            d=1,
                            origin=self.last_sl_price,
                            extreme=c_high,
                            bos_time=now_time,
                            bos_idx=i,
                        )
                    elif self.last_sl_idx > self.last_sh_idx and c_close < self.last_sl_price:
                        cand = _LiveLeg(
                            d=-1,
                            origin=self.last_sh_price,
                            extreme=c_low,
                            bos_time=now_time,
                            bos_idx=i,
                        )

                    if cand is not None and abs(cand.extreme - cand.origin) > self.spread * self.config.min_leg_spread_mult:
                        self.active_leg = cand

                # 4. Avaliação da perna ativa (F-01: só a partir da barra seguinte ao BOS)
                elif self.active_leg is not None and i > self.active_leg.bos_idx:
                    leg = self.active_leg
                    leg.candles += 1
                    if leg.candles > self.config.max_holding_candles:
                        if leg.pending_ticket:
                            actions.append(
                                FiboLiveAction(
                                    action_type="CANCEL_ORDER",
                                    ticket=leg.pending_ticket,
                                    reason="LEG_EXPIRED",
                                )
                            )
                        self.active_leg = None
                    else:
                        entry_level = leg.level(self.config.fibo_entry)
                        stop_level = leg.level(self.config.fibo_stop)
                        d = leg.d
                        direction_str: Literal["long", "short"] = (
                            "long" if d == 1 else "short"
                        )
                        risk = d * (entry_level - stop_level)

                        if risk > self.spread * 1.5:
                            target = (
                                entry_level + d * risk * self.config.target_r
                                if self.config.target_mode == "3R"
                                else leg.extreme
                            )
                            # F-04: Testa toque contra níveis antes de expandir
                            touched = (
                                (c_low <= entry_level)
                                if d == 1
                                else (c_high >= entry_level)
                            )
                            if touched:
                                actions.append(
                                    FiboLiveAction(
                                        action_type="MARKET_ENTRY",
                                        direction=direction_str,
                                        price=entry_level + (self.spread if d == 1 else 0.0),
                                        stop_loss=stop_level,
                                        take_profit=target,
                                        risk=risk,
                                        reason="FIBO_OTE_TOUCH",
                                    )
                                )
                                self.active_leg = None
                                is_positioned = True
                            else:
                                if d == 1 and c_high > leg.extreme:
                                    leg.extreme = c_high
                                elif d == -1 and c_low < leg.extreme:
                                    leg.extreme = c_low

            self.last_processed_m5_time = now_time

        return actions

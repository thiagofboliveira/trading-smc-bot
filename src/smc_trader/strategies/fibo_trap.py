"""Estratégia de Super Tendência com Retração Fibonacci OTE e Trap na MME 8.

Conceito Operacional:
1. Regime de Tendência:
   - Alinhamento de Médias: MME 80 e MME 200 no candle anterior (i-1)
   - Preço > MME 80 > MME 200 (compra) ou Preço < MME 80 < MME 200 (venda)
2. Retração de Fibonacci:
   - O preço corrige até a zona OTE (61.8% a 78.6%) do swing recente
3. Gatilho de Trap na MME 8:
   - Violação da mínima anterior (falso rompimento) com fechamento acima da MME 8
   - Entrada via BuyStop/SellStop no rompimento do candle de sinal
4. Condução:
   - Trailing Stop livre pela MME 8: saída na abertura seguinte ao primeiro fechamento do lado errado da MME 8
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


@dataclass
class FiboTrapConfig:
    fibo_min: float = 0.618
    fibo_max: float = 0.786
    swing_lookback: int = 20
    conduction_ma: Literal["mme8", "mme20"] = "mme8"
    slippage_pts: float = 1.0


@dataclass
class FiboTrapTrade:
    symbol: str
    direction: Literal["long", "short"]
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float | None
    exit_price: float
    exit_reason: str
    r_multiple: float
    win: bool
    initial_risk: float


class FiboTrapStrategy:
    """Implementação causal da estratégia Fibo OTE + Trap na MME 8."""

    def __init__(self, config: FiboTrapConfig | None = None) -> None:
        self.config = config or FiboTrapConfig()

    @staticmethod
    def calculate_indicators(df: pd.DataFrame) -> dict[str, np.ndarray]:
        close = df["close"]
        mme8 = close.shift(1).ewm(span=8, adjust=False).mean().to_numpy(dtype=float)
        mme20 = close.shift(1).ewm(span=20, adjust=False).mean().to_numpy(dtype=float)
        mme80 = close.shift(1).ewm(span=80, adjust=False).mean().to_numpy(dtype=float)
        mme200 = close.shift(1).ewm(span=200, adjust=False).mean().to_numpy(dtype=float)

        return {
            "mme8": mme8,
            "mme20": mme20,
            "mme80": mme80,
            "mme200": mme200,
        }

    def run_simulation(
        self,
        df: pd.DataFrame,
        symbol: str,
        spread: float,
    ) -> list[FiboTrapTrade]:
        n = len(df)
        if n < 220:
            return []

        cfg = self.config
        ind = self.calculate_indicators(df)

        opens = df["open"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        closes = df["close"].to_numpy(dtype=float)
        ts = df.index

        mme8 = ind["mme8"]
        mme80 = ind["mme80"]
        mme200 = ind["mme200"]
        slip = cfg.slippage_pts

        trades: list[FiboTrapTrade] = []
        open_pos = None

        for i in range(210, n - 1):
            cur_t = ts[i]

            # 1. Gestão de posição aberta
            if open_pos is not None:
                pos = open_pos
                d = 1 if pos["direction"] == "long" else -1
                hit_sl = lows[i] <= pos["stop_price"] if d == 1 else highs[i] + spread >= pos["stop_price"]
                exit_by_ma = (closes[i - 1] < mme8[i - 1]) if d == 1 else (closes[i - 1] > mme8[i - 1])

                if hit_sl:
                    exit_p = min(pos["stop_price"], opens[i]) - slip if d == 1 else max(pos["stop_price"], opens[i] + spread) + slip
                    r = (exit_p - pos["entry_price"]) / pos["risk"] if d == 1 else (pos["entry_price"] - exit_p) / pos["risk"]
                    trades.append(FiboTrapTrade(
                        symbol=symbol,
                        direction=pos["direction"],
                        entry_time=pos["entry_time"],
                        exit_time=cur_t,
                        entry_price=pos["entry_price"],
                        stop_price=pos["stop_price"],
                        target_price=pos["target_price"],
                        exit_price=exit_p,
                        exit_reason="STOP_LOSS",
                        r_multiple=float(r),
                        win=r > 0,
                        initial_risk=pos["risk"],
                    ))
                    open_pos = None
                    continue

                elif exit_by_ma and i > pos["entry_idx"]:
                    exit_p = opens[i] - slip if d == 1 else opens[i] + spread + slip
                    r = (exit_p - pos["entry_price"]) / pos["risk"] if d == 1 else (pos["entry_price"] - exit_p) / pos["risk"]
                    trades.append(FiboTrapTrade(
                        symbol=symbol,
                        direction=pos["direction"],
                        entry_time=pos["entry_time"],
                        exit_time=cur_t,
                        entry_price=pos["entry_price"],
                        stop_price=pos["stop_price"],
                        target_price=pos["target_price"],
                        exit_price=exit_p,
                        exit_reason="TRAILING_MME8",
                        r_multiple=float(r),
                        win=r > 0,
                        initial_risk=pos["risk"],
                    ))
                    open_pos = None
                    continue

            # 2. Setup
            if open_pos is None:
                trend_bull = closes[i - 1] > mme80[i - 1] > mme200[i - 1]
                trend_bear = closes[i - 1] < mme80[i - 1] < mme200[i - 1]

                lb = cfg.swing_lookback
                recent_high = np.max(highs[i - lb : i - 1])
                recent_low = np.min(lows[i - lb : i - 1])
                rng = recent_high - recent_low
                if rng < spread * 6 or rng > 300:
                    continue

                if trend_bull:
                    fibo_618 = recent_high - (cfg.fibo_min * rng)
                    fibo_786 = recent_high - (cfg.fibo_max * rng)
                    in_fibo = lows[i - 1] <= fibo_618 and closes[i - 1] >= fibo_786
                    trap_mme8 = lows[i - 1] < lows[i - 2] and closes[i - 1] > mme8[i - 1] and closes[i - 1] > opens[i - 1]

                    if in_fibo and trap_mme8:
                        trig_p = highs[i - 1]
                        if highs[i] >= trig_p:
                            entry_p = max(trig_p, opens[i]) + spread + slip
                            stop_p = lows[i - 1] - slip
                            risk = entry_p - stop_p
                            if risk > spread * 3 and risk < 150:
                                target_p = recent_high + (0.618 * rng)
                                open_pos = {
                                    "direction": "long", "entry_time": cur_t, "entry_idx": i,
                                    "entry_price": entry_p, "stop_price": stop_p, "target_price": target_p,
                                    "risk": risk
                                }
                                if lows[i] <= stop_p:
                                    exit_p = min(stop_p, opens[i]) - slip
                                    r = (exit_p - entry_p) / risk
                                    trades.append(FiboTrapTrade(
                                        symbol=symbol, direction="long", entry_time=cur_t, exit_time=cur_t,
                                        entry_price=entry_p, stop_price=stop_p, target_price=target_p, exit_price=exit_p,
                                        exit_reason="STOP_ENTRY_BAR", r_multiple=float(r), win=False, initial_risk=risk
                                    ))
                                    open_pos = None

                elif trend_bear:
                    fibo_618 = recent_low + (cfg.fibo_min * rng)
                    fibo_786 = recent_low + (cfg.fibo_max * rng)
                    in_fibo = highs[i - 1] >= fibo_618 and closes[i - 1] <= fibo_786
                    trap_mme8 = highs[i - 1] > highs[i - 2] and closes[i - 1] < mme8[i - 1] and closes[i - 1] < opens[i - 1]

                    if in_fibo and trap_mme8:
                        trig_p = lows[i - 1]
                        if lows[i] <= trig_p:
                            entry_p = min(trig_p, opens[i]) - slip
                            stop_p = highs[i - 1] + spread + slip
                            risk = stop_p - entry_p
                            if risk > spread * 3 and risk < 150:
                                target_p = recent_low - (0.618 * rng)
                                open_pos = {
                                    "direction": "short", "entry_time": cur_t, "entry_idx": i,
                                    "entry_price": entry_p, "stop_price": stop_p, "target_price": target_p,
                                    "risk": risk
                                }
                                if highs[i] + spread >= stop_p:
                                    exit_p = max(stop_p, opens[i] + spread) + slip
                                    r = (entry_p - exit_p) / risk
                                    trades.append(FiboTrapTrade(
                                        symbol=symbol, direction="short", entry_time=cur_t, exit_time=cur_t,
                                        entry_price=entry_p, stop_price=stop_p, target_price=target_p, exit_price=exit_p,
                                        exit_reason="STOP_ENTRY_BAR", r_multiple=float(r), win=False, initial_risk=risk
                                    ))
                                    open_pos = None

        return trades

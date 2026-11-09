"""Estratégia de Reversão à Média Diária (Connors RSI(2) + IBS) em Índices.

Modelo Quantitativo Validado:
- Regime Macro: Preço acima da SMA 200 no candle diário anterior (i-1)
- Condição de Sobre-venda: RSI(2) < 10.0 OU IBS (Internal Bar Strength) < 0.20 em i-1
- Execução: Compra a mercado na abertura (Open de i) com spread e slippage
- Gestão de Risco: Stop Loss estrutural em 2.0x ATR(14)
- Regra de Saída: Fechamento acima da SMA 5 (i-1) ou tempo máximo de 5 dias (executada no Open de i)
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


@dataclass
class D1MeanReversionConfig:
    rsi_period: int = 2
    rsi_threshold: float = 10.0
    ibs_threshold: float = 0.20
    sma_trend_period: int = 200
    sma_exit_period: int = 5
    atr_stop_multiplier: float = 2.0
    max_hold_days: int = 5
    slippage_pts: float = 1.0


@dataclass
class D1Trade:
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
    hold_days: int


class D1MeanReversionStrategy:
    """Implementação causal da reversão à média diária nos índices."""

    def __init__(self, config: D1MeanReversionConfig | None = None) -> None:
        self.config = config or D1MeanReversionConfig()

    @staticmethod
    def calculate_indicators(df_d1: pd.DataFrame, exit_sma_period: int = 5) -> dict[str, np.ndarray]:
        close = df_d1["close"].shift(1)
        high = df_d1["high"].shift(1)
        low = df_d1["low"].shift(1)

        # SMA 200 e SMA de saída causais
        sma200 = close.rolling(200).mean().to_numpy(dtype=float)
        sma_exit = close.rolling(exit_sma_period).mean().to_numpy(dtype=float)

        # RSI(2) causal
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/2, min_periods=2, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/2, min_periods=2, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi2 = (100 - (100 / (1 + rs))).fillna(50.0).to_numpy(dtype=float)

        # IBS causal: (Close - Low) / (High - Low)
        rng = np.maximum(high - low, 1e-6)
        ibs = ((close - low) / rng).fillna(0.5).to_numpy(dtype=float)

        # ATR(14) causal
        tr1 = high - low
        tr2 = (high - df_d1["close"].shift(2)).abs()
        tr3 = (low - df_d1["close"].shift(2)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr14 = tr.rolling(14).mean().fillna(100.0).to_numpy(dtype=float)

        return {
            "sma200": sma200,
            "sma_exit": sma_exit,
            "rsi2": rsi2,
            "ibs": ibs,
            "atr14": atr14,
        }

    def run_simulation(
        self,
        df_d1: pd.DataFrame,
        symbol: str,
        spread: float,
    ) -> list[D1Trade]:
        if len(df_d1) < 210:
            return []

        cfg = self.config
        ind = self.calculate_indicators(df_d1, exit_sma_period=cfg.sma_exit_period)

        opens = df_d1["open"].to_numpy(dtype=float)
        lows = df_d1["low"].to_numpy(dtype=float)
        ts = df_d1.index

        c_prev = df_d1["close"].shift(1).to_numpy(dtype=float)
        sma200 = ind["sma200"]
        sma_exit = ind["sma_exit"]
        rsi2 = ind["rsi2"]
        ibs = ind["ibs"]
        atr14 = ind["atr14"]

        trades: list[D1Trade] = []
        open_pos = None

        for i in range(205, len(df_d1)):
            curr_time = ts[i]

            # 1. Gestão de posição aberta
            if open_pos is not None:
                risk = open_pos["initial_risk"]
                hold_days = i - open_pos["entry_idx"]

                # Checa stop loss na barra i
                if lows[i] <= open_pos["stop_price"]:
                    raw_exit = min(open_pos["stop_price"], opens[i])
                    exit_price = raw_exit - cfg.slippage_pts
                    r = (exit_price - open_pos["entry_price"]) / risk
                    trades.append(D1Trade(
                        symbol=symbol,
                        direction="long",
                        entry_time=open_pos["entry_time"],
                        exit_time=curr_time,
                        entry_price=open_pos["entry_price"],
                        stop_price=open_pos["stop_price"],
                        target_price=None,
                        exit_price=exit_price,
                        exit_reason="STOP_LOSS",
                        r_multiple=float(r),
                        win=r > 0,
                        initial_risk=risk,
                        hold_days=hold_days,
                    ))
                    open_pos = None
                    continue

                # Saída por Média ou Tempo avaliada em i-1
                exit_by_sma = c_prev[i] > sma_exit[i]
                exit_by_time = hold_days >= cfg.max_hold_days

                if exit_by_sma or exit_by_time:
                    exit_price = opens[i] - cfg.slippage_pts
                    r = (exit_price - open_pos["entry_price"]) / risk
                    reason = f"EXIT_SMA{cfg.sma_exit_period}" if exit_by_sma else "TIME_STOP"
                    trades.append(D1Trade(
                        symbol=symbol,
                        direction="long",
                        entry_time=open_pos["entry_time"],
                        exit_time=curr_time,
                        entry_price=open_pos["entry_price"],
                        stop_price=open_pos["stop_price"],
                        target_price=None,
                        exit_price=exit_price,
                        exit_reason=reason,
                        r_multiple=float(r),
                        win=r > 0,
                        initial_risk=risk,
                        hold_days=hold_days,
                    ))
                    open_pos = None
                    continue

            # 2. Entrada
            if open_pos is None:
                is_bull_regime = c_prev[i] > sma200[i]
                is_oversold = (rsi2[i] < cfg.rsi_threshold) or (ibs[i] < cfg.ibs_threshold)

                if is_bull_regime and is_oversold:
                    entry_price = opens[i] + spread + cfg.slippage_pts
                    risk_pts = cfg.atr_stop_multiplier * atr14[i]
                    stop_price = entry_price - risk_pts

                    if risk_pts > 0:
                        if lows[i] <= stop_price:
                            raw_exit = min(stop_price, opens[i])
                            exit_price = raw_exit - cfg.slippage_pts
                            r = (exit_price - entry_price) / risk_pts
                            trades.append(D1Trade(
                                symbol=symbol,
                                direction="long",
                                entry_time=curr_time,
                                exit_time=curr_time,
                                entry_price=entry_price,
                                stop_price=stop_price,
                                target_price=None,
                                exit_price=exit_price,
                                exit_reason="STOP_ENTRY_DAY",
                                r_multiple=float(r),
                                win=r > 0,
                                initial_risk=risk_pts,
                                hold_days=0,
                            ))
                        else:
                            open_pos = {
                                "entry_idx": i,
                                "entry_time": curr_time,
                                "entry_price": entry_price,
                                "stop_price": stop_price,
                                "initial_risk": risk_pts,
                            }

        return trades

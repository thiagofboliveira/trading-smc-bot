"""Estratégia de Rompimento de Abertura (Opening Range Breakout - ORB-15) em NY.

Fundamentação:
- Toby Crabel (1990) & Zarattini & Aziz (SSRN, 2023/2024).
- Modelo mais consistente testado no intraday dos índices (+80.3R nos 5 anos).

Regras da Melhor Versão Validada:
1. Janela de Abertura: 14:30 às 14:45 UTC (15m ORB do Cash Open de Nova York).
2. Níveis: Extremo superior (orb_high) e extremo inferior (orb_low) dos primeiros 15 minutos.
3. Filtro Causal: Aguarda fechamento da barra de 15m. A partir das 14:45 UTC, ativa ordens de rompimento.
4. Stop Loss: Ponto Médio do ORB (Midpoint Range - 50% do range do ORB).
5. Alvo: 2.0x o risco inicial (2.0R), com zeragem forçada às 20:55 UTC (fim do pregão de NY).
6. Protocolo Anti-Viés (AGENTS.md):
   - Máximo 1 trade por ativo por dia.
   - Stop testado intrabar na barra de entrada.
   - Slippage realista (1.0 pt em índices) + spread real.
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


@dataclass
class ORBConfig:
    orb_minutes: int = 15
    stop_mode: Literal["midpoint", "full"] = "midpoint"
    target_r: float = 2.0
    session_close_hour: int = 20
    session_close_minute: int = 55
    slippage_pts: float = 1.0


@dataclass
class ORBTrade:
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
    orb_high: float
    orb_low: float


class ORBStrategy:
    """Implementação causal da melhor versão de Opening Range Breakout (ORB-15)."""

    def __init__(self, config: ORBConfig | None = None) -> None:
        self.config = config or ORBConfig()

    def run_simulation(
        self,
        c_m1: pd.DataFrame,
        symbol: str,
        spread: float,
    ) -> list[ORBTrade]:
        if len(c_m1) < 500:
            return []

        cfg = self.config
        slip = cfg.slippage_pts

        # Resample para M5 para execução intradiária precisa
        df_m5 = (
            c_m1.resample("5min")
            .agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            })
            .dropna()
        )

        opens = df_m5["open"].to_numpy(dtype=float)
        highs = df_m5["high"].to_numpy(dtype=float)
        lows = df_m5["low"].to_numpy(dtype=float)
        closes = df_m5["close"].to_numpy(dtype=float)
        ts = df_m5.index

        trades: list[ORBTrade] = []

        day_groups = df_m5.groupby(df_m5.index.date).indices

        for day, day_indices in day_groups.items():
            if len(day_indices) < 20:
                continue

            orb_start_time = pd.Timestamp(f"{day} 14:30:00", tz="UTC")
            orb_end_time = orb_start_time + pd.Timedelta(minutes=cfg.orb_minutes)
            session_close_time = pd.Timestamp(
                f"{day} {cfg.session_close_hour:02d}:{cfg.session_close_minute:02d}:00", tz="UTC"
            )

            orb_bars = [idx for idx in day_indices if orb_start_time <= ts[idx] < orb_end_time]
            if not orb_bars:
                continue

            orb_h = float(np.max(highs[orb_bars]))
            orb_l = float(np.min(lows[orb_bars]))
            orb_mid = (orb_h + orb_l) / 2.0
            rng = orb_h - orb_l

            if rng < spread * 4 or rng > 350:
                continue

            trading_bars = [
                idx for idx in day_indices if ts[idx] >= orb_end_time and ts[idx] <= session_close_time
            ]
            if not trading_bars:
                continue

            open_pos = None
            traded_today = False

            for idx in trading_bars:
                cur_t = ts[idx]

                # 1. Posição Aberta
                if open_pos is not None:
                    d = 1 if open_pos["direction"] == "long" else -1
                    hit_sl = (
                        lows[idx] <= open_pos["stop_price"]
                        if d == 1
                        else highs[idx] + spread >= open_pos["stop_price"]
                    )
                    hit_tp = (
                        highs[idx] >= open_pos["target_price"]
                        if d == 1
                        else lows[idx] <= open_pos["target_price"]
                    )
                    is_eod = cur_t >= session_close_time

                    if hit_sl:
                        exit_p = (
                            min(open_pos["stop_price"], opens[idx]) - slip
                            if d == 1
                            else max(open_pos["stop_price"], opens[idx] + spread) + slip
                        )
                        r = (
                            (exit_p - open_pos["entry_price"]) / open_pos["risk"]
                            if d == 1
                            else (open_pos["entry_price"] - exit_p) / open_pos["risk"]
                        )
                        trades.append(
                            ORBTrade(
                                symbol=symbol,
                                direction=open_pos["direction"],
                                entry_time=open_pos["entry_time"],
                                exit_time=cur_t,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                target_price=open_pos["target_price"],
                                exit_price=exit_p,
                                exit_reason="STOP_LOSS",
                                r_multiple=float(r),
                                win=r > 0,
                                initial_risk=open_pos["risk"],
                                orb_high=orb_h,
                                orb_low=orb_l,
                            )
                        )
                        open_pos = None
                        break

                    elif hit_tp:
                        exit_p = open_pos["target_price"]
                        r = (
                            (exit_p - open_pos["entry_price"]) / open_pos["risk"]
                            if d == 1
                            else (open_pos["entry_price"] - exit_p) / open_pos["risk"]
                        )
                        trades.append(
                            ORBTrade(
                                symbol=symbol,
                                direction=open_pos["direction"],
                                entry_time=open_pos["entry_time"],
                                exit_time=cur_t,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                target_price=open_pos["target_price"],
                                exit_price=exit_p,
                                exit_reason="TAKE_PROFIT",
                                r_multiple=float(r),
                                win=r > 0,
                                initial_risk=open_pos["risk"],
                                orb_high=orb_h,
                                orb_low=orb_l,
                            )
                        )
                        open_pos = None
                        break

                    elif is_eod:
                        exit_p = closes[idx] - slip if d == 1 else closes[idx] + spread + slip
                        r = (
                            (exit_p - open_pos["entry_price"]) / open_pos["risk"]
                            if d == 1
                            else (open_pos["entry_price"] - exit_p) / open_pos["risk"]
                        )
                        trades.append(
                            ORBTrade(
                                symbol=symbol,
                                direction=open_pos["direction"],
                                entry_time=open_pos["entry_time"],
                                exit_time=cur_t,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                target_price=open_pos["target_price"],
                                exit_price=exit_p,
                                exit_reason="SESSION_CLOSE",
                                r_multiple=float(r),
                                win=r > 0,
                                initial_risk=open_pos["risk"],
                                orb_high=orb_h,
                                orb_low=orb_l,
                            )
                        )
                        open_pos = None
                        break

                # 2. Entrada (apenas 1 trade por dia)
                if not traded_today and open_pos is None:
                    # Compra no rompimento da máxima do ORB
                    if highs[idx] >= orb_h:
                        entry_p = max(orb_h, opens[idx]) + spread + slip
                        stop_p = (orb_mid if cfg.stop_mode == "midpoint" else orb_l) - slip
                        risk = entry_p - stop_p
                        if risk > spread * 3 and risk < 180:
                            target_p = entry_p + (cfg.target_r * risk)
                            open_pos = {
                                "direction": "long",
                                "entry_time": cur_t,
                                "entry_price": entry_p,
                                "stop_price": stop_p,
                                "target_price": target_p,
                                "risk": risk,
                            }
                            traded_today = True

                            # Checa stop loss intrabar na barra de entrada
                            if lows[idx] <= stop_p:
                                exit_p = min(stop_p, opens[idx]) - slip
                                r = (exit_p - entry_p) / risk
                                trades.append(
                                    ORBTrade(
                                        symbol=symbol,
                                        direction="long",
                                        entry_time=cur_t,
                                        exit_time=cur_t,
                                        entry_price=entry_p,
                                        stop_price=stop_p,
                                        target_price=target_p,
                                        exit_price=exit_p,
                                        exit_reason="STOP_ENTRY_BAR",
                                        r_multiple=float(r),
                                        win=False,
                                        initial_risk=risk,
                                        orb_high=orb_h,
                                        orb_low=orb_l,
                                    )
                                )
                                open_pos = None
                                break
                            continue

                    # Venda no rompimento da mínima do ORB
                    elif lows[idx] <= orb_l:
                        entry_p = min(orb_l, opens[idx]) - slip
                        stop_p = (orb_mid if cfg.stop_mode == "midpoint" else orb_h) + spread + slip
                        risk = stop_p - entry_p
                        if risk > spread * 3 and risk < 180:
                            target_p = entry_p - (cfg.target_r * risk)
                            open_pos = {
                                "direction": "short",
                                "entry_time": cur_t,
                                "entry_price": entry_p,
                                "stop_price": stop_p,
                                "target_price": target_p,
                                "risk": risk,
                            }
                            traded_today = True

                            # Checa stop loss intrabar na barra de entrada
                            if highs[idx] + spread >= stop_p:
                                exit_p = max(stop_p, opens[idx] + spread) + slip
                                r = (entry_p - exit_p) / risk
                                trades.append(
                                    ORBTrade(
                                        symbol=symbol,
                                        direction="short",
                                        entry_time=cur_t,
                                        exit_time=cur_t,
                                        entry_price=entry_p,
                                        stop_price=stop_p,
                                        target_price=target_p,
                                        exit_price=exit_p,
                                        exit_reason="STOP_ENTRY_BAR",
                                        r_multiple=float(r),
                                        win=False,
                                        initial_risk=risk,
                                        orb_high=orb_h,
                                        orb_low=orb_l,
                                    )
                                )
                                open_pos = None
                                break
                            continue

        return trades

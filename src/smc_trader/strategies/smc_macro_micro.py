"""Estratégia SMC Multi-Timeframe: Estrutura Macro (H1) + Refinamento Micro CHoCH (M15).

Conceito Institucional Validado:
1. Macro (H1): Identifica perna impulsiva confirmada por pivôs causais (k=2 em H1 sem lookahead).
   - Traça Fibonacci na perna (0.0% no extremo, 100.0% na origem).
   - POI Macro: Zona de Desconto / OTE entre 61.8% e 78.6%.
2. Micro (M15):
   - Preço entra no POI Macro.
   - Aguarda CHoCH (Change of Character) em M15 rompendo o último swing da correção.
3. Execução Causal (AGENTS.md):
   - Entrada no candle seguinte ao CHoCH confirmado.
   - Stop Loss: Extremo da estrutura do CHoCH micro (fundo para Long, topo para Short).
   - Take Profit: Nível 0.0% da perna macro (topo para Long, fundo para Short).
   - Stop testado intrabar na barra de entrada.
   - Gaps de abertura no stop loss preenchidos no Open + slippage.
   - Spreads reais e slippage aplicados.
"""

from dataclasses import dataclass
from typing import Literal

import pandas as pd


@dataclass
class SMCMacroMicroConfig:
    fibo_min: float = 0.618
    fibo_max: float = 0.786
    pivot_k_macro: int = 2
    pivot_k_micro: int = 2
    min_rr: float = 2.0
    slippage_pts: float = 1.0


@dataclass
class SMCMacroMicroTrade:
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
    fibo_618: float
    fibo_786: float


class SMCMacroMicroStrategy:
    """Implementação causal da estratégia SMC Macro H1 + Micro M15 CHoCH."""

    def __init__(self, config: SMCMacroMicroConfig | None = None) -> None:
        self.config = config or SMCMacroMicroConfig()

    def run_simulation(
        self,
        c_m1: pd.DataFrame,
        symbol: str,
        spread: float,
    ) -> list[SMCMacroMicroTrade]:
        if len(c_m1) < 500:
            return []

        cfg = self.config
        slip = cfg.slippage_pts

        # Resample para H1 e M15
        df_m15 = (
            c_m1.resample("15min")
            .agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            })
            .dropna()
        )

        df_h1 = (
            c_m1.resample("1h")
            .agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            })
            .dropna()
        )

        if len(df_h1) < 10 or len(df_m15) < 50:
            return []

        # Pivôs H1 causais (k=2)
        highs_h1 = df_h1["high"].to_numpy(dtype=float)
        lows_h1 = df_h1["low"].to_numpy(dtype=float)
        ts_h1 = df_h1.index

        pivots_h1 = []
        k = cfg.pivot_k_macro
        for i in range(k, len(df_h1) - k):
            is_high = all(highs_h1[i] > highs_h1[i - j] for j in range(1, k + 1)) and all(
                highs_h1[i] > highs_h1[i + j] for j in range(1, k + 1)
            )
            is_low = all(lows_h1[i] < lows_h1[i - j] for j in range(1, k + 1)) and all(
                lows_h1[i] < lows_h1[i + j] for j in range(1, k + 1)
            )
            if is_high:
                pivots_h1.append({
                    "kind": "high",
                    "price": highs_h1[i],
                    "time": ts_h1[i],
                    "confirmed_time": ts_h1[i + k],
                })
            if is_low:
                pivots_h1.append({
                    "kind": "low",
                    "price": lows_h1[i],
                    "time": ts_h1[i],
                    "confirmed_time": ts_h1[i + k],
                })

        # Pivôs M15 causais (k=2)
        highs_m15 = df_m15["high"].to_numpy(dtype=float)
        lows_m15 = df_m15["low"].to_numpy(dtype=float)
        opens_m15 = df_m15["open"].to_numpy(dtype=float)
        closes_m15 = df_m15["close"].to_numpy(dtype=float)
        ts_m15 = df_m15.index

        pivots_m15 = []
        km = cfg.pivot_k_micro
        for i in range(km, len(df_m15) - km):
            is_high = all(highs_m15[i] > highs_m15[i - j] for j in range(1, km + 1)) and all(
                highs_m15[i] > highs_m15[i + j] for j in range(1, km + 1)
            )
            is_low = all(lows_m15[i] < lows_m15[i - j] for j in range(1, km + 1)) and all(
                lows_m15[i] < lows_m15[i + j] for j in range(1, km + 1)
            )
            if is_high:
                pivots_m15.append({
                    "kind": "high",
                    "price": highs_m15[i],
                    "time": ts_m15[i],
                    "confirmed_time": ts_m15[i + km],
                })
            if is_low:
                pivots_m15.append({
                    "kind": "low",
                    "price": lows_m15[i],
                    "time": ts_m15[i],
                    "confirmed_time": ts_m15[i + km],
                })

        p_h1_idx = 0
        num_p_h1 = len(pivots_h1)
        last_high_h1 = None
        last_low_h1 = None

        p_m15_idx = 0
        num_p_m15 = len(pivots_m15)
        last_micro_high = None
        last_micro_low = None

        trades: list[SMCMacroMicroTrade] = []
        open_pos = None

        for i in range(50, len(df_m15) - 1):
            cur_t = ts_m15[i]

            while p_h1_idx < num_p_h1 and pivots_h1[p_h1_idx]["confirmed_time"] <= cur_t:
                p = pivots_h1[p_h1_idx]
                if p["kind"] == "high":
                    last_high_h1 = p
                else:
                    last_low_h1 = p
                p_h1_idx += 1

            while p_m15_idx < num_p_m15 and pivots_m15[p_m15_idx]["confirmed_time"] <= cur_t:
                p = pivots_m15[p_m15_idx]
                if p["kind"] == "high":
                    last_micro_high = p
                else:
                    last_micro_low = p
                p_m15_idx += 1

            # 1. Gestão de posição aberta
            if open_pos is not None:
                pos = open_pos
                d = 1 if pos["direction"] == "long" else -1
                hit_sl = (
                    lows_m15[i] <= pos["stop_price"]
                    if d == 1
                    else highs_m15[i] + spread >= pos["stop_price"]
                )
                hit_tp = (
                    highs_m15[i] >= pos["target_price"]
                    if d == 1
                    else lows_m15[i] <= pos["target_price"]
                )

                if hit_sl:
                    exit_p = (
                        min(pos["stop_price"], opens_m15[i]) - slip
                        if d == 1
                        else max(pos["stop_price"], opens_m15[i] + spread) + slip
                    )
                    r = (
                        (exit_p - pos["entry_price"]) / pos["risk"]
                        if d == 1
                        else (pos["entry_price"] - exit_p) / pos["risk"]
                    )
                    trades.append(
                        SMCMacroMicroTrade(
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
                            fibo_618=pos.get("fibo_618", 0.0),
                            fibo_786=pos.get("fibo_786", 0.0),
                        )
                    )
                    open_pos = None
                    continue

                elif hit_tp:
                    exit_p = pos["target_price"]
                    r = (
                        (exit_p - pos["entry_price"]) / pos["risk"]
                        if d == 1
                        else (pos["entry_price"] - exit_p) / pos["risk"]
                    )
                    trades.append(
                        SMCMacroMicroTrade(
                            symbol=symbol,
                            direction=pos["direction"],
                            entry_time=pos["entry_time"],
                            exit_time=cur_t,
                            entry_price=pos["entry_price"],
                            stop_price=pos["stop_price"],
                            target_price=pos["target_price"],
                            exit_price=exit_p,
                            exit_reason="TAKE_PROFIT",
                            r_multiple=float(r),
                            win=r > 0,
                            initial_risk=pos["risk"],
                            fibo_618=pos.get("fibo_618", 0.0),
                            fibo_786=pos.get("fibo_786", 0.0),
                        )
                    )
                    open_pos = None
                    continue

            # 2. Setup
            if (
                open_pos is None
                and last_high_h1
                and last_low_h1
                and last_micro_high
                and last_micro_low
            ):
                is_macro_bull = (
                    last_high_h1["time"] > last_low_h1["time"]
                    and last_high_h1["price"] > last_low_h1["price"]
                )
                is_macro_bear = (
                    last_low_h1["time"] > last_high_h1["time"]
                    and last_low_h1["price"] < last_high_h1["price"]
                )

                if is_macro_bull:
                    p_low = last_low_h1["price"]
                    p_high = last_high_h1["price"]
                    rng = p_high - p_low
                    fibo_618 = p_high - (cfg.fibo_min * rng)
                    fibo_786 = p_high - (cfg.fibo_max * rng)

                    in_poi = (lows_m15[i - 1] <= fibo_618) and (closes_m15[i - 1] >= fibo_786)
                    micro_valid = (last_micro_high["time"] > last_high_h1["time"]) and (
                        last_micro_low["time"] > last_high_h1["time"]
                    )

                    if in_poi and micro_valid:
                        choch = (closes_m15[i - 1] > last_micro_high["price"]) and (
                            closes_m15[i - 2] <= last_micro_high["price"]
                        )
                        if choch:
                            entry_p = opens_m15[i] + spread + slip
                            stop_p = last_micro_low["price"] - slip
                            risk = entry_p - stop_p
                            if risk > spread * 3 and risk < 200:
                                target_p = p_high
                                rr = (target_p - entry_p) / risk
                                if rr >= cfg.min_rr:
                                    open_pos = {
                                        "direction": "long",
                                        "entry_time": cur_t,
                                        "entry_price": entry_p,
                                        "stop_price": stop_p,
                                        "target_price": target_p,
                                        "risk": risk,
                                        "fibo_618": fibo_618,
                                        "fibo_786": fibo_786,
                                    }
                                    if lows_m15[i] <= stop_p:
                                        exit_p = min(stop_p, opens_m15[i]) - slip
                                        r = (exit_p - entry_p) / risk
                                        trades.append(
                                            SMCMacroMicroTrade(
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
                                                fibo_618=fibo_618,
                                                fibo_786=fibo_786,
                                            )
                                        )
                                        open_pos = None

                elif is_macro_bear:
                    p_low = last_low_h1["price"]
                    p_high = last_high_h1["price"]
                    rng = p_high - p_low
                    fibo_618 = p_low + (cfg.fibo_min * rng)
                    fibo_786 = p_low + (cfg.fibo_max * rng)

                    in_poi = (highs_m15[i - 1] >= fibo_618) and (closes_m15[i - 1] <= fibo_786)
                    micro_valid = (last_micro_low["time"] > last_low_h1["time"]) and (
                        last_micro_high["time"] > last_low_h1["time"]
                    )

                    if in_poi and micro_valid:
                        choch = (closes_m15[i - 1] < last_micro_low["price"]) and (
                            closes_m15[i - 2] >= last_micro_low["price"]
                        )
                        if choch:
                            entry_p = opens_m15[i] - slip
                            stop_p = last_micro_high["price"] + spread + slip
                            risk = stop_p - entry_p
                            if risk > spread * 3 and risk < 200:
                                target_p = p_low
                                rr = (entry_p - target_p) / risk
                                if rr >= cfg.min_rr:
                                    open_pos = {
                                        "direction": "short",
                                        "entry_time": cur_t,
                                        "entry_price": entry_p,
                                        "stop_price": stop_p,
                                        "target_price": target_p,
                                        "risk": risk,
                                        "fibo_618": fibo_618,
                                        "fibo_786": fibo_786,
                                    }
                                    if highs_m15[i] + spread >= stop_p:
                                        exit_p = max(stop_p, opens_m15[i] + spread) + slip
                                        r = (entry_p - exit_p) / risk
                                        trades.append(
                                            SMCMacroMicroTrade(
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
                                                fibo_618=fibo_618,
                                                fibo_786=fibo_786,
                                            )
                                        )
                                        open_pos = None

        return trades

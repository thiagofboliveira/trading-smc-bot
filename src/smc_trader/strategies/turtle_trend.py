"""Estratégia Sistemática de Trend Following (Turtle Trend) — Motor Experimental de Pesquisa.

Baseada nos princípios clássicos de Richard Dennis e William Eckhardt (Turtle Trading System),
implementada com regras causais estritas e verificação anti-viés:
1. Entrada: Rompimento do canal Donchian de N barras (calculado em i-1).
2. Stop Loss: Múltiplo do ATR (calculado em i-1).
3. Saída: Rompimento do canal Donchian oposto de M barras (calculado em i-1).
4. Causalidade e Anti-Viés:
   - Indicadores estritamente shiftados em 1 barra.
   - Ordem BuyStop/SellStop executada no nível ou com gap no Open da barra i.
   - Checagem imediata do stop loss na barra de entrada i.
   - Gaps de abertura no stop loss executados no Open + slippage.
   - Modo single-position estrito (máximo 1 trade ativo por ativo).

AVISO DE AUDITORIA:
- Esta estratégia foi implementada para fins de pesquisa e testes estatísticos.
- Em testes corrigidos sem bug de sobrescrita de gatilhos:
  * No D1, entrega retorno próximo de zero (+13.8R em 5 anos, t=0.51, PF 1.08).
  * No intradiário (H4, H2, H1, M30), acumula prejuízos severos devido a falsos rompimentos.
  * NÃO utilizar como produto em produção sem base de dados de décadas e dezenas de mercados.
"""

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd


@dataclass
class TurtleTrendConfig:
    timeframe: str = "1D"
    entry_channel_period: int = 20
    exit_channel_period: int = 10
    atr_period: int = 20
    stop_atr_mult: float = 2.0
    spread: float = 0.0
    slippage: float = 0.0
    profile_name: Literal["swing", "dynamic"] = "swing"


@dataclass
class TurtleTrade:
    symbol: str
    profile: str
    direction: Literal["long", "short"]
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_price: float
    exit_price: float
    exit_reason: str
    r_multiple: float
    win: bool
    initial_risk: float
    bars_held: int


class TurtleTrendStrategy:
    """Implementação causal da estratégia Turtle Trend Following."""

    def __init__(self, config: TurtleTrendConfig | None = None) -> None:
        self.config = config or TurtleTrendConfig()

    @staticmethod
    def calculate_indicators(
        df: pd.DataFrame,
        entry_period: int = 20,
        exit_period: int = 10,
        atr_period: int = 20,
    ) -> dict[str, np.ndarray]:
        """Calcula canais Donchian e ATR de forma estritamente causal.

        Garante que para a barra i, os valores foram calculados observando
        apenas as barras até i-1.
        """
        high = df["high"]
        low = df["low"]
        close = df["close"]

        # ATR
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=atr_period).mean().bfill().to_numpy(dtype=float)

        # Canais Donchian com shift(1) para causalidade estrita
        donchian_high_entry = high.shift(1).rolling(window=entry_period).max().to_numpy(dtype=float)
        donchian_low_entry = low.shift(1).rolling(window=entry_period).min().to_numpy(dtype=float)

        donchian_high_exit = high.shift(1).rolling(window=exit_period).max().to_numpy(dtype=float)
        donchian_low_exit = low.shift(1).rolling(window=exit_period).min().to_numpy(dtype=float)

        return {
            "atr": atr,
            "dh_entry": donchian_high_entry,
            "dl_entry": donchian_low_entry,
            "dh_exit": donchian_high_exit,
            "dl_exit": donchian_low_exit,
        }

    def simulate(self, df: pd.DataFrame, symbol: str) -> list[TurtleTrade]:
        """Executa simulação de backtest causal respeitando regras do AGENTS.md."""
        cfg = self.config
        ind = self.calculate_indicators(
            df,
            entry_period=cfg.entry_channel_period,
            exit_period=cfg.exit_channel_period,
            atr_period=cfg.atr_period,
        )

        opens = df["open"].to_numpy(dtype=float)
        highs = df["high"].to_numpy(dtype=float)
        lows = df["low"].to_numpy(dtype=float)
        ts = df.index
        n = len(opens)

        atr = ind["atr"]
        dh_entry = ind["dh_entry"]
        dl_entry = ind["dl_entry"]
        dh_exit = ind["dh_exit"]
        dl_exit = ind["dl_exit"]

        spread = cfg.spread
        slippage = cfg.slippage
        stop_mult = cfg.stop_atr_mult

        trades: list[TurtleTrade] = []
        open_pos: dict[str, Any] | None = None
        warmup = max(cfg.entry_channel_period, cfg.exit_channel_period, cfg.atr_period) + 5

        for i in range(warmup, n):
            # 1. Posição Aberta: verificar saídas na barra i
            if open_pos is not None:
                pos = open_pos
                d = 1 if pos["direction"] == "long" else -1
                hit_sl = False
                exit_by_rule = False
                exit_rule_price = 0.0

                # A. Teste de Stop Loss na barra i
                if d == 1:
                    if lows[i] <= pos["stop_price"]:
                        hit_sl = True
                else:
                    if highs[i] + spread >= pos["stop_price"]:
                        hit_sl = True

                # B. Teste de Saída por canal oposto (apenas após a barra de entrada)
                if not hit_sl and i > pos["entry_idx"]:
                    if d == 1 and lows[i] <= dl_exit[i]:
                        exit_by_rule = True
                        exit_rule_price = min(dl_exit[i], opens[i]) - slippage
                    elif d == -1 and highs[i] + spread >= dh_exit[i]:
                        exit_by_rule = True
                        exit_rule_price = max(dh_exit[i], opens[i] + spread) + slippage

                if hit_sl:
                    if d == 1:
                        raw_exit = min(pos["stop_price"], opens[i])
                        exit_price = raw_exit - slippage
                        r = (exit_price - pos["entry_price"]) / pos["initial_risk"]
                    else:
                        raw_exit = max(pos["stop_price"], opens[i] + spread)
                        exit_price = raw_exit + slippage
                        r = (pos["entry_price"] - exit_price) / pos["initial_risk"]

                    trades.append(
                        TurtleTrade(
                            symbol=symbol,
                            profile=cfg.profile_name,
                            direction=pos["direction"],
                            entry_time=pos["entry_time"],
                            exit_time=ts[i],
                            entry_price=pos["entry_price"],
                            stop_price=pos["stop_price"],
                            exit_price=exit_price,
                            exit_reason="STOP_LOSS",
                            r_multiple=float(r),
                            win=bool(r > 0),
                            initial_risk=pos["initial_risk"],
                            bars_held=i - pos["entry_idx"],
                        )
                    )
                    open_pos = None
                    continue

                elif exit_by_rule:
                    exit_price = exit_rule_price
                    r = (
                        (exit_price - pos["entry_price"]) / pos["initial_risk"]
                        if d == 1
                        else (pos["entry_price"] - exit_price) / pos["initial_risk"]
                    )
                    trades.append(
                        TurtleTrade(
                            symbol=symbol,
                            profile=cfg.profile_name,
                            direction=pos["direction"],
                            entry_time=pos["entry_time"],
                            exit_time=ts[i],
                            entry_price=pos["entry_price"],
                            stop_price=pos["stop_price"],
                            exit_price=exit_price,
                            exit_reason="RULE_EXIT",
                            r_multiple=float(r),
                            win=bool(r > 0),
                            initial_risk=pos["initial_risk"],
                            bars_held=i - pos["entry_idx"],
                        )
                    )
                    open_pos = None
                    continue

            # 2. Ordem de Entrada Armada em i-1 para Execução na barra i
            if open_pos is None:
                long_trigger = dh_entry[i]
                short_trigger = dl_entry[i]
                stop_dist = stop_mult * atr[i - 1]

                if np.isnan(long_trigger) or np.isnan(short_trigger) or stop_dist <= 0:
                    continue

                long_triggered = highs[i] >= long_trigger
                short_triggered = lows[i] <= short_trigger

                # Se ambos romperem na mesma barra: sem entrada (conflito de sinal)
                if long_triggered and short_triggered:
                    continue

                if long_triggered:
                    exec_price = max(opens[i], long_trigger) + spread + slippage
                    stop_price = exec_price - stop_dist
                    risk = exec_price - stop_price

                    # Teste obrigatório de stop loss na própria barra de entrada
                    if lows[i] <= stop_price:
                        raw_exit = min(stop_price, opens[i])
                        exit_price = raw_exit - slippage
                        r = (exit_price - exec_price) / risk
                        trades.append(
                            TurtleTrade(
                                symbol=symbol,
                                profile=cfg.profile_name,
                                direction="long",
                                entry_time=ts[i],
                                exit_time=ts[i],
                                entry_price=exec_price,
                                stop_price=stop_price,
                                exit_price=exit_price,
                                exit_reason="STOP_LOSS_ENTRY",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                initial_risk=risk,
                                bars_held=0,
                            )
                        )
                    else:
                        open_pos = {
                            "direction": "long",
                            "entry_idx": i,
                            "entry_time": ts[i],
                            "entry_price": exec_price,
                            "stop_price": stop_price,
                            "initial_risk": risk,
                        }

                elif short_triggered:
                    exec_price = min(opens[i], short_trigger) - slippage
                    stop_price = exec_price + stop_dist
                    risk = stop_price - exec_price

                    # Teste obrigatório de stop loss na própria barra de entrada
                    if highs[i] + spread >= stop_price:
                        raw_exit = max(stop_price, opens[i] + spread)
                        exit_price = raw_exit + slippage
                        r = (exec_price - exit_price) / risk
                        trades.append(
                            TurtleTrade(
                                symbol=symbol,
                                profile=cfg.profile_name,
                                direction="short",
                                entry_time=ts[i],
                                exit_time=ts[i],
                                entry_price=exec_price,
                                stop_price=stop_price,
                                exit_price=exit_price,
                                exit_reason="STOP_LOSS_ENTRY",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                initial_risk=risk,
                                bars_held=0,
                            )
                        )
                    else:
                        open_pos = {
                            "direction": "short",
                            "entry_idx": i,
                            "entry_time": ts[i],
                            "entry_price": exec_price,
                            "stop_price": stop_price,
                            "initial_risk": risk,
                        }

        return trades

    def pending_setup(self, df: pd.DataFrame) -> dict[str, Any] | None:
        """Gera os parâmetros da ordem pendente para o candle seguinte (live / paper)."""
        cfg = self.config
        ind = self.calculate_indicators(
            df,
            entry_period=cfg.entry_channel_period,
            exit_period=cfg.exit_channel_period,
            atr_period=cfg.atr_period,
        )
        last_idx = len(df) - 1
        atr_val = ind["atr"][last_idx]
        stop_dist = cfg.stop_atr_mult * atr_val

        # Na próxima barra, os triggers serão a máxima/mínima das últimas N barras fechadas
        high = df["high"]
        low = df["low"]
        next_long_trigger = float(high.iloc[-cfg.entry_channel_period :].max())
        next_short_trigger = float(low.iloc[-cfg.entry_channel_period :].min())
        next_exit_long = float(low.iloc[-cfg.exit_channel_period :].min())
        next_exit_short = float(high.iloc[-cfg.exit_channel_period :].max())

        return {
            "profile": cfg.profile_name,
            "timeframe": cfg.timeframe,
            "next_long_trigger": next_long_trigger,
            "next_short_trigger": next_short_trigger,
            "stop_dist": stop_dist,
            "next_exit_long": next_exit_long,
            "next_exit_short": next_exit_short,
            "atr": atr_val,
        }

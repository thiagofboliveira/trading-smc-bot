"""
Módulo Oficial da Estratégia SMC Fibonacci OTE (Optimal Trade Entry) — Versão Auditada Realista
Implementa execução 100% livre de viés intrabar (anti-imunidade de mesma barra),
Trailing Stop MME 8 com filtro de proteção de lucro e Trava de Lucro 2:1 (Blindagem de Capital).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
import numpy as np
import pandas as pd


@dataclass
class FiboOTEConfig:
    timeframe: str = "5min"
    fibo_entry: float = 0.705           # Nível Sweet Spot Institucional (70.5%)
    fibo_stop: float = 0.790            # Nível de Invalidação (79.0% ou 1.000 estrutural)
    target_mode: Literal["3R", "0_percent", "proj_618", "trailing_only"] = "0_percent"
    target_r: float = 3.0
    pivot_k: int = 2                    # Delay fractal (2 barras para confirmação sem lookahead)
    max_holding_candles: int = 60
    enable_reentry_79: bool = False
    min_leg_spread_mult: float = 10.0
    trailing_exit_ma: str | None = "ema8"  # 'ema8', 'sma20', 'sma9', 'ema80' ou None
    trailing_profit_only: bool = True     # Exige fechamento no lucro para encerrar por trailing
    use_lock_2to1: bool = False           # Trava 2:1 (Perfil Blindado: ao atingir +2R, sobe stop para +1R)
    lock_trigger_r: float = 2.0
    lock_guarantee_r: float = 1.0
    check_intrabar_sl: bool = True        # Auditoria anti-imunidade: verifica se a própria barra de entrada estopou


@dataclass
class FiboTrade:
    symbol: str
    stage: int  # 1 = entrada primária, 2 = reentrada
    direction: Literal["long", "short"]
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_points: float
    pnl_points: float
    r_multiple: float
    win: bool
    exit_reason: str


class FiboOTEStrategy:
    """Estratégia institucional baseada em impulsão com BOS e retração OTE de Fibonacci."""

    def __init__(self, config: FiboOTEConfig | None = None) -> None:
        self.config = config or FiboOTEConfig()

    def resample_data(self, df_m1: pd.DataFrame) -> pd.DataFrame:
        """Resampleia candles M1 para o timeframe operacional (padrão M5)."""
        if not isinstance(df_m1.index, pd.DatetimeIndex):
            if "time" in df_m1.columns:
                df_m1 = df_m1.copy()
                df_m1["time"] = pd.to_datetime(df_m1["time"])
                df_m1.set_index("time", inplace=True)
            elif "timestamp" in df_m1.columns:
                df_m1 = df_m1.copy()
                df_m1["timestamp"] = pd.to_datetime(df_m1["timestamp"])
                df_m1.set_index("timestamp", inplace=True)

        rule = "5min" if self.config.timeframe in ("M5", "5min", "5m") else self.config.timeframe
        df_res = df_m1.resample(rule).agg({
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum"
        }).dropna()

        if self.config.trailing_exit_ma:
            ma = self.config.trailing_exit_ma.lower()
            if ma == "ema8":
                df_res["trailing_ma"] = df_res["close"].ewm(span=8, adjust=False).mean()
            elif ma == "sma20":
                df_res["trailing_ma"] = df_res["close"].rolling(20).mean()
            elif ma == "sma9":
                df_res["trailing_ma"] = df_res["close"].rolling(9).mean()
            elif ma == "ema80":
                df_res["trailing_ma"] = df_res["close"].ewm(span=80, adjust=False).mean()
            else:
                df_res["trailing_ma"] = df_res["close"].ewm(span=8, adjust=False).mean()
        return df_res

    def run_backtest(self, df_m1: pd.DataFrame, symbol: str, spread: float) -> list[FiboTrade]:
        """Executa simulação cronológica candle a candle sem viés de mesma barra."""
        df = self.resample_data(df_m1)
        cfg = self.config
        k = cfg.pivot_k
        n = len(df)

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        opens = df["open"].values
        timestamps = df.index
        trailing_mas = df["trailing_ma"].values if "trailing_ma" in df.columns else None

        # Detecção de swings fractais (evitando lookahead usando delay k)
        swing_highs = np.zeros(n, dtype=bool)
        swing_lows = np.zeros(n, dtype=bool)

        for i in range(k, n - k):
            if highs[i] == max(highs[i - k : i + k + 1]):
                swing_highs[i] = True
            if lows[i] == min(lows[i - k : i + k + 1]):
                swing_lows[i] = True

        trades: list[FiboTrade] = []
        last_sh_price = None
        last_sh_idx = None
        last_sl_price = None
        last_sl_idx = None

        in_pos = False
        pos_dir = 0
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0
        entry_idx = 0
        risk = 0.0
        trade_stage = 1
        trava_ativada = False

        active_leg = None

        for i in range(k + 1, n - 1):
            # 1. Swings confirmados com atraso de k períodos
            chk_idx = i - k
            if swing_highs[chk_idx]:
                last_sh_price = highs[chk_idx]
                last_sh_idx = chk_idx
            if swing_lows[chk_idx]:
                last_sl_price = lows[chk_idx]
                last_sl_idx = chk_idx

            # 2. Gerenciamento de posição aberta (barras subsequentes à entrada)
            if in_pos:
                c_high = highs[i]
                c_low = lows[i]
                c_close = closes[i]

                # 2.1 Trava 2:1 (Blindagem de Capital)
                if cfg.use_lock_2to1 and not trava_ativada:
                    if pos_dir == 1:
                        if c_high >= (entry_price + risk * cfg.lock_trigger_r):
                            sl_price = entry_price + (risk * cfg.lock_guarantee_r)
                            trava_ativada = True
                    else:
                        if c_low <= (entry_price - risk * cfg.lock_trigger_r):
                            sl_price = entry_price - (risk * cfg.lock_guarantee_r)
                            trava_ativada = True

                # 2.2 Verificação de Saída por Trailing MA (Apenas se estiver no lucro!)
                exit_by_trailing = False
                trailing_exit_price = 0.0
                if trailing_mas is not None and i > entry_idx:
                    curr_ma = trailing_mas[i]
                    if pos_dir == 1 and c_close < curr_ma:
                        if (not cfg.trailing_profit_only) or (c_close > entry_price):
                            exit_by_trailing = True
                            trailing_exit_price = c_close
                    elif pos_dir == -1 and c_close > curr_ma:
                        if (not cfg.trailing_profit_only) or (c_close < entry_price):
                            exit_by_trailing = True
                            trailing_exit_price = c_close

                # 2.3 Resolução de Saídas (Stop Loss / Take Profit / Trailing MA)
                if pos_dir == 1:  # LONG
                    hit_sl = c_low <= sl_price
                    hit_tp = (c_high >= tp_price) if cfg.target_mode != "trailing_only" else False

                    if hit_sl and hit_tp:
                        # Pior cenário primeiro (conservador)
                        pnl_pts = sl_price - entry_price
                        r_mult = pnl_pts / risk
                        trades.append(FiboTrade(
                            symbol=symbol, stage=trade_stage, direction="long",
                            entry_time=timestamps[entry_idx], exit_time=timestamps[i],
                            entry_price=entry_price, stop_loss=sl_price, take_profit=tp_price,
                            risk_points=risk, pnl_points=pnl_pts, r_multiple=r_mult, win=(r_mult > 0),
                            exit_reason="LOCK_PROFIT_SL" if trava_ativada else "STOP_LOSS"
                        ))
                        in_pos = False
                        active_leg = None
                    elif hit_sl:
                        pnl_pts = sl_price - entry_price
                        r_mult = pnl_pts / risk
                        trades.append(FiboTrade(
                            symbol=symbol, stage=trade_stage, direction="long",
                            entry_time=timestamps[entry_idx], exit_time=timestamps[i],
                            entry_price=entry_price, stop_loss=sl_price, take_profit=tp_price,
                            risk_points=risk, pnl_points=pnl_pts, r_multiple=r_mult, win=(r_mult > 0),
                            exit_reason="LOCK_PROFIT_SL" if trava_ativada else "STOP_LOSS"
                        ))
                        in_pos = False
                        active_leg = None
                    elif exit_by_trailing:
                        pnl_pts = trailing_exit_price - entry_price
                        r_mult = pnl_pts / risk
                        trades.append(FiboTrade(
                            symbol=symbol, stage=trade_stage, direction="long",
                            entry_time=timestamps[entry_idx], exit_time=timestamps[i],
                            entry_price=entry_price, stop_loss=sl_price, take_profit=tp_price,
                            risk_points=risk, pnl_points=pnl_pts, r_multiple=r_mult, win=(r_mult > 0),
                            exit_reason="TRAILING_MA"
                        ))
                        in_pos = False
                        active_leg = None
                    elif hit_tp:
                        r_mult = cfg.target_r if cfg.target_mode == "3R" else (tp_price - entry_price) / risk
                        pnl_pts = tp_price - entry_price
                        trades.append(FiboTrade(
                            symbol=symbol, stage=trade_stage, direction="long",
                            entry_time=timestamps[entry_idx], exit_time=timestamps[i],
                            entry_price=entry_price, stop_loss=sl_price, take_profit=tp_price,
                            risk_points=risk, pnl_points=pnl_pts, r_multiple=r_mult, win=True,
                            exit_reason="TAKE_PROFIT"
                        ))
                        in_pos = False
                        active_leg = None
                else:  # SHORT
                    hit_sl = c_high >= sl_price
                    hit_tp = (c_low <= tp_price) if cfg.target_mode != "trailing_only" else False

                    if hit_sl and hit_tp:
                        pnl_pts = entry_price - sl_price
                        r_mult = pnl_pts / risk
                        trades.append(FiboTrade(
                            symbol=symbol, stage=trade_stage, direction="short",
                            entry_time=timestamps[entry_idx], exit_time=timestamps[i],
                            entry_price=entry_price, stop_loss=sl_price, take_profit=tp_price,
                            risk_points=risk, pnl_points=pnl_pts, r_multiple=r_mult, win=(r_mult > 0),
                            exit_reason="LOCK_PROFIT_SL" if trava_ativada else "STOP_LOSS"
                        ))
                        in_pos = False
                        active_leg = None
                    elif hit_sl:
                        pnl_pts = entry_price - sl_price
                        r_mult = pnl_pts / risk
                        trades.append(FiboTrade(
                            symbol=symbol, stage=trade_stage, direction="short",
                            entry_time=timestamps[entry_idx], exit_time=timestamps[i],
                            entry_price=entry_price, stop_loss=sl_price, take_profit=tp_price,
                            risk_points=risk, pnl_points=pnl_pts, r_multiple=r_mult, win=(r_mult > 0),
                            exit_reason="LOCK_PROFIT_SL" if trava_ativada else "STOP_LOSS"
                        ))
                        in_pos = False
                        active_leg = None
                    elif exit_by_trailing:
                        pnl_pts = entry_price - trailing_exit_price
                        r_mult = pnl_pts / risk
                        trades.append(FiboTrade(
                            symbol=symbol, stage=trade_stage, direction="short",
                            entry_time=timestamps[entry_idx], exit_time=timestamps[i],
                            entry_price=entry_price, stop_loss=sl_price, take_profit=tp_price,
                            risk_points=risk, pnl_points=pnl_pts, r_multiple=r_mult, win=(r_mult > 0),
                            exit_reason="TRAILING_MA"
                        ))
                        in_pos = False
                        active_leg = None
                    elif hit_tp:
                        r_mult = cfg.target_r if cfg.target_mode == "3R" else (entry_price - tp_price) / risk
                        pnl_pts = entry_price - tp_price
                        trades.append(FiboTrade(
                            symbol=symbol, stage=trade_stage, direction="short",
                            entry_time=timestamps[entry_idx], exit_time=timestamps[i],
                            entry_price=entry_price, stop_loss=sl_price, take_profit=tp_price,
                            risk_points=risk, pnl_points=pnl_pts, r_multiple=r_mult, win=True,
                            exit_reason="TAKE_PROFIT"
                        ))
                        in_pos = False
                        active_leg = None
                continue

            # 3. Detectar nova perna de impulsão por quebra de estrutura (BOS)
            if active_leg is None and last_sh_price is not None and last_sl_price is not None:
                if last_sh_idx > last_sl_idx:  # BOS de Alta
                    if closes[i] > last_sh_price:
                        leg_low = last_sl_price
                        leg_high = highs[i]
                        leg_range = leg_high - leg_low
                        if leg_range > spread * cfg.min_leg_spread_mult:
                            active_leg = {
                                "dir": 1,
                                "low": leg_low,
                                "high": leg_high,
                                "range": leg_range,
                                "fibo_entry": leg_high - cfg.fibo_entry * leg_range,
                                "fibo_stop": leg_high - cfg.fibo_stop * leg_range,
                                "origin_100": leg_low,
                                "touched_entry": False,
                                "awaiting_79": False,
                                "candles": 0
                            }
                elif last_sl_idx > last_sh_idx:  # BOS de Baixa
                    if closes[i] < last_sl_price:
                        leg_high = last_sh_price
                        leg_low = lows[i]
                        leg_range = leg_high - leg_low
                        if leg_range > spread * cfg.min_leg_spread_mult:
                            active_leg = {
                                "dir": -1,
                                "high": leg_high,
                                "low": leg_low,
                                "range": leg_range,
                                "fibo_entry": leg_low + cfg.fibo_entry * leg_range,
                                "fibo_stop": leg_low + cfg.fibo_stop * leg_range,
                                "origin_100": leg_high,
                                "touched_entry": False,
                                "awaiting_79": False,
                                "candles": 0
                            }

            # 4. Avaliar gatilhos na perna ativa
            if active_leg is not None:
                active_leg["candles"] += 1
                if active_leg["candles"] > cfg.max_holding_candles:
                    active_leg = None
                    continue

                # Expansão da perna caso continue antes de retrair
                if not active_leg["touched_entry"] and not active_leg["awaiting_79"]:
                    if active_leg["dir"] == 1 and highs[i] > active_leg["high"]:
                        active_leg["high"] = highs[i]
                        active_leg["range"] = active_leg["high"] - active_leg["low"]
                        active_leg["fibo_entry"] = active_leg["high"] - cfg.fibo_entry * active_leg["range"]
                        active_leg["fibo_stop"] = active_leg["high"] - cfg.fibo_stop * active_leg["range"]
                    elif active_leg["dir"] == -1 and lows[i] < active_leg["low"]:
                        active_leg["low"] = lows[i]
                        active_leg["range"] = active_leg["high"] - active_leg["low"]
                        active_leg["fibo_entry"] = active_leg["low"] + cfg.fibo_entry * active_leg["range"]
                        active_leg["fibo_stop"] = active_leg["low"] + cfg.fibo_stop * active_leg["range"]

                # ENTRADA PRIMÁRIA: Toque no nível de Fibonacci
                if not active_leg["touched_entry"] and not active_leg["awaiting_79"]:
                    if active_leg["dir"] == 1:
                        if lows[i] <= active_leg["fibo_entry"]:
                            active_leg["touched_entry"] = True
                            raw_entry = active_leg["fibo_entry"]
                            raw_sl = active_leg["fibo_stop"]

                            entry_price = raw_entry + spread
                            sl_price = raw_sl
                            risk = entry_price - sl_price

                            if risk > spread * 1.5:
                                if cfg.target_mode == "3R":
                                    tp_price = entry_price + (risk * cfg.target_r)
                                elif cfg.target_mode == "0_percent":
                                    tp_price = active_leg["high"]
                                elif cfg.target_mode == "proj_618":
                                    corr_size = active_leg["high"] - active_leg["fibo_entry"]
                                    tp_price = active_leg["high"] + (corr_size * 0.618)
                                else:
                                    tp_price = active_leg["high"]

                                in_pos = True
                                pos_dir = 1
                                trade_stage = 1
                                entry_idx = i
                                trava_ativada = False

                                # ==========================================================
                                # AUDITORIA ANTI-IMUNIDADE (GEMINI ARGON):
                                # Verifica se a própria barra de entrada afundou no Stop Loss!
                                # ==========================================================
                                if cfg.check_intrabar_sl and lows[i] <= sl_price:
                                    pnl_pts = sl_price - entry_price
                                    trades.append(FiboTrade(
                                        symbol=symbol, stage=trade_stage, direction="long",
                                        entry_time=timestamps[i], exit_time=timestamps[i],
                                        entry_price=entry_price, stop_loss=sl_price, take_profit=tp_price,
                                        risk_points=risk, pnl_points=pnl_pts, r_multiple=-1.0, win=False,
                                        exit_reason="INTRABAR_STOP_LOSS"
                                    ))
                                    in_pos = False
                                    active_leg = None
                                continue
                    else:
                        if highs[i] >= active_leg["fibo_entry"]:
                            active_leg["touched_entry"] = True
                            raw_entry = active_leg["fibo_entry"]
                            raw_sl = active_leg["fibo_stop"]

                            entry_price = raw_entry
                            sl_price = raw_sl + spread
                            risk = sl_price - entry_price

                            if risk > spread * 1.5:
                                if cfg.target_mode == "3R":
                                    tp_price = entry_price - (risk * cfg.target_r)
                                elif cfg.target_mode == "0_percent":
                                    tp_price = active_leg["low"]
                                elif cfg.target_mode == "proj_618":
                                    corr_size = active_leg["fibo_entry"] - active_leg["low"]
                                    tp_price = active_leg["low"] - (corr_size * 0.618)
                                else:
                                    tp_price = active_leg["low"]

                                in_pos = True
                                pos_dir = -1
                                trade_stage = 1
                                entry_idx = i
                                trava_ativada = False

                                # ==========================================================
                                # AUDITORIA ANTI-IMUNIDADE (GEMINI ARGON):
                                # Verifica se a própria barra de entrada subiu no Stop Loss!
                                # ==========================================================
                                if cfg.check_intrabar_sl and highs[i] >= sl_price:
                                    pnl_pts = entry_price - sl_price
                                    trades.append(FiboTrade(
                                        symbol=symbol, stage=trade_stage, direction="short",
                                        entry_time=timestamps[i], exit_time=timestamps[i],
                                        entry_price=entry_price, stop_loss=sl_price, take_profit=tp_price,
                                        risk_points=risk, pnl_points=pnl_pts, r_multiple=-1.0, win=False,
                                        exit_reason="INTRABAR_STOP_LOSS"
                                    ))
                                    in_pos = False
                                    active_leg = None
                                continue

        return trades

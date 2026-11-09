"""Pesquisa Quantitativa:
Parte 1: POI 50% a 79% com Condução de Trade (MME 20, MME 9, Trailing Barra a Barra)
Parte 2: Pivô Clássico Alinhado nas Médias (MMA 9/20 + MME 80 + MMA 200)

Protocolo Anti-Viés Estrito (AGENTS.md):
- Indicadores causais em i-1 (shift(1)).
- Entradas no rompimento executadas no gatilho ou com gap no Open.
- Checagem imediata de stop na barra de entrada.
- Stops em gap executados no Open + slippage.
- Spreads reais e slippage realista aplicados.
- Modo single-position por ativo.
- Auditoria de compras vs vendas.
"""

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

SYMBOLS = ["NAS100", "US30", "BRENT", "EURUSD", "GBPUSD", "XAUUSD"]

SPREADS = {
    "XAUUSD": 0.20,
    "EURUSD": 0.00008,
    "GBPUSD": 0.00010,
    "US30": 2.0,
    "NAS100": 1.5,
    "BRENT": 0.03,
}

SLIPPAGES = {
    "XAUUSD": 0.10,
    "EURUSD": 0.00005,
    "GBPUSD": 0.00005,
    "US30": 1.0,
    "NAS100": 1.0,
    "BRENT": 0.02,
}

OOS_SPLIT_DATE = pd.Timestamp("2024-11-01", tz="UTC")


@dataclass
class Pivot:
    time: pd.Timestamp
    kind: str
    price: float
    confirmed_idx: int
    confirmed_time: pd.Timestamp


@dataclass
class Trade:
    symbol: str
    strategy: str
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_price: float
    exit_price: float
    exit_reason: str
    r_multiple: float
    win: bool
    is_oos: bool


def find_causal_pivots(df: pd.DataFrame, k: int = 2) -> list[Pivot]:
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    ts = df.index
    n = len(df)
    pivots: list[Pivot] = []

    for i in range(k, n - k):
        is_high = np.all(highs[i] > highs[i - k : i]) and np.all(highs[i] >= highs[i + 1 : i + k + 1])
        is_low = np.all(lows[i] < lows[i - k : i]) and np.all(lows[i] <= lows[i + 1 : i + k + 1])
        if is_high:
            pivots.append(Pivot(ts[i], "high", float(highs[i]), i + k, ts[i + k]))
        if is_low:
            pivots.append(Pivot(ts[i], "low", float(lows[i]), i + k, ts[i + k]))
    return pivots


def calc_stats(trades: list[Trade]) -> dict:
    if not trades:
        return {
            "n": 0, "wr": 0.0, "pf": 0.0, "total_r": 0.0,
            "mean_r": 0.0, "se_r": 0.0, "t_stat": 0.0,
            "max_dd": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "longs": 0, "shorts": 0,
        }
    rs = np.array([t.r_multiple for t in trades])
    wins = rs[rs > 0]
    losses = rs[rs < 0]

    gp = float(wins.sum()) if len(wins) > 0 else 0.0
    gl = float(abs(losses.sum())) if len(losses) > 0 else 0.0
    pf = (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0)

    wr = float(len(wins) / len(rs)) * 100.0
    total_r = float(rs.sum())
    mean_r = float(rs.mean())
    se_r = float(rs.std(ddof=1) / np.sqrt(len(rs))) if len(rs) > 1 else 0.0
    t_stat = (mean_r / se_r) if se_r > 0 else 0.0

    cum_r = np.cumsum(rs)
    peak = np.maximum.accumulate(cum_r)
    dd = peak - cum_r
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

    avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(abs(losses.mean())) if len(losses) > 0 else 0.0

    longs = sum(1 for t in trades if t.direction == "long")
    shorts = sum(1 for t in trades if t.direction == "short")

    return {
        "n": len(trades),
        "wr": wr,
        "pf": pf,
        "total_r": total_r,
        "mean_r": mean_r,
        "se_r": se_r,
        "t_stat": t_stat,
        "max_dd": max_dd,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "longs": longs,
        "shorts": shorts,
    }


# ===================================================================================================
# PARTE 1: POI 50% A 79% COM CONDUÇÃO DE TRADE
# ===================================================================================================

def simulate_poi_conducao(
    df_h1: pd.DataFrame,
    df_m15: pd.DataFrame,
    symbol: str,
    spread: float,
    slippage: float,
    exit_mode: str = "TRAILING_EMA20",  # 'TRAILING_EMA20', 'TRAILING_EMA9', 'BAR_BY_BAR', 'FIXED_1R'
) -> list[Trade]:
    h1_pivots = find_causal_pivots(df_h1, k=2)
    m15_pivots = find_causal_pivots(df_m15, k=2)

    opens = df_m15["open"].to_numpy(dtype=float)
    highs = df_m15["high"].to_numpy(dtype=float)
    lows = df_m15["low"].to_numpy(dtype=float)
    closes = df_m15["close"].to_numpy(dtype=float)
    ts = df_m15.index

    # Médias M15 causais (calculadas com fechamento até i-1)
    ema20 = df_m15["close"].shift(1).ewm(span=20, adjust=False).mean().to_numpy(dtype=float)
    ema9 = df_m15["close"].shift(1).ewm(span=9, adjust=False).mean().to_numpy(dtype=float)

    h1_ptr = 0
    m15_ptr = 0
    last_high_h1 = None
    last_low_h1 = None
    last_micro_high = None
    last_micro_low = None

    trades: list[Trade] = []
    open_pos = None

    for i in range(25, len(df_m15)):
        curr_time = ts[i]

        while h1_ptr < len(h1_pivots) and h1_pivots[h1_ptr].confirmed_time <= curr_time:
            p = h1_pivots[h1_ptr]
            if p.kind == "high":
                last_high_h1 = p
            elif p.kind == "low":
                last_low_h1 = p
            h1_ptr += 1

        while m15_ptr < len(m15_pivots) and m15_pivots[m15_ptr].confirmed_time <= curr_time:
            p = m15_pivots[m15_ptr]
            if p.kind == "high":
                last_micro_high = p
            elif p.kind == "low":
                last_micro_low = p
            m15_ptr += 1

        # Gestão de posição aberta
        if open_pos is not None:
            risk = open_pos["initial_risk"]
            pos_dir = open_pos["direction"]

            # 1. Checa stop loss estrutural / trailing stop
            if pos_dir == "long":
                if lows[i] <= open_pos["stop_price"]:
                    raw_exit = min(open_pos["stop_price"], opens[i])
                    exit_price = raw_exit - slippage
                    r = (exit_price - open_pos["entry_price"]) / risk
                    trades.append(
                        Trade(
                            symbol=symbol,
                            strategy=f"POI_50_79_{exit_mode}",
                            direction="long",
                            entry_time=open_pos["entry_time"],
                            exit_time=curr_time,
                            entry_price=open_pos["entry_price"],
                            stop_price=open_pos["stop_price"],
                            exit_price=exit_price,
                            exit_reason=open_pos["last_stop_reason"],
                            r_multiple=float(r),
                            win=bool(r > 0),
                            is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                        )
                    )
                    open_pos = None
                    continue

                # 2. Condução / Saída de fechamento da barra anterior i-1
                if exit_mode == "TRAILING_EMA20":
                    if closes[i - 1] < ema20[i - 1]:
                        # Saída a mercado na abertura da barra i
                        exit_price = opens[i] - slippage
                        r = (exit_price - open_pos["entry_price"]) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"POI_50_79_{exit_mode}",
                                direction="long",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="EXIT_BELOW_EMA20",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

                elif exit_mode == "TRAILING_EMA9":
                    if closes[i - 1] < ema9[i - 1]:
                        exit_price = opens[i] - slippage
                        r = (exit_price - open_pos["entry_price"]) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"POI_50_79_{exit_mode}",
                                direction="long",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="EXIT_BELOW_EMA9",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

                elif exit_mode == "BAR_BY_BAR":
                    # Mover stop para mínima do candle anterior se trade já atingiu +1R
                    unrealized_r = (highs[i - 1] - open_pos["entry_price"]) / risk
                    if unrealized_r >= 1.0:
                        new_sl = lows[i - 1] - slippage
                        if new_sl > open_pos["stop_price"]:
                            open_pos["stop_price"] = new_sl
                            open_pos["last_stop_reason"] = "TRAILING_BAR_BY_BAR"

                elif exit_mode == "FIXED_1R":
                    tp = open_pos["entry_price"] + 1.0 * risk
                    if highs[i] >= tp:
                        raw_exit = max(tp, opens[i])
                        exit_price = raw_exit - slippage
                        r = (exit_price - open_pos["entry_price"]) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"POI_50_79_{exit_mode}",
                                direction="long",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="TAKE_PROFIT_1R",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

            else:  # short
                if highs[i] + spread >= open_pos["stop_price"]:
                    raw_exit = max(open_pos["stop_price"], opens[i] + spread)
                    exit_price = raw_exit + slippage
                    r = (open_pos["entry_price"] - exit_price) / risk
                    trades.append(
                        Trade(
                            symbol=symbol,
                            strategy=f"POI_50_79_{exit_mode}",
                            direction="short",
                            entry_time=open_pos["entry_time"],
                            exit_time=curr_time,
                            entry_price=open_pos["entry_price"],
                            stop_price=open_pos["stop_price"],
                            exit_price=exit_price,
                            exit_reason=open_pos["last_stop_reason"],
                            r_multiple=float(r),
                            win=bool(r > 0),
                            is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                        )
                    )
                    open_pos = None
                    continue

                if exit_mode == "TRAILING_EMA20":
                    if closes[i - 1] > ema20[i - 1]:
                        exit_price = opens[i] + spread + slippage
                        r = (open_pos["entry_price"] - exit_price) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"POI_50_79_{exit_mode}",
                                direction="short",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="EXIT_ABOVE_EMA20",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

                elif exit_mode == "TRAILING_EMA9":
                    if closes[i - 1] > ema9[i - 1]:
                        exit_price = opens[i] + spread + slippage
                        r = (open_pos["entry_price"] - exit_price) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"POI_50_79_{exit_mode}",
                                direction="short",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="EXIT_ABOVE_EMA9",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

                elif exit_mode == "BAR_BY_BAR":
                    unrealized_r = (open_pos["entry_price"] - (lows[i - 1] + spread)) / risk
                    if unrealized_r >= 1.0:
                        new_sl = highs[i - 1] + spread + slippage
                        if new_sl < open_pos["stop_price"]:
                            open_pos["stop_price"] = new_sl
                            open_pos["last_stop_reason"] = "TRAILING_BAR_BY_BAR"

                elif exit_mode == "FIXED_1R":
                    tp = open_pos["entry_price"] - 1.0 * risk
                    if lows[i] <= tp:
                        raw_exit = min(tp, opens[i])
                        exit_price = raw_exit + slippage
                        r = (open_pos["entry_price"] - exit_price) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"POI_50_79_{exit_mode}",
                                direction="short",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="TAKE_PROFIT_1R",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

        # Detecção de novos sinais se desposicionado
        if open_pos is None and last_high_h1 is not None and last_low_h1 is not None:
            is_macro_bullish = last_high_h1.time > last_low_h1.time
            is_macro_bearish = last_low_h1.time > last_high_h1.time

            long_signal = False
            short_signal = False

            # Long: POI entre 50% e 79%
            if is_macro_bullish and last_micro_high is not None and last_micro_low is not None:
                p_high = last_high_h1.price
                p_low = last_low_h1.price
                leg_range = p_high - p_low

                poi_bottom = p_high - 0.790 * leg_range
                poi_top = p_high - 0.500 * leg_range

                in_poi = (lows[i - 1] <= poi_top) and (closes[i - 1] >= poi_bottom) and (lows[i - 1] > p_low)
                micro_valid = (last_micro_high.time > last_low_h1.time) and (last_micro_low.time > last_low_h1.time)

                if in_poi and micro_valid:
                    # CHoCH micro confirmado em i-1
                    choch = (closes[i - 1] > last_micro_high.price) and (closes[i - 2] <= last_micro_high.price)
                    # MME 20 alinhada: preço acima da MME20 e inclinação positiva
                    ema_aligned = (closes[i - 1] > ema20[i - 1]) and (ema20[i - 1] >= ema20[i - 2])

                    if choch and ema_aligned:
                        long_entry = opens[i] + spread + slippage
                        long_sl = last_micro_low.price - slippage
                        risk = long_entry - long_sl
                        if risk > 0:
                            long_signal = True

            # Short: POI entre 50% e 79%
            elif is_macro_bearish and last_micro_high is not None and last_micro_low is not None:
                p_high = last_high_h1.price
                p_low = last_low_h1.price
                leg_range = p_high - p_low

                poi_bottom = p_low + 0.500 * leg_range
                poi_top = p_low + 0.790 * leg_range

                in_poi = (highs[i - 1] >= poi_bottom) and (closes[i - 1] <= poi_top) and (highs[i - 1] < p_high)
                micro_valid = (last_micro_high.time > last_low_h1.time) and (last_micro_low.time > last_low_h1.time)

                if in_poi and micro_valid:
                    choch = (closes[i - 1] < last_micro_low.price) and (closes[i - 2] >= last_micro_low.price)
                    ema_aligned = (closes[i - 1] < ema20[i - 1]) and (ema20[i - 1] <= ema20[i - 2])

                    if choch and ema_aligned:
                        short_entry = opens[i] - slippage
                        short_sl = last_micro_high.price + spread + slippage
                        risk = short_sl - short_entry
                        if risk > 0:
                            short_signal = True

            if long_signal and short_signal:
                continue

            if long_signal:
                risk = long_entry - long_sl
                # Checagem imediata de stop intrabar na barra de entrada i
                if lows[i] <= long_sl:
                    raw_exit = min(long_sl, opens[i])
                    exit_price = raw_exit - slippage
                    r = (exit_price - long_entry) / risk
                    trades.append(
                        Trade(
                            symbol=symbol,
                            strategy=f"POI_50_79_{exit_mode}",
                            direction="long",
                            entry_time=curr_time,
                            exit_time=curr_time,
                            entry_price=long_entry,
                            stop_price=long_sl,
                            exit_price=exit_price,
                            exit_reason="STOP_ENTRY_BAR",
                            r_multiple=float(r),
                            win=bool(r > 0),
                            is_oos=bool(curr_time >= OOS_SPLIT_DATE),
                        )
                    )
                else:
                    open_pos = {
                        "direction": "long",
                        "entry_time": curr_time,
                        "entry_price": long_entry,
                        "stop_price": long_sl,
                        "initial_risk": risk,
                        "last_stop_reason": "INITIAL_STOP_LOSS",
                    }

            elif short_signal:
                risk = short_sl - short_entry
                if highs[i] + spread >= short_sl:
                    raw_exit = max(short_sl, opens[i] + spread)
                    exit_price = raw_exit + slippage
                    r = (short_entry - exit_price) / risk
                    trades.append(
                        Trade(
                            symbol=symbol,
                            strategy=f"POI_50_79_{exit_mode}",
                            direction="short",
                            entry_time=curr_time,
                            exit_time=curr_time,
                            entry_price=short_entry,
                            stop_price=short_sl,
                            exit_price=exit_price,
                            exit_reason="STOP_ENTRY_BAR",
                            r_multiple=float(r),
                            win=bool(r > 0),
                            is_oos=bool(curr_time >= OOS_SPLIT_DATE),
                        )
                    )
                else:
                    open_pos = {
                        "direction": "short",
                        "entry_time": curr_time,
                        "entry_price": short_entry,
                        "stop_price": short_sl,
                        "initial_risk": risk,
                        "last_stop_reason": "INITIAL_STOP_LOSS",
                    }

    return trades


# ===================================================================================================
# PARTE 2: PIVÔ CLÁSSICO ALINHADO NAS MÉDIAS (MMA 9/20 + MME 80 + MMA 200)
# ===================================================================================================

def simulate_pivo_medias_alinhadas(
    df: pd.DataFrame,
    symbol: str,
    spread: float,
    slippage: float,
    exit_mode: str = "FIXED_1R",  # 'FIXED_1R', 'FIXED_2R', 'TRAILING_EMA9', 'TRAILING_SMA20'
) -> list[Trade]:
    """Estratégia Clássica de Médias Alinhadas:
    - Macro: Fechamento > MME 80 > MMA 200 (compra) ou Fechamento < MME 80 < MMA 200 (venda)
    - Micro: MMA 9 > MMA 20 (compra) ou MMA 9 < MMA 20 (venda)
    - Setup do Pivô: O preço recua até tocar na MMA 20 ou MMA 9 na barra i-1
    - Entrada por Rompimento: BuyStop na máxima da barra i-1 + slippage + spread (ou SellStop na mínima)
    - Stop Loss: Mínima do candle de sinal i-1 (ou máxima)
    """
    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    ts = df.index

    # Médias estritamente causais (shift(1))
    # MMA = Simple Moving Average, MME = Exponential Moving Average
    sma9 = df["close"].shift(1).rolling(window=9).mean().to_numpy(dtype=float)
    sma20 = df["close"].shift(1).rolling(window=20).mean().to_numpy(dtype=float)
    ema80 = df["close"].shift(1).ewm(span=80, adjust=False).mean().to_numpy(dtype=float)
    sma200 = df["close"].shift(1).rolling(window=200).mean().to_numpy(dtype=float)

    trades: list[Trade] = []
    open_pos = None

    for i in range(205, len(df)):
        curr_time = ts[i]

        # Gestão de posição aberta
        if open_pos is not None:
            risk = open_pos["initial_risk"]
            pos_dir = open_pos["direction"]

            if pos_dir == "long":
                # 1. Stop loss
                if lows[i] <= open_pos["stop_price"]:
                    raw_exit = min(open_pos["stop_price"], opens[i])
                    exit_price = raw_exit - slippage
                    r = (exit_price - open_pos["entry_price"]) / risk
                    trades.append(
                        Trade(
                            symbol=symbol,
                            strategy=f"MEDIAS_ALINHADAS_{exit_mode}",
                            direction="long",
                            entry_time=open_pos["entry_time"],
                            exit_time=curr_time,
                            entry_price=open_pos["entry_price"],
                            stop_price=open_pos["stop_price"],
                            exit_price=exit_price,
                            exit_reason=open_pos["last_stop_reason"],
                            r_multiple=float(r),
                            win=bool(r > 0),
                            is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                        )
                    )
                    open_pos = None
                    continue

                # 2. Modos de Saída
                if exit_mode == "FIXED_1R":
                    tp = open_pos["entry_price"] + 1.0 * risk
                    if highs[i] >= tp:
                        raw_exit = max(tp, opens[i])
                        exit_price = raw_exit - slippage
                        r = (exit_price - open_pos["entry_price"]) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"MEDIAS_ALINHADAS_{exit_mode}",
                                direction="long",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="TAKE_PROFIT_1R",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

                elif exit_mode == "FIXED_2R":
                    tp = open_pos["entry_price"] + 2.0 * risk
                    if highs[i] >= tp:
                        raw_exit = max(tp, opens[i])
                        exit_price = raw_exit - slippage
                        r = (exit_price - open_pos["entry_price"]) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"MEDIAS_ALINHADAS_{exit_mode}",
                                direction="long",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="TAKE_PROFIT_2R",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

                elif exit_mode == "TRAILING_EMA9":
                    if closes[i - 1] < sma9[i - 1]:
                        exit_price = opens[i] - slippage
                        r = (exit_price - open_pos["entry_price"]) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"MEDIAS_ALINHADAS_{exit_mode}",
                                direction="long",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="EXIT_BELOW_SMA9",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

                elif exit_mode == "TRAILING_SMA20":
                    if closes[i - 1] < sma20[i - 1]:
                        exit_price = opens[i] - slippage
                        r = (exit_price - open_pos["entry_price"]) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"MEDIAS_ALINHADAS_{exit_mode}",
                                direction="long",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="EXIT_BELOW_SMA20",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

            else:  # short
                if highs[i] + spread >= open_pos["stop_price"]:
                    raw_exit = max(open_pos["stop_price"], opens[i] + spread)
                    exit_price = raw_exit + slippage
                    r = (open_pos["entry_price"] - exit_price) / risk
                    trades.append(
                        Trade(
                            symbol=symbol,
                            strategy=f"MEDIAS_ALINHADAS_{exit_mode}",
                            direction="short",
                            entry_time=open_pos["entry_time"],
                            exit_time=curr_time,
                            entry_price=open_pos["entry_price"],
                            stop_price=open_pos["stop_price"],
                            exit_price=exit_price,
                            exit_reason=open_pos["last_stop_reason"],
                            r_multiple=float(r),
                            win=bool(r > 0),
                            is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                        )
                    )
                    open_pos = None
                    continue

                if exit_mode == "FIXED_1R":
                    tp = open_pos["entry_price"] - 1.0 * risk
                    if lows[i] <= tp:
                        raw_exit = min(tp, opens[i])
                        exit_price = raw_exit + slippage
                        r = (open_pos["entry_price"] - exit_price) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"MEDIAS_ALINHADAS_{exit_mode}",
                                direction="short",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="TAKE_PROFIT_1R",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

                elif exit_mode == "FIXED_2R":
                    tp = open_pos["entry_price"] - 2.0 * risk
                    if lows[i] <= tp:
                        raw_exit = min(tp, opens[i])
                        exit_price = raw_exit + slippage
                        r = (open_pos["entry_price"] - exit_price) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"MEDIAS_ALINHADAS_{exit_mode}",
                                direction="short",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="TAKE_PROFIT_2R",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

                elif exit_mode == "TRAILING_EMA9":
                    if closes[i - 1] > sma9[i - 1]:
                        exit_price = opens[i] + spread + slippage
                        r = (open_pos["entry_price"] - exit_price) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"MEDIAS_ALINHADAS_{exit_mode}",
                                direction="short",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="EXIT_ABOVE_SMA9",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

                elif exit_mode == "TRAILING_SMA20":
                    if closes[i - 1] > sma20[i - 1]:
                        exit_price = opens[i] + spread + slippage
                        r = (open_pos["entry_price"] - exit_price) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"MEDIAS_ALINHADAS_{exit_mode}",
                                direction="short",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="EXIT_ABOVE_SMA20",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

        # Novo sinal de entrada
        if open_pos is None:
            # 1. Alinhamento de Médias em i-1:
            # Tendência de Alta: Preço > MME 80 > MMA 200 E MMA 9 > MMA 20 > MME 80
            bullish_alignment = (
                (closes[i - 1] > ema80[i - 1])
                and (ema80[i - 1] > sma200[i - 1])
                and (sma9[i - 1] > sma20[i - 1])
                and (sma20[i - 1] > ema80[i - 1])
            )
            # Tendência de Baixa: Preço < MME 80 < MMA 200 E MMA 9 < MMA 20 < MME 80
            bearish_alignment = (
                (closes[i - 1] < ema80[i - 1])
                and (ema80[i - 1] < sma200[i - 1])
                and (sma9[i - 1] < sma20[i - 1])
                and (sma20[i - 1] < ema80[i - 1])
            )

            # 2. Recuo / Setup de Pivô em i-1:
            # Compra: barra i-1 recua tocando na MMA 20 ou MMA 9 (low <= sma20 ou low <= sma9) mas fecha acima da MMA 20
            long_setup = (
                bullish_alignment
                and (lows[i - 1] <= max(sma20[i - 1], sma9[i - 1]))
                and (closes[i - 1] >= sma20[i - 1])
            )

            # Venda: barra i-1 repica tocando na MMA 20 ou MMA 9 mas fecha abaixo da MMA 20
            short_setup = (
                bearish_alignment
                and (highs[i - 1] >= min(sma20[i - 1], sma9[i - 1]))
                and (closes[i - 1] <= sma20[i - 1])
            )

            if long_setup:
                # Gatilho de compra: rompimento da máxima de i-1
                trigger_price = highs[i - 1]
                long_sl = min(lows[i - 1], lows[i - 2]) - slippage

                # Execução stop dentro da barra i
                if highs[i] + spread >= trigger_price:
                    # Preço de entrada
                    fill_price = max(trigger_price, opens[i]) + spread + slippage
                    risk = fill_price - long_sl
                    if risk > 0:
                        # Checagem imediata de stop intrabar na barra de entrada i
                        if lows[i] <= long_sl:
                            raw_exit = min(long_sl, opens[i])
                            exit_price = raw_exit - slippage
                            r = (exit_price - fill_price) / risk
                            trades.append(
                                Trade(
                                    symbol=symbol,
                                    strategy=f"MEDIAS_ALINHADAS_{exit_mode}",
                                    direction="long",
                                    entry_time=curr_time,
                                    exit_time=curr_time,
                                    entry_price=fill_price,
                                    stop_price=long_sl,
                                    exit_price=exit_price,
                                    exit_reason="STOP_ENTRY_BAR",
                                    r_multiple=float(r),
                                    win=bool(r > 0),
                                    is_oos=bool(curr_time >= OOS_SPLIT_DATE),
                                )
                            )
                        else:
                            open_pos = {
                                "direction": "long",
                                "entry_time": curr_time,
                                "entry_price": fill_price,
                                "stop_price": long_sl,
                                "initial_risk": risk,
                                "last_stop_reason": "INITIAL_STOP_LOSS",
                            }

            elif short_setup:
                trigger_price = lows[i - 1]
                short_sl = max(highs[i - 1], highs[i - 2]) + spread + slippage

                if lows[i] <= trigger_price:
                    fill_price = min(trigger_price, opens[i]) - slippage
                    risk = short_sl - fill_price
                    if risk > 0:
                        if highs[i] + spread >= short_sl:
                            raw_exit = max(short_sl, opens[i] + spread)
                            exit_price = raw_exit + slippage
                            r = (fill_price - exit_price) / risk
                            trades.append(
                                Trade(
                                    symbol=symbol,
                                    strategy=f"MEDIAS_ALINHADAS_{exit_mode}",
                                    direction="short",
                                    entry_time=curr_time,
                                    exit_time=curr_time,
                                    entry_price=fill_price,
                                    stop_price=short_sl,
                                    exit_price=exit_price,
                                    exit_reason="STOP_ENTRY_BAR",
                                    r_multiple=float(r),
                                    win=bool(r > 0),
                                    is_oos=bool(curr_time >= OOS_SPLIT_DATE),
                                )
                            )
                        else:
                            open_pos = {
                                "direction": "short",
                                "entry_time": curr_time,
                                "entry_price": fill_price,
                                "stop_price": short_sl,
                                "initial_risk": risk,
                                "last_stop_reason": "INITIAL_STOP_LOSS",
                            }

    return trades


def run_full_suite():
    print("=" * 115)
    print("AVALIAÇÃO EMPÍRICA RIGOROSA: CONDUÇÃO NO POI (50-79%) E PIVÔ COM MÉDIAS ALINHADAS (9/20/80/200)")
    print("=" * 115)

    # ---------------------------------------------------------
    # PARTE 1: POI (50-79%) COM MODOS DE CONDUÇÃO
    # ---------------------------------------------------------
    print("\n" + "#" * 115)
    print("PARTE 1: POI MACRO H1 (50% A 79% FIBONACCI) + CHOCH MICRO M15 + MME 20")
    print("#" * 115)

    poi_modes = ["FIXED_1R", "TRAILING_EMA20", "TRAILING_EMA9", "BAR_BY_BAR"]

    for mode in poi_modes:
        print(f"\n>>> MODO DE CONDUÇÃO POI: {mode}")
        print("-" * 115)
        all_trades = []
        for sym in SYMBOLS:
            p = Path(f"data/{sym}_M1_dukascopy.parquet")
            if not p.exists():
                continue
            df_m1 = pd.read_parquet(p)
            df_h1 = df_m1.resample("1h").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
            df_m15 = df_m1.resample("15min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()

            tr = simulate_poi_conducao(df_h1, df_m15, sym, SPREADS[sym], SLIPPAGES[sym], exit_mode=mode)
            st = calc_stats(tr)
            all_trades.extend(tr)
            print(
                f"{sym:6s} | Trades={st['n']:3d} (C:{st['longs']:2d} V:{st['shorts']:2d}) | "
                f"TotalR={st['total_r']:+6.1f}R | R/trade={st['mean_r']:+0.2f}±{st['se_r']:0.2f} (t={st['t_stat']:4.2f}) | "
                f"PF={st['pf']:4.2f} | WR={st['wr']:4.1f}% | AvgWin={st['avg_win']:4.1f}R | AvgLoss={st['avg_loss']:4.1f}R | MaxDD={st['max_dd']:4.1f}R"
            )

        st_all = calc_stats(all_trades)
        print(f"\n[CONSOLIDADO CARTEIRA - POI {mode}]")
        print(
            f"Trades: {st_all['n']} (C:{st_all['longs']} V:{st_all['shorts']}) | Total R: {st_all['total_r']:+.1f}R | "
            f"R/trade: {st_all['mean_r']:+.3f} ± {st_all['se_r']:.3f} | t-stat: {st_all['t_stat']:.2f} | PF: {st_all['pf']:.2f} | WR: {st_all['wr']:.1f}% | MaxDD: {st_all['max_dd']:.1f}R"
        )

    # ---------------------------------------------------------
    # PARTE 2: PIVÔ DE MÉDIAS ALINHADAS (MMA 9/20 + MME 80 + MMA 200)
    # ---------------------------------------------------------
    print("\n" + "#" * 115)
    print("PARTE 2: PIVÔ CLÁSSICO DE MÉDIAS ALINHADAS (M15: MMA 9 > MMA 20 > MME 80 > MMA 200)")
    print("#" * 115)

    medias_modes = ["FIXED_1R", "FIXED_2R", "TRAILING_SMA20", "TRAILING_EMA9"]

    for mode in medias_modes:
        print(f"\n>>> MODO DE SAÍDA MÉDIAS ALINHADAS: {mode}")
        print("-" * 115)
        all_trades_med = []
        for sym in SYMBOLS:
            p = Path(f"data/{sym}_M1_dukascopy.parquet")
            if not p.exists():
                continue
            df_m1 = pd.read_parquet(p)
            df_m15 = df_m1.resample("15min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()

            tr = simulate_pivo_medias_alinhadas(df_m15, sym, SPREADS[sym], SLIPPAGES[sym], exit_mode=mode)
            st = calc_stats(tr)
            all_trades_med.extend(tr)
            print(
                f"{sym:6s} | Trades={st['n']:3d} (C:{st['longs']:2d} V:{st['shorts']:2d}) | "
                f"TotalR={st['total_r']:+6.1f}R | R/trade={st['mean_r']:+0.2f}±{st['se_r']:0.2f} (t={st['t_stat']:4.2f}) | "
                f"PF={st['pf']:4.2f} | WR={st['wr']:4.1f}% | AvgWin={st['avg_win']:4.1f}R | AvgLoss={st['avg_loss']:4.1f}R | MaxDD={st['max_dd']:4.1f}R"
            )

        st_med = calc_stats(all_trades_med)
        print(f"\n[CONSOLIDADO CARTEIRA - MÉDIAS ALINHADAS {mode}]")
        print(
            f"Trades: {st_med['n']} (C:{st_med['longs']} V:{st_med['shorts']}) | Total R: {st_med['total_r']:+.1f}R | "
            f"R/trade: {st_med['mean_r']:+.3f} ± {st_med['se_r']:.3f} | t-stat: {st_med['t_stat']:.2f} | PF: {st_med['pf']:.2f} | WR: {st_med['wr']:.1f}% | MaxDD: {st_med['max_dd']:.1f}R"
        )


if __name__ == "__main__":
    run_full_suite()

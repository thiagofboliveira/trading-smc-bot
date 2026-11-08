"""Estudo Comparativo Completo de Timeframe no Forex: M5 vs M10 vs M15.

Avalia:
1. Modelo Oficial: SMC Fibo Rejeição EMA80 Pavio + Indução (Alvo 4R, Trava 1.618R, Stop 0.886)
2. Modelo FVOB/OB Projeção: Alinhamento EMA80+SMA200 + Indução + Alvo Projeção 1.618 (Stop 0.800 e 0.886)
3. Modelo FVOB/OB 3R: Alinhamento EMA80+SMA200 + Indução + Alvo 3.0R fixo (Stop 0.886 e 1.000)
"""
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

FOREX_SYMBOLS = ["EURUSD", "GBPUSD"]
SPREADS = {
    "EURUSD": 0.00008,
    "GBPUSD": 0.00010,
}

@dataclass
class Trade:
    symbol: str
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    exit_price: float
    exit_reason: str
    r_multiple: float
    win: bool

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["ema8"] = d["close"].ewm(span=8, adjust=False).mean()
    d["ema80"] = d["close"].ewm(span=80, adjust=False).mean()
    d["sma200"] = d["close"].rolling(window=200).mean()
    return d

def run_fibo_pavio(symbol: str, df_tf: pd.DataFrame, spread: float) -> list[Trade]:
    n = len(df_tf)
    if n < 100:
        return []

    opens, highs, lows, closes = df_tf["open"].to_numpy(), df_tf["high"].to_numpy(), df_tf["low"].to_numpy(), df_tf["close"].to_numpy()
    ts, ema80 = df_tf.index, df_tf["ema80"].to_numpy()

    k = 2
    swing_highs = []
    swing_lows = []
    for i in range(k, n - k):
        if np.all(highs[i] >= highs[i - k : i]) and np.all(highs[i] >= highs[i + 1 : i + k + 1]):
            swing_highs.append((i, highs[i]))
        if np.all(lows[i] <= lows[i - k : i]) and np.all(lows[i] <= lows[i + 1 : i + k + 1]):
            swing_lows.append((i, lows[i]))

    highs_by_conf = {idx + k: (idx, p) for idx, p in swing_highs}
    lows_by_conf = {idx + k: (idx, p) for idx, p in swing_lows}

    trades = []
    active_leg = None
    open_pos = None
    last_high = None
    last_low = None

    for i in range(80, n):
        if i in highs_by_conf:
            last_high = highs_by_conf[i]
        if i in lows_by_conf:
            last_low = lows_by_conf[i]

        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_tp = False
            hit_sl = False

            if not pos["locked"]:
                if d == 1 and highs[i] >= pos["entry_price"] + 1.618 * pos["initial_risk"]:
                    pos["stop_price"] = pos["entry_price"] + 1.0 * pos["initial_risk"]
                    pos["locked"] = True
                elif d == -1 and (lows[i] + spread) <= pos["entry_price"] - 1.618 * pos["initial_risk"]:
                    pos["stop_price"] = pos["entry_price"] - 1.0 * pos["initial_risk"]
                    pos["locked"] = True

            if d == 1:
                if lows[i] <= pos["stop_price"]:
                    hit_sl = True
                if highs[i] >= pos["target_price"]:
                    hit_tp = True
            else:
                if highs[i] + spread >= pos["stop_price"]:
                    hit_sl = True
                if lows[i] + spread <= pos["target_price"]:
                    hit_tp = True

            if hit_sl and hit_tp:
                hit_sl = True
                hit_tp = False

            if hit_sl:
                exit_price = pos["stop_price"]
                r = (exit_price - pos["entry_price"]) / pos["initial_risk"] if d == 1 else (pos["entry_price"] - exit_price) / pos["initial_risk"]
                trades.append(Trade(
                    symbol=symbol,
                    direction=pos["direction"],
                    entry_time=pos["entry_time"],
                    exit_time=ts[i],
                    entry_price=pos["entry_price"],
                    stop_price=pos["stop_price"],
                    target_price=pos["target_price"],
                    exit_price=exit_price,
                    exit_reason="STOP_LOSS" if r <= 0 else "PROFIT_LOCK",
                    r_multiple=r,
                    win=r > 0,
                ))
                open_pos = None
                active_leg = None
                continue
            elif hit_tp:
                trades.append(Trade(
                    symbol=symbol,
                    direction=pos["direction"],
                    entry_time=pos["entry_time"],
                    exit_time=ts[i],
                    entry_price=pos["entry_price"],
                    stop_price=pos["stop_price"],
                    target_price=pos["target_price"],
                    exit_price=pos["target_price"],
                    exit_reason="TAKE_PROFIT",
                    r_multiple=4.0,
                    win=True,
                ))
                open_pos = None
                active_leg = None
                continue

        if last_high is not None and last_low is not None:
            if closes[i] > last_high[1] and closes[i - 1] <= last_high[1]:
                orig_idx, orig_p = last_low
                if i - orig_idx >= 3 and highs[i] > orig_p:
                    active_leg = {
                        "direction": "long",
                        "origin_idx": orig_idx,
                        "origin_price": orig_p,
                        "bos_idx": i,
                        "extreme_price": highs[i],
                        "extreme_idx": i,
                        "idm_pivots": [],
                    }

            if closes[i] < last_low[1] and closes[i - 1] >= last_low[1]:
                orig_idx, orig_p = last_high
                if i - orig_idx >= 3 and lows[i] < orig_p:
                    active_leg = {
                        "direction": "short",
                        "origin_idx": orig_idx,
                        "origin_price": orig_p,
                        "bos_idx": i,
                        "extreme_price": lows[i],
                        "extreme_idx": i,
                        "idm_pivots": [],
                    }

        if active_leg is not None and open_pos is None:
            leg = active_leg
            d = 1 if leg["direction"] == "long" else -1
            span = d * (leg["extreme_price"] - leg["origin_price"])
            if span <= 0:
                active_leg = None
                continue

            lvl_50 = leg["extreme_price"] - d * 0.50 * span
            if d == 1:
                if lows[i] > lvl_50 and highs[i] > leg["extreme_price"]:
                    leg["extreme_price"] = highs[i]
                    leg["extreme_idx"] = i
            else:
                if highs[i] < lvl_50 and lows[i] < leg["extreme_price"]:
                    leg["extreme_price"] = lows[i]
                    leg["extreme_idx"] = i

            span = d * (leg["extreme_price"] - leg["origin_price"])
            lvl_50 = leg["extreme_price"] - d * 0.50 * span
            lvl_79 = leg["extreme_price"] - d * 0.79 * span
            lvl_stop = leg["extreme_price"] - d * 0.886 * span

            if i > leg["extreme_idx"]:
                if d == 1 and lows[i] > lvl_50:
                    leg["idm_pivots"].append(lows[i])
                elif d == -1 and highs[i] < lvl_50:
                    leg["idm_pivots"].append(highs[i])

            if d == 1 and lows[i] <= lvl_stop:
                active_leg = None
                continue
            elif d == -1 and highs[i] >= lvl_stop:
                active_leg = None
                continue

            touch_zone = (lows[i] <= lvl_50 and highs[i] >= lvl_79) if d == 1 else (highs[i] >= lvl_50 and lows[i] <= lvl_79)
            touch_ema80 = (lows[i] <= ema80[i] <= highs[i])

            if touch_zone and touch_ema80 and i < n - 1:
                h_curr = ts[i].hour
                in_session = (7 <= h_curr < 18)

                if in_session and len(leg["idm_pivots"]) >= 1:
                    rng = highs[i] - lows[i]
                    if rng > 0:
                        rejection = False
                        if d == 1:
                            lower_wick = min(opens[i], closes[i]) - lows[i]
                            if lower_wick / rng >= 0.50 and closes[i] > ema80[i] and closes[i] > lvl_79:
                                rejection = True
                        else:
                            upper_wick = highs[i] - max(opens[i], closes[i])
                            if upper_wick / rng >= 0.50 and closes[i] < ema80[i] and closes[i] < lvl_79:
                                rejection = True

                        if rejection:
                            exec_price = opens[i + 1] + spread if d == 1 else opens[i + 1]
                            risk = abs(exec_price - lvl_stop)
                            if risk > 0:
                                target_price = exec_price + d * 4.0 * risk
                                open_pos = {
                                    "direction": leg["direction"],
                                    "entry_idx": i + 1,
                                    "entry_time": ts[i + 1],
                                    "entry_price": exec_price,
                                    "stop_price": lvl_stop,
                                    "target_price": target_price,
                                    "initial_risk": risk,
                                    "locked": False,
                                }
                                active_leg = None

    return trades

def run_fvob_proj(symbol: str, df_tf: pd.DataFrame, spread: float, stop_ratio: float = 0.886) -> list[Trade]:
    n = len(df_tf)
    if n < 200:
        return []

    opens, highs, lows, closes = df_tf["open"].to_numpy(), df_tf["high"].to_numpy(), df_tf["low"].to_numpy(), df_tf["close"].to_numpy()
    ts, ema80, sma200 = df_tf.index, df_tf["ema80"].to_numpy(), df_tf["sma200"].to_numpy()

    k = 2
    swing_highs = []
    swing_lows = []
    for i in range(k, n - k):
        if np.all(highs[i] >= highs[i - k : i]) and np.all(highs[i] >= highs[i + 1 : i + k + 1]):
            swing_highs.append((i, highs[i]))
        if np.all(lows[i] <= lows[i - k : i]) and np.all(lows[i] <= lows[i + 1 : i + k + 1]):
            swing_lows.append((i, lows[i]))

    highs_by_conf = {idx + k: (idx, p) for idx, p in swing_highs}
    lows_by_conf = {idx + k: (idx, p) for idx, p in swing_lows}

    trades = []
    active_leg = None
    open_pos = None
    last_high = None
    last_low = None

    for i in range(200, n):
        if i in highs_by_conf:
            last_high = highs_by_conf[i]
        if i in lows_by_conf:
            last_low = lows_by_conf[i]

        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_tp = False
            hit_sl = False

            if d == 1:
                if lows[i] <= pos["stop_price"]:
                    hit_sl = True
                if highs[i] >= pos["target_price"]:
                    hit_tp = True
            else:
                if highs[i] + spread >= pos["stop_price"]:
                    hit_sl = True
                if lows[i] + spread <= pos["target_price"]:
                    hit_tp = True

            if hit_sl and hit_tp:
                hit_sl = True
                hit_tp = False

            if hit_sl:
                exit_price = pos["stop_price"]
                r = -1.0
                trades.append(Trade(
                    symbol=symbol,
                    direction=pos["direction"],
                    entry_time=pos["entry_time"],
                    exit_time=ts[i],
                    entry_price=pos["entry_price"],
                    stop_price=pos["stop_price"],
                    target_price=pos["target_price"],
                    exit_price=exit_price,
                    exit_reason="STOP_LOSS",
                    r_multiple=r,
                    win=False,
                ))
                open_pos = None
                active_leg = None
                continue
            elif hit_tp:
                trades.append(Trade(
                    symbol=symbol,
                    direction=pos["direction"],
                    entry_time=pos["entry_time"],
                    exit_time=ts[i],
                    entry_price=pos["entry_price"],
                    stop_price=pos["stop_price"],
                    target_price=pos["target_price"],
                    exit_price=pos["target_price"],
                    exit_reason="TAKE_PROFIT",
                    r_multiple=pos["r_target"],
                    win=True,
                ))
                open_pos = None
                active_leg = None
                continue

        bullish_trend = (ema80[i - 1] > sma200[i - 1]) and (closes[i - 1] > sma200[i - 1])
        bearish_trend = (ema80[i - 1] < sma200[i - 1]) and (closes[i - 1] < sma200[i - 1])

        if bullish_trend and last_high is not None and last_low is not None:
            if closes[i] > last_high[1] and closes[i - 1] <= last_high[1]:
                orig_idx, orig_p = last_low
                if i - orig_idx >= 3 and highs[i] > orig_p:
                    active_leg = {
                        "direction": "long",
                        "origin_idx": orig_idx,
                        "origin_price": orig_p,
                        "bos_idx": i,
                        "extreme_price": highs[i],
                        "extreme_idx": i,
                        "impulse_candles": i - orig_idx,
                        "idm_pivots": [],
                    }

        if bearish_trend and last_low is not None and last_high is not None:
            if closes[i] < last_low[1] and closes[i - 1] >= last_low[1]:
                orig_idx, orig_p = last_high
                if i - orig_idx >= 3 and lows[i] < orig_p:
                    active_leg = {
                        "direction": "short",
                        "origin_idx": orig_idx,
                        "origin_price": orig_p,
                        "bos_idx": i,
                        "extreme_price": lows[i],
                        "extreme_idx": i,
                        "impulse_candles": i - orig_idx,
                        "idm_pivots": [],
                    }

        if active_leg is not None and open_pos is None:
            leg = active_leg
            d = 1 if leg["direction"] == "long" else -1
            span = d * (leg["extreme_price"] - leg["origin_price"])
            if span <= 0:
                active_leg = None
                continue

            lvl_50 = leg["extreme_price"] - d * 0.50 * span
            if d == 1:
                if lows[i] > lvl_50 and highs[i] > leg["extreme_price"]:
                    leg["extreme_price"] = highs[i]
                    leg["extreme_idx"] = i
                    leg["impulse_candles"] = i - leg["origin_idx"]
            else:
                if highs[i] < lvl_50 and lows[i] < leg["extreme_price"]:
                    leg["extreme_price"] = lows[i]
                    leg["extreme_idx"] = i
                    leg["impulse_candles"] = i - leg["origin_idx"]

            span = d * (leg["extreme_price"] - leg["origin_price"])
            lvl_618 = leg["extreme_price"] - d * 0.618 * span
            lvl_790 = leg["extreme_price"] - d * 0.790 * span
            lvl_stop = leg["extreme_price"] - d * stop_ratio * span

            if i > leg["extreme_idx"]:
                if d == 1 and lows[i] > lvl_50:
                    leg["idm_pivots"].append(lows[i])
                elif d == -1 and highs[i] < lvl_50:
                    leg["idm_pivots"].append(highs[i])

            if d == 1 and lows[i] <= lvl_stop:
                active_leg = None
                continue
            elif d == -1 and highs[i] >= lvl_stop:
                active_leg = None
                continue

            touch_zone = (lows[i] <= lvl_618 and highs[i] >= lvl_790) if d == 1 else (highs[i] >= lvl_618 and lows[i] <= lvl_790)

            if touch_zone and i < n - 1:
                h_curr = ts[i].hour
                in_session = (7 <= h_curr < 18)

                if in_session:
                    ret_candles = i - leg["extreme_idx"]
                    criterio_a = ret_candles >= leg["impulse_candles"]
                    criterio_b = len(leg["idm_pivots"]) >= 1

                    if criterio_a or criterio_b:
                        rng = highs[i] - lows[i]
                        if rng > 0:
                            rejection_ok = False
                            if d == 1:
                                lower_wick = min(opens[i], closes[i]) - lows[i]
                                if lower_wick / rng >= 0.40 and closes[i] > lvl_790:
                                    rejection_ok = True
                            else:
                                upper_wick = highs[i] - max(opens[i], closes[i])
                                if upper_wick / rng >= 0.40 and closes[i] < lvl_790:
                                    rejection_ok = True

                            if rejection_ok:
                                exec_price = opens[i + 1] + spread if d == 1 else opens[i + 1]
                                risk = abs(exec_price - lvl_stop)
                                if risk > 0:
                                    target_price = leg["extreme_price"] + d * 0.618 * span
                                    reward = abs(target_price - exec_price)
                                    r_target = reward / risk

                                    open_pos = {
                                        "direction": leg["direction"],
                                        "entry_idx": i + 1,
                                        "entry_time": ts[i + 1],
                                        "entry_price": exec_price,
                                        "stop_price": lvl_stop,
                                        "target_price": target_price,
                                        "initial_risk": risk,
                                        "r_target": r_target,
                                        "locked": False,
                                    }
                                    active_leg = None

    return trades

def run_study():
    timeframes = ["5min", "10min", "15min"]

    print("=" * 86)
    print("  ESTUDO DE TIMEFRAME NO FOREX: M5 vs M10 vs M15")
    print("=" * 86)

    print("\n--- MODELO 1: SMC Fibo Rejeição EMA80 Pavio + Indução (Alvo 4R, Trava 1.618R, Stop 0.886) ---")
    print(f"{'Ativo':8s} | {'TF':6s} | {'Trades':>6s} | {'R Total':>8s} | {'Acerto %':>8s} | {'PF':>5s} | {'R/tr ± EP':>16s} | {'IS':>8s} | {'OOS':>8s}")
    print("-" * 86)

    for sym in FOREX_SYMBOLS:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        df_m1 = pd.read_parquet(p)
        spread = SPREADS[sym]

        for tf in timeframes:
            df_tf = df_m1.resample(tf).agg({
                "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
            }).dropna()
            df_tf = compute_indicators(df_tf)

            trades = run_fibo_pavio(sym, df_tf, spread)
            n = len(trades)
            tf_label = "M5" if tf == "5min" else ("M10" if tf == "10min" else "M15")
            if n > 0:
                r_vals = [t.r_multiple for t in trades]
                r_tot = sum(r_vals)
                wins = sum(1 for t in trades if t.win)
                wr = 100.0 * wins / n
                gp = sum(r for r in r_vals if r > 0)
                gl = -sum(r for r in r_vals if r < 0)
                pf = gp / gl if gl > 0 else float("inf")
                r_tr = r_tot / n
                ep = np.std(r_vals) / np.sqrt(n) if n > 1 else 0.0

                split_dt = pd.Timestamp("2026-06-25", tz="UTC")
                is_r = sum(t.r_multiple for t in trades if t.entry_time < split_dt)
                oos_r = sum(t.r_multiple for t in trades if t.entry_time >= split_dt)
                print(f"{sym:8s} | {tf_label:6s} | {n:6d} | {r_tot:7.1f}R | {wr:7.1f}% | {pf:5.2f} | {r_tr:6.3f} ± {ep:5.3f} | {is_r:7.1f}R | {oos_r:7.1f}R")

    print("\n--- MODELO 2: FVOB / OB com Alvo em Projeção 1.618 e Alinhamento EMA80+SMA200 ---")
    print(f"{'Ativo':8s} | {'TF':6s} | {'Trades':>6s} | {'R Total':>8s} | {'Acerto %':>8s} | {'PF':>5s} | {'R/tr ± EP':>16s} | {'IS':>8s} | {'OOS':>8s}")
    print("-" * 86)

    for sym in FOREX_SYMBOLS:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        df_m1 = pd.read_parquet(p)
        spread = SPREADS[sym]

        for tf in timeframes:
            df_tf = df_m1.resample(tf).agg({
                "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
            }).dropna()
            df_tf = compute_indicators(df_tf)

            trades = run_fvob_proj(sym, df_tf, spread, stop_ratio=0.886)
            n = len(trades)
            tf_label = "M5" if tf == "5min" else ("M10" if tf == "10min" else "M15")
            if n > 0:
                r_vals = [t.r_multiple for t in trades]
                r_tot = sum(r_vals)
                wins = sum(1 for t in trades if t.win)
                wr = 100.0 * wins / n
                gp = sum(r for r in r_vals if r > 0)
                gl = -sum(r for r in r_vals if r < 0)
                pf = gp / gl if gl > 0 else float("inf")
                r_tr = r_tot / n
                ep = np.std(r_vals) / np.sqrt(n) if n > 1 else 0.0

                split_dt = pd.Timestamp("2026-06-25", tz="UTC")
                is_r = sum(t.r_multiple for t in trades if t.entry_time < split_dt)
                oos_r = sum(t.r_multiple for t in trades if t.entry_time >= split_dt)
                print(f"{sym:8s} | {tf_label:6s} | {n:6d} | {r_tot:7.1f}R | {wr:7.1f}% | {pf:5.2f} | {r_tr:6.3f} ± {ep:5.3f} | {is_r:7.1f}R | {oos_r:7.1f}R")

if __name__ == "__main__":
    run_study()

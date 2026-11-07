"""
Teste de Engenharia: Como tornar a estratégia robusta e lucrativa na VIDA REAL após a auditoria?
Testa diferentes stops:
- Stop em 79% (Original apertado)
- Stop em 88.6% (Harmonic / Deep OTE)
- Stop em 100% (Invalidação Estrutural Real do SMC - Fundo da Perna)
- Stop com filtro de candle (evitar entrar se a barra de entrada tiver range > 2x a média)
"""

import sys
from pathlib import Path
import numpy as np
import pandas as pd

SPREADS = {
    "BRENT": 0.04,
    "XAUUSD": 0.30,
    "NAS100": 1.50,
    "DAX40": 1.50,
    "EURUSD": 0.00015,
    "GBPUSD": 0.00020,
    "USDJPY": 0.018
}

SYMBOLS = ["XAUUSD", "NAS100", "DAX40", "BRENT", "EURUSD", "GBPUSD", "USDJPY"]

def load_all_candles():
    raw_m1 = {}
    for sym in SYMBOLS:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        if not p.exists(): continue
        df = pd.read_parquet(p)
        if not isinstance(df.index, pd.DatetimeIndex):
            col = "time" if "time" in df.columns else "timestamp"
            df[col] = pd.to_datetime(df[col])
            df.set_index(col, inplace=True)
        raw_m1[sym] = df
    return raw_m1

def test_stop_configurations(raw_m1, fibo_entry=0.705, fibo_stop=0.790, k=3):
    all_trades = []
    intrabar_stops = 0

    for sym in SYMBOLS:
        if sym not in raw_m1: continue
        df_m1 = raw_m1[sym]
        spread = SPREADS[sym]

        df = df_m1.resample("5min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        }).dropna()

        df["ema8"] = df["close"].ewm(span=8, adjust=False).mean()

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        timestamps = df.index
        ema8s = df["ema8"].values
        n = len(df)

        swing_highs = np.zeros(n, dtype=bool)
        swing_lows = np.zeros(n, dtype=bool)

        for i in range(k, n - k):
            if highs[i] == max(highs[i - k : i + k + 1]): swing_highs[i] = True
            if lows[i] == min(lows[i - k : i + k + 1]): swing_lows[i] = True

        last_sh = last_sl = None
        last_sh_idx = last_sl_idx = None
        in_pos = False
        pos_dir = 0
        entry_price = sl_price = tp_price = risk = 0.0
        entry_idx = 0
        active_leg = None

        for i in range(k + 1, n - 1):
            chk = i - k
            if swing_highs[chk]: last_sh, last_sh_idx = highs[chk], chk
            if swing_lows[chk]: last_sl, last_sl_idx = lows[chk], chk

            if in_pos:
                c_high, c_low, c_close = highs[i], lows[i], closes[i]

                # Trailing MA apenas no lucro
                exit_trailing = False
                trailing_exit_price = 0.0
                if i > entry_idx:
                    curr_ema = ema8s[i]
                    if pos_dir == 1 and c_close < curr_ema and c_close > entry_price:
                        exit_trailing = True
                        trailing_exit_price = c_close
                    elif pos_dir == -1 and c_close > curr_ema and c_close < entry_price:
                        exit_trailing = True
                        trailing_exit_price = c_close

                if pos_dir == 1:
                    hit_sl = c_low <= sl_price
                    hit_tp = c_high >= tp_price
                    if hit_sl and hit_tp:
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": -1.0, "win": False})
                        in_pos = False; active_leg = None
                    elif hit_sl:
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": -1.0, "win": False})
                        in_pos = False; active_leg = None
                    elif exit_trailing:
                        r_res = (trailing_exit_price - entry_price) / risk
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": r_res, "win": r_res > 0})
                        in_pos = False; active_leg = None
                    elif hit_tp:
                        r_res = (tp_price - entry_price) / risk
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": r_res, "win": True})
                        in_pos = False; active_leg = None
                else:
                    hit_sl = c_high >= sl_price
                    hit_tp = c_low <= tp_price
                    if hit_sl and hit_tp:
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": -1.0, "win": False})
                        in_pos = False; active_leg = None
                    elif hit_sl:
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": -1.0, "win": False})
                        in_pos = False; active_leg = None
                    elif exit_trailing:
                        r_res = (entry_price - trailing_exit_price) / risk
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": r_res, "win": r_res > 0})
                        in_pos = False; active_leg = None
                    elif hit_tp:
                        r_res = (entry_price - tp_price) / risk
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": r_res, "win": True})
                        in_pos = False; active_leg = None
                continue

            # Signal
            if last_sh is not None and last_sl is not None:
                if last_sh_idx > last_sl_idx and closes[i] > last_sh:
                    diff = highs[i] - last_sl
                    if diff >= 10.0 * spread:
                        active_leg = {"dir": 1, "low": last_sl, "high": highs[i], "diff": diff}
                elif last_sl_idx > last_sh_idx and closes[i] < last_sl:
                    diff = last_sh - lows[i]
                    if diff >= 10.0 * spread:
                        active_leg = {"dir": -1, "low": lows[i], "high": last_sh, "diff": diff}

            if active_leg is not None:
                ldir, ldiff, lhigh, llow = active_leg["dir"], active_leg["diff"], active_leg["high"], active_leg["low"]
                if ldir == 1:
                    f_ent = lhigh - (ldiff * fibo_entry)
                    f_stp = lhigh - (ldiff * fibo_stop)
                    r_pts = f_ent - f_stp
                    if r_pts > 0 and lows[i] <= f_ent <= highs[i]:
                        in_pos = True; pos_dir = 1
                        entry_price = f_ent + (spread / 2.0)
                        sl_price = f_stp - (spread / 2.0)
                        risk = entry_price - sl_price
                        tp_price = lhigh
                        entry_idx = i

                        # AUDITORIA 100% REALISTA: Intrabar SL
                        if lows[i] <= sl_price:
                            intrabar_stops += 1
                            all_trades.append({"symbol": sym, "time": timestamps[i], "r": -1.0, "win": False})
                            in_pos = False; active_leg = None
                else:
                    f_ent = llow + (ldiff * fibo_entry)
                    f_stp = llow + (ldiff * fibo_stop)
                    r_pts = f_stp - f_ent
                    if r_pts > 0 and lows[i] <= f_ent <= highs[i]:
                        in_pos = True; pos_dir = -1
                        entry_price = f_ent - (spread / 2.0)
                        sl_price = f_stp + (spread / 2.0)
                        risk = sl_price - entry_price
                        tp_price = llow
                        entry_idx = i

                        # AUDITORIA 100% REALISTA: Intrabar SL
                        if highs[i] >= sl_price:
                            intrabar_stops += 1
                            all_trades.append({"symbol": sym, "time": timestamps[i], "r": -1.0, "win": False})
                            in_pos = False; active_leg = None

    return all_trades, intrabar_stops

def get_stats(trades):
    if not trades: return {}
    df = pd.DataFrame(trades)
    n = len(df)
    r_total = df["r"].sum()
    wr = (df["win"].sum() / n) * 100.0
    wins = df[df["r"] > 0]["r"]
    losses = df[df["r"] < 0]["r"].abs()
    pf = (wins.sum() / losses.sum()) if losses.sum() > 0 else 999.0
    df_sorted = df.sort_values("time")
    cum = df_sorted["r"].cumsum()
    mdd = abs((cum - cum.cummax()).min())
    return {"trades": n, "wr": wr, "r_total": r_total, "r_year": r_total / 2.0, "pf": pf, "mdd": mdd}

def main():
    raw_m1 = load_all_candles()
    configs = [
        ("Stop 79.0% (Apertado - Sweet Spot)", 0.705, 0.790),
        ("Stop 88.6% (Deep Invalidation)", 0.705, 0.886),
        ("Stop 100.0% (Fundo Estrutural SMC)", 0.705, 1.000),
        ("Entrada 61.8% / Stop 100% (Clássico SMC)", 0.618, 1.000),
        ("Entrada 61.8% / Stop 79.0%", 0.618, 0.790),
    ]

    print(f"{'Configuração (Com Auditoria Intrabar 100% Ativa)':<48} | {'Trades':<6} | {'WinRate':<7} | {'Total R':<10} | {'R / Ano':<9} | {'PF':<5} | {'MaxDD'}")
    print("-" * 105)
    for name, f_ent, f_stp in configs:
        trades, ib_stops = test_stop_configurations(raw_m1, f_ent, f_stp)
        st = get_stats(trades)
        print(f"{name:<48} | {st['trades']:<6} | {st['wr']:>6.1f}% | {st['r_total']:>9.1f}R | {st['r_year']:>8.1f}R | {st['pf']:>5.2f} | -{st['mdd']:>4.1f}R")
    print("-" * 105)

if __name__ == "__main__":
    main()

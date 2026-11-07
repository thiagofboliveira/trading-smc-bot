"""
Cálculo comparativo de métricas completas: 1 Ano vs 2 Anos
Compara:
- smc_fibo_trailing_44pct_2500R_2.23pf_32dd
- smc_fibo_blindado_50pct_2278R_2.24pf_30dd
Métricas: Win Rate, Max Drawdown, Profit Factor, Expectativa (R/trade), Payoff
"""

import sys
from pathlib import Path
from typing import Any
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
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if not isinstance(df.index, pd.DatetimeIndex):
            col = "time" if "time" in df.columns else "timestamp"
            df[col] = pd.to_datetime(df[col])
            df.set_index(col, inplace=True)
        raw_m1[sym] = df
    return raw_m1

def run_sim(raw_m1, trailing_ma="ema8", be_trigger_r=None, be_lock_r=0.0, fibo_entry=0.705, fibo_stop=0.790, k=3):
    all_trades = []
    for sym in SYMBOLS:
        if sym not in raw_m1:
            continue
        df_m1 = raw_m1[sym]
        spread = SPREADS[sym]

        df = df_m1.resample("5min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        }).dropna()

        if trailing_ma == "ema8":
            df["ema8"] = df["close"].ewm(span=8, adjust=False).mean()

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        timestamps = df.index
        ema8s = df["ema8"].values if trailing_ma == "ema8" else None
        n = len(df)

        swing_highs = np.zeros(n, dtype=bool)
        swing_lows = np.zeros(n, dtype=bool)

        for i in range(k, n - k):
            if highs[i] == max(highs[i - k : i + k + 1]):
                swing_highs[i] = True
            if lows[i] == min(lows[i - k : i + k + 1]):
                swing_lows[i] = True

        last_sh = last_sl = None
        last_sh_idx = last_sl_idx = None
        in_pos = False
        pos_dir = 0
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0
        risk = 0.0
        entry_idx = 0
        be_activated = False
        active_leg = None

        for i in range(k + 1, n - 1):
            chk = i - k
            if swing_highs[chk]: last_sh, last_sh_idx = highs[chk], chk
            if swing_lows[chk]: last_sl, last_sl_idx = lows[chk], chk

            if in_pos:
                c_high = highs[i]
                c_low = lows[i]
                c_close = closes[i]

                # Breakeven / Lock
                if be_trigger_r is not None and not be_activated:
                    if pos_dir == 1:
                        fav = c_high - entry_price
                        if fav >= (risk * be_trigger_r):
                            sl_price = entry_price + (risk * be_lock_r)
                            be_activated = True
                    else:
                        fav = entry_price - c_low
                        if fav >= (risk * be_trigger_r):
                            sl_price = entry_price - (risk * be_lock_r)
                            be_activated = True

                # Trailing MA
                exit_trailing = False
                trailing_exit_price = 0.0
                if trailing_ma == "ema8" and i > entry_idx:
                    curr_ema = ema8s[i]
                    if pos_dir == 1 and c_close < curr_ema:
                        exit_trailing = True
                        trailing_exit_price = c_close
                    elif pos_dir == -1 and c_close > curr_ema:
                        exit_trailing = True
                        trailing_exit_price = c_close

                # Outcome
                if pos_dir == 1:
                    hit_sl = c_low <= sl_price
                    hit_tp = c_high >= tp_price
                    if hit_sl and hit_tp:
                        r_res = -1.0 if not be_activated else be_lock_r
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": r_res, "win": r_res > 0})
                        in_pos = False; active_leg = None
                    elif hit_sl:
                        r_res = -1.0 if not be_activated else be_lock_r
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": r_res, "win": r_res > 0})
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
                        r_res = -1.0 if not be_activated else be_lock_r
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": r_res, "win": r_res > 0})
                        in_pos = False; active_leg = None
                    elif hit_sl:
                        r_res = -1.0 if not be_activated else be_lock_r
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": r_res, "win": r_res > 0})
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
                    leg_low = last_sl
                    leg_high = highs[i]
                    diff = leg_high - leg_low
                    if diff >= 10.0 * spread:
                        active_leg = {"dir": 1, "low": leg_low, "high": leg_high, "diff": diff}
                elif last_sl_idx > last_sh_idx and closes[i] < last_sl:
                    leg_high = last_sh
                    leg_low = lows[i]
                    diff = leg_high - leg_low
                    if diff >= 10.0 * spread:
                        active_leg = {"dir": -1, "low": leg_low, "high": leg_high, "diff": diff}

            if active_leg is not None:
                ldir = active_leg["dir"]
                ldiff = active_leg["diff"]
                lhigh = active_leg["high"]
                llow = active_leg["low"]

                if ldir == 1:
                    f_ent = lhigh - (ldiff * fibo_entry)
                    f_stp = lhigh - (ldiff * fibo_stop)
                    r_pts = f_ent - f_stp
                    if r_pts > 0 and lows[i] <= f_ent <= highs[i]:
                        in_pos = True
                        pos_dir = 1
                        entry_price = f_ent + (spread / 2.0)
                        sl_price = f_stp - (spread / 2.0)
                        risk = entry_price - sl_price
                        tp_price = lhigh
                        entry_idx = i
                        be_activated = False
                else:
                    f_ent = llow + (ldiff * fibo_entry)
                    f_stp = llow + (ldiff * fibo_stop)
                    r_pts = f_stp - f_ent
                    if r_pts > 0 and lows[i] <= f_ent <= highs[i]:
                        in_pos = True
                        pos_dir = -1
                        entry_price = f_ent - (spread / 2.0)
                        sl_price = f_stp + (spread / 2.0)
                        risk = sl_price - entry_price
                        tp_price = llow
                        entry_idx = i
                        be_activated = False

    return all_trades

def calculate_detailed_metrics(trades: list[dict[str, Any]], name: str) -> dict[str, Any]:
    df = pd.DataFrame(trades)
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)
    
    total_trades = len(df)
    wins = df[df["win"]]
    losses = df[~df["win"]]
    
    wr = (len(wins) / total_trades) * 100 if total_trades > 0 else 0.0
    net_r = df["r"].sum()
    gross_win = wins["r"].sum()
    gross_loss = abs(losses["r"].sum())
    pf = gross_win / gross_loss if gross_loss > 0 else 99.0
    
    avg_win = wins["r"].mean() if len(wins) > 0 else 0.0
    avg_loss = abs(losses["r"].mean()) if len(losses) > 0 else 0.0
    payoff = avg_win / avg_loss if avg_loss > 0 else 0.0
    expectancy = df["r"].mean() if total_trades > 0 else 0.0
    
    # Portfolio equity curve and max drawdown
    df["equity"] = df["r"].cumsum()
    df["peak"] = df["equity"].cummax()
    df["drawdown"] = df["equity"] - df["peak"]
    max_dd = df["drawdown"].min()
    recovery_factor = net_r / abs(max_dd) if abs(max_dd) > 0 else 0.0

    return {
        "Estratégia": name,
        "Total Trades": total_trades,
        "Taxa Acerto (%)": round(wr, 1),
        "Retorno Total (R)": round(net_r, 1),
        "Profit Factor": round(pf, 2),
        "Max Drawdown (R)": round(max_dd, 1),
        "Expectativa (R/trade)": round(expectancy, 2),
        "Payoff (Ganho/Perda)": round(payoff, 2),
        "Fator Recuperação": round(recovery_factor, 1)
    }

def split_period_metrics(trades: list[dict[str, Any]], strat_name: str) -> pd.DataFrame:
    df = pd.DataFrame(trades)
    df["time"] = pd.to_datetime(df["time"])
    
    # Períodos
    t_split = pd.Timestamp("2025-11-01", tz="UTC")
    df_y1 = df[df["time"] < t_split]
    df_y2 = df[df["time"] >= t_split]
    
    m_y1 = calculate_detailed_metrics(df_y1.to_dict("records"), f"{strat_name} (Ano 1: 2024-2025)")
    m_y2 = calculate_detailed_metrics(df_y2.to_dict("records"), f"{strat_name} (Ano 2: 2025-2026)")
    m_all = calculate_detailed_metrics(df.to_dict("records"), f"{strat_name} (2 Anos: 2024-2026)")
    
    return pd.DataFrame([m_y1, m_y2, m_all])

def main():
    print("⏳ Carregando dados M1 dos 7 ativos...")
    raw = load_all_candles()
    print("✅ Dados carregados!\n")

    print("▶️ Simulando Trailing MME 8...")
    trades_tr = run_sim(raw, trailing_ma="ema8", be_trigger_r=None)
    
    print("▶️ Simulando Blindado (Trava 2:1)...")
    trades_bl = run_sim(raw, trailing_ma="ema8", be_trigger_r=2.0, be_lock_r=1.0)

    df_tr = split_period_metrics(trades_tr, "👑 Trailing")
    df_bl = split_period_metrics(trades_bl, "🛡️ Blindado")

    df_full = pd.concat([df_tr, df_bl], ignore_index=True)
    print("\n" + "=" * 110)
    print("📊 COMPARATIVO COMPLETO: ANO 1 vs ANO 2 vs CONSOLIDADO 2 ANOS")
    print("=" * 110)
    print(df_full.to_string(index=False))

    df_full.to_csv("reports/metrics_1y_vs_2y_comparison.csv", index=False)
    print("\n💾 Salvo em reports/metrics_1y_vs_2y_comparison.csv")

if __name__ == "__main__":
    main()

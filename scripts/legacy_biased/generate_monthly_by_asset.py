"""
Relatório Mensal das Duas Melhores Estratégias por Ativo (1 Ano Dukascopy)
Estratégias:
1. smc_fibo_trailing_44pct_2500R_2.23pf_32dd (Campeã Suprema)
2. smc_fibo_blindado_50pct_2278R_2.24pf_30dd (Blindado Trava 2:1)
Ativos: NAS100, XAUUSD, DAX40, BRENT, EURUSD, GBPUSD, USDJPY
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

def run_simulation(
    raw_m1: dict[str, pd.DataFrame],
    trailing_ma: str | None = "ema8",
    be_trigger_r: float | None = None,
    be_lock_r: float = 0.0,
    fibo_entry: float = 0.705,
    fibo_stop: float = 0.790,
    k: int = 3
) -> list[dict[str, Any]]:
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

                # 1. Profit Lock trigger
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

                # 2. Trailing MA exit
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

                # 3. Position outcome
                if pos_dir == 1:
                    hit_sl = c_low <= sl_price
                    hit_tp = c_high >= tp_price

                    if hit_sl and hit_tp:
                        r_res = -1.0 if not be_activated else be_lock_r
                        all_trades.append({
                            "symbol": sym, "time": timestamps[entry_idx], "r": r_res,
                            "win": r_res > 0
                        })
                        in_pos = False; active_leg = None
                    elif hit_sl:
                        r_res = -1.0 if not be_activated else be_lock_r
                        all_trades.append({
                            "symbol": sym, "time": timestamps[entry_idx], "r": r_res,
                            "win": r_res > 0
                        })
                        in_pos = False; active_leg = None
                    elif exit_trailing:
                        r_res = (trailing_exit_price - entry_price) / risk
                        all_trades.append({
                            "symbol": sym, "time": timestamps[entry_idx], "r": r_res,
                            "win": r_res > 0
                        })
                        in_pos = False; active_leg = None
                    elif hit_tp:
                        r_res = (tp_price - entry_price) / risk
                        all_trades.append({
                            "symbol": sym, "time": timestamps[entry_idx], "r": r_res,
                            "win": True
                        })
                        in_pos = False; active_leg = None
                else:
                    hit_sl = c_high >= sl_price
                    hit_tp = c_low <= tp_price

                    if hit_sl and hit_tp:
                        r_res = -1.0 if not be_activated else be_lock_r
                        all_trades.append({
                            "symbol": sym, "time": timestamps[entry_idx], "r": r_res,
                            "win": r_res > 0
                        })
                        in_pos = False; active_leg = None
                    elif hit_sl:
                        r_res = -1.0 if not be_activated else be_lock_r
                        all_trades.append({
                            "symbol": sym, "time": timestamps[entry_idx], "r": r_res,
                            "win": r_res > 0
                        })
                        in_pos = False; active_leg = None
                    elif exit_trailing:
                        r_res = (entry_price - trailing_exit_price) / risk
                        all_trades.append({
                            "symbol": sym, "time": timestamps[entry_idx], "r": r_res,
                            "win": r_res > 0
                        })
                        in_pos = False; active_leg = None
                    elif hit_tp:
                        r_res = (entry_price - tp_price) / risk
                        all_trades.append({
                            "symbol": sym, "time": timestamps[entry_idx], "r": r_res,
                            "win": True
                        })
                        in_pos = False; active_leg = None

                continue

            # BOS detection
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

def build_pivot_table(trades: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(trades)
    df["month"] = pd.to_datetime(df["time"]).dt.to_period("M").astype(str)
    
    # Pivot: Index = month, Columns = symbol, Values = sum(r)
    pivot_r = df.pivot_table(index="month", columns="symbol", values="r", aggfunc="sum", fill_value=0.0)
    
    # Ensure all symbols are present in specific order
    for sym in SYMBOLS:
        if sym not in pivot_r.columns:
            pivot_r[sym] = 0.0
    pivot_r = pivot_r[SYMBOLS]
    pivot_r["TOTAL_PORTFOLIO"] = pivot_r.sum(axis=1)
    
    # Format to 1 decimal place
    return pivot_r.round(1)

def build_wr_pivot_table(trades: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(trades)
    df["month"] = pd.to_datetime(df["time"]).dt.to_period("M").astype(str)
    
    def calc_wr_series(g):
        return round((g.sum() / len(g)) * 100, 1) if len(g) > 0 else 0.0
    
    pivot_wr = df.pivot_table(index="month", columns="symbol", values="win", aggfunc=calc_wr_series, fill_value=0.0)
    for sym in SYMBOLS:
        if sym not in pivot_wr.columns:
            pivot_wr[sym] = 0.0
    pivot_wr = pivot_wr[SYMBOLS]
    
    # Total portfolio WR per month
    month_total_wr = df.groupby("month")["win"].apply(calc_wr_series)
    pivot_wr["TOTAL_PORTFOLIO"] = month_total_wr
    return pivot_wr

def main():
    print("⏳ Carregando dados M1 dos 7 ativos...")
    raw_m1 = load_all_candles()
    print("✅ Dados carregados com sucesso!\n")

    # 1. Estratégia Campeã Suprema (Trailing MME 8, sem trava)
    print("▶️ Simulando 1. Campeã Suprema (Trailing MME 8)...")
    trades_trailing = run_simulation(raw_m1, trailing_ma="ema8", be_trigger_r=None)
    pivot_trailing_r = build_pivot_table(trades_trailing)
    pivot_trailing_wr = build_wr_pivot_table(trades_trailing)

    # 2. Estratégia Blindada (Trava 2:1 com stop em +1R)
    print("▶️ Simulando 2. Blindada (Trava 2:1 -> +1R)...")
    trades_blindado = run_simulation(raw_m1, trailing_ma="ema8", be_trigger_r=2.0, be_lock_r=1.0)
    pivot_blindado_r = build_pivot_table(trades_blindado)
    pivot_blindado_wr = build_wr_pivot_table(trades_blindado)

    Path("reports").mkdir(parents=True, exist_ok=True)
    
    # Salvar CSVs
    pivot_trailing_r.to_csv("reports/monthly_by_asset_trailing_r.csv")
    pivot_blindado_r.to_csv("reports/monthly_by_asset_blindado_r.csv")
    
    print("\n" + "=" * 100)
    print("👑 ESTRATÉGIA 1: CAMPEÃ SUPREMA (smc_fibo_trailing_44pct_2500R_2.23pf_32dd) — RETORNO MENSAL EM R")
    print("=" * 100)
    print(pivot_trailing_r.to_string())

    print("\n" + "=" * 100)
    print("🛡️ ESTRATÉGIA 2: BLINDADA (smc_fibo_blindado_50pct_2278R_2.24pf_30dd) — RETORNO MENSAL EM R")
    print("=" * 100)
    print(pivot_blindado_r.to_string())

    # Totais anuais por ativo
    print("\n" + "=" * 100)
    print("📊 TOTAIS ANUAIS POR ATIVO (LADO A LADO)")
    print("=" * 100)
    summary_annual = pd.DataFrame({
        "Ativo": SYMBOLS + ["TOTAL_PORTFOLIO"],
        "👑 Trailing (R)": [pivot_trailing_r[s].sum().round(1) for s in SYMBOLS] + [pivot_trailing_r["TOTAL_PORTFOLIO"].sum().round(1)],
        "🛡️ Blindado (R)": [pivot_blindado_r[s].sum().round(1) for s in SYMBOLS] + [pivot_blindado_r["TOTAL_PORTFOLIO"].sum().round(1)],
    })
    print(summary_annual.to_string(index=False))

if __name__ == "__main__":
    main()

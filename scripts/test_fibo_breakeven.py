"""
Teste Quantitativo: Efeito do Breakeven (BE) em 1:1 e 2:1 na Estratégia Campeã
Compara:
1. Baseline Oficial: Sem Breakeven (apenas Stop 79% e Trailing MME 8)
2. Breakeven no 1:1 (+1.0R): Move stop para o preço de entrada ao atingir +1R
3. Breakeven no 1.5:1 (+1.5R): Move stop para o preço de entrada ao atingir +1.5R
4. Breakeven no 2:1 (+2.0R): Move stop para o preço de entrada ao atingir +2R
5. Lock Protetor no 2:1: Move stop para +1.0R de lucro ao atingir +2R
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

SYMBOLS = ["NAS100", "XAUUSD", "DAX40", "BRENT", "EURUSD", "GBPUSD", "USDJPY"]

def load_data() -> dict[str, pd.DataFrame]:
    data = {}
    for sym in SYMBOLS:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        df_m1 = pd.read_parquet(p)
        if not isinstance(df_m1.index, pd.DatetimeIndex):
            if "time" in df_m1.columns:
                df_m1["time"] = pd.to_datetime(df_m1["time"])
                df_m1.set_index("time", inplace=True)
            elif "timestamp" in df_m1.columns:
                df_m1["timestamp"] = pd.to_datetime(df_m1["timestamp"])
                df_m1.set_index("timestamp", inplace=True)

        df_m5 = df_m1.resample("5min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        }).dropna()
        df_m5["ema8"] = df_m5["close"].ewm(span=8, adjust=False).mean()
        data[sym] = df_m5.dropna().copy()
    return data

def simulate_with_be(
    df: pd.DataFrame,
    spread: float,
    be_trigger_r: float | None = None,     # ex: 1.0 ou 2.0
    be_target_level_r: float = 0.0,       # 0.0 = Breakeven (preço de entrada), 1.0 = Trava em +1R
    fibo_entry: float = 0.705,
    fibo_stop: float = 0.790,
    k: int = 3
) -> list[dict[str, Any]]:
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    timestamps = df.index
    ema8s = df["ema8"].values
    n = len(df)

    swing_highs = np.zeros(n, dtype=bool)
    swing_lows = np.zeros(n, dtype=bool)

    for i in range(k, n - k):
        if highs[i] == max(highs[i - k : i + k + 1]):
            swing_highs[i] = True
        if lows[i] == min(lows[i - k : i + k + 1]):
            swing_lows[i] = True

    trades = []
    last_sh = last_sl = None
    last_sh_idx = last_sl_idx = None

    in_pos = False
    pos_dir = 0
    entry_price = 0.0
    sl_price = 0.0
    initial_sl = 0.0
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

            # 1. Checar ativação de Breakeven durante a operação
            if be_trigger_r is not None and not be_activated:
                if pos_dir == 1:
                    unrealized_fav = c_high - entry_price
                    if unrealized_fav >= (risk * be_trigger_r):
                        # Move stop para o nível de BE definido (0.0R ou 1.0R)
                        sl_price = entry_price + (risk * be_target_level_r)
                        be_activated = True
                else:
                    unrealized_fav = entry_price - c_low
                    if unrealized_fav >= (risk * be_trigger_r):
                        sl_price = entry_price - (risk * be_target_level_r)
                        be_activated = True

            # 2. Saída por Trailing MME 8
            exit_by_trailing = False
            trailing_exit_price = 0.0
            if i > entry_idx:
                curr_ema8 = ema8s[i]
                if pos_dir == 1 and c_close < curr_ema8:
                    exit_by_trailing = True
                    trailing_exit_price = c_close
                elif pos_dir == -1 and c_close > curr_ema8:
                    exit_by_trailing = True
                    trailing_exit_price = c_close

            # 3. Execução de Saída
            if pos_dir == 1:
                hit_sl = c_low <= sl_price
                hit_tp = c_high >= tp_price

                if hit_sl and hit_tp:
                    r_res = -1.0 if not be_activated else be_target_level_r
                    trades.append({"r": r_res, "win": r_res > 0, "be": be_activated, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
                elif hit_sl:
                    r_res = -1.0 if not be_activated else be_target_level_r
                    trades.append({"r": r_res, "win": r_res > 0, "be": be_activated, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
                elif exit_by_trailing:
                    r_res = (trailing_exit_price - entry_price) / risk
                    trades.append({"r": r_res, "win": r_res > 0, "be": be_activated, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
                elif hit_tp:
                    r_res = (tp_price - entry_price) / risk
                    trades.append({"r": r_res, "win": True, "be": be_activated, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
            else:
                hit_sl = c_high >= sl_price
                hit_tp = c_low <= tp_price

                if hit_sl and hit_tp:
                    r_res = -1.0 if not be_activated else be_target_level_r
                    trades.append({"r": r_res, "win": r_res > 0, "be": be_activated, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
                elif hit_sl:
                    r_res = -1.0 if not be_activated else be_target_level_r
                    trades.append({"r": r_res, "win": r_res > 0, "be": be_activated, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
                elif exit_by_trailing:
                    r_res = (entry_price - trailing_exit_price) / risk
                    trades.append({"r": r_res, "win": r_res > 0, "be": be_activated, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
                elif hit_tp:
                    r_res = (entry_price - tp_price) / risk
                    trades.append({"r": r_res, "win": True, "be": be_activated, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
            continue

        # Detecção de perna
        if active_leg is None and last_sh is not None and last_sl is not None:
            if last_sh_idx > last_sl_idx and closes[i] > last_sh:
                r_pts = highs[i] - last_sl
                if r_pts > spread * 10:
                    active_leg = {
                        "dir": 1, "high": highs[i], "low": last_sl, "range": r_pts,
                        "entry": highs[i] - fibo_entry * r_pts,
                        "sl": highs[i] - fibo_stop * r_pts,
                        "touched": False, "c": 0
                    }
            elif last_sl_idx > last_sh_idx and closes[i] < last_sl:
                r_pts = last_sh - lows[i]
                if r_pts > spread * 10:
                    active_leg = {
                        "dir": -1, "high": last_sh, "low": lows[i], "range": r_pts,
                        "entry": lows[i] + fibo_entry * r_pts,
                        "sl": lows[i] + fibo_stop * r_pts,
                        "touched": False, "c": 0
                    }

        # Gatilho
        if active_leg is not None:
            active_leg["c"] += 1
            if active_leg["c"] > 60: active_leg = None; continue

            if not active_leg["touched"]:
                if active_leg["dir"] == 1 and highs[i] > active_leg["high"]:
                    active_leg["high"] = highs[i]
                    active_leg["range"] = active_leg["high"] - active_leg["low"]
                    active_leg["entry"] = active_leg["high"] - fibo_entry * active_leg["range"]
                    active_leg["sl"] = active_leg["high"] - fibo_stop * active_leg["range"]
                elif active_leg["dir"] == -1 and lows[i] < active_leg["low"]:
                    active_leg["low"] = lows[i]
                    active_leg["range"] = active_leg["high"] - active_leg["low"]
                    active_leg["entry"] = active_leg["low"] + fibo_entry * active_leg["range"]
                    active_leg["sl"] = active_leg["low"] + fibo_stop * active_leg["range"]

                if active_leg["dir"] == 1 and lows[i] <= active_leg["entry"]:
                    active_leg["touched"] = True
                    entry_price = active_leg["entry"] + spread
                    sl_price = active_leg["sl"]
                    initial_sl = sl_price
                    risk = entry_price - sl_price
                    if risk > spread * 1.5:
                        tp_price = active_leg["high"]
                        in_pos = True; pos_dir = 1; entry_idx = i; be_activated = False
                elif active_leg["dir"] == -1 and highs[i] >= active_leg["entry"]:
                    active_leg["touched"] = True
                    entry_price = active_leg["entry"]
                    sl_price = active_leg["sl"] + spread
                    initial_sl = sl_price
                    risk = sl_price - entry_price
                    if risk > spread * 1.5:
                        tp_price = active_leg["low"]
                        in_pos = True; pos_dir = -1; entry_idx = i; be_activated = False

    return trades

def run_test():
    print("=" * 80)
    print("🔬 TESTE QUANTITATIVO: IMPACTO DO BREAKEVEN (BE) NA ESTRATÉGIA CAMPEÃ")
    print("Período: 1 Ano Real (Dukascopy)")
    print("=" * 80 + "\n")

    data = load_data()
    split_date = pd.Timestamp("2026-05-01", tz="UTC")

    scenarios = [
        ("1. Baseline: Sem Breakeven (Campeã Atual)", None, 0.0),
        ("2. Breakeven em +1.0R (Stop vai para Entrada)", 1.0, 0.0),
        ("3. Breakeven em +1.5R (Stop vai para Entrada)", 1.5, 0.0),
        ("4. Breakeven em +2.0R (Stop vai para Entrada)", 2.0, 0.0),
        ("5. Trava de Lucro em +2.0R (Stop vai para +1.0R)", 2.0, 1.0)
    ]

    out = []

    for name, trig, lvl in scenarios:
        all_t = []
        sym_r = {}
        for sym in SYMBOLS:
            trades = simulate_with_be(data[sym], SPREADS[sym], be_trigger_r=trig, be_target_level_r=lvl)
            df_t = pd.DataFrame(trades)
            if not df_t.empty:
                df_t["symbol"] = sym
                all_t.append(df_t)
                sym_r[sym] = df_t["r"].sum()
            else:
                sym_r[sym] = 0.0

        df_all = pd.concat(all_t, ignore_index=True)
        tot_trades = len(df_all)
        wins = (df_all["win"] == True).sum()
        wr = (wins / tot_trades) * 100
        total_r = df_all["r"].sum()

        df_all["time"] = pd.to_datetime(df_all["time"])
        is_r = df_all[df_all["time"] < split_date]["r"].sum()
        oos_r = df_all[df_all["time"] >= split_date]["r"].sum()

        gp = df_all[df_all["win"] == True]["r"].sum()
        gl = abs(df_all[df_all["r"] < 0]["r"].sum())
        pf = (gp / gl) if gl > 0 else np.nan

        cum = df_all["r"].cumsum()
        max_dd = (cum.cummax() - cum).max()
        pos_assets = sum(1 for v in sym_r.values() if v > 0)

        out.append({
            "Cenário": name,
            "Trades": tot_trades,
            "Taxa Acerto (%)": round(wr, 1),
            "Retorno Total (R)": round(total_r, 1),
            "In-Sample (R)": round(is_r, 1),
            "Out-of-Sample (R)": round(oos_r, 1),
            "Profit Factor": round(pf, 2),
            "Max Drawdown (R)": round(max_dd, 1),
            "Ativos Positivos": f"{pos_assets}/7"
        })

        print(f"📊 {name:50s} -> Retorno: {total_r:+7.1f}R | OOS: {oos_r:+7.1f}R | WR: {wr:4.1f}% | PF: {pf:.2f} | MaxDD: -{max_dd:.1f}R | Ativos: {pos_assets}/7")

    df_res = pd.DataFrame(out)
    out_path = Path("out/fibo_optimization/breakeven_experiments.csv")
    df_res.to_csv(out_path, index=False)
    print(f"\n📁 Resultados salvos em: {out_path}")

if __name__ == "__main__":
    run_test()

"""
Teste Quantitativo: Impacto da Realização Parcial (Scaling-Out) na Estratégia Campeã
Compara:
1. Baseline: Sem Parcial (100% da mão surfando na MME 8)
2. Parcial de 50% no 1:1 (+1.0R), 50% restante na MME 8
3. Parcial de 50% no 1.5:1 (+1.5R), 50% restante na MME 8
4. Parcial de 50% no 2:1 (+2.0R), 50% restante na MME 8
5. Parcial de 50% no 2:1 (+2.0R) + Stop do restante no Breakeven
6. Parcial Escalonada: 33% no 1:1 + 33% no 2:1 + 34% na MME 8
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

def simulate_partials(
    df: pd.DataFrame,
    spread: float,
    partial_mode: str = "none",  # 'none', '50pct_1r', '50pct_1.5r', '50pct_2r', '50pct_2r_be', 'ladder_33'
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
    tp_price = 0.0
    risk = 0.0
    entry_idx = 0

    # Estado de parciais
    realized_r_accum = 0.0
    remaining_fraction = 1.0
    p1_done = False
    p2_done = False

    active_leg = None

    for i in range(k + 1, n - 1):
        chk = i - k
        if swing_highs[chk]: last_sh, last_sh_idx = highs[chk], chk
        if swing_lows[chk]: last_sl, last_sl_idx = lows[chk], chk

        if in_pos:
            c_high = highs[i]
            c_low = lows[i]
            c_close = closes[i]
            curr_ema8 = ema8s[i]

            # 1. Checar se atinge os gatilhos de realização parcial
            if remaining_fraction > 0:
                if pos_dir == 1:
                    max_fav_pts = c_high - entry_price
                else:
                    max_fav_pts = entry_price - c_low

                max_fav_r = max_fav_pts / risk

                if partial_mode == "50pct_1r" and not p1_done:
                    if max_fav_r >= 1.0:
                        realized_r_accum += 0.5 * 1.0
                        remaining_fraction -= 0.5
                        p1_done = True

                elif partial_mode == "50pct_1.5r" and not p1_done:
                    if max_fav_r >= 1.5:
                        realized_r_accum += 0.5 * 1.5
                        remaining_fraction -= 0.5
                        p1_done = True

                elif partial_mode == "50pct_2r" and not p1_done:
                    if max_fav_r >= 2.0:
                        realized_r_accum += 0.5 * 2.0
                        remaining_fraction -= 0.5
                        p1_done = True

                elif partial_mode == "50pct_2r_be" and not p1_done:
                    if max_fav_r >= 2.0:
                        realized_r_accum += 0.5 * 2.0
                        remaining_fraction -= 0.5
                        p1_done = True
                        sl_price = entry_price # move restante para o zero

                elif partial_mode == "ladder_33":
                    if not p1_done and max_fav_r >= 1.0:
                        realized_r_accum += 0.33 * 1.0
                        remaining_fraction -= 0.33
                        p1_done = True
                    if not p2_done and max_fav_r >= 2.0:
                        realized_r_accum += 0.33 * 2.0
                        remaining_fraction -= 0.33
                        p2_done = True

            # 2. Saída por Trailing MME 8 para o restante da mão
            exit_by_trailing = False
            trailing_exit_price = 0.0
            if i > entry_idx:
                if pos_dir == 1 and c_close < curr_ema8:
                    exit_by_trailing = True
                    trailing_exit_price = c_close
                elif pos_dir == -1 and c_close > curr_ema8:
                    exit_by_trailing = True
                    trailing_exit_price = c_close

            # 3. Execução de Saída da posição restante
            if pos_dir == 1:
                hit_sl = c_low <= sl_price
                hit_tp = c_high >= tp_price

                if hit_sl:
                    # Se stopou no SL
                    r_exit = -1.0 if sl_price < entry_price else 0.0
                    final_r = realized_r_accum + (remaining_fraction * r_exit)
                    trades.append({"r": final_r, "win": final_r > 0, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
                elif exit_by_trailing:
                    r_exit = (trailing_exit_price - entry_price) / risk
                    final_r = realized_r_accum + (remaining_fraction * r_exit)
                    trades.append({"r": final_r, "win": final_r > 0, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
                elif hit_tp:
                    r_exit = (tp_price - entry_price) / risk
                    final_r = realized_r_accum + (remaining_fraction * r_exit)
                    trades.append({"r": final_r, "win": final_r > 0, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
            else:
                hit_sl = c_high >= sl_price
                hit_tp = c_low <= tp_price

                if hit_sl:
                    r_exit = -1.0 if sl_price > entry_price else 0.0
                    final_r = realized_r_accum + (remaining_fraction * r_exit)
                    trades.append({"r": final_r, "win": final_r > 0, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
                elif exit_by_trailing:
                    r_exit = (entry_price - trailing_exit_price) / risk
                    final_r = realized_r_accum + (remaining_fraction * r_exit)
                    trades.append({"r": final_r, "win": final_r > 0, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
                elif hit_tp:
                    r_exit = (entry_price - tp_price) / risk
                    final_r = realized_r_accum + (remaining_fraction * r_exit)
                    trades.append({"r": final_r, "win": final_r > 0, "time": timestamps[entry_idx]})
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
                    risk = entry_price - sl_price
                    if risk > spread * 1.5:
                        tp_price = active_leg["high"]
                        in_pos = True; pos_dir = 1; entry_idx = i
                        realized_r_accum = 0.0; remaining_fraction = 1.0
                        p1_done = False; p2_done = False
                elif active_leg["dir"] == -1 and highs[i] >= active_leg["entry"]:
                    active_leg["touched"] = True
                    entry_price = active_leg["entry"]
                    sl_price = active_leg["sl"] + spread
                    risk = sl_price - entry_price
                    if risk > spread * 1.5:
                        tp_price = active_leg["low"]
                        in_pos = True; pos_dir = -1; entry_idx = i
                        realized_r_accum = 0.0; remaining_fraction = 1.0
                        p1_done = False; p2_done = False

    return trades

def main():
    print("=" * 80)
    print("🔬 TESTE QUANTITATIVO: IMPACTO DA REALIZAÇÃO PARCIAL NA ESTRATÉGIA CAMPEÃ")
    print("Período: 1 Ano Real (Dukascopy)")
    print("=" * 80 + "\n")

    data = load_data()
    split_date = pd.Timestamp("2026-05-01", tz="UTC")

    scenarios = [
        ("1. Baseline: Sem Parcial (100% surfando na MME 8)", "none"),
        ("2. Parcial 50% no 1:1 (+1.0R), 50% na MME 8", "50pct_1r"),
        ("3. Parcial 50% no 1.5:1 (+1.5R), 50% na MME 8", "50pct_1.5r"),
        ("4. Parcial 50% no 2:1 (+2.0R), 50% na MME 8", "50pct_2r"),
        ("5. Parcial 50% no 2:1 + Stop Restante no Breakeven", "50pct_2r_be"),
        ("6. Parcial Escalonada: 33% 1R + 33% 2R + 34% MME 8", "ladder_33")
    ]

    out = []

    for name, mode in scenarios:
        all_t = []
        sym_r = {}
        for sym in SYMBOLS:
            trades = simulate_partials(data[sym], SPREADS[sym], partial_mode=mode)
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
            "Estratégia": name,
            "Trades": tot_trades,
            "Taxa Acerto (%)": round(wr, 1),
            "Retorno Total (R)": round(total_r, 1),
            "In-Sample (R)": round(is_r, 1),
            "Out-of-Sample (R)": round(oos_r, 1),
            "Profit Factor": round(pf, 2),
            "Max Drawdown (R)": round(max_dd, 1),
            "Ativos Positivos": f"{pos_assets}/7"
        })

        print(f"📊 {name:55s} -> Retorno: {total_r:+7.1f}R | OOS: {oos_r:+7.1f}R | WR: {wr:4.1f}% | PF: {pf:.2f} | MaxDD: -{max_dd:.1f}R | Ativos: {pos_assets}/7")

    df_res = pd.DataFrame(out)
    out_path = Path("out/fibo_optimization/partials_experiments.csv")
    df_res.to_csv(out_path, index=False)
    print(f"\n📁 Resultados salvos em: {out_path}")

if __name__ == "__main__":
    main()

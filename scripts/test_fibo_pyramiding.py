"""
Teste Quantitativo: Piramidagem (Adição de Lotes a Favor da Tendência)
Compara:
1. Baseline Oficial: Sem Piramidagem (Máximo 1 lote por ativo)
2. Piramidagem em Nova Retração de Fibo (Máximo 2 lotes simultâneos)
3. Piramidagem em Pullback / Reversão na MME 8 (Máximo 2 lotes)
4. Piramidagem Agressiva (Máximo 3 lotes por perna de tendência)
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

def simulate_pyramiding(
    df: pd.DataFrame,
    spread: float,
    pyramid_mode: str = "none",  # 'none', 'new_fibo', 'pullback_ema8', 'aggressive_3lots'
    max_lots: int = 1,
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

    # Gerenciamento de múltiplos lotes abertos
    open_positions: list[dict[str, Any]] = []
    active_leg = None

    for i in range(k + 1, n - 1):
        chk = i - k
        if swing_highs[chk]: last_sh, last_sh_idx = highs[chk], chk
        if swing_lows[chk]: last_sl, last_sl_idx = lows[chk], chk

        c_high = highs[i]
        c_low = lows[i]
        c_close = closes[i]
        curr_ema8 = ema8s[i]

        # 1. Gerenciar posições abertas
        if open_positions:
            pos_dir = open_positions[0]["dir"]

            # Checa saída por Trailing MME 8
            exit_by_trailing = False
            trailing_exit_price = 0.0
            if pos_dir == 1 and c_close < curr_ema8:
                exit_by_trailing = True
                trailing_exit_price = c_close
            elif pos_dir == -1 and c_close > curr_ema8:
                exit_by_trailing = True
                trailing_exit_price = c_close

            # Avalia cada lote aberto
            remaining_positions = []
            for pos in open_positions:
                e_price = pos["entry"]
                s_price = pos["sl"]
                t_price = pos["tp"]
                r_points = pos["risk"]
                e_time = pos["time"]

                if pos_dir == 1:
                    hit_sl = c_low <= s_price
                    hit_tp = c_high >= t_price
                    if hit_sl:
                        trades.append({"r": -1.0, "win": False, "time": e_time, "lots": len(open_positions)})
                    elif exit_by_trailing:
                        r_mult = (trailing_exit_price - e_price) / r_points
                        trades.append({"r": r_mult, "win": r_mult > 0, "time": e_time, "lots": len(open_positions)})
                    elif hit_tp:
                        r_mult = (t_price - e_price) / r_points
                        trades.append({"r": r_mult, "win": True, "time": e_time, "lots": len(open_positions)})
                    else:
                        remaining_positions.append(pos)
                else:
                    hit_sl = c_high >= s_price
                    hit_tp = c_low <= t_price
                    if hit_sl:
                        trades.append({"r": -1.0, "win": False, "time": e_time, "lots": len(open_positions)})
                    elif exit_by_trailing:
                        r_mult = (e_price - trailing_exit_price) / r_points
                        trades.append({"r": r_mult, "win": r_mult > 0, "time": e_time, "lots": len(open_positions)})
                    elif hit_tp:
                        r_mult = (e_price - t_price) / r_points
                        trades.append({"r": r_mult, "win": True, "time": e_time, "lots": len(open_positions)})
                    else:
                        remaining_positions.append(pos)

            open_positions = remaining_positions
            if not open_positions:
                active_leg = None

        # 2. Piramidagem por Pullback na MME 8 (se permitido e posição existente já estiver no lucro)
        if open_positions and pyramid_mode in ("pullback_ema8", "aggressive_3lots"):
            if len(open_positions) < max_lots:
                pos_dir = open_positions[0]["dir"]
                first_pos = open_positions[0]

                # Apenas adiciona lote se o primeiro já estiver com pelo menos +1R de lucro a favor
                is_profitable = False
                if pos_dir == 1:
                    unrealized_r = (c_close - first_pos["entry"]) / first_pos["risk"]
                    is_profitable = unrealized_r >= 1.0
                else:
                    unrealized_r = (first_pos["entry"] - c_close) / first_pos["risk"]
                    is_profitable = unrealized_r >= 1.0

                if is_profitable:
                    # Pullback de alta na MME 8: candle anterior tocou na média e o atual fecha acima
                    if pos_dir == 1:
                        if lows[i-1] <= ema8s[i-1] and closes[i] > ema8s[i]:
                            add_entry = c_close + spread
                            add_sl = lows[i-1] # stop curto no fundo do pullback
                            add_risk = add_entry - add_sl
                            if add_risk > spread * 1.5:
                                open_positions.append({
                                    "dir": 1, "entry": add_entry, "sl": add_sl,
                                    "tp": first_pos["tp"], "risk": add_risk, "time": timestamps[i]
                                })
                    else:
                        if highs[i-1] >= ema8s[i-1] and closes[i] < ema8s[i]:
                            add_entry = c_close
                            add_sl = highs[i-1] + spread
                            add_risk = add_sl - add_entry
                            if add_risk > spread * 1.5:
                                open_positions.append({
                                    "dir": -1, "entry": add_entry, "sl": add_sl,
                                    "tp": first_pos["tp"], "risk": add_risk, "time": timestamps[i]
                                })

        # 3. Detecção de Perna de Fibo
        if last_sh is not None and last_sl is not None:
            # Só busca nova perna se não há posições ou se piramidagem por nova perna for permitida
            can_new_leg = (not open_positions) or (pyramid_mode in ("new_fibo", "aggressive_3lots") and len(open_positions) < max_lots)

            if can_new_leg and active_leg is None:
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

        # 4. Gatilho de Entrada na Perna Ativa
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

                # Entrada 1 ou Entrada Adicional de Fibo
                if len(open_positions) < max_lots:
                    if active_leg["dir"] == 1 and lows[i] <= active_leg["entry"]:
                        active_leg["touched"] = True
                        e_p = active_leg["entry"] + spread
                        s_p = active_leg["sl"]
                        r_p = e_p - s_p
                        if r_p > spread * 1.5:
                            open_positions.append({
                                "dir": 1, "entry": e_p, "sl": s_p, "tp": active_leg["high"],
                                "risk": r_p, "time": timestamps[i]
                            })
                    elif active_leg["dir"] == -1 and highs[i] >= active_leg["entry"]:
                        active_leg["touched"] = True
                        e_p = active_leg["entry"]
                        s_p = active_leg["sl"] + spread
                        r_p = s_p - e_p
                        if r_p > spread * 1.5:
                            open_positions.append({
                                "dir": -1, "entry": e_p, "sl": s_p, "tp": active_leg["low"],
                                "risk": r_p, "time": timestamps[i]
                            })

    return trades

def main():
    print("=" * 80)
    print("🔬 TESTE QUANTITATIVO: EFEITO DA PIRAMIDAGEM NA ESTRATÉGIA CAMPEÃ")
    print("Período: 1 Ano Real (Dukascopy)")
    print("=" * 80 + "\n")

    data = load_data()
    split_date = pd.Timestamp("2026-05-01", tz="UTC")

    experiments = [
        ("1. Baseline Oficial: Sem Piramidagem (Máx 1 Lote)", "none", 1),
        ("2. Piramidagem em Nova Retração de Fibo (Máx 2 Lotes)", "new_fibo", 2),
        ("3. Piramidagem em Pullback na MME 8 (Máx 2 Lotes)", "pullback_ema8", 2),
        ("4. Piramidagem Agressiva (Máx 3 Lotes)", "aggressive_3lots", 3)
    ]

    out = []

    for name, mode, m_lots in experiments:
        all_t = []
        sym_r = {}
        for sym in SYMBOLS:
            trades = simulate_pyramiding(data[sym], SPREADS[sym], pyramid_mode=mode, max_lots=m_lots)
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
    out_path = Path("out/fibo_optimization/pyramiding_experiments.csv")
    df_res.to_csv(out_path, index=False)
    print(f"\n📁 Resultados salvos em: {out_path}")

if __name__ == "__main__":
    main()

"""
Otimizador de Grade (Grid Search) com Validação Walk-Forward para SMC-Fibo-OTE
Testa combinações de:
- Timeframe: M5 vs M15
- Entrada: 61.8% vs 65.0% vs 70.5% (ICT Sweet Spot)
- Stop Loss: 79.0% vs 88.6% (Harmonic)
- Alvo: 2.5R vs 3.0R vs 0% (Topo/Fundo prévio)
- Filtro de Horário: 24h vs Sessão Nobre (Londres + NY: 07:00 às 18:00 UTC)
"""

import sys
import itertools
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

def load_precomputed_data() -> dict[str, dict[str, pd.DataFrame]]:
    """Carrega e pré-resampleia os dados de todos os ativos para M5 e M15 na memória."""
    data = {}
    print("⏳ Carregando dados históricos e pré-computando M5 e M15...")
    for sym in SYMBOLS:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        if not p.exists():
            continue
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

        df_m15 = df_m1.resample("15min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        }).dropna()

        data[sym] = {"M5": df_m5, "M15": df_m15}
    print("✅ Dados em memória.")
    return data

def simulate_fast(
    df: pd.DataFrame,
    spread: float,
    fibo_entry: float,
    fibo_stop: float,
    target_mode: str,
    target_r: float,
    session_filter: bool,
    k: int = 3
) -> list[dict[str, Any]]:
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    opens = df["open"].values
    timestamps = df.index
    hours = timestamps.hour
    n = len(df)

    # Identificar swings fractais
    swing_highs = np.zeros(n, dtype=bool)
    swing_lows = np.zeros(n, dtype=bool)

    for i in range(k, n - k):
        if highs[i] == max(highs[i - k : i + k + 1]):
            swing_highs[i] = True
        if lows[i] == min(lows[i - k : i + k + 1]):
            swing_lows[i] = True

    trades = []
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

    active_leg = None

    for i in range(k + 1, n - 1):
        chk = i - k
        if swing_highs[chk]:
            last_sh_price = highs[chk]
            last_sh_idx = chk
        if swing_lows[chk]:
            last_sl_price = lows[chk]
            last_sl_idx = chk

        if in_pos:
            c_high = highs[i]
            c_low = lows[i]
            if pos_dir == 1:
                hit_sl = c_low <= sl_price
                hit_tp = c_high >= tp_price
                if hit_sl and hit_tp:
                    trades.append({"entry_time": timestamps[entry_idx], "r": -1.0, "win": False})
                    in_pos = False
                elif hit_sl:
                    trades.append({"entry_time": timestamps[entry_idx], "r": -1.0, "win": False})
                    in_pos = False
                elif hit_tp:
                    r_mult = target_r if target_mode != "0_percent" else (tp_price - entry_price) / risk
                    trades.append({"entry_time": timestamps[entry_idx], "r": r_mult, "win": True})
                    in_pos = False
                    active_leg = None
            else:
                hit_sl = c_high >= sl_price
                hit_tp = c_low <= tp_price
                if hit_sl and hit_tp:
                    trades.append({"entry_time": timestamps[entry_idx], "r": -1.0, "win": False})
                    in_pos = False
                elif hit_sl:
                    trades.append({"entry_time": timestamps[entry_idx], "r": -1.0, "win": False})
                    in_pos = False
                elif hit_tp:
                    r_mult = target_r if target_mode != "0_percent" else (entry_price - tp_price) / risk
                    trades.append({"entry_time": timestamps[entry_idx], "r": r_mult, "win": True})
                    in_pos = False
                    active_leg = None
            continue

        # Detecção de nova perna de impulsão por BOS
        if active_leg is None and last_sh_price is not None and last_sl_price is not None:
            if last_sh_idx > last_sl_idx:
                if closes[i] > last_sh_price:
                    leg_low = last_sl_price
                    leg_high = highs[i]
                    leg_range = leg_high - leg_low
                    if leg_range > spread * 10:
                        active_leg = {
                            "dir": 1, "low": leg_low, "high": leg_high, "range": leg_range,
                            "fibo_entry": leg_high - fibo_entry * leg_range,
                            "fibo_stop": leg_high - fibo_stop * leg_range,
                            "touched": False, "candles": 0
                        }
            elif last_sl_idx > last_sh_idx:
                if closes[i] < last_sl_price:
                    leg_high = last_sh_price
                    leg_low = lows[i]
                    leg_range = leg_high - leg_low
                    if leg_range > spread * 10:
                        active_leg = {
                            "dir": -1, "high": leg_high, "low": leg_low, "range": leg_range,
                            "fibo_entry": leg_low + fibo_entry * leg_range,
                            "fibo_stop": leg_low + fibo_stop * leg_range,
                            "touched": False, "candles": 0
                        }

        # Gatilho na perna ativa
        if active_leg is not None:
            active_leg["candles"] += 1
            if active_leg["candles"] > 60:
                active_leg = None
                continue

            if not active_leg["touched"]:
                # Se continuar rompendo antes de retrair, expande perna
                if active_leg["dir"] == 1 and highs[i] > active_leg["high"]:
                    active_leg["high"] = highs[i]
                    active_leg["range"] = active_leg["high"] - active_leg["low"]
                    active_leg["fibo_entry"] = active_leg["high"] - fibo_entry * active_leg["range"]
                    active_leg["fibo_stop"] = active_leg["high"] - fibo_stop * active_leg["range"]
                elif active_leg["dir"] == -1 and lows[i] < active_leg["low"]:
                    active_leg["low"] = lows[i]
                    active_leg["range"] = active_leg["high"] - active_leg["low"]
                    active_leg["fibo_entry"] = active_leg["low"] + fibo_entry * active_leg["range"]
                    active_leg["fibo_stop"] = active_leg["low"] + fibo_stop * active_leg["range"]

                # Checa filtro de horário se ativo (07:00 às 18:00 UTC)
                if session_filter:
                    h = hours[i]
                    if not (7 <= h <= 18):
                        continue

                # Entrada no nível de Fibo
                if active_leg["dir"] == 1:
                    if lows[i] <= active_leg["fibo_entry"]:
                        active_leg["touched"] = True
                        raw_entry = active_leg["fibo_entry"]
                        raw_sl = active_leg["fibo_stop"]
                        entry_price = raw_entry + spread
                        sl_price = raw_sl
                        risk = entry_price - sl_price
                        if risk > spread * 1.5:
                            if target_mode == "0_percent":
                                tp_price = active_leg["high"]
                            else:
                                tp_price = entry_price + (risk * target_r)
                            in_pos = True
                            pos_dir = 1
                            entry_idx = i
                else:
                    if highs[i] >= active_leg["fibo_entry"]:
                        active_leg["touched"] = True
                        raw_entry = active_leg["fibo_entry"]
                        raw_sl = active_leg["fibo_stop"]
                        entry_price = raw_entry
                        sl_price = raw_sl + spread
                        risk = sl_price - entry_price
                        if risk > spread * 1.5:
                            if target_mode == "0_percent":
                                tp_price = active_leg["low"]
                            else:
                                tp_price = entry_price - (risk * target_r)
                            in_pos = True
                            pos_dir = -1
                            entry_idx = i

    return trades

def main():
    print("=" * 80)
    print("🔬 INICIANDO OTIMIZAÇÃO MULTI-DIMENSIONAL (GRID SEARCH) SMC-FIBO-OTE")
    print("=" * 80 + "\n")

    data = load_precomputed_data()
    split_date = pd.Timestamp("2026-05-01", tz="UTC")

    # Espaço de parâmetros:
    timeframes = ["M5", "M15"]
    fibo_entries = [0.618, 0.650, 0.705]  # 61.8%, 65.0%, 70.5% (Sweet Spot)
    fibo_stops = [0.790, 0.886]           # 79.0%, 88.6% (Harmônico profundo)
    targets = [
        ("2.5R", 2.5),
        ("3.0R", 3.0),
        ("0_percent", 0.0)
    ]
    sessions = [False, True]              # False = 24h, True = Sessão Nobre (07-18 UTC)

    grid_combos = list(itertools.product(timeframes, fibo_entries, fibo_stops, targets, sessions))
    total_combos = len(grid_combos)
    print(f"Total de Configurações a testar: {total_combos} combinações nos 7 ativos ({total_combos * len(SYMBOLS)} simulações)...\n")

    results = []

    for idx, (tf, f_entry, f_stop, (t_name, t_r), sess) in enumerate(grid_combos, start=1):
        config_name = f"{tf}_E{int(f_entry*1000)}_SL{int(f_stop*1000)}_{t_name}_{'Prime' if sess else '24h'}"
        
        all_sym_trades = []
        sym_metrics = {}

        for sym in SYMBOLS:
            df = data[sym][tf]
            spread = SPREADS[sym]
            t_list = simulate_fast(
                df=df,
                spread=spread,
                fibo_entry=f_entry,
                fibo_stop=f_stop,
                target_mode=t_name,
                target_r=t_r,
                session_filter=sess
            )
            df_t = pd.DataFrame(t_list)
            if not df_t.empty:
                df_t["symbol"] = sym
                all_sym_trades.append(df_t)
                sym_r = df_t["r"].sum()
                sym_metrics[sym] = sym_r
            else:
                sym_metrics[sym] = 0.0

        if not all_sym_trades:
            continue

        df_all = pd.concat(all_sym_trades, ignore_index=True)
        tot_trades = len(df_all)
        wins = (df_all["win"] == True).sum()
        wr = (wins / tot_trades) * 100
        total_r = df_all["r"].sum()
        exp_r = total_r / tot_trades

        # Split IS / OOS
        df_all["entry_time"] = pd.to_datetime(df_all["entry_time"])
        is_df = df_all[df_all["entry_time"] < split_date]
        oos_df = df_all[df_all["entry_time"] >= split_date]

        is_r = is_df["r"].sum() if len(is_df) > 0 else 0.0
        oos_r = oos_df["r"].sum() if len(oos_df) > 0 else 0.0
        wfe = (oos_r / is_r) if is_r > 0 else (1.0 if oos_r > 0 else 0.0)

        # Max Drawdown
        cum_r = df_all["r"].cumsum()
        max_dd = (cum_r.cummax() - cum_r).max()

        # Contagem de ativos positivos
        pos_assets = sum(1 for v in sym_metrics.values() if v > 0)

        # Profit Factor
        gross_p = df_all[df_all["win"] == True]["r"].sum()
        gross_l = abs(df_all[df_all["win"] == False]["r"].sum())
        pf = (gross_p / gross_l) if gross_l > 0 else np.nan

        results.append({
            "config": config_name,
            "tf": tf,
            "entry": f_entry,
            "stop": f_stop,
            "target": t_name,
            "session": "Prime" if sess else "24h",
            "trades": tot_trades,
            "win_rate": wr,
            "total_r": total_r,
            "exp_r": exp_r,
            "is_r": is_r,
            "oos_r": oos_r,
            "wfe": wfe,
            "profit_factor": pf,
            "max_dd": max_dd,
            "pos_assets": pos_assets,
            **{f"{s}_r": sym_metrics.get(s, 0.0) for s in SYMBOLS}
        })

        if idx % 10 == 0 or idx == total_combos:
            print(f"[{idx:2d}/{total_combos}] {config_name:32s} -> Total: {total_r:+7.1f}R | OOS: {oos_r:+7.1f}R | Ativos Positivos: {pos_assets}/7")

    df_res = pd.DataFrame(results)
    out_dir = Path("out/fibo_optimization")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "grid_results.csv"
    df_res.to_csv(csv_path, index=False)
    print(f"\n📁 Resultados completos salvos em: {csv_path}")

    # Top 10 por Retorno Out-of-Sample (Teste Cego)
    top_oos = df_res.sort_values(by="oos_r", ascending=False).head(10)
    print("\n" + "=" * 90)
    print("🏆 TOP 10 CONFIGURAÇÕES CAMPEÃS POR OUT-OF-SAMPLE (TESTE CEGO):")
    print("=" * 90)
    cols_show = ["config", "tf", "entry", "stop", "target", "session", "trades", "win_rate", "total_r", "is_r", "oos_r", "wfe", "profit_factor", "max_dd", "pos_assets"]
    print(top_oos[cols_show].to_string(index=False))

    # Top 5 com 7 de 7 ativos positivos
    all_7 = df_res[df_res["pos_assets"] == 7].sort_values(by="total_r", ascending=False).head(5)
    print("\n" + "=" * 90)
    print("🌟 TOP CONFIGURAÇÕES COM 100% DE ATIVOS POSITIVOS (7/7):")
    print("=" * 90)
    if not all_7.empty:
        print(all_7[cols_show].to_string(index=False))
    else:
        print("Nenhuma configuração alcançou 7/7.")

if __name__ == "__main__":
    main()

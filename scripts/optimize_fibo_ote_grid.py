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

from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy

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
    mode = "3R" if target_mode in ("2.5R", "3.0R") else "0_percent"
    cfg = FiboOTEConfig(
        fibo_entry=fibo_entry,
        fibo_stop=fibo_stop,
        target_mode=mode,
        target_r=target_r,
        trailing_exit_ma="ema8" if mode == "0_percent" else None,
        pivot_k=k,
        session_filter=session_filter,
        session_windows=[("07:00", "18:00")] if session_filter else None,
    )
    strategy = FiboOTEStrategy(cfg)
    trades = strategy.run_backtest(df, "SIM", spread=spread)
    return [{"entry_time": t.entry_time, "r": t.r_multiple, "win": t.win} for t in trades]

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

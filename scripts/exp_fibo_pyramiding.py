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
    cfg = FiboOTEConfig(
        fibo_entry=fibo_entry,
        fibo_stop=fibo_stop,
        target_mode="0_percent",
        trailing_exit_ma="ema8",
        pivot_k=k,
    )
    strategy = FiboOTEStrategy(cfg)
    trades = strategy.run_backtest(df, "SIM", spread=spread)
    return [{"r": t.r_multiple, "win": t.win, "time": t.entry_time, "lots": 1} for t in trades]

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

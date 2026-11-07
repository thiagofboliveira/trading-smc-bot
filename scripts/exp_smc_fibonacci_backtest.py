"""
Teste Quantitativo: SMC com Fibonacci OTE (61.8% -> Stop 79% + Rejeição no 79% -> Stop 100%)
Período: 1 Ano Completo (Dados M1 Dukascopy resampleados para M5)
Compara 3 Alvos:
1. Alvo Fixo 3R (1:3)
2. Alvo Estrutural no Topo/Fundo prévio (0% Fibo)
3. Alvo na Projeção de 61.8% da correção além do topo
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path

from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy

SPREADS = {
    "BRENT": 0.04,     # 4 cents
    "XAUUSD": 0.30,    # 30 cents ($0.30)
    "NAS100": 1.50,    # 1.5 pts
    "DAX40": 1.50,     # 1.5 pts
    "EURUSD": 0.00015, # 1.5 pips
    "GBPUSD": 0.00020, # 2.0 pips
    "USDJPY": 0.018    # 1.8 pips
}

def load_and_resample_m5(symbol: str) -> pd.DataFrame:
    path = Path(f"data/{symbol}_M1_dukascopy.parquet")
    df_m1 = pd.read_parquet(path)
    if not isinstance(df_m1.index, pd.DatetimeIndex):
        if "time" in df_m1.columns:
            df_m1["time"] = pd.to_datetime(df_m1["time"])
            df_m1.set_index("time", inplace=True)
        elif "timestamp" in df_m1.columns:
            df_m1["timestamp"] = pd.to_datetime(df_m1["timestamp"])
            df_m1.set_index("timestamp", inplace=True)
            
    df_m5 = df_m1.resample("5min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }).dropna()
    return df_m5

def simulate_fibo_ote(symbol: str, target_mode: str = "3R", timeframe: str = "5min"):
    df = load_and_resample_m5(symbol)
    spread = SPREADS[symbol]
    target_m = "3R" if target_mode == "3R" else ("proj_618" if target_mode == "proj_618" else "0_percent")
    cfg = FiboOTEConfig(
        fibo_entry=0.618,
        fibo_stop=0.790,
        target_mode=target_m,
        trailing_exit_ma=None,
        pivot_k=2,
    )
    strategy = FiboOTEStrategy(cfg)
    trades = strategy.run_backtest(df, symbol, spread=spread)
    return [
        {
            "stage": t.stage,
            "direction": t.direction,
            "entry_time": t.entry_time,
            "exit_time": t.exit_time,
            "entry_price": t.entry_price,
            "stop_loss": t.stop_loss,
            "take_profit": t.take_profit,
            "risk_points": t.risk_points,
            "pnl_points": t.pnl_points,
            "r_multiple": t.r_multiple,
            "win": t.win,
            "exit_reason": t.exit_reason,
            "r": t.r_multiple,
        }
        for t in trades
    ]

def main():
    symbols = ["BRENT", "XAUUSD", "NAS100", "DAX40", "EURUSD", "GBPUSD", "USDJPY"]
    modes = ["3R", "0_percent", "proj_618"]
    
    print("================================================================================")
    print("🚀 BACKTEST QUANTITATIVO: SMC FIBONACCI OTE (61.8% -> 79% -> 100%)")
    print("Período: 1 Ano Completo (01/11/2025 a 04/11/2026)")
    print("Modos de Alvo: [3R], [0% Topo/Fundo], [Projeção 61.8% da Correção]")
    print("================================================================================\n")
    
    all_summary = []
    
    for mode in modes:
        print(f"\n👉 TESTANDO ALVO: [{mode}]")
        mode_trades = []
        for sym in symbols:
            try:
                t = simulate_fibo_ote(sym, target_mode=mode)
                if not t:
                    continue
                df_t = pd.DataFrame(t)
                total = len(df_t)
                wins = (df_t["win"] == True).sum()
                wr = (wins / total) * 100
                total_r = df_t["r"].sum()
                exp_r = total_r / total
                
                # Split IS / OOS
                df_t["entry_time"] = pd.to_datetime(df_t["entry_time"])
                split_date = pd.Timestamp("2026-05-01", tz="UTC")
                is_df = df_t[df_t["entry_time"] < split_date]
                oos_df = df_t[df_t["entry_time"] >= split_date]
                
                is_r = is_df["r"].sum() if len(is_df) > 0 else 0
                oos_r = oos_df["r"].sum() if len(oos_df) > 0 else 0
                
                # Desempenho por Estágio (Estágio 1 = 61.8%, Estágio 2 = Rejeição 79%)
                s1_trades = df_t[df_t["stage"] == 1]
                s2_trades = df_t[df_t["stage"] == 2]
                s1_r = s1_trades["r"].sum() if len(s1_trades) > 0 else 0
                s2_r = s2_trades["r"].sum() if len(s2_trades) > 0 else 0
                
                all_summary.append({
                    "mode": mode,
                    "symbol": sym,
                    "total_trades": total,
                    "win_rate": wr,
                    "total_r": total_r,
                    "exp_r": exp_r,
                    "is_r": is_r,
                    "oos_r": oos_r,
                    "s1_trades": len(s1_trades),
                    "s1_r": s1_r,
                    "s2_trades": len(s2_trades),
                    "s2_r": s2_r
                })
                
                print(f"  [{sym:6s}] Trades: {total:4d} | WR: {wr:4.1f}% | Total: {total_r:+6.1f}R | IS: {is_r:+5.1f}R | OOS: {oos_r:+5.1f}R | S1 (61.8%): {s1_r:+5.1f}R | S2 (79%): {s2_r:+5.1f}R")
            except Exception as e:
                print(f"  Erro em {sym}: {e}")
                
    df_res = pd.DataFrame(all_summary)
    out_path = Path("out/fibo_analysis/smc_fibo_ote_results.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_res.to_csv(out_path, index=False)
    
    print("\n" + "="*80)
    print("🏆 RANKING GERAL POR MODO DE ALVO (Soma dos 7 Ativos no Ano):")
    print("="*80)
    grouped = df_res.groupby("mode").agg({
        "total_trades": "sum",
        "total_r": "sum",
        "is_r": "sum",
        "oos_r": "sum"
    }).sort_values(by="oos_r", ascending=False)
    print(grouped.to_string())

if __name__ == "__main__":
    main()

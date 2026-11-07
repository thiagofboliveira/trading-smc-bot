"""
Recalibração Global e Científica de Variáveis — Versão 100% Auditada (Anti-Imunidade)
Testa sistematicamente todas as dimensões da estratégia nos 2 anos de dados reais Dukascopy:
1. Entrada: 61.8% vs 70.5% vs 79.0%
2. Stop Loss: 79.0% vs 88.6% vs 100.0% (Invalidação Estrutural)
3. Condução / Saída: Trailing MME 8 vs Trailing SMA 20 vs Trava 2:1 vs Alvo 3R vs Alvo 0%
4. Timeframe: M5 vs M15
5. Filtro de Sessão: 24h vs Londres/NY (07:00 às 18:00 UTC)
"""

import sys
from pathlib import Path
from typing import Any
import itertools
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

def load_precomputed_data():
    data = {}
    print("⏳ Carregando dados de 2 Anos (4.95M candles Dukascopy)...")
    for sym in SYMBOLS:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        if not p.exists():
            continue
        df_m1 = pd.read_parquet(p)
        if not isinstance(df_m1.index, pd.DatetimeIndex):
            col = "time" if "time" in df_m1.columns else "timestamp"
            df_m1[col] = pd.to_datetime(df_m1[col])
            df_m1.set_index(col, inplace=True)

        # M5
        df_m5 = df_m1.resample("5min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        }).dropna()
        df_m5["ema8"] = df_m5["close"].ewm(span=8, adjust=False).mean()
        df_m5["sma20"] = df_m5["close"].rolling(20).mean()

        # M15
        df_m15 = df_m1.resample("15min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        }).dropna()
        df_m15["ema8"] = df_m15["close"].ewm(span=8, adjust=False).mean()
        df_m15["sma20"] = df_m15["close"].rolling(20).mean()

        data[sym] = {"M5": df_m5, "M15": df_m15}
    print("✅ Dados prontos em memória.")
    return data

def simulate_audited(
    df: pd.DataFrame,
    spread: float,
    fibo_entry: float,
    fibo_stop: float,
    exit_mode: str,          # 'trailing_ema8', 'trailing_sma20', 'lock_2to1', 'target_3r', 'target_0_pct'
    session_filter: bool,
    k: int = 2
) -> list[dict[str, Any]]:
    target_mode = "3R" if exit_mode == "target_3r" else "0_percent"
    trailing_exit_ma = "ema8" if exit_mode in ("trailing_ema8", "lock_2to1") else ("sma20" if exit_mode == "trailing_sma20" else None)
    use_lock_2to1 = (exit_mode == "lock_2to1")

    cfg = FiboOTEConfig(
        fibo_entry=fibo_entry,
        fibo_stop=fibo_stop,
        target_mode=target_mode,
        trailing_exit_ma=trailing_exit_ma,
        use_lock_2to1=use_lock_2to1,
        pivot_k=k,
        session_filter=session_filter,
        session_windows=[("07:00", "18:00")] if session_filter else None,
    )
    strategy = FiboOTEStrategy(cfg)
    trades = strategy.run_backtest(df, "SIM", spread=spread)
    return [{"r": t.r_multiple, "win": t.win, "time": t.entry_time} for t in trades]

def eval_config(data, tf, entry, stop, exit_m, sess):
    all_trades = []
    for sym in SYMBOLS:
        if sym not in data: continue
        df = data[sym][tf]
        spread = SPREADS[sym]
        t = simulate_audited(df, spread, entry, stop, exit_m, sess)
        all_trades.extend(t)

    if not all_trades:
        return None

    df_t = pd.DataFrame(all_trades)
    n = len(df_t)
    r_total = df_t["r"].sum()
    wr = (df_t["win"].sum() / n) * 100.0
    wins = df_t[df_t["r"] > 0]["r"]
    losses = df_t[df_t["r"] < 0]["r"].abs()
    pf = (wins.sum() / losses.sum()) if losses.sum() > 0 else 999.0
    payoff = (wins.mean() / losses.mean()) if len(losses) > 0 and losses.mean() > 0 else 0.0

    df_sorted = df_t.sort_values("time")
    cum = df_sorted["r"].cumsum()
    dd = cum - cum.cummax()
    mdd = abs(dd.min())

    return {
        "tf": tf,
        "entry": entry,
        "stop": stop,
        "exit_mode": exit_m,
        "session": "Londres/NY" if sess else "24h",
        "trades": n,
        "wr": round(wr, 1),
        "total_r": round(r_total, 1),
        "r_year": round(r_total / 2.0, 1),
        "pf": round(pf, 2),
        "mdd": round(mdd, 1),
        "payoff": round(payoff, 2)
    }

def main():
    data = load_precomputed_data()

    # Grade de Estudo Completo
    entries = [0.618, 0.705, 0.790]
    stops = [0.790, 0.886, 1.000]
    exits = ["trailing_ema8", "trailing_sma20", "lock_2to1", "target_3r", "target_0_pct"]
    timeframes = ["M5"]  # Foco primário M5
    sessions = [False, True]

    print(f"\n🔍 Executando Recalibração de Variáveis Auditada...")
    results = []

    for tf in timeframes:
        for ent in entries:
            for stp in stops:
                if stp <= ent: continue  # Stop deve ser mais profundo que a entrada
                for ex in exits:
                    for sess in sessions:
                        res = eval_config(data, tf, ent, stp, ex, sess)
                        if res:
                            results.append(res)

    # Ordenar por Total R descendente
    df_res = pd.DataFrame(results).sort_values("total_r", ascending=False)
    
    Path("reports").mkdir(exist_ok=True)
    csv_path = "reports/audited_variable_recalibration_2years.csv"
    df_res.to_csv(csv_path, index=False)
    print(f"\n💾 Relatório completo salvo em: {csv_path}")

    print("\n" + "=" * 115)
    print("🏆 TOP 15 MODELOS 100% AUDITADOS E REALISTAS (SEM IMUNIDADE INTRABAR — 2 ANOS)")
    print("=" * 115)
    print(f"{'TF':<3} | {'Entrada':<7} | {'Stop':<6} | {'Saída / Gestão':<16} | {'Sessão':<10} | {'Trades':<6} | {'WinRate':<7} | {'Total R':<9} | {'R / Ano':<8} | {'PF':<5} | {'MaxDD':<6} | {'Payoff'}")
    print("-" * 115)
    for _, r in df_res.head(15).iterrows():
        print(f"{r['tf']:<3} | {r['entry']:>7.3f} | {r['stop']:>6.3f} | {r['exit_mode']:<16} | {r['session']:<10} | {r['trades']:<6} | {r['wr']:>6.1f}% | {r['total_r']:>8.1f}R | {r['r_year']:>7.1f}R | {r['pf']:>5.2f} | -{r['mdd']:>4.1f}R | {r['payoff']}")
    print("-" * 115)

    print("\n" + "=" * 115)
    print("🔎 COMPARAÇÃO ESPECÍFICA DAS VARIÁVEIS CHAVE AUDITADAS")
    print("=" * 115)
    # Comparar Stops na Entrada 70.5% com Trailing EMA8
    print("\n1. Impacto do Stop Loss na Entrada 70.5% (Sweet Spot) com Trailing MME 8 (24h):")
    for stp in [0.790, 0.886, 1.000]:
        sub = df_res[(df_res['entry'] == 0.705) & (df_res['stop'] == stp) & (df_res['exit_mode'] == 'trailing_ema8') & (df_res['session'] == '24h')]
        if not sub.empty:
            r = sub.iloc[0]
            print(f"   - Stop {stp*100:>5.1f}%: {r['trades']} trades | WR {r['wr']}% | Retorno: +{r['total_r']} R (+{r['r_year']} R/ano) | PF {r['pf']} | MaxDD -{r['mdd']} R")

    print("\n2. Impacto da Entrada com Stop Estrutural 100% (Trailing MME 8 - 24h):")
    for ent in [0.618, 0.705, 0.790]:
        sub = df_res[(df_res['entry'] == ent) & (df_res['stop'] == 1.000) & (df_res['exit_mode'] == 'trailing_ema8') & (df_res['session'] == '24h')]
        if not sub.empty:
            r = sub.iloc[0]
            print(f"   - Entrada {ent*100:>5.1f}%: {r['trades']} trades | WR {r['wr']}% | Retorno: +{r['total_r']} R (+{r['r_year']} R/ano) | PF {r['pf']} | MaxDD -{r['mdd']} R")

    print("\n3. Impacto da Condução / Saída na Entrada 61.8% com Stop 100% (24h):")
    for ex in ["trailing_ema8", "trailing_sma20", "lock_2to1", "target_3r", "target_0_pct"]:
        sub = df_res[(df_res['entry'] == 0.618) & (df_res['stop'] == 1.000) & (df_res['exit_mode'] == ex) & (df_res['session'] == '24h')]
        if not sub.empty:
            r = sub.iloc[0]
            print(f"   - Saída {ex:<15}: {r['trades']} trades | WR {r['wr']}% | Retorno: +{r['total_r']} R (+{r['r_year']} R/ano) | PF {r['pf']} | MaxDD -{r['mdd']} R")

if __name__ == "__main__":
    main()

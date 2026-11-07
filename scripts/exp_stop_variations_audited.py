"""
Teste de Engenharia: Como tornar a estratégia robusta e lucrativa na VIDA REAL após a auditoria?
Testa diferentes stops:
- Stop em 79% (Original apertado)
- Stop em 88.6% (Harmonic / Deep OTE)
- Stop em 100% (Invalidação Estrutural Real do SMC - Fundo da Perna)
- Stop com filtro de candle (evitar entrar se a barra de entrada tiver range > 2x a média)
"""

import sys
from pathlib import Path
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

SYMBOLS = ["XAUUSD", "NAS100", "DAX40", "BRENT", "EURUSD", "GBPUSD", "USDJPY"]

def load_all_candles():
    raw_m1 = {}
    for sym in SYMBOLS:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        if not p.exists(): continue
        df = pd.read_parquet(p)
        if not isinstance(df.index, pd.DatetimeIndex):
            col = "time" if "time" in df.columns else "timestamp"
            df[col] = pd.to_datetime(df[col])
            df.set_index(col, inplace=True)
        raw_m1[sym] = df
    return raw_m1

def test_stop_configurations(raw_m1, fibo_entry=0.705, fibo_stop=0.790, k=3):
    all_trades = []
    intrabar_stops = 0

    for sym in SYMBOLS:
        if sym not in raw_m1:
            continue
        df_m1 = raw_m1[sym]
        spread = SPREADS[sym]

        cfg = FiboOTEConfig(
            fibo_entry=fibo_entry,
            fibo_stop=fibo_stop,
            target_mode="0_percent",
            trailing_exit_ma="ema8",
            pivot_k=k,
        )
        strategy = FiboOTEStrategy(cfg)
        trades = strategy.run_backtest(df_m1, sym, spread=spread)
        for t in trades:
            if t.exit_reason == "INTRABAR_STOP_LOSS":
                intrabar_stops += 1
            all_trades.append({
                "symbol": sym,
                "time": t.entry_time,
                "r": t.r_multiple,
                "win": t.win,
            })

    return all_trades, intrabar_stops

def main():
    raw_m1 = load_all_candles()
    configs = [
        ("Stop 79.0% (Apertado - Sweet Spot)", 0.705, 0.790),
        ("Stop 88.6% (Deep Invalidation)", 0.705, 0.886),
        ("Stop 100.0% (Fundo Estrutural SMC)", 0.705, 1.000),
        ("Entrada 61.8% / Stop 100% (Clássico SMC)", 0.618, 1.000),
        ("Entrada 61.8% / Stop 79.0%", 0.618, 0.790),
    ]

    print(f"{'Configuração (Com Auditoria Intrabar 100% Ativa)':<48} | {'Trades':<6} | {'WinRate':<7} | {'Total R':<10} | {'R / Ano':<9} | {'PF':<5} | {'MaxDD'}")
    print("-" * 105)
    for name, f_ent, f_stp in configs:
        trades, ib_stops = test_stop_configurations(raw_m1, f_ent, f_stp)
        st = get_stats(trades)
        print(f"{name:<48} | {st['trades']:<6} | {st['wr']:>6.1f}% | {st['r_total']:>9.1f}R | {st['r_year']:>8.1f}R | {st['pf']:>5.2f} | -{st['mdd']:>4.1f}R")
    print("-" * 105)

if __name__ == "__main__":
    main()

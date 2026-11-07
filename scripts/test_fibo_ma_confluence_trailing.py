"""
Teste Quantitativo: SMC-Fibo-OTE com Médias Móveis
Testa 3 Novas Dimensões:
1. Confluência no Toque de Fibo: MMA20, MMA50, MME80
2. Filtro de Tendência Alinhada: MME80 + MMA200
3. Condução / Trailing Stop por Média: MMA9, MME8, MMA20, MME80
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

def load_precomputed_m5() -> dict[str, pd.DataFrame]:
    data = {}
    print("⏳ Carregando candles M1 e calculando indicadores M5...")
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

        # Médias Móveis
        df_m5["sma9"] = df_m5["close"].rolling(9).mean()
        df_m5["ema8"] = df_m5["close"].ewm(span=8, adjust=False).mean()
        df_m5["sma20"] = df_m5["close"].rolling(20).mean()
        df_m5["sma50"] = df_m5["close"].rolling(50).mean()
        df_m5["ema80"] = df_m5["close"].ewm(span=80, adjust=False).mean()
        df_m5["sma200"] = df_m5["close"].rolling(200).mean()

        data[sym] = df_m5.dropna().copy()
    print("✅ Dados e Médias Móveis carregados.")
    return data

def simulate_fibo_ma(
    df: pd.DataFrame,
    spread: float,
    fibo_entry: float = 0.705,
    fibo_stop: float = 0.790,
    target_mode: str = "0_percent",
    confluence_ma: str | None = None,     # 'sma20', 'sma50', 'ema80' ou None
    trend_filter_80_200: bool = False,    # EMA80 > SMA200 (Long) / EMA80 < SMA200 (Short)
    trailing_exit_ma: str | None = None,  # 'sma9', 'ema8', 'sma20', 'ema80' ou None
    k: int = 3
) -> list[dict[str, Any]]:
    cfg = FiboOTEConfig(
        fibo_entry=fibo_entry,
        fibo_stop=fibo_stop,
        target_mode=target_mode,
        trailing_exit_ma=trailing_exit_ma,
        confluence_ma=confluence_ma,
        trend_filter_80_200=trend_filter_80_200,
        pivot_k=k,
    )
    strategy = FiboOTEStrategy(cfg)
    trades = strategy.run_backtest(df, "SIM", spread=spread)
    return [{"r": t.r_multiple, "win": t.win, "entry_time": t.entry_time} for t in trades]

def evaluate_suite(name: str, params: dict[str, Any], data: dict[str, pd.DataFrame]) -> dict[str, Any]:
    split_date = pd.Timestamp("2026-05-01", tz="UTC")
    all_trades = []
    sym_r = {}

    for sym in SYMBOLS:
        df = data[sym]
        spread = SPREADS[sym]
        trades = simulate_fibo_ma(df, spread, **params)
        df_t = pd.DataFrame(trades)
        if not df_t.empty:
            df_t["symbol"] = sym
            all_trades.append(df_t)
            sym_r[sym] = df_t["r"].sum()
        else:
            sym_r[sym] = 0.0

    if not all_trades:
        return {"name": name, "trades": 0, "win_rate": 0, "total_r": 0, "is_r": 0, "oos_r": 0, "pf": 0, "max_dd": 0, "pos": 0}

    df_res = pd.concat(all_trades, ignore_index=True)
    n_t = len(df_res)
    wr = (df_res["win"] == True).sum() / n_t * 100
    tot_r = df_res["r"].sum()

    df_res["entry_time"] = pd.to_datetime(df_res["entry_time"])
    is_r = df_res[df_res["entry_time"] < split_date]["r"].sum()
    oos_r = df_res[df_res["entry_time"] >= split_date]["r"].sum()

    gp = df_res[df_res["win"] == True]["r"].sum()
    gl = abs(df_res[df_res["win"] == False]["r"].sum())
    pf = (gp / gl) if gl > 0 else np.nan

    cum = df_res["r"].cumsum()
    max_dd = (cum.cummax() - cum).max()
    pos_count = sum(1 for v in sym_r.values() if v > 0)

    return {
        "name": name,
        "trades": n_t,
        "win_rate": wr,
        "total_r": tot_r,
        "is_r": is_r,
        "oos_r": oos_r,
        "pf": pf,
        "max_dd": max_dd,
        "pos": pos_count,
        "sym_r": sym_r
    }

def main():
    print("=" * 80)
    print("🔬 TESTE QUANTITATIVO: FIBONACCI OTE + MÉDIAS MÓVEIS (3 NOVAS DIMENSÕES)")
    print("=" * 80 + "\n")

    data = load_precomputed_m5()

    experiments = [
        # BASELINE (Campeã Agressiva)
        ("1. Baseline Oficial (Sem Filtros de Média)", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": None, "trend_filter_80_200": False, "trailing_exit_ma": None
        }),

        # DIMENSÃO 1: CONFLUÊNCIA NO TOQUE DE FIBO
        ("2. Confluência com MMA 20 no Toque", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": "sma20", "trend_filter_80_200": False, "trailing_exit_ma": None
        }),
        ("3. Confluência com MMA 50 no Toque", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": "sma50", "trend_filter_80_200": False, "trailing_exit_ma": None
        }),
        ("4. Confluência com MME 80 no Toque", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": "ema80", "trend_filter_80_200": False, "trailing_exit_ma": None
        }),

        # DIMENSÃO 2: FILTRO DE TENDÊNCIA ALINHADA (MME 80 + MMA 200)
        ("5. Filtro de Tendência Alinhada (MME80 + MMA200)", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": None, "trend_filter_80_200": True, "trailing_exit_ma": None
        }),

        # DIMENSÃO 3: CONDUÇÃO POR MÉDIA MÓVEL (TRAILING STOP)
        ("6. Condução por MMA 9 (Trailing)", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": None, "trend_filter_80_200": False, "trailing_exit_ma": "sma9"
        }),
        ("7. Condução por MME 8 (Trailing)", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": None, "trend_filter_80_200": False, "trailing_exit_ma": "ema8"
        }),
        ("8. Condução por MMA 20 (Trailing)", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": None, "trend_filter_80_200": False, "trailing_exit_ma": "sma20"
        }),
        ("9. Condução por MME 80 (Trailing)", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": None, "trend_filter_80_200": False, "trailing_exit_ma": "ema80"
        }),

        # COMBO: FILTRO 80/200 + CONFLUÊNCIA
        ("10. Combo: Filtro MME80/200 + Confluência MMA20", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": "sma20", "trend_filter_80_200": True, "trailing_exit_ma": None
        })
    ]

    out_records = []
    print("🚀 Executando simulações das 10 variações nos 7 ativos...\n")
    for name, p in experiments:
        res = evaluate_suite(name, p, data)
        out_records.append(res)
        print(f"📊 {name:48s} -> Trades: {res['trades']:4d} | WR: {res['win_rate']:4.1f}% | Total: {res['total_r']:+7.1f}R | OOS: {res['oos_r']:+7.1f}R | PF: {res['pf']:.2f} | MaxDD: -{res['max_dd']:.1f}R | Ativos: {res['pos']}/7")

    df_out = pd.DataFrame([{
        "Estratégia": r["name"],
        "Trades": r["trades"],
        "Win Rate (%)": round(r["win_rate"], 1),
        "Total (R)": round(r["total_r"], 1),
        "In-Sample (R)": round(r["is_r"], 1),
        "Out-of-Sample (R)": round(r["oos_r"], 1),
        "Profit Factor": round(r["pf"], 2),
        "Max Drawdown (R)": round(r["max_dd"], 1),
        "Ativos Positivos": f"{r['pos']}/7"
    } for r in out_records])

    csv_path = Path("out/fibo_optimization/fibo_ma_experiments.csv")
    df_out.to_csv(csv_path, index=False)
    print(f"\n📁 Resultados salvos em: {csv_path}")

if __name__ == "__main__":
    main()

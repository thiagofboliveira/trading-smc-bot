"""Estudo Científico e Quantitativo: Filtros de Confluência com Médias Móveis no SMC Fibo OTE.

Testa o impacto de 5 médias móveis:
- MMA 20 (sma20)
- MMA 50 (sma50)
- MMA 200 (sma200)
- MME 80 (ema80)
- MME 20 (ema20)

Sob duas abordagens de confluência:
1. Confluência no Toque (Touch Confluence): O candle da retração toca a média móvel.
2. Filtro de Tendência / Regime (Trend Alignment): O preço está a favor da média (Long > MA, Short < MA).
"""

from pathlib import Path
from typing import Any
import pandas as pd
import yaml

from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy

with open("config/default.yaml", "r", encoding="utf-8") as f:
    _CFG = yaml.safe_load(f)

CONTRACTS = _CFG.get("contracts", {})
SPREADS = {
    sym: spec.get("spread", 0.0)
    for sym, spec in CONTRACTS.items()
    if isinstance(spec, dict) and "spread" in spec
}

SYMBOLS = ["XAUUSD", "NAS100", "US30", "BRENT", "EURUSD", "GBPUSD"]


def load_data() -> dict[str, pd.DataFrame]:
    data = {}
    print("⏳ Carregando dados M1 dos ativos locais...")
    for sym in SYMBOLS:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        if not p.exists():
            continue
        df_m1 = pd.read_parquet(p)
        if not isinstance(df_m1.index, pd.DatetimeIndex):
            col = "time" if "time" in df_m1.columns else "timestamp"
            df_m1[col] = pd.to_datetime(df_m1[col])
            df_m1.set_index(col, inplace=True)
        data[sym] = df_m1.sort_index()
    print(f"✅ Dados carregados: {list(data.keys())}\n")
    return data


def run_experiment(
    data: dict[str, pd.DataFrame],
    fibo_entry: float,
    fibo_stop: float,
    session_filter: bool,
    confluence_ma: str | None,
    trend_ma: str | None,
) -> dict[str, Any]:
    cfg = FiboOTEConfig(
        fibo_entry=fibo_entry,
        fibo_stop=fibo_stop,
        target_mode="0_percent",
        trailing_exit_ma=None,
        confluence_ma=confluence_ma,
        trend_ma=trend_ma,
        session_filter=session_filter,
        session_windows=[("07:00", "18:00")] if session_filter else None,
        pivot_k=2,
    )
    strat = FiboOTEStrategy(cfg)
    all_trades = []
    sym_stats = {}

    for sym, df in data.items():
        spread = SPREADS.get(sym, 0.0)
        trades = strat.run_backtest(df, sym, spread=spread)
        all_trades.extend(trades)
        r_sym = sum(t.r_multiple for t in trades)
        sym_stats[sym] = {
            "trades": len(trades),
            "r": r_sym,
            "wr": (sum(1 for t in trades if t.r_multiple > 0) / len(trades) * 100) if trades else 0.0,
        }

    n = len(all_trades)
    if n == 0:
        return {
            "trades": 0, "r_total": 0.0, "wr": 0.0, "pf": 0.0,
            "max_dd": 0.0, "pos_assets": 0, "sym_stats": sym_stats
        }

    wins = [t.r_multiple for t in all_trades if t.r_multiple > 0]
    losses = [abs(t.r_multiple) for t in all_trades if t.r_multiple <= 0]
    wr = len(wins) / n * 100.0
    pf = sum(wins) / sum(losses) if sum(losses) > 0 else 999.0
    r_total = sum(t.r_multiple for t in all_trades)

    # Max Drawdown em R
    r_series = pd.Series([t.r_multiple for t in all_trades])
    cum = r_series.cumsum()
    dd = (cum.cummax() - cum).max()
    pos_assets = sum(1 for s, st in sym_stats.items() if st["r"] > 0)

    return {
        "trades": n,
        "r_total": r_total,
        "wr": wr,
        "pf": pf,
        "max_dd": dd,
        "pos_assets": pos_assets,
        "sym_stats": sym_stats,
    }


def main():
    data = load_data()

    mas = ["sma20", "sma50", "sma200", "ema80", "ema20"]

    print("=" * 100)
    print("🔬 BATERIA 1: CONFLUÊNCIA NO TOQUE (TOUCH CONFLUENCE) — Entrada 0.618 / Stop 0.800 (Sessão Londres/NY)")
    print("=" * 100)

    # 1. Baseline
    base_res = run_experiment(data, fibo_entry=0.618, fibo_stop=0.800, session_filter=True, confluence_ma=None, trend_ma=None)
    print(f"📌 BASELINE (Sem Média)      | Trades: {base_res['trades']:4d} | WR: {base_res['wr']:4.1f}% | R Total: {base_res['r_total']:+7.1f}R | PF: {base_res['pf']:4.2f} | MaxDD: {base_res['max_dd']:5.1f}R | Pos: {base_res['pos_assets']}/6")

    touch_results = []
    for ma in mas:
        res = run_experiment(data, fibo_entry=0.618, fibo_stop=0.800, session_filter=True, confluence_ma=ma, trend_ma=None)
        touch_results.append((f"Toque com {ma.upper()}", res))
        print(f"👉 Toque com {ma.upper():6s}        | Trades: {res['trades']:4d} | WR: {res['wr']:4.1f}% | R Total: {res['r_total']:+7.1f}R | PF: {res['pf']:4.2f} | MaxDD: {res['max_dd']:5.1f}R | Pos: {res['pos_assets']}/6")

    print("\n" + "=" * 100)
    print("🔬 BATERIA 2: FILTRO DE TENDÊNCIA / REGIME (TREND ALIGNMENT) — Entrada 0.618 / Stop 0.800 (Sessão Londres/NY)")
    print("=" * 100)

    trend_results = []
    for ma in mas:
        res = run_experiment(data, fibo_entry=0.618, fibo_stop=0.800, session_filter=True, confluence_ma=None, trend_ma=ma)
        trend_results.append((f"Regime com {ma.upper()}", res))
        print(f"👉 Regime com {ma.upper():6s}       | Trades: {res['trades']:4d} | WR: {res['wr']:4.1f}% | R Total: {res['r_total']:+7.1f}R | PF: {res['pf']:4.2f} | MaxDD: {res['max_dd']:5.1f}R | Pos: {res['pos_assets']}/6")

    print("\n" + "=" * 100)
    print("🔬 BATERIA 3: FOCO NO OURO (XAUUSD) — Testando Stop 0.800 vs Stop 1.000")
    print("=" * 100)
    gold_data = {"XAUUSD": data["XAUUSD"]}
    for stop in [0.800, 1.000]:
        print(f"\n--- XAUUSD com Entrada 0.618 / Stop {stop:.3f} ---")
        g_base = run_experiment(gold_data, fibo_entry=0.618, fibo_stop=stop, session_filter=True, confluence_ma=None, trend_ma=None)
        print(f"  Baseline XAUUSD (Sem MA)  | Trades: {g_base['trades']:3d} | WR: {g_base['wr']:4.1f}% | R: {g_base['r_total']:+6.1f}R | PF: {g_base['pf']:4.2f}")
        for ma in mas:
            g_touch = run_experiment(gold_data, fibo_entry=0.618, fibo_stop=stop, session_filter=True, confluence_ma=ma, trend_ma=None)
            g_trend = run_experiment(gold_data, fibo_entry=0.618, fibo_stop=stop, session_filter=True, confluence_ma=None, trend_ma=ma)
            print(f"  MA {ma.upper():6s} -> Toque: {g_touch['trades']:2d} trades, {g_touch['wr']:4.1f}% WR, {g_touch['r_total']:+5.1f}R, PF {g_touch['pf']:.2f} | Regime: {g_trend['trades']:2d} trades, {g_trend['wr']:4.1f}% WR, {g_trend['r_total']:+5.1f}R, PF {g_trend['pf']:.2f}")

    print("\n" + "=" * 100)
    print("🔬 BATERIA 4: ÍNDICES (NAS100 e US30) — Entrada 0.618 / Stop 0.800")
    print("=" * 100)
    idx_data = {k: data[k] for k in ["NAS100", "US30"] if k in data}
    idx_base = run_experiment(idx_data, fibo_entry=0.618, fibo_stop=0.800, session_filter=True, confluence_ma=None, trend_ma=None)
    print(f"  Baseline Índices (Sem MA) | Trades: {idx_base['trades']:3d} | WR: {idx_base['wr']:4.1f}% | R: {idx_base['r_total']:+6.1f}R | PF: {idx_base['pf']:4.2f}")
    for ma in mas:
        idx_touch = run_experiment(idx_data, fibo_entry=0.618, fibo_stop=0.800, session_filter=True, confluence_ma=ma, trend_ma=None)
        idx_trend = run_experiment(idx_data, fibo_entry=0.618, fibo_stop=0.800, session_filter=True, confluence_ma=None, trend_ma=ma)
        print(f"  MA {ma.upper():6s} -> Toque: {idx_touch['trades']:2d} trades, {idx_touch['wr']:4.1f}% WR, {idx_touch['r_total']:+5.1f}R, PF {idx_touch['pf']:.2f} | Regime: {idx_trend['trades']:2d} trades, {idx_trend['wr']:4.1f}% WR, {idx_trend['r_total']:+5.1f}R, PF {idx_trend['pf']:.2f}")


if __name__ == "__main__":
    main()

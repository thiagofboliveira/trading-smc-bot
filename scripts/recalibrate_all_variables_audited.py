"""Recalibração Global e Científica de Variáveis — Versão 100% Auditada.

Testa sistematicamente todas as dimensões da estratégia Fibo OTE:
1. Entrada: 61.8% (0.618) vs 70.5% (0.705) vs 79.0% (0.790)
2. Stop Loss: 79.0% (0.790) vs 80.0% (0.800) vs 88.6% (0.886) vs 100.0% (1.000)
3. Condução / Saída:
   - trailing_ema8 (condução MME8 com proteção de lucro)
   - lock_2to1 (trava 2:1 com condução MME8)
   - target_3r (alvo fixo 3R)
   - target_0_pct (alvo no 0% Fibo - topo/fundo da perna)
4. Filtro de Sessão: 24h vs Londres/NY (07:00 às 18:00 UTC)
"""

from pathlib import Path
from typing import Any
import pandas as pd
import yaml

from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy

# Carrega contratos e spreads oficiais
with open("config/default.yaml", "r", encoding="utf-8") as f:
    _CFG = yaml.safe_load(f)

CONTRACTS = _CFG.get("contracts", {})
SPREADS = {
    sym: spec.get("spread", 0.0)
    for sym, spec in CONTRACTS.items()
    if isinstance(spec, dict) and "spread" in spec
}

SYMBOLS = ["XAUUSD", "NAS100", "US30", "BRENT", "EURUSD", "GBPUSD"]


def load_all_m1_candles() -> dict[str, pd.DataFrame]:
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
    print(f"✅ Dados carregados com sucesso: {list(data.keys())}")
    return data


def simulate_variant(
    data: dict[str, pd.DataFrame],
    entry: float,
    stop: float,
    exit_mode: str,
    session_filter: bool,
    target_sym: str | None = None,
) -> dict[str, Any] | None:
    target_mode = "3R" if exit_mode == "target_3r" else "0_percent"
    trailing_exit_ma = "ema8" if exit_mode in ("trailing_ema8", "lock_2to1") else None
    use_lock = (exit_mode == "lock_2to1")

    cfg = FiboOTEConfig(
        fibo_entry=entry,
        fibo_stop=stop,
        target_mode=target_mode,
        trailing_exit_ma=trailing_exit_ma,
        trailing_profit_only=True,
        use_lock_2to1=use_lock,
        lock_trigger_r=2.0 if use_lock else 2.0,
        lock_guarantee_r=1.0 if use_lock else 1.0,
        session_filter=session_filter,
        session_windows=[("07:00", "18:00")] if session_filter else None,
        pivot_k=2,
    )
    strat = FiboOTEStrategy(cfg)

    all_trades = []
    symbols_to_test = [target_sym] if target_sym else list(data.keys())

    for sym in symbols_to_test:
        if sym not in data:
            continue
        df = data[sym]
        spread = SPREADS.get(sym, 0.0)
        trades = strat.run_backtest(df, sym, spread=spread)
        all_trades.extend(trades)

    if not all_trades:
        return None

    n = len(all_trades)
    r_total = sum(t.r_multiple for t in all_trades)
    wins = [t.r_multiple for t in all_trades if t.r_multiple > 0]
    losses = [abs(t.r_multiple) for t in all_trades if t.r_multiple <= 0]

    wr = (len(wins) / n * 100.0) if n > 0 else 0.0
    pf = (sum(wins) / sum(losses)) if sum(losses) > 0 else (999.0 if sum(wins) > 0 else 0.0)
    payoff = (sum(wins) / len(wins)) / (sum(losses) / len(losses)) if wins and losses else 0.0

    # Drawdown
    sorted_trades = sorted(all_trades, key=lambda t: t.exit_time)
    cum_r = 0.0
    peak_r = 0.0
    max_dd = 0.0
    for t in sorted_trades:
        cum_r += t.r_multiple
        if cum_r > peak_r:
            peak_r = cum_r
        else:
            dd = peak_r - cum_r
            if dd > max_dd:
                max_dd = dd

    first_t = sorted_trades[0].entry_time
    last_t = sorted_trades[-1].exit_time
    days = max(1.0, (last_t - first_t).total_seconds() / 86400.0)
    years = days / 365.25

    return {
        "symbol": target_sym or "ALL",
        "entry": entry,
        "stop": stop,
        "exit_mode": exit_mode,
        "session": "07-18 UTC" if session_filter else "24h",
        "trades": n,
        "wr": round(wr, 1),
        "total_r": round(r_total, 1),
        "r_year": round(r_total / years, 1) if years > 0 else 0.0,
        "pf": round(pf, 2),
        "payoff": round(payoff, 2),
        "mdd": round(max_dd, 1),
    }


def main():
    data = load_all_m1_candles()

    entries = [0.618, 0.705, 0.790]
    stops = [0.790, 0.800, 0.886, 1.000]
    exits = ["trailing_ema8", "lock_2to1", "target_3r", "target_0_pct"]
    sessions = [False, True]

    print("\n🔍 Executando Grade Completa de Recalibração de Variáveis...")
    results = []

    for ent in entries:
        for stp in stops:
            if stp <= ent:
                continue
            for ex in exits:
                for sess in sessions:
                    res = simulate_variant(data, ent, stp, ex, sess)
                    if res:
                        results.append(res)

    df_res = pd.DataFrame(results).sort_values("total_r", ascending=False)
    Path("reports").mkdir(exist_ok=True)
    df_res.to_csv("reports/audited_variable_recalibration_2years.csv", index=False)

    print("\n" + "=" * 115)
    print("🏆 TOP 15 CONFIGURAÇÕES AUDITADAS (TODOS OS ATIVOS AGREGADOS)")
    print("=" * 115)
    print(f"{'Entrada':<8} | {'Stop':<6} | {'Saída / Gestão':<16} | {'Sessão':<10} | {'Trades':<6} | {'WinRate':<7} | {'Total R':<9} | {'R / Ano':<8} | {'PF':<5} | {'Payoff':<6} | {'MaxDD'}")
    print("-" * 115)
    for _, r in df_res.head(15).iterrows():
        print(f"{r['entry']:>8.3f} | {r['stop']:>6.3f} | {r['exit_mode']:<16} | {r['session']:<10} | {r['trades']:<6} | {r['wr']:>6.1f}% | {r['total_r']:>8.1f}R | {r['r_year']:>7.1f}R | {r['pf']:>5.2f} | {r['payoff']:>6.2f} | -{r['mdd']:>4.1f}R")
    print("-" * 115)

    # Estudo Focado: Entrada 0.618 vs Stops (0.790, 0.800, 0.886, 1.000)
    print("\n" + "=" * 115)
    print("🎯 FOCO SOLICITADO: ENTRADA 0.618 COM STOP 0.800 VS OUTROS STOPS (TODOS OS ATIVOS)")
    print("=" * 115)
    foco = df_res[df_res["entry"] == 0.618]
    print(f"{'Entrada':<8} | {'Stop':<6} | {'Saída / Gestão':<16} | {'Sessão':<10} | {'Trades':<6} | {'WinRate':<7} | {'Total R':<9} | {'PF':<5} | {'Payoff':<6} | {'MaxDD'}")
    print("-" * 115)
    for _, r in foco.sort_values(["stop", "total_r"], ascending=[True, False]).iterrows():
        print(f"{r['entry']:>8.3f} | {r['stop']:>6.3f} | {r['exit_mode']:<16} | {r['session']:<10} | {r['trades']:<6} | {r['wr']:>6.1f}% | {r['total_r']:>8.1f}R | {r['pf']:>5.2f} | {r['payoff']:>6.2f} | -{r['mdd']:>4.1f}R")
    print("-" * 115)

    # Detalhamento por Ativo Individual para Entrada 0.618 e Stop 0.800
    print("\n" + "=" * 115)
    print("📌 DESEMPENHO ATIVO POR ATIVO: ENTRADA 0.618 | STOP 0.800 (LOCK 2:1 vs TRAILING MME8)")
    print("=" * 115)
    print(f"{'Ativo':<8} | {'Saída / Gestão':<16} | {'Sessão':<10} | {'Trades':<6} | {'WinRate':<7} | {'Total R':<9} | {'PF':<5} | {'Payoff':<6} | {'MaxDD'}")
    print("-" * 115)
    for sym in list(data.keys()):
        for ex in ["lock_2to1", "trailing_ema8", "target_3r"]:
            for sess in [False, True]:
                res = simulate_variant(data, 0.618, 0.800, ex, sess, target_sym=sym)
                if res and res["trades"] > 0:
                    print(f"{sym:<8} | {res['exit_mode']:<16} | {res['session']:<10} | {res['trades']:<6} | {res['wr']:>6.1f}% | {res['total_r']:>8.1f}R | {res['pf']:>5.2f} | {res['payoff']:>6.2f} | -{res['mdd']:>4.1f}R")
    print("-" * 115)


if __name__ == "__main__":
    main()

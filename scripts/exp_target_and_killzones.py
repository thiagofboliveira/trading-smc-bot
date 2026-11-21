"""
Experimento Quantitativo Auditado (Pós-Correção F-17 Inducement, F-03 Lock Intrabar e Persistência da Perna na Zona):
Avaliação de Alvos Estruturais e Killzones na Estratégia SMC Fibo Rejeição EMA80 Pavio.

Reporta separadamente:
- Ano 1 (2024-11 a 2025-10) vs Ano 2 (2025-11 a 2026-11)
- Cesta (BRENT, NAS100, XAUUSD) vs Portfólio Completo (7 ativos)
"""

from pathlib import Path

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

SYMBOLS = ["BRENT", "NAS100", "XAUUSD", "DAX40", "EURUSD", "GBPUSD", "USDJPY"]
SPLIT_TS = pd.Timestamp("2025-11-01", tz="UTC")


def load_data():
    raw = {}
    for sym in SYMBOLS:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if not isinstance(df.index, pd.DatetimeIndex):
            col = "time" if "time" in df.columns else "timestamp"
            df[col] = pd.to_datetime(df[col])
            df.set_index(col, inplace=True)
        raw[sym] = df.sort_index()
    return raw


def compute_metrics(trades):
    if not trades:
        return {
            "n_trades": 0,
            "r_total": 0.0,
            "y1_r": 0.0,
            "y2_r": 0.0,
            "wr": 0.0,
            "pf": 0.0,
            "max_dd": 0.0,
            "r_per_trade": 0.0,
        }
    n = len(trades)
    r_total = sum(t.r_multiple for t in trades)
    y1_r = sum(t.r_multiple for t in trades if t.entry_time < SPLIT_TS)
    y2_r = sum(t.r_multiple for t in trades if t.entry_time >= SPLIT_TS)
    wins = [t.r_multiple for t in trades if t.r_multiple > 0]
    losses = [abs(t.r_multiple) for t in trades if t.r_multiple <= 0]
    wr = (len(wins) / n * 100.0) if n > 0 else 0.0
    pf = (
        (sum(wins) / sum(losses))
        if sum(losses) > 0
        else (999.0 if sum(wins) > 0 else 0.0)
    )

    sorted_trades = sorted(trades, key=lambda t: t.exit_time)
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

    return {
        "n_trades": n,
        "r_total": round(r_total, 2),
        "y1_r": round(y1_r, 2),
        "y2_r": round(y2_r, 2),
        "wr": round(wr, 1),
        "pf": round(pf, 2),
        "max_dd": round(max_dd, 1),
        "r_per_trade": round(r_total / n, 3) if n > 0 else 0.0,
    }


def main():
    print("⏳ Carregando dados históricos locais (M1)...")
    data = load_data()
    print(f"✅ Ativos disponíveis: {list(data.keys())}\n")

    test_cases = [
        {
            "name": "1. Baseline (Alvo 4.0R, Sessão Ampla 07-18)",
            "target_mode": "3R",
            "target_r": 4.0,
            "session_windows": [("07:00", "18:00")],
            "lock_trig": 1.618,
            "lock_guar": 1.0,
            "wick_ratio": 0.50,
            "req_idm": True,
        },
        {
            "name": "2. Alvo 3.0R (Sessão Ampla 07-18)",
            "target_mode": "3R",
            "target_r": 3.0,
            "session_windows": [("07:00", "18:00")],
            "lock_trig": 1.618,
            "lock_guar": 1.0,
            "wick_ratio": 0.50,
            "req_idm": True,
        },
        {
            "name": "3. Alvo 2.5R (Sessão Ampla 07-18)",
            "target_mode": "3R",
            "target_r": 2.5,
            "session_windows": [("07:00", "18:00")],
            "lock_trig": 1.618,
            "lock_guar": 1.0,
            "wick_ratio": 0.50,
            "req_idm": True,
        },
        {
            "name": "4. Alvo 0.0% Estrutural (Topo/Fundo do BOS)",
            "target_mode": "0_percent",
            "target_r": 3.0,
            "session_windows": [("07:00", "18:00")],
            "lock_trig": 1.618,
            "lock_guar": 1.0,
            "wick_ratio": 0.50,
            "req_idm": True,
        },
        {
            "name": "5. ICT Killzones [07-10:30, 12:30-16:30] (Alvo 4R)",
            "target_mode": "3R",
            "target_r": 4.0,
            "session_windows": [("07:00", "10:30"), ("12:30", "16:30")],
            "lock_trig": 1.618,
            "lock_guar": 1.0,
            "wick_ratio": 0.50,
            "req_idm": True,
        },
        {
            "name": "6. London Killzone Apenas [07:00 - 11:30] (Alvo 4R)",
            "target_mode": "3R",
            "target_r": 4.0,
            "session_windows": [("07:00", "11:30")],
            "lock_trig": 1.618,
            "lock_guar": 1.0,
            "wick_ratio": 0.50,
            "req_idm": True,
        },
        {
            "name": "7. NY Killzone Apenas [12:30 - 17:00] (Alvo 4R)",
            "target_mode": "3R",
            "target_r": 4.0,
            "session_windows": [("12:30", "17:00")],
            "lock_trig": 1.618,
            "lock_guar": 1.0,
            "wick_ratio": 0.50,
            "req_idm": True,
        },
        {
            "name": "8. NY Killzone Apenas [12:30 - 17:00] (Alvo 3R)",
            "target_mode": "3R",
            "target_r": 3.0,
            "session_windows": [("12:30", "17:00")],
            "lock_trig": 1.618,
            "lock_guar": 1.0,
            "wick_ratio": 0.50,
            "req_idm": True,
        },
        {
            "name": "9. NY Killzone [12:30 - 17:00] (Alvo 4R, Sem IDM)",
            "target_mode": "3R",
            "target_r": 4.0,
            "session_windows": [("12:30", "17:00")],
            "lock_trig": 1.618,
            "lock_guar": 1.0,
            "wick_ratio": 0.50,
            "req_idm": False,
        },
        {
            "name": "10. Confluência ICT Killzones + Alvo 3.0R",
            "target_mode": "3R",
            "target_r": 3.0,
            "session_windows": [("07:00", "10:30"), ("12:30", "16:30")],
            "lock_trig": 1.618,
            "lock_guar": 1.0,
            "wick_ratio": 0.50,
            "req_idm": True,
        },
        {
            "name": "11. Sem Trava de Lucro (Corre solto até 4R)",
            "target_mode": "3R",
            "target_r": 4.0,
            "session_windows": [("07:00", "18:00")],
            "lock_trig": None,
            "lock_guar": 0.0,
            "wick_ratio": 0.50,
            "req_idm": True,
        },
    ]

    results = []
    basket = ["BRENT", "NAS100", "XAUUSD"]

    print(
        f"{'Cenário':<52} | {'Tr':<4} | {'R Tot':<7} | {'Ano 1':<7} | {'Ano 2':<7} | {'WR%':<5} | {'PF':<5} | {'DD':<5} | {'7Ativos R':<9}"
    )
    print("-" * 120)

    for tc in test_cases:
        cfg = FiboOTEConfig(
            fibo_entry=0.500,
            fibo_rejection_max=0.790,
            fibo_stop=0.886,
            entry_mode="m5_close_rejection",
            stop_mode="fibo",
            rejection_min_wick_ratio=tc["wick_ratio"],
            target_mode=tc["target_mode"],
            target_r=tc["target_r"],
            pivot_k=2,
            trailing_exit_ma=None,
            trend_ma="ema80",
            confluence_ma="ema80",
            bos_swing_trailing=False,
            require_inducement=tc["req_idm"],
            max_trades_per_day=3,
            max_stops_per_day=2,
            max_gains_per_day=1,
            profit_lock_trigger_r=tc["lock_trig"],
            profit_lock_guarantee_r=tc["lock_guar"],
            session_filter=True,
            session_windows=tc["session_windows"],
        )
        strat = FiboOTEStrategy(cfg)
        trades_by_sym = {}
        for sym, df in data.items():
            trades_by_sym[sym] = strat.run_backtest(df, sym, spread=SPREADS.get(sym, 0.0))

        basket_trades = [t for s in basket if s in trades_by_sym for t in trades_by_sym[s]]
        all_trades = [t for s in data.keys() for t in trades_by_sym[s]]

        res_basket = compute_metrics(basket_trades)
        res_all = compute_metrics(all_trades)

        name = tc["name"]
        print(
            f"{name:<52} | {res_basket['n_trades']:<4} | {res_basket['r_total']:<+7.2f} | "
            f"{res_basket['y1_r']:<+7.2f} | {res_basket['y2_r']:<+7.2f} | {res_basket['wr']:<5.1f} | "
            f"{res_basket['pf']:<5.2f} | {res_basket['max_dd']:<5.1f} | {res_all['r_total']:<+9.2f}"
        )

        results.append(
            {
                "scenario": name,
                "basket_trades": res_basket["n_trades"],
                "basket_r": res_basket["r_total"],
                "basket_y1_r": res_basket["y1_r"],
                "basket_y2_r": res_basket["y2_r"],
                "basket_wr": res_basket["wr"],
                "basket_pf": res_basket["pf"],
                "basket_maxdd": res_basket["max_dd"],
                "basket_r_per_trade": res_basket["r_per_trade"],
                "brent_r": round(sum(t.r_multiple for t in trades_by_sym.get("BRENT", [])), 2),
                "nas100_r": round(sum(t.r_multiple for t in trades_by_sym.get("NAS100", [])), 2),
                "xauusd_r": round(sum(t.r_multiple for t in trades_by_sym.get("XAUUSD", [])), 2),
                "all_trades": res_all["n_trades"],
                "all_r": res_all["r_total"],
                "all_y1_r": res_all["y1_r"],
                "all_y2_r": res_all["y2_r"],
                "all_pf": res_all["pf"],
                "all_maxdd": res_all["max_dd"],
            }
        )

    df_res = pd.DataFrame(results)
    out_path = Path("reports/exp_target_and_killzones_results.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_res.to_csv(out_path, index=False)
    print(f"\n📊 Resultados auditados exportados para: {out_path}")


if __name__ == "__main__":
    main()

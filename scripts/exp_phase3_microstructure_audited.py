"""
Experimento Quantitativo Auditado — Fase 3 (Geometria da Perna e Microestrutura do Gatilho):
Avalia as 8 novas dimensões sobre a base ICT Killzones + Rejeição EMA80 Pavio (Alvo 3.0R):
1. Frescor da Perna (max_holding_candles: 24 e 36 vs 60)
2. Amplitude Mínima da Perna (min_leg_spread_mult: 25x vs 10x)
3. Raio do Fractal (pivot_k: 3 vs 2)
4. Zona OTE Estrita [61.8% - 79.0%] e Stop Estrutural 100.0%
5. Rigor do Pavio (40% vs 50% vs 60%) e Média SMA 50 vs EMA 80
6. Corpo Direcional do Candle de Rejeição (close >= open p/ compra)
7. Pico de Volume VSA no Candle de Rejeição (volume >= 1.2x e 1.5x SMA20)
8. Presença de FVG (Fair Value Gap) na Perna Impulsiva do BOS
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
KILLZONES = [("07:00", "10:30"), ("12:30", "16:30")]


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


def make_cfg(**overrides) -> FiboOTEConfig:
    base = dict(
        timeframe="5min",
        fibo_entry=0.500,
        fibo_rejection_max=0.790,
        fibo_stop=0.886,
        entry_mode="m5_close_rejection",
        stop_mode="fibo",
        rejection_min_wick_ratio=0.50,
        target_mode="3R",
        target_r=3.0,
        pivot_k=2,
        max_holding_candles=60,
        min_leg_spread_mult=10.0,
        trailing_exit_ma=None,
        trend_ma="ema80",
        confluence_ma="ema80",
        bos_swing_trailing=False,
        require_inducement=True,
        rejection_require_directional_body=False,
        rejection_min_volume_mult=0.0,
        require_leg_fvg=False,
        max_trades_per_day=3,
        max_stops_per_day=2,
        max_gains_per_day=1,
        profit_lock_trigger_r=1.618,
        profit_lock_guarantee_r=1.0,
        session_filter=True,
        session_windows=KILLZONES,
    )
    base.update(overrides)
    return FiboOTEConfig(**base)


def main():
    print("⏳ Carregando dados históricos locais (M1)...")
    data = load_data()
    print(f"✅ Ativos disponíveis: {list(data.keys())}\n")

    scenarios = [
        ("1. Base Auditada (Killzones + Alvo 3.0R)", make_cfg()),
        ("2. Perna Fresca: max_holding_candles=24 (2h)", make_cfg(max_holding_candles=24)),
        ("3. Perna Fresca: max_holding_candles=36 (3h)", make_cfg(max_holding_candles=36)),
        ("4. Amplitude Mínima: 25x Spread (min_leg=25)", make_cfg(min_leg_spread_mult=25.0)),
        ("5. Amplitude Mínima: 40x Spread (min_leg=40)", make_cfg(min_leg_spread_mult=40.0)),
        ("6. Fractal Maior: pivot_k=3 (7 barras)", make_cfg(pivot_k=3)),
        ("7. Zona OTE Estrita [61.8% - 79.0%]", make_cfg(fibo_entry=0.618)),
        ("8. Stop Estrutural na Origem 100% (fibo_stop=1.0)", make_cfg(fibo_stop=1.000)),
        ("9. Pavio Exigente >= 60% (Pinbar Forte)", make_cfg(rejection_min_wick_ratio=0.60)),
        ("10. Pavio Flexível >= 40%", make_cfg(rejection_min_wick_ratio=0.40)),
        ("11. Corpo Direcional a Favor (close >= open)", make_cfg(rejection_require_directional_body=True)),
        ("12. Volume VSA >= 1.2x SMA20 no Gatilho", make_cfg(rejection_min_volume_mult=1.2)),
        ("13. Volume VSA >= 1.5x SMA20 no Gatilho", make_cfg(rejection_min_volume_mult=1.5)),
        ("14. Exigir FVG (Imbalance) na Perna do BOS", make_cfg(require_leg_fvg=True)),
        ("15. Confluência SMA 50 em vez de EMA 80", make_cfg(trend_ma="sma50", confluence_ma="sma50")),
        ("16. Combo: FVG + Zona OTE [61.8% - 79.0%]", make_cfg(require_leg_fvg=True, fibo_entry=0.618)),
        (
            "17. Combo: FVG + Parcial 50% (+1.5R / BE 0R)",
            make_cfg(
                require_leg_fvg=True,
                partial_exit_trigger_r=1.5,
                partial_exit_pct=0.50,
                profit_lock_trigger_r=1.5,
                profit_lock_guarantee_r=0.0,
            ),
        ),
        (
            "18. Combo: FVG + OTE 61.8% + Parcial 50%",
            make_cfg(
                require_leg_fvg=True,
                fibo_entry=0.618,
                partial_exit_trigger_r=1.5,
                partial_exit_pct=0.50,
                profit_lock_trigger_r=1.5,
                profit_lock_guarantee_r=0.0,
            ),
        ),
    ]

    basket = ["BRENT", "NAS100", "XAUUSD"]
    results = []

    print(
        f"{'Cenário':<50} | {'Tr':<4} | {'R Tot':<7} | {'Ano 1':<7} | {'Ano 2':<7} | {'WR%':<5} | {'PF':<5} | {'DD':<5} | {'7Ativos R':<9}"
    )
    print("-" * 118)

    for name, cfg in scenarios:
        strat = FiboOTEStrategy(cfg)
        trades_by_sym = {}
        for sym, df in data.items():
            trades_by_sym[sym] = strat.run_backtest(df, sym, spread=SPREADS.get(sym, 0.0))

        basket_trades = [t for s in basket if s in trades_by_sym for t in trades_by_sym[s]]
        all_trades = [t for s in data.keys() for t in trades_by_sym[s]]

        res_basket = compute_metrics(basket_trades)
        res_all = compute_metrics(all_trades)

        print(
            f"{name:<50} | {res_basket['n_trades']:<4} | {res_basket['r_total']:<+7.2f} | "
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
                "dax40_r": round(sum(t.r_multiple for t in trades_by_sym.get("DAX40", [])), 2),
                "eurusd_r": round(sum(t.r_multiple for t in trades_by_sym.get("EURUSD", [])), 2),
                "gbpusd_r": round(sum(t.r_multiple for t in trades_by_sym.get("GBPUSD", [])), 2),
                "usdjpy_r": round(sum(t.r_multiple for t in trades_by_sym.get("USDJPY", [])), 2),
                "all_trades": res_all["n_trades"],
                "all_r": res_all["r_total"],
                "all_y1_r": res_all["y1_r"],
                "all_y2_r": res_all["y2_r"],
                "all_pf": res_all["pf"],
                "all_maxdd": res_all["max_dd"],
            }
        )

    df_res = pd.DataFrame(results)
    out_path = Path("reports/exp_phase3_microstructure_audited.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_res.to_csv(out_path, index=False)
    print(f"\n📊 Resultados Fase 3 exportados para: {out_path}")


if __name__ == "__main__":
    main()

"""Simulação da Carteira Unificada Multi-Estratégia (E1 + E2 + E3) e Expansão M5 + M15.

Combina de forma estritamente causal (AGENTS.md):
1. Estratégia 1 (D1 Mean Reversion - RSI2 + IBS): NAS100, US30, SPX500
2. Estratégia 2 (SMC Fibo Rejeição EMA80 Pavio >= 50% + Parcial 1.618R + Lock 1.0R): BRENT, NAS100, XAUUSD (M5)
3. Estratégia 3 (Fibo Dynamic Zone 30° + Macro H1 + ADX 22..35 + Stop 92% + 2 Estágios):
   Testada em M5 e M15 nos 9 ativos aprovados (EURUSD, USDJPY, AUDUSD, GBPUSD, XAUUSD, XAGUSD, BRENT, US30, SPX500).
"""

from dataclasses import replace

import pandas as pd

from scripts.research.test_12assets_autopsy import (
    ALL_12,
    SLIPPAGES,
    SPREADS,
    load_any_asset,
    summarize,
)
from smc_trader.strategies.d1_mean_reversion import (
    D1MeanReversionConfig,
    D1MeanReversionStrategy,
)
from smc_trader.strategies.fibo_dynamic_zone import (
    FiboDynamicZoneConfig,
    FiboDynamicZoneStrategy,
)
from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy

E1_ASSETS = ["NAS100", "US30", "SPX500"]
E2_ASSETS = ["BRENT", "NAS100", "XAUUSD"]
E3_ASSETS_9 = ["EURUSD", "USDJPY", "AUDUSD", "GBPUSD", "XAUUSD", "XAGUSD", "BRENT", "US30", "SPX500"]


def resample_to_d1_rth(df_m1: pd.DataFrame) -> pd.DataFrame:
    """Agrega para D1 no horário do Cash Market de NY (13:30 a 20:00 UTC) ou D1 UTC limpo."""
    df_d1 = (
        df_m1.resample("1D")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last"})
        .dropna()
    )
    # Remove domingos curtos
    return df_d1[df_d1.index.dayofweek < 5]


def main():
    dfs = {sym: load_any_asset(sym) for sym in ALL_12}

    # =========================================================================
    # 1. TESTE DA ESTRATÉGIA 3 EM M15 vs M5 NOS 12 ATIVOS E NOS 9 ATIVOS
    # =========================================================================
    cfg_e3_m5 = FiboDynamicZoneConfig(
        timeframe="M5",
        fibo_entry=0.618,
        fibo_zone_shallow=0.618,
        fibo_zone_deep=0.790,
        fibo_stop=0.920,
        stop_mode="fibo_82",
        target_rr=3.0,
        ema_fast_period=80,
        sma_slow_period=200,
        min_slope_degrees=30.0,
        slope_lookback=50,
        zone_confluence_mode="fibo_within_ma",
        require_leg_fvg=True,
        session_filter=True,
        max_stops_per_day=2,
        max_gains_per_day=1,
        max_trades_per_day=3,
        breakeven_trigger_r=1.25,
        breakeven_lock_r=0.1,
        profit_lock_trigger_r=2.0,
        profit_lock_lock_r=1.0,
        require_h1_trend_alignment=True,
        min_adx=22.0,
        max_adx=35.0,
    )
    cfg_e3_m15 = replace(cfg_e3_m5, timeframe="M15", slope_lookback=50)

    e3_m5_records = []
    e3_m15_records = []

    print("=" * 115)
    print("PARTE 1: ESTRATÉGIA 3 EM M5 vs M15 NOS 12 ATIVOS")
    print("=" * 115)
    for sym in ALL_12:
        t_m5 = FiboDynamicZoneStrategy(replace(cfg_e3_m5, slippage=SLIPPAGES[sym])).run_backtest(
            dfs[sym], sym, SPREADS[sym]
        )
        t_m15 = FiboDynamicZoneStrategy(replace(cfg_e3_m15, slippage=SLIPPAGES[sym])).run_backtest(
            dfs[sym], sym, SPREADS[sym]
        )
        for t in t_m5:
            e3_m5_records.append({"strategy": "E3_M5", "sym": sym, "time": t.exit_time, "r": t.r_multiple})
        for t in t_m15:
            e3_m15_records.append({"strategy": "E3_M15", "sym": sym, "time": t.exit_time, "r": t.r_multiple})

    df_e3_m5 = pd.DataFrame(e3_m5_records)
    df_e3_m15 = pd.DataFrame(e3_m15_records)

    for label, sub_df in [
        ("E3_M5  (12 Ativos)", df_e3_m5),
        ("E3_M15 (12 Ativos)", df_e3_m15),
        ("E3_M5  (9 Ativos Aprovados)", df_e3_m5[df_e3_m5["sym"].isin(E3_ASSETS_9)]),
        ("E3_M15 (9 Ativos Aprovados)", df_e3_m15[df_e3_m15["sym"].isin(E3_ASSETS_9)]),
    ]:
        n, wr, tot, mr, se, t_st, pf, dd = summarize(sub_df["r"].tolist())
        pos_c = sum(1 for _, g in sub_df.groupby("sym") if g["r"].sum() > 0)
        tot_c = sub_df["sym"].nunique()
        print(
            f"  {label:<30}: {n:3d} tr | WR {wr:5.1f}% | Total {tot:+6.1f}R | "
            f"R/tr {mr:+.3f}±{se:.3f} | t={t_st:+5.2f} | PF {pf:4.2f} | MaxDD {dd:4.1f}R | Ativos+: {pos_c}/{tot_c}"
        )

    # =========================================================================
    # 2. CARTEIRA UNIFICADA: E1 (D1) + E2 (M5 REJEIÇÃO) + E3 (M5 + M15 DYNAMIC ZONE)
    # =========================================================================
    e1_records = []
    for sym in E1_ASSETS:
        df_d1 = resample_to_d1_rth(dfs[sym])
        cfg_d1 = D1MeanReversionConfig(slippage_pts=SLIPPAGES[sym])
        t_d1 = D1MeanReversionStrategy(cfg_d1).run_simulation(df_d1, symbol=sym, spread=SPREADS[sym])
        for t in t_d1:
            e1_records.append({"strategy": "E1_D1_MeanRev", "sym": sym, "time": t.exit_time, "r": t.r_multiple})

    base_s2 = FiboOTEConfig(
        timeframe="M5",
        fibo_entry=0.618,
        fibo_rejection_max=0.790,
        fibo_stop=0.886,
        entry_mode="m5_close_rejection",
        stop_mode="fibo",
        rejection_min_wick_ratio=0.50,
        target_mode="3R",
        target_r=3.0,
        pivot_k=2,
        max_holding_candles=60,
        trend_ma="ema80",
        confluence_ma="ema80",
        require_inducement=True,
        require_leg_fvg=True,
        max_trades_per_day=3,
        max_stops_per_day=2,
        max_gains_per_day=1,
        partial_exit_trigger_r=1.618,
        partial_exit_pct=0.50,
        profit_lock_trigger_r=1.618,
        profit_lock_guarantee_r=1.0,
        session_filter=True,
        session_windows=[("07:00", "10:30"), ("12:30", "16:30")],
    )
    e2_records = []
    for sym in E2_ASSETS:
        cfg_s2 = replace(base_s2, slippage=SLIPPAGES[sym])
        t_s2 = FiboOTEStrategy(cfg_s2).run_backtest(dfs[sym], symbol=sym, spread=SPREADS[sym])
        for t in t_s2:
            e2_records.append({"strategy": "E2_M5_RejPavio", "sym": sym, "time": t.exit_time, "r": t.r_multiple})

    df_e1 = pd.DataFrame(e1_records)
    df_e2 = pd.DataFrame(e2_records)
    df_e3_9_m5 = df_e3_m5[df_e3_m5["sym"].isin(E3_ASSETS_9)].copy()
    df_e3_9_m15 = df_e3_m15[df_e3_m15["sym"].isin(E3_ASSETS_9)].copy()

    # Também testa E3 com Lookback 80 nos 9 ativos para maior frequência
    cfg_e3_lb80 = replace(cfg_e3_m5, slope_lookback=80)
    e3_lb80_records = []
    for sym in E3_ASSETS_9:
        t_80 = FiboDynamicZoneStrategy(replace(cfg_e3_lb80, slippage=SLIPPAGES[sym])).run_backtest(
            dfs[sym], sym, SPREADS[sym]
        )
        for t in t_80:
            e3_lb80_records.append({"strategy": "E3_M5_LB80", "sym": sym, "time": t.exit_time, "r": t.r_multiple})
    df_e3_lb80 = pd.DataFrame(e3_lb80_records)

    print("\n" + "=" * 115)
    print("PARTE 2: DESEMPENHO INDIVIDUAL DE CADA PILAR E DA CARTEIRA UNIFICADA (ORDEM CRONOLÓGICA)")
    print("=" * 115)

    port_sniper = pd.concat([df_e1, df_e2, df_e3_9_m5], ignore_index=True).sort_values("time")
    port_expanded = pd.concat([df_e1, df_e2, df_e3_lb80, df_e3_9_m15], ignore_index=True).sort_values("time")

    for pname, pdf in [
        ("Pilar 1: E1 (D1 Mean Reversion - 3 Índices)", df_e1),
        ("Pilar 2: E2 (M5 Fibo Rejeição Pavio - 3 Ativos)", df_e2),
        ("Pilar 3a: E3 Sniper (M5 Dynamic Zone LB50 - 9 Ativos)", df_e3_9_m5),
        ("Pilar 3b: E3 Ciclo80 (M5 Dynamic Zone LB80 - 9 Ativos)", df_e3_lb80),
        ("Pilar 3c: E3 M15 (M15 Dynamic Zone - 9 Ativos)", df_e3_9_m15),
        ("--> CARTEIRA UNIFICADA SNIPER (E1 + E2 + E3_M5)", port_sniper),
        ("--> CARTEIRA UNIFICADA EXPANDIDA (E1 + E2 + E3_LB80 + E3_M15)", port_expanded),
    ]:
        n, wr, tot, mr, se, t_st, pf, dd = summarize(pdf["r"].tolist())
        tr_per_yr = n / 5.0
        print(
            f"  {pname:<62} | {n:3d} tr ({tr_per_yr:5.1f}/ano) | WR {wr:5.1f}% | "
            f"Total {tot:+6.1f}R | R/tr {mr:+.3f}±{se:.3f} | t={t_st:+5.2f} | PF {pf:4.2f} | MaxDD {dd:4.1f}R"
        )

    print("\n" + "=" * 115)
    print("PARTE 3: CONSISTÊNCIA ANO A ANO DA CARTEIRA UNIFICADA SNIPER (E1 + E2 + E3_M5)")
    print("=" * 115)
    port_sniper["year"] = port_sniper["time"].dt.year
    for yr, g in port_sniper.groupby("year"):
        n, wr, tot, mr, se, t_st, pf, dd = summarize(g["r"].tolist())
        c_e1 = len(g[g["strategy"] == "E1_D1_MeanRev"])
        c_e2 = len(g[g["strategy"] == "E2_M5_RejPavio"])
        c_e3 = len(g[g["strategy"] == "E3_M5"])
        print(
            f"  Ano {yr}: {n:3d} trades (E1:{c_e1:2d}, E2:{c_e2:2d}, E3:{c_e3:2d}) | "
            f"WR {wr:5.1f}% | Total {tot:+6.1f}R | PF {pf:4.2f} | MaxDD {dd:4.1f}R"
        )


if __name__ == "__main__":
    main()

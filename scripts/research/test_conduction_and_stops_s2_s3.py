"""Estudo de Validação de Condução de Trade, Breakeven e Níveis de Stop Loss:
Estratégia 2 (SMC Fibo Rejeição EMA80 Pavio) & Estratégia 3 (Fibo Dynamic Zone 30°).

Avalia de forma estritamente causal (AGENTS.md):
1. Níveis de Stop Loss: 82.0%, 85.0%, 88.6%, 92.0%, 100.0% (Swing Extreme)
2. Modelos de Condução e Proteção:
   - Alvo 3.0R Seco (Sem trava)
   - Breakeven Rápido (+1.0R -> 0.0R)
   - Breakeven Moderado (+1.25R -> +0.1R)
   - Trava Áurea (+1.618R -> +1.0R)
   - Trava Larga (+2.0R -> +1.0R)
   - Condução em 2 Estágios (BE +1.0R->0.0R e depois Lock +1.618R->+1.0R)
   - Condução em 2 Estágios Folgada (BE +1.25R->+0.1R e depois Lock +2.0R->+1.0R)
   - Realização Parcial (50% em +1.5R + BE 0.0R + 50% em +3.0R)
   - Condução Estrutural BOS Swing Trailing (+ Lock 1.618R->1.0R)
3. Separação In-Sample (2021-2024) vs. Out-of-Sample (2025-2026) e Portfólio Combinado (E2 + E3).
"""

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from smc_trader.data.store import load_candles
from smc_trader.strategies.fibo_dynamic_zone import (
    FiboDynamicZoneConfig,
    FiboDynamicZoneStrategy,
)
from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy

SYMBOLS = ["NAS100", "US30", "BRENT", "EURUSD", "GBPUSD", "XAUUSD"]

SPREADS = {
    "XAUUSD": 0.20,
    "EURUSD": 0.00008,
    "GBPUSD": 0.00010,
    "US30": 2.0,
    "NAS100": 1.5,
    "BRENT": 0.03,
}

SLIPPAGES = {
    "XAUUSD": 0.05,
    "EURUSD": 0.00002,
    "GBPUSD": 0.00002,
    "US30": 1.0,
    "NAS100": 1.0,
    "BRENT": 0.01,
}

OOS_START = pd.Timestamp("2025-01-01", tz="UTC")


def summarize_rs(rs_list: list[float]) -> tuple[int, float, float, float, float, float, float]:
    n = len(rs_list)
    if n == 0:
        return 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    rs = np.array(rs_list, dtype=float)
    wins = int(np.sum(rs > 0))
    wr = (wins / n) * 100.0
    tot_r = float(np.sum(rs))
    mean_r = float(np.mean(rs))
    std_r = float(np.std(rs, ddof=1)) if n > 1 else 0.0
    se = std_r / np.sqrt(n) if n > 1 else 0.0
    t_stat = mean_r / se if se > 0 else 0.0
    gp = float(np.sum(rs[rs > 0])) if wins > 0 else 0.0
    gl = float(abs(np.sum(rs[rs <= 0]))) if (n - wins) > 0 else 0.0
    pf = (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0)
    eq = np.cumsum(rs)
    dd = float(np.max(np.maximum.accumulate(eq) - eq)) if len(eq) > 0 else 0.0
    return n, wr, tot_r, mean_r, t_stat, pf, dd


def run_study():
    data_dir = Path("data")
    dfs: dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        dfs[sym] = load_candles(data_dir, sym, "M1", source="dukascopy")

    # =========================================================================
    # PARTE 1: ESTRATÉGIA 3 (FIBO DYNAMIC ZONE 30° + FVG + KILLZONES)
    # =========================================================================
    base_s3 = FiboDynamicZoneConfig(
        timeframe="M5",
        fibo_entry=0.618,
        fibo_zone_deep=0.790,
        fibo_stop=0.820,
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
    )

    s3_variants = [
        # 1. Variações de Stop Loss (mantendo Lock 1.618R -> 1.0R)
        ("S3_Stop82_Lock1618", replace(base_s3, fibo_stop=0.820, profit_lock_trigger_r=1.618, profit_lock_lock_r=1.0)),
        ("S3_Stop85_Lock1618", replace(base_s3, fibo_stop=0.850, profit_lock_trigger_r=1.618, profit_lock_lock_r=1.0)),
        ("S3_Stop886_Lock1618", replace(base_s3, fibo_stop=0.886, profit_lock_trigger_r=1.618, profit_lock_lock_r=1.0)),
        ("S3_Stop92_Lock1618", replace(base_s3, fibo_stop=0.920, profit_lock_trigger_r=1.618, profit_lock_lock_r=1.0)),
        ("S3_Stop100_Lock1618", replace(base_s3, stop_mode="swing_extreme", profit_lock_trigger_r=1.618, profit_lock_lock_r=1.0)),
        # 2. Variações de Breakeven e Condução (com Stop 85% e 88.6%)
        ("S3_Stop85_BE10_00", replace(base_s3, fibo_stop=0.850, breakeven_trigger_r=1.0, breakeven_lock_r=0.0)),
        ("S3_Stop85_BE125_01", replace(base_s3, fibo_stop=0.850, breakeven_trigger_r=1.25, breakeven_lock_r=0.1)),
        (
            "S3_Stop85_2Stage_BE10_Lock1618",
            replace(base_s3, fibo_stop=0.850, breakeven_trigger_r=1.0, breakeven_lock_r=0.0, profit_lock_trigger_r=1.618, profit_lock_lock_r=1.0),
        ),
        (
            "S3_Stop85_2Stage_BE125_Lock20",
            replace(base_s3, fibo_stop=0.850, breakeven_trigger_r=1.25, breakeven_lock_r=0.1, profit_lock_trigger_r=2.0, profit_lock_lock_r=1.0),
        ),
        (
            "S3_Stop85_Partial50_15R_BE",
            replace(base_s3, fibo_stop=0.850, partial_trigger_r=1.5, partial_pct=0.5, breakeven_trigger_r=1.5, breakeven_lock_r=0.1),
        ),
        (
            "S3_Stop85_BOSTrail_Lock1618",
            replace(base_s3, fibo_stop=0.850, bos_swing_trailing=True, profit_lock_trigger_r=1.618, profit_lock_lock_r=1.0),
        ),
        (
            "S3_Stop886_2Stage_BE125_Lock20",
            replace(base_s3, fibo_stop=0.886, breakeven_trigger_r=1.25, breakeven_lock_r=0.1, profit_lock_trigger_r=2.0, profit_lock_lock_r=1.0),
        ),
        (
            "S3_Stop886_Partial50_15R_BE",
            replace(base_s3, fibo_stop=0.886, partial_trigger_r=1.5, partial_pct=0.5, breakeven_trigger_r=1.5, breakeven_lock_r=0.1),
        ),
    ]

    print("=" * 120)
    print("PARTE 1: ESTRATÉGIA 3 (FIBO DYNAMIC ZONE 30°) - CONDUÇÃO, BREAKEVEN E STOP MAIOR")
    print("=" * 120)
    print(
        f"{'Variante':<32} | {'Total (6 Ativos)':<28} | {'In-Sample (21-24)':<18} | {'Out-of-Sample (25-26)':<20} | {'Cesta EURUSD+XAUUSD'}"
    )
    print("-" * 120)

    s3_trades_by_var: dict[str, dict[str, list]] = {}

    for vname, vcfg in s3_variants:
        s3_trades_by_var[vname] = {}
        all_rs, is_rs, oos_rs, basket_rs = [], [], [], []
        for sym in SYMBOLS:
            cfg = replace(vcfg, slippage=SLIPPAGES[sym])
            trades = FiboDynamicZoneStrategy(cfg).run_backtest(dfs[sym], symbol=sym, spread=SPREADS[sym])
            s3_trades_by_var[vname][sym] = trades
            for t in trades:
                all_rs.append(t.r_multiple)
                if t.entry_time < OOS_START:
                    is_rs.append(t.r_multiple)
                else:
                    oos_rs.append(t.r_multiple)
                if sym in ("EURUSD", "XAUUSD"):
                    basket_rs.append(t.r_multiple)

        n_a, wr_a, tot_a, _, t_a, pf_a, dd_a = summarize_rs(all_rs)
        n_is, _, tot_is, _, _, pf_is, _ = summarize_rs(is_rs)
        n_oos, _, tot_oos, _, _, pf_oos, _ = summarize_rs(oos_rs)
        n_b, wr_b, tot_b, _, t_b, pf_b, dd_b = summarize_rs(basket_rs)
        print(
            f"{vname:<32} | {n_a:3d}tr {tot_a:+6.1f}R WR{wr_a:4.1f}% PF{pf_a:4.2f} | "
            f"{n_is:3d}tr {tot_is:+6.1f}R PF{pf_is:4.2f} | "
            f"{n_oos:2d}tr {tot_oos:+6.1f}R PF{pf_oos:4.2f} | "
            f"{n_b:2d}tr {tot_b:+5.1f}R WR{wr_b:4.1f}% PF{pf_b:4.2f} DD{dd_b:3.1f}R"
        )

    # =========================================================================
    # PARTE 2: ESTRATÉGIA 2 (SMC FIBO REJEIÇÃO EMA80 PAVIO)
    # =========================================================================
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
        profit_lock_trigger_r=1.618,
        profit_lock_guarantee_r=1.0,
        session_filter=True,
        session_windows=[("07:00", "10:30"), ("12:30", "16:30")],
    )

    s2_variants = [
        ("S2_Stop82_Lock1618", replace(base_s2, fibo_stop=0.820)),
        ("S2_Stop85_Lock1618", replace(base_s2, fibo_stop=0.850)),
        ("S2_Stop886_Lock1618_Atual", base_s2),
        ("S2_Stop92_Lock1618", replace(base_s2, fibo_stop=0.920)),
        ("S2_Stop100_Lock1618", replace(base_s2, fibo_stop=1.000)),
        ("S2_Stop886_BE125_01", replace(base_s2, profit_lock_trigger_r=1.25, profit_lock_guarantee_r=0.1)),
        ("S2_Stop886_Lock20_10", replace(base_s2, profit_lock_trigger_r=2.0, profit_lock_guarantee_r=1.0)),
        (
            "S2_Stop886_Partial50_1618_Lock10",
            replace(base_s2, partial_exit_trigger_r=1.618, partial_exit_pct=0.50, profit_lock_trigger_r=1.618, profit_lock_guarantee_r=1.0),
        ),
        (
            "S2_Stop886_BOSTrail_Lock1618",
            replace(base_s2, bos_swing_trailing=True),
        ),
        (
            "S2_Stop92_BOSTrail_Lock1618",
            replace(base_s2, fibo_stop=0.920, bos_swing_trailing=True),
        ),
    ]

    print("\n" + "=" * 120)
    print("PARTE 2: ESTRATÉGIA 2 (SMC FIBO REJEIÇÃO PAVIO >= 50%) - CONDUÇÃO, BREAKEVEN E STOP MAIOR")
    print("=" * 120)
    print(
        f"{'Variante':<32} | {'Total (6 Ativos)':<28} | {'In-Sample (21-24)':<18} | {'Out-of-Sample (25-26)':<20} | {'Cesta BRENT+NAS100+XAU'}"
    )
    print("-" * 120)

    for vname, vcfg in s2_variants:
        all_rs, is_rs, oos_rs, basket_rs = [], [], [], []
        for sym in SYMBOLS:
            cfg = replace(vcfg, slippage=SLIPPAGES[sym])
            trades = FiboOTEStrategy(cfg).run_backtest(dfs[sym], symbol=sym, spread=SPREADS[sym])
            for t in trades:
                all_rs.append(t.r_multiple)
                if t.entry_time < OOS_START:
                    is_rs.append(t.r_multiple)
                else:
                    oos_rs.append(t.r_multiple)
                if sym in ("BRENT", "NAS100", "XAUUSD"):
                    basket_rs.append(t.r_multiple)

        n_a, wr_a, tot_a, _, t_a, pf_a, dd_a = summarize_rs(all_rs)
        n_is, _, tot_is, _, _, pf_is, _ = summarize_rs(is_rs)
        n_oos, _, tot_oos, _, _, pf_oos, _ = summarize_rs(oos_rs)
        n_b, wr_b, tot_b, _, t_b, pf_b, dd_b = summarize_rs(basket_rs)
        print(
            f"{vname:<32} | {n_a:3d}tr {tot_a:+6.1f}R WR{wr_a:4.1f}% PF{pf_a:4.2f} | "
            f"{n_is:3d}tr {tot_is:+6.1f}R PF{pf_is:4.2f} | "
            f"{n_oos:2d}tr {tot_oos:+6.1f}R PF{pf_oos:4.2f} | "
            f"{n_b:3d}tr {tot_b:+5.1f}R WR{wr_b:4.1f}% PF{pf_b:4.2f} DD{dd_b:3.1f}R"
        )


if __name__ == "__main__":
    run_study()

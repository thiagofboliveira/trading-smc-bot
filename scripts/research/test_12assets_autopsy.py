"""Validação Cronológica Barra-a-Barra dos 3 Refinamentos Estruturais nos 12 Ativos (6 Principais + 6 Holdouts):
1. Alinhamento Macro H1 (MME 80 > MME 960 no M5)
2. Largura do Canal [MMA 200, MME 80] não exaurida (1.5 a 4.0 ATR)
3. ADX(14)[i-1] na faixa de tendência saudável (22 a 35)
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

MAIN_SYMBOLS = ["NAS100", "US30", "BRENT", "EURUSD", "GBPUSD", "XAUUSD"]
HOLD_M5 = ["USDJPY", "AUDUSD", "USDCAD", "XAGUSD"]
HOLD_M1 = ["GER40", "SPX500"]
ALL_12 = MAIN_SYMBOLS + HOLD_M5 + HOLD_M1

SPREADS = {
    "XAUUSD": 0.20,
    "EURUSD": 0.00008,
    "GBPUSD": 0.00010,
    "US30": 2.0,
    "NAS100": 1.5,
    "BRENT": 0.03,
    "USDJPY": 0.010,
    "AUDUSD": 0.00010,
    "USDCAD": 0.00012,
    "XAGUSD": 0.020,
    "GER40": 1.5,
    "SPX500": 0.5,
}
SLIPPAGES = {
    "XAUUSD": 0.05,
    "EURUSD": 0.00002,
    "GBPUSD": 0.00002,
    "US30": 1.0,
    "NAS100": 1.0,
    "BRENT": 0.01,
    "USDJPY": 0.003,
    "AUDUSD": 0.00002,
    "USDCAD": 0.00002,
    "XAGUSD": 0.005,
    "GER40": 1.0,
    "SPX500": 0.25,
}


def load_any_asset(sym: str) -> pd.DataFrame:
    if sym in MAIN_SYMBOLS:
        df_raw = load_candles(Path("data"), sym, "M1", source="dukascopy")
    elif sym in HOLD_M5:
        df_raw = pd.read_parquet(Path(f"data/holdout/{sym}_M5_holdout.parquet"))
    else:
        df_raw = pd.read_parquet(Path(f"data/holdout/{sym}_M1.parquet"))
        if not isinstance(df_raw.index, pd.DatetimeIndex):
            df_raw = df_raw.set_index("timestamp" if "timestamp" in df_raw.columns else "time")
    if df_raw.index.tz is None:
        df_raw.index = df_raw.index.tz_localize("UTC")
    return df_raw


def summarize(rs_list: list[float]) -> tuple[int, float, float, float, float, float, float, float]:
    n = len(rs_list)
    if n == 0:
        return 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
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
    return n, wr, tot_r, mean_r, se, t_stat, pf, dd


def main():
    dfs = {sym: load_any_asset(sym) for sym in ALL_12}

    base = FiboDynamicZoneConfig(
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
    )

    variants = [
        ("0_Base_30deg_Stop920", base),
        ("1_MacroH1_Only", replace(base, require_h1_trend_alignment=True)),
        ("2_Canal_1.5_a_4.0_ATR", replace(base, min_channel_atr=1.5, max_channel_atr=4.0)),
        ("3_ADX_22_a_35", replace(base, min_adx=22.0, max_adx=35.0)),
        ("4_MacroH1_e_Canal_1.5_4.0", replace(base, require_h1_trend_alignment=True, min_channel_atr=1.5, max_channel_atr=4.0)),
        ("5_MacroH1_e_ADX_22_35", replace(base, require_h1_trend_alignment=True, min_adx=22.0, max_adx=35.0)),
        (
            "6_MacroH1_ADX22_CanalMax4.2",
            replace(base, require_h1_trend_alignment=True, min_adx=22.0, max_channel_atr=4.2),
        ),
        (
            "7_Stop886_MacroH1_Canal_1.5_4.0",
            replace(base, fibo_stop=0.886, require_h1_trend_alignment=True, min_channel_atr=1.5, max_channel_atr=4.0),
        ),
        (
            "8_Stop886_MacroH1_ADX_22_35",
            replace(base, fibo_stop=0.886, require_h1_trend_alignment=True, min_adx=22.0, max_adx=35.0),
        ),
    ]

    print("=" * 130)
    print("SIMULAÇÃO CRONOLÓGICA REAL BARRA-A-BARRA NOS 12 ATIVOS (6 PRINCIPAIS + 6 HOLDOUTS)")
    print("=" * 130)
    print(
        f"{'Variante':<32} | {'Global 12 Ativos':<36} | {'6 Principais':<22} | {'6 Holdouts Cegos':<24} | {'Ativos+'}"
    )
    print("-" * 130)

    per_asset_results: dict[str, dict[str, list[float]]] = {}

    for vname, vcfg in variants:
        per_asset_results[vname] = {}
        all_rs, main_rs, hold_rs = [], [], []
        pos_main, pos_hold = 0, 0
        for sym in ALL_12:
            cfg = replace(vcfg, slippage=SLIPPAGES[sym])
            trades = FiboDynamicZoneStrategy(cfg).run_backtest(dfs[sym], symbol=sym, spread=SPREADS[sym])
            rs = [t.r_multiple for t in trades]
            per_asset_results[vname][sym] = rs
            all_rs.extend(rs)
            if sym in MAIN_SYMBOLS:
                main_rs.extend(rs)
                if sum(rs) > 0:
                    pos_main += 1
            else:
                hold_rs.extend(rs)
                if sum(rs) > 0:
                    pos_hold += 1

        na, wra, tota, mra, sea, ta, pfa, dda = summarize(all_rs)
        nm, wrm, totm, _, _, tm, pfm, _ = summarize(main_rs)
        nh, wrh, toth, _, _, th, pfh, _ = summarize(hold_rs)
        print(
            f"{vname:<32} | {na:3d}tr {tota:+6.1f}R WR{wra:4.1f}% PF{pfa:4.2f} t{ta:+4.2f} | "
            f"{nm:3d}tr {totm:+6.1f}R PF{pfm:4.2f} | "
            f"{nh:3d}tr {toth:+6.1f}R PF{pfh:4.2f} t{th:+4.2f} | "
            f"{pos_main + pos_hold:2d}/12 ({pos_main}/6 M, {pos_hold}/6 H)"
        )

    for focus in ["4_MacroH1_e_Canal_1.5_4.0", "5_MacroH1_e_ADX_22_35", "7_Stop886_MacroH1_Canal_1.5_4.0"]:
        print("\n" + "=" * 100)
        print(f"DETALHAMENTO DOS 12 ATIVOS: {focus}")
        print("=" * 100)
        for sym in ALL_12:
            rs = per_asset_results[focus][sym]
            n, wr, tot, mr, se, t_st, pf, dd = summarize(rs)
            tag = "[MAIN]   " if sym in MAIN_SYMBOLS else "[HOLDOUT]"
            print(
                f"  {tag} {sym:<8} | {n:3d} tr | WR {wr:5.1f}% | Total {tot:+6.1f}R | "
                f"R/tr {mr:+.3f}±{se:.3f} | t={t_st:+5.2f} | PF {pf:4.2f} | MaxDD {dd:4.1f}R"
            )


if __name__ == "__main__":
    main()

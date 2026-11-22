"""Expansão da Carteira Unificada para 22 Ativos Globais (12 Existentes + 10 Novos da Dukascopy).

Novos ativos baixados e testados com parâmetros 100% congelados:
1. USDCHF (Major FX)
2. NZDUSD (Major FX)
3. EURJPY (Cross JPY #1)
4. GBPJPY (Cross JPY #2)
5. AUDJPY (Cross JPY #3)
6. CADJPY (Cross JPY #4)
7. EURGBP (Cross Europeu #1)
8. EURAUD (Cross Tendência #2)
9. WTI    (Petróleo WTI - E_Light)
10. US2000 (Índice Russell 2000 - RUSSELL.IDX/USD)
"""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import dukascopy_python
import pandas as pd
from dukascopy_python import instruments

from scripts.research.test_12assets_autopsy import (
    ALL_12,
    load_any_asset,
    summarize,
)
from scripts.research.test_12assets_autopsy import (
    SLIPPAGES as SLIP_12,
)
from scripts.research.test_12assets_autopsy import (
    SPREADS as SPREAD_12,
)
from smc_trader.data.dukascopy_source import normalize_dukascopy
from smc_trader.strategies.d1_mean_reversion import (
    D1MeanReversionConfig,
    D1MeanReversionStrategy,
)
from smc_trader.strategies.fibo_dynamic_zone import (
    FiboDynamicZoneConfig,
    FiboDynamicZoneStrategy,
)
from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy

NEW_10_ASSETS = [
    ("USDCHF", instruments.INSTRUMENT_FX_MAJORS_USD_CHF, 0.00010, 0.00002),
    ("NZDUSD", instruments.INSTRUMENT_FX_MAJORS_NZD_USD, 0.00012, 0.00002),
    ("EURJPY", instruments.INSTRUMENT_FX_CROSSES_EUR_JPY, 0.015, 0.003),
    ("GBPJPY", instruments.INSTRUMENT_FX_CROSSES_GBP_JPY, 0.020, 0.004),
    ("AUDJPY", instruments.INSTRUMENT_FX_CROSSES_AUD_JPY, 0.015, 0.003),
    ("CADJPY", instruments.INSTRUMENT_FX_CROSSES_CAD_JPY, 0.015, 0.003),
    ("EURGBP", instruments.INSTRUMENT_FX_CROSSES_EUR_GBP, 0.00010, 0.00002),
    ("EURAUD", instruments.INSTRUMENT_FX_CROSSES_EUR_AUD, 0.00020, 0.00004),
    ("WTI", instruments.INSTRUMENT_CMD_ENERGY_E_LIGHT, 0.03, 0.01),
    ("US2000", instruments.INSTRUMENT_IDX_AMERICA_RUSSELL_IDX_USD, 0.8, 0.3),
]

SPREADS = {**SPREAD_12, **{s: sp for s, _, sp, _ in NEW_10_ASSETS}}
SLIPPAGES = {**SLIP_12, **{s: sl for s, _, _, sl in NEW_10_ASSETS}}


def fetch_or_load_new(symbol: str, instrument: str, start: datetime, end: datetime) -> pd.DataFrame:
    out_dir = Path("data/holdout")
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = out_dir / f"{symbol}_M5_holdout.parquet"
    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df

    print(f"Baixando {symbol} ({instrument}) de {start.date()} até {end.date()}...")
    df_raw = dukascopy_python.fetch(
        instrument=instrument,
        interval=dukascopy_python.INTERVAL_MIN_5,
        offer_side=dukascopy_python.OFFER_SIDE_BID,
        start=start,
        end=end,
    )
    df = normalize_dukascopy(df_raw)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.to_parquet(cache_path)
    print(f"  -> {symbol}: {len(df):,} candles M5 salvos.")
    return df


def resample_to_d1(df: pd.DataFrame) -> pd.DataFrame:
    d1 = df.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    return d1[d1.index.dayofweek < 5]


def main():
    start = datetime(2022, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, tzinfo=timezone.utc)

    dfs: dict[str, pd.DataFrame] = {sym: load_any_asset(sym) for sym in ALL_12}
    for sym, instr, _, _ in NEW_10_ASSETS:
        dfs[sym] = fetch_or_load_new(sym, instr, start, end)

    ALL_22 = ALL_12 + [s for s, _, _, _ in NEW_10_ASSETS]

    cfg_e3 = FiboDynamicZoneConfig(
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

    print("\n" + "=" * 115)
    print("PARTE 1: TESTE CEGO DA ESTRATÉGIA 3 (FIBO DYNAMIC ZONE 30° + H1 + ADX 22..35) NOS 10 NOVOS ATIVOS")
    print("=" * 115)
    new_rs_all = []
    pos_new = 0
    for sym, _, spread, slip in NEW_10_ASSETS:
        trades = FiboDynamicZoneStrategy(replace(cfg_e3, slippage=slip)).run_backtest(dfs[sym], sym, spread)
        rs = [t.r_multiple for t in trades]
        new_rs_all.extend(rs)
        n, wr, tot, mr, se, t_st, pf, dd = summarize(rs)
        if tot > 0:
            pos_new += 1
        print(
            f"  [NOVO] {sym:<8} | {n:3d} tr | WR {wr:5.1f}% | Total {tot:+6.1f}R | "
            f"R/tr {mr:+.3f}±{se:.3f} | t={t_st:+5.2f} | PF {pf:4.2f} | MaxDD {dd:4.1f}R"
        )
    n, wr, tot, mr, se, t_st, pf, dd = summarize(new_rs_all)
    print("-" * 115)
    print(
        f"  CONSOLIDADO 10 NOVOS ATIVOS: {n:3d} tr | WR {wr:5.1f}% | Total {tot:+6.1f}R | "
        f"R/tr {mr:+.3f}±{se:.3f} | t={t_st:+5.2f} | PF {pf:4.2f} | MaxDD {dd:4.1f}R | Positivos: {pos_new}/10"
    )

    # Teste de US2000 na Estratégia 1 (D1 Mean Reversion) e WTI na Estratégia 2
    df_us2000_d1 = resample_to_d1(dfs["US2000"])
    t_us2000_e1 = D1MeanReversionStrategy(D1MeanReversionConfig(slippage_pts=SLIPPAGES["US2000"])).run_simulation(
        df_us2000_d1, "US2000", SPREADS["US2000"]
    )
    n1, wr1, tot1, mr1, se1, t1, pf1, dd1 = summarize([t.r_multiple for t in t_us2000_e1])
    print(f"\n  [E1 D1 MeanRev] US2000 (Russell 2000): {n1:3d} tr | WR {wr1:5.1f}% | Total {tot1:+6.1f}R | PF {pf1:4.2f} | MaxDD {dd1:4.1f}R")

    base_s2 = FiboOTEConfig(
        timeframe="M5", fibo_entry=0.618, fibo_rejection_max=0.790, fibo_stop=0.886,
        entry_mode="m5_close_rejection", stop_mode="fibo", rejection_min_wick_ratio=0.50,
        target_mode="3R", target_r=3.0, pivot_k=2, max_holding_candles=60,
        trend_ma="ema80", confluence_ma="ema80", require_inducement=True, require_leg_fvg=True,
        max_trades_per_day=3, max_stops_per_day=2, max_gains_per_day=1,
        partial_exit_trigger_r=1.618, partial_exit_pct=0.50,
        profit_lock_trigger_r=1.618, profit_lock_guarantee_r=1.0,
        session_filter=True, session_windows=[("07:00", "10:30"), ("12:30", "16:30")],
        slippage=SLIPPAGES["WTI"],
    )
    t_wti_e2 = FiboOTEStrategy(base_s2).run_backtest(dfs["WTI"], "WTI", SPREADS["WTI"])
    n2, wr2, tot2, mr2, se2, t2, pf2, dd2 = summarize([t.r_multiple for t in t_wti_e2])
    print(f"  [E2 M5 RejPavio] WTI (Petróleo WTI)   : {n2:3d} tr | WR {wr2:5.1f}% | Total {tot2:+6.1f}R | PF {pf2:4.2f} | MaxDD {dd2:4.1f}R")

    # =========================================================================
    # PARTE 2: CONSOLIDADO GERAL DOS 22 ATIVOS NA ESTRATÉGIA 3 (SEM FILTRAR VENCEDORES)
    # =========================================================================
    print("\n" + "=" * 115)
    print("PARTE 2: RESULTADO GLOBAL DA ESTRATÉGIA 3 EM TODOS OS 22 ATIVOS (6 ORIGINAIS + 16 HOLDOUTS)")
    print("=" * 115)
    all_22_rs = []
    pos_22 = 0
    approved_e3_assets = []
    for sym in ALL_22:
        trades = FiboDynamicZoneStrategy(replace(cfg_e3, slippage=SLIPPAGES[sym])).run_backtest(dfs[sym], sym, SPREADS[sym])
        rs = [t.r_multiple for t in trades]
        all_22_rs.extend(rs)
        if sum(rs) > 0:
            pos_22 += 1
            approved_e3_assets.append(sym)
    n22, wr22, tot22, mr22, se22, t22, pf22, dd22 = summarize(all_22_rs)
    print(
        f"  TODOS OS 22 ATIVOS (E3_M5): {n22:3d} tr | WR {wr22:5.1f}% | Total {tot22:+6.1f}R | "
        f"R/tr {mr22:+.3f}±{se22:.3f} | t={t22:+5.2f} | PF {pf22:4.2f} | MaxDD {dd22:4.1f}R | Ativos+: {pos_22}/22"
    )
    print(f"  Ativos Positivos em E3 ({len(approved_e3_assets)}/22): {approved_e3_assets}")


if __name__ == "__main__":
    main()

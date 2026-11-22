"""Teste Cego da Verdade (Blind Out-of-Sample Holdout) em Novos Pares de Forex e Metais:
Baixa dados inéditos da Dukascopy para USDJPY, AUDUSD, USDCAD e XAGUSD (Prata)
e executa a configuração CONGELADA da Estratégia 3 (Fibo Dynamic Zone 30°) sem alterar nenhum parâmetro.
"""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import dukascopy_python
import numpy as np
import pandas as pd
from dukascopy_python import instruments

from smc_trader.data.dukascopy_source import normalize_dukascopy
from smc_trader.strategies.fibo_dynamic_zone import (
    FiboDynamicZoneConfig,
    FiboDynamicZoneStrategy,
)

HOLDOUT_ASSETS = [
    ("USDJPY", instruments.INSTRUMENT_FX_MAJORS_USD_JPY, 0.010, 0.003),
    ("AUDUSD", instruments.INSTRUMENT_FX_MAJORS_AUD_USD, 0.00010, 0.00002),
    ("USDCAD", instruments.INSTRUMENT_FX_MAJORS_USD_CAD, 0.00012, 0.00002),
    ("XAGUSD", instruments.INSTRUMENT_FX_METALS_XAG_USD, 0.020, 0.005),
]


def fetch_or_load_holdout(symbol: str, instrument: str, start: datetime, end: datetime) -> pd.DataFrame:
    out_dir = Path("data/holdout")
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_path = out_dir / f"{symbol}_M5_holdout.parquet"
    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df

    print(f"Baixando {symbol} ({instrument}) da Dukascopy de {start.date()} até {end.date()}...")
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
    print(f"  -> {symbol}: {len(df):,} candles M5 salvos em {cache_path}")
    return df


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
    start = datetime(2022, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, tzinfo=timezone.utc)

    dfs: dict[str, pd.DataFrame] = {}
    for sym, instr, _, _ in HOLDOUT_ASSETS:
        dfs[sym] = fetch_or_load_holdout(sym, instr, start, end)

    frozen_a1 = FiboDynamicZoneConfig(
        timeframe="M5",
        fibo_entry=0.618,
        fibo_zone_shallow=0.618,
        fibo_zone_deep=0.790,
        fibo_stop=0.886,
        stop_mode="fibo_82",
        target_rr=3.0,
        target_mode="fixed_rr",
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

    frozen_configs = [
        ("A1_Stop886_2Stage_Congelado", frozen_a1),
        ("A5_Stop920_2Stage_Congelado", replace(frozen_a1, fibo_stop=0.920)),
        (
            "V6_Stop820_Lock1618_Congelado",
            replace(
                frozen_a1,
                fibo_stop=0.820,
                breakeven_trigger_r=0.0,
                profit_lock_trigger_r=1.618,
                profit_lock_lock_r=1.0,
            ),
        ),
    ]

    print("\n" + "=" * 115)
    print("RESULTADO DO TESTE CEGO DA VERDADE EM 4 ATIVOS INÉDITOS (USDJPY, AUDUSD, USDCAD, XAGUSD - 2022 A 2026)")
    print("=" * 115)

    for cfg_name, base_cfg in frozen_configs:
        print(f"\n--- {cfg_name} ---")
        print(
            f"{'Ativo':<10} | {'Trades':<6} | {'WR%':<6} | {'Total R':<9} | "
            f"{'R/Trade (±EP)':<18} | {'t-stat':<6} | {'PF':<5} | {'MaxDD':<7} | {'Longs/Shorts'}"
        )
        print("-" * 100)
        all_rs = []
        for sym, _, spread, slip in HOLDOUT_ASSETS:
            cfg = replace(base_cfg, slippage=slip)
            trades = FiboDynamicZoneStrategy(cfg).run_backtest(dfs[sym], symbol=sym, spread=spread)
            rs = [t.r_multiple for t in trades]
            all_rs.extend(rs)
            n, wr, tot, mr, se, t_st, pf, dd = summarize(rs)
            nl = sum(1 for t in trades if t.direction == "long")
            ns = sum(1 for t in trades if t.direction == "short")
            r_str = f"{mr:+.3f}±{se:.3f}"
            print(
                f"{sym:<10} | {n:<6} | {wr:5.1f}% | {tot:+8.1f}R | "
                f"{r_str:<18} | {t_st:+6.2f} | {pf:5.2f} | {dd:6.1f}R | {nl}/{ns}"
            )
        n, wr, tot, mr, se, t_st, pf, dd = summarize(all_rs)
        r_str = f"{mr:+.3f}±{se:.3f}"
        print("-" * 100)
        print(
            f"{'CONSOLIDADO':<10} | {n:<6} | {wr:5.1f}% | {tot:+8.1f}R | "
            f"{r_str:<18} | {t_st:+6.2f} | {pf:5.2f} | {dd:6.1f}R |"
        )


if __name__ == "__main__":
    main()

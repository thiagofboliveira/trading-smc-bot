"""Pesquisa Quantitativa e Backtest:
Estratégia Fibo Dynamic Zone (M5) com MME 80 + MMA 200 (Slope 20°/30°) e Fibo 61.8% / 79.0%.

Avalia empiricamente as variações de:
1. Toque Limite vs. Candle de Rejeição (Pavio)
2. Ângulo da MME 80 na caixa do range de candles (20° vs. 30°)
3. Trava de Proteção de Lucro (Profit Lock: move stop para +1.0R ao atingir +1.618R)
4. Qualidade SMC: FVG na perna do BOS + ICT Killzones (Londres/NY) + Inducement (IDM)
"""

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from smc_trader.data.store import load_candles
from smc_trader.strategies.fibo_dynamic_zone import (
    DynamicZoneTrade,
    FiboDynamicZoneConfig,
    FiboDynamicZoneStrategy,
)

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


@dataclass
class VariantResult:
    name: str
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    total_r: float
    r_per_trade: float
    stderr_r: float
    t_stat: float
    profit_factor: float
    max_dd_r: float
    total_pnl_pct: float
    trades_long: int
    trades_short: int


def calculate_metrics(name: str, trades: list[DynamicZoneTrade]) -> VariantResult:
    n = len(trades)
    if n == 0:
        return VariantResult(name, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0)

    rs = np.array([t.r_multiple for t in trades], dtype=float)
    wins = int(np.sum(rs > 0))
    losses = int(np.sum(rs <= 0))
    win_rate = (wins / n) * 100.0
    total_r = float(np.sum(rs))
    mean_r = float(np.mean(rs))
    std_r = float(np.std(rs, ddof=1)) if n > 1 else 0.0
    stderr = std_r / np.sqrt(n) if n > 1 else 0.0
    t_stat = mean_r / stderr if stderr > 0 else 0.0

    gross_profit = float(np.sum(rs[rs > 0])) if wins > 0 else 0.0
    gross_loss = float(abs(np.sum(rs[rs <= 0]))) if losses > 0 else 0.0
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

    equity_curve = np.cumsum(rs)
    peak = np.maximum.accumulate(equity_curve)
    drawdowns = peak - equity_curve
    max_dd_r = float(np.max(drawdowns)) if len(drawdowns) > 0 else 0.0

    total_pnl_pct = total_r * 2.0

    n_long = sum(1 for t in trades if t.direction == "long")
    n_short = sum(1 for t in trades if t.direction == "short")

    return VariantResult(
        name=name,
        total_trades=n,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        total_r=total_r,
        r_per_trade=mean_r,
        stderr_r=stderr,
        t_stat=t_stat,
        profit_factor=pf,
        max_dd_r=max_dd_r,
        total_pnl_pct=total_pnl_pct,
        trades_long=n_long,
        trades_short=n_short,
    )


def run_experiment():
    data_dir = Path("data")
    print("=" * 100)
    print("BACKTEST COMPARATIVO DE VARIAÇÕES: FIBO DYNAMIC ZONE (M5) - 2021 A 2026")
    print("=" * 100)

    base = FiboDynamicZoneConfig(
        timeframe="M5",
        fibo_entry=0.618,
        fibo_zone_deep=0.790,
        fibo_stop=0.820,
        stop_mode="fibo_82",
        target_rr=3.0,
        ema_fast_period=80,
        sma_slow_period=200,
        slope_lookback=50,
        zone_confluence_mode="fibo_within_ma",
        max_stops_per_day=2,
        max_gains_per_day=1,
        max_trades_per_day=3,
    )

    variants = [
        # Baselines sem Profit Lock
        ("V1_20deg_Limit_Base", replace(base, min_slope_degrees=20.0)),
        ("V2_30deg_Limit_Base", replace(base, min_slope_degrees=30.0)),
        # Com Profit Lock (+1.0R ao atingir +1.618R)
        (
            "V3_20deg_Limit_ProfitLock",
            replace(base, min_slope_degrees=20.0, profit_lock_trigger_r=1.618, profit_lock_lock_r=1.0),
        ),
        (
            "V4_30deg_Limit_ProfitLock",
            replace(base, min_slope_degrees=30.0, profit_lock_trigger_r=1.618, profit_lock_lock_r=1.0),
        ),
        # Com FVG na perna + ICT Killzones + Profit Lock
        (
            "V5_20deg_Limit_FVG_KZ_PL",
            replace(
                base,
                min_slope_degrees=20.0,
                require_leg_fvg=True,
                session_filter=True,
                profit_lock_trigger_r=1.618,
                profit_lock_lock_r=1.0,
            ),
        ),
        (
            "V6_30deg_Limit_FVG_KZ_PL",
            replace(
                base,
                min_slope_degrees=30.0,
                require_leg_fvg=True,
                session_filter=True,
                profit_lock_trigger_r=1.618,
                profit_lock_lock_r=1.0,
            ),
        ),
        # Com Inducement (IDM) + FVG + Profit Lock
        (
            "V7_20deg_Limit_IDM_FVG_PL",
            replace(
                base,
                min_slope_degrees=20.0,
                require_leg_fvg=True,
                require_inducement=True,
                profit_lock_trigger_r=1.618,
                profit_lock_lock_r=1.0,
            ),
        ),
        (
            "V8_20deg_Overlap_IDM_FVG_PL",
            replace(
                base,
                min_slope_degrees=20.0,
                zone_confluence_mode="overlap",
                require_leg_fvg=True,
                require_inducement=True,
                session_filter=True,
                profit_lock_trigger_r=1.618,
                profit_lock_lock_r=1.0,
            ),
        ),
        # Rejeição com Profit Lock (+1.0R em +1.618R) + FVG + Killzones
        (
            "V9_20deg_Rej_FVG_KZ_PL",
            replace(
                base,
                min_slope_degrees=20.0,
                entry_mode="rejection",
                rejection_min_wick_ratio=0.35,
                require_leg_fvg=True,
                session_filter=True,
                profit_lock_trigger_r=1.618,
                profit_lock_lock_r=1.0,
            ),
        ),
        (
            "V10_20deg_Overlap_Rej_PL",
            replace(
                base,
                min_slope_degrees=20.0,
                zone_confluence_mode="overlap",
                entry_mode="rejection",
                rejection_min_wick_ratio=0.35,
                require_leg_fvg=True,
                session_filter=True,
                profit_lock_trigger_r=1.618,
                profit_lock_lock_r=1.0,
            ),
        ),
        # Novos modos: MME 80 passando dentro da zona Fibo [61.8%-79%] com MMA 200 como piso
        (
            "V11_20deg_EMA80inFibo_PL",
            replace(
                base,
                min_slope_degrees=20.0,
                zone_confluence_mode="ema80_in_fibo",
                profit_lock_trigger_r=1.618,
                profit_lock_lock_r=1.0,
            ),
        ),
        (
            "V12_30deg_EMA80inFibo_PL",
            replace(
                base,
                min_slope_degrees=30.0,
                zone_confluence_mode="ema80_in_fibo",
                profit_lock_trigger_r=1.618,
                profit_lock_lock_r=1.0,
            ),
        ),
        (
            "V13_20deg_EMA80inFibo_FVG_KZ",
            replace(
                base,
                min_slope_degrees=20.0,
                zone_confluence_mode="ema80_in_fibo",
                require_leg_fvg=True,
                session_filter=True,
                profit_lock_trigger_r=1.618,
                profit_lock_lock_r=1.0,
            ),
        ),
        (
            "V14_20deg_AboveSMA200_FVG_KZ",
            replace(
                base,
                min_slope_degrees=20.0,
                zone_confluence_mode="fibo_above_sma200",
                require_leg_fvg=True,
                session_filter=True,
                profit_lock_trigger_r=1.618,
                profit_lock_lock_r=1.0,
            ),
        ),
        (
            "V15_30deg_AboveSMA200_FVG_KZ",
            replace(
                base,
                min_slope_degrees=30.0,
                zone_confluence_mode="fibo_above_sma200",
                require_leg_fvg=True,
                session_filter=True,
                profit_lock_trigger_r=1.618,
                profit_lock_lock_r=1.0,
            ),
        ),
    ]

    all_trades: dict[str, list[DynamicZoneTrade]] = {v[0]: [] for v in variants}
    asset_trades: dict[str, dict[str, list[DynamicZoneTrade]]] = {
        sym: {v[0]: [] for v in variants} for sym in SYMBOLS
    }

    for sym in SYMBOLS:
        print(f"\nCarregando dados para {sym}...")
        df_m1 = load_candles(data_dir, sym, "M1", source="dukascopy")
        spread = SPREADS[sym]
        slip = SLIPPAGES[sym]

        for var_name, base_cfg in variants:
            cfg = replace(base_cfg, slippage=slip)
            strat = FiboDynamicZoneStrategy(cfg)
            trades = strat.run_backtest(df_m1, symbol=sym, spread=spread)
            all_trades[var_name].extend(trades)
            asset_trades[sym][var_name].extend(trades)

    print("\n" + "=" * 115)
    print("CONSOLIDADO GERAL (6 ATIVOS - 5 ANOS 2021-2026)")
    print("=" * 115)
    print(
        f"{'Variante':<28} | {'Trades':<6} | {'WR%':<6} | {'Total R':<9} | "
        f"{'R/Trade (±EP)':<18} | {'t-stat':<6} | {'PF':<5} | {'MaxDD':<7} | {'PnL Banca%':<10}"
    )
    print("-" * 115)

    for var_name, _ in variants:
        res = calculate_metrics(var_name, all_trades[var_name])
        r_str = f"{res.r_per_trade:+.3f}±{res.stderr_r:.3f}"
        print(
            f"{res.name:<28} | {res.total_trades:<6} | {res.win_rate:5.1f}% | {res.total_r:+8.1f}R | "
            f"{r_str:<18} | {res.t_stat:6.2f} | {res.profit_factor:5.2f} | {res.max_dd_r:6.1f}R | {res.total_pnl_pct:+8.1f}%"
        )

    for focus_var in [
        "V6_30deg_Limit_FVG_KZ_PL",
        "V11_20deg_EMA80inFibo_PL",
        "V12_30deg_EMA80inFibo_PL",
        "V13_20deg_EMA80inFibo_FVG_KZ",
        "V14_20deg_AboveSMA200_FVG_KZ",
        "V15_30deg_AboveSMA200_FVG_KZ",
    ]:
        print("\n" + "=" * 95)
        print(f"DETALHAMENTO POR ATIVO ({focus_var})")
        print("=" * 95)
        print(
            f"{'Ativo':<8} | {'Trades':<6} | {'WR%':<6} | {'Total R':<9} | "
            f"{'R/Trade (±EP)':<18} | {'t-stat':<6} | {'PF':<5} | {'MaxDD':<7} | {'Longs/Shorts'}"
        )
        print("-" * 95)
        for sym in SYMBOLS:
            res = calculate_metrics(sym, asset_trades[sym][focus_var])
            r_str = f"{res.r_per_trade:+.3f}±{res.stderr_r:.3f}"
            print(
                f"{res.name:<8} | {res.total_trades:<6} | {res.win_rate:5.1f}% | {res.total_r:+8.1f}R | "
                f"{r_str:<18} | {res.t_stat:6.2f} | {res.profit_factor:5.2f} | {res.max_dd_r:6.1f}R | {res.trades_long}/{res.trades_short}"
            )


if __name__ == "__main__":
    run_experiment()

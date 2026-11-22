"""Auditoria anti-viés da Carteira Unificada (E1 + E2 + E3) nos 21 ativos.

Objetivos:
1. Período real de dados de cada ativo (para calcular trades/ano corretamente).
2. Separar os ativos por grau de contaminação:
   - Lote 1 (6 principais): usados para desenhar a estratégia (in-sample).
   - Lote 2 (6 holdouts): usados na autópsia que escolheu os filtros H1/ADX/Canal (contaminados).
   - Lote 3 (9 novos): testados com a configuração congelada (único fora da amostra limpo).
3. Recalcular a carteira sem escolher ativos depois de ver o resultado.
4. Medir exposição simultânea (posições abertas ao mesmo tempo) e sobreposição E2 x E3.
"""

from dataclasses import replace
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from scripts.research.test_12assets_autopsy import ALL_12, MAIN_SYMBOLS, load_any_asset, summarize
from scripts.research.test_expand_22_assets_portfolio import (
    NEW_10_ASSETS,
    SLIPPAGES,
    SPREADS,
    fetch_or_load_new,
    resample_to_d1,
)
from smc_trader.strategies.d1_mean_reversion import D1MeanReversionConfig, D1MeanReversionStrategy
from smc_trader.strategies.fibo_dynamic_zone import FiboDynamicZoneConfig, FiboDynamicZoneStrategy
from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy

LOTE1 = list(MAIN_SYMBOLS)
LOTE2 = [s for s in ALL_12 if s not in MAIN_SYMBOLS]
LOTE3 = [s for s, _, _, _ in NEW_10_ASSETS if s != "US2000"]
ALL_21 = LOTE1 + LOTE2 + LOTE3

CFG_E3 = FiboDynamicZoneConfig(
    timeframe="M5", fibo_entry=0.618, fibo_zone_shallow=0.618, fibo_zone_deep=0.790, fibo_stop=0.920,
    stop_mode="fibo_82", target_rr=3.0, ema_fast_period=80, sma_slow_period=200,
    min_slope_degrees=30.0, slope_lookback=50, zone_confluence_mode="fibo_within_ma",
    require_leg_fvg=True, session_filter=True, max_stops_per_day=2, max_gains_per_day=1, max_trades_per_day=3,
    breakeven_trigger_r=1.25, breakeven_lock_r=0.1, profit_lock_trigger_r=2.0, profit_lock_lock_r=1.0,
    require_h1_trend_alignment=True, min_adx=22.0, max_adx=35.0,
)

CFG_E2 = FiboOTEConfig(
    timeframe="M5", fibo_entry=0.618, fibo_rejection_max=0.790, fibo_stop=0.886,
    entry_mode="m5_close_rejection", stop_mode="fibo", rejection_min_wick_ratio=0.50,
    target_mode="3R", target_r=3.0, pivot_k=2, max_holding_candles=60,
    trend_ma="ema80", confluence_ma="ema80", require_inducement=True, require_leg_fvg=True,
    max_trades_per_day=3, max_stops_per_day=2, max_gains_per_day=1,
    partial_exit_trigger_r=1.618, partial_exit_pct=0.50,
    profit_lock_trigger_r=1.618, profit_lock_guarantee_r=1.0,
    session_filter=True, session_windows=[("07:00", "10:30"), ("12:30", "16:30")],
)


def line(label: str, rs: list[float], years: float | None = None) -> str:
    n, wr, tot, mr, se, t, pf, dd = summarize(rs)
    per_year = f"{n / years:5.1f}/ano" if years else "   -    "
    return (
        f"  {label:<46} | {n:4d} tr ({per_year}) | WR {wr:5.1f}% | Total {tot:+6.1f}R | "
        f"R/tr {mr:+.3f}±{se:.3f} | t={t:+5.2f} | PF {pf:4.2f} | MaxDD {dd:4.1f}R"
    )


def max_concurrency(records: pd.DataFrame) -> tuple[int, float]:
    events = []
    for _, r in records.iterrows():
        events.append((r["entry"], 1))
        events.append((r["exit"], -1))
    events.sort(key=lambda e: (e[0], e[1]))  # saídas antes de entradas no mesmo instante
    cur, peak, above4 = 0, 0, 0
    for _, delta in events:
        cur += delta
        peak = max(peak, cur)
        if delta == 1 and cur > 4:
            above4 += 1
    pct_above4 = 100.0 * above4 / max(1, len(records))
    return peak, pct_above4


def main() -> None:
    start = datetime(2022, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dfs = {s: load_any_asset(s) for s in ALL_12}
    for sym, instr, _, _ in NEW_10_ASSETS:
        if sym != "US2000":
            dfs[sym] = fetch_or_load_new(sym, instr, start, end)

    print("=" * 120)
    print("1) PERÍODO REAL DE DADOS POR ATIVO")
    print("=" * 120)
    spans = {}
    for s in ALL_21:
        idx = dfs[s].index
        yrs = (idx[-1] - idx[0]).days / 365.25
        spans[s] = yrs
        lote = "Lote1" if s in LOTE1 else ("Lote2" if s in LOTE2 else "Lote3")
        print(f"  {lote} {s:<8}: {idx[0].date()} -> {idx[-1].date()}  ({yrs:4.2f} anos)")

    print("\n" + "=" * 120)
    print("2) ESTRATÉGIA 3 POR GRAU DE CONTAMINAÇÃO")
    print("=" * 120)
    rec = []
    for s in ALL_21:
        trades = FiboDynamicZoneStrategy(replace(CFG_E3, slippage=SLIPPAGES[s])).run_backtest(dfs[s], s, SPREADS[s])
        for t in trades:
            rec.append({"strategy": "E3", "sym": s, "entry": t.entry_time, "exit": t.exit_time, "r": t.r_multiple})
    e3 = pd.DataFrame(rec)
    for label, syms in [("Lote 1 (in-sample, desenho)", LOTE1), ("Lote 2 (holdout usado na autópsia)", LOTE2),
                        ("Lote 3 (fora da amostra limpo)", LOTE3), ("Todos os 21 (sem escolher ativos)", ALL_21)]:
        sub = e3[e3["sym"].isin(syms)]
        yrs = float(np.mean([spans[s] for s in syms]))
        pos = sum(1 for s in syms if sub[sub["sym"] == s]["r"].sum() > 0)
        print(line(f"{label} [{pos}/{len(syms)} ativos +]", sub["r"].tolist(), yrs * len(syms) / len(syms)))

    pos_assets = [s for s in ALL_21 if e3[e3["sym"] == s]["r"].sum() > 0]
    sel = e3[e3["sym"].isin(pos_assets)]
    print(line(f"Só ativos positivos ({len(pos_assets)}) — CIRCULAR", sel["r"].tolist()))

    print("\n" + "=" * 120)
    print("3) CARTEIRA UNIFICADA RECALCULADA")
    print("=" * 120)
    rec1 = []
    for s in ["NAS100", "US30", "SPX500"]:
        tr = D1MeanReversionStrategy(D1MeanReversionConfig(slippage_pts=SLIPPAGES[s])).run_simulation(
            resample_to_d1(dfs[s]), s, SPREADS[s])
        rec1 += [{"strategy": "E1", "sym": s, "entry": t.entry_time, "exit": t.exit_time, "r": t.r_multiple} for t in tr]
    rec2 = []
    for s in ["BRENT", "NAS100", "XAUUSD"]:
        tr = FiboOTEStrategy(replace(CFG_E2, slippage=SLIPPAGES[s])).run_backtest(dfs[s], s, SPREADS[s])
        rec2 += [{"strategy": "E2", "sym": s, "entry": t.entry_time, "exit": t.exit_time, "r": t.r_multiple} for t in tr]
    e1, e2 = pd.DataFrame(rec1), pd.DataFrame(rec2)

    port = pd.concat([e1, e2, e3], ignore_index=True).sort_values("exit")
    first, last = port["exit"].min(), port["exit"].max()
    yrs_port = (last - first).days / 365.25
    print(f"  Janela efetiva da carteira: {first.date()} -> {last.date()} ({yrs_port:.2f} anos)")
    print(line("E1 (D1, 3 índices)", e1["r"].tolist(), yrs_port))
    print(line("E2 (M5, BRENT/NAS100/XAUUSD)", e2["r"].tolist(), yrs_port))
    print(line("E3 (M5, 21 ativos, sem seleção)", e3["r"].tolist(), yrs_port))
    print(line("CARTEIRA E1+E2+E3 (21 ativos)", port["r"].tolist(), yrs_port))
    port_oos = port[port["exit"] >= pd.Timestamp("2025-01-01", tz="UTC")]
    print(line("CARTEIRA só 2025+ (fora da amostra temporal)", port_oos["r"].tolist()))

    print("\n  Ano a ano (por data de saída):")
    port["year"] = port["exit"].dt.year
    for y, g in port.groupby("year"):
        n, wr, tot, _, _, _, pf, dd = summarize(g["r"].tolist())
        comp = " ".join(f"{k}:{len(g[g['strategy'] == k])}" for k in ["E1", "E2", "E3"])
        print(f"    {y}: {n:4d} tr ({comp}) | WR {wr:5.1f}% | {tot:+6.1f}R | PF {pf:4.2f} | DD {dd:4.1f}R")

    print("\n" + "=" * 120)
    print("4) EXPOSIÇÃO SIMULTÂNEA")
    print("=" * 120)
    peak, pct4 = max_concurrency(port)
    print(f"  Máximo de posições abertas ao mesmo tempo: {peak}")
    print(f"  Entradas que ocorreram com mais de 4 posições abertas: {pct4:.1f}%")
    for s in ["XAUUSD", "BRENT"]:
        a = e2[e2["sym"] == s]
        b = e3[e3["sym"] == s]
        overlap = sum(1 for _, x in a.iterrows() for _, y in b.iterrows()
                      if x["entry"] < y["exit"] and y["entry"] < x["exit"])
        print(f"  {s}: {overlap} pares de trades E2 x E3 abertos ao mesmo tempo no mesmo ativo")


if __name__ == "__main__":
    main()

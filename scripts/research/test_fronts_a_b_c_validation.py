"""Validação Científica das 3 Frentes Estruturais (A, B e C):
Frente A: Nível de Entrada dentro da Zona [61.8% - 79.0%] (61.8%, 65.0%, 66.0%, 70.5% e Entrada Fracionada 50/50)
Frente B: Alvo Estrutural no Topo/Fundo da Perna (0% Fibo) vs. Parcial no 0% Fibo + Runner 3R vs. 3R Fixo
Frente C:
  1) Teste Cego em Bases Holdout Nunca Vistas (GER40, SPX500 e NAS100 Pré-2021)
  2) Teste de Controle de Entrada Aleatória sob o mesmo Regime Macro (30° + Killzones + Condução 2 Estágios)
  3) Teste Sem Custo (Zero-Cost Round) vs. Com Custo Real
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

SYMBOLS = ["NAS100", "US30", "BRENT", "EURUSD", "GBPUSD", "XAUUSD"]
BASKET_4 = ["EURUSD", "XAUUSD", "US30", "BRENT"]

SPREADS = {
    "XAUUSD": 0.20,
    "EURUSD": 0.00008,
    "GBPUSD": 0.00010,
    "US30": 2.0,
    "NAS100": 1.5,
    "BRENT": 0.03,
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
    "GER40": 1.0,
    "SPX500": 0.25,
}

OOS_START = pd.Timestamp("2025-01-01", tz="UTC")


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


def run_random_control(
    df_m1: pd.DataFrame,
    cfg: FiboDynamicZoneConfig,
    spread: float,
    target_n_trades: int,
    seed: int = 42,
) -> list[float]:
    """Simula entrada aleatória sob o MESMO regime macro (MME80 vs MMA200 a >=30° + Killzones)
    e MESMA condução em 2 estágios (BE +0.1R em +1.25R, Lock +1.0R em +2.0R, Alvo 3.0R).
    """
    if target_n_trades <= 0:
        return []
    strat = FiboDynamicZoneStrategy(cfg)
    df = strat.resample_data(df_m1)
    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    emas80 = df["ema80"].to_numpy()
    smas200 = df["sma200"].to_numpy()
    slope_deg = df["slope_deg"].to_numpy()
    atrs = df["atr"].to_numpy()
    ts = df.index
    n = len(df)

    # Identifica todas as barras elegíveis pelo regime macro (avaliado em i-1) + Killzones
    eligible_bars: list[tuple[int, int]] = []
    for i in range(210, n - 72):
        t_str = ts[i].strftime("%H:%M")
        if cfg.session_filter and not any(w0 <= t_str < w1 for w0, w1 in cfg.session_windows):
            continue
        if np.isnan(emas80[i - 1]) or np.isnan(smas200[i - 1]) or np.isnan(atrs[i - 1]) or atrs[i - 1] <= 0:
            continue
        if emas80[i - 1] > smas200[i - 1] and slope_deg[i - 1] >= cfg.min_slope_degrees:
            eligible_bars.append((i, 1))
        elif emas80[i - 1] < smas200[i - 1] and slope_deg[i - 1] <= -cfg.min_slope_degrees:
            eligible_bars.append((i, -1))

    if not eligible_bars:
        return []

    rng = np.random.default_rng(seed)
    all_mc_rs: list[float] = []
    # Roda 20 realizações de Monte Carlo com a mesma frequência
    for _ in range(20):
        chosen_indices = sorted(
            rng.choice(len(eligible_bars), size=min(target_n_trades, len(eligible_bars)), replace=False)
        )
        last_exit = -1
        for idx in chosen_indices:
            bar_i, d = eligible_bars[idx]
            if bar_i <= last_exit:
                continue
            slip = cfg.slippage if d == 1 else -cfg.slippage
            entry = opens[bar_i] + (spread if d == 1 else 0.0) + slip
            risk = 1.5 * atrs[bar_i - 1]
            if risk <= spread * 1.5:
                continue
            stop = entry - d * risk
            target = entry + d * risk * cfg.target_rr
            be_act = False
            locked = False

            # Checa stop intrabar na barra de entrada
            adv_entry = lows[bar_i] if d == 1 else highs[bar_i] + spread
            if d * (stop - adv_entry) >= 0:
                exit_px = (min(opens[bar_i], stop) - cfg.slippage) if d == 1 else (max(opens[bar_i] + spread, stop) + cfg.slippage)
                all_mc_rs.append(d * (exit_px - entry) / risk)
                last_exit = bar_i
                continue

            for j in range(bar_i + 1, min(bar_i + 72, n)):
                adv = lows[j] if d == 1 else highs[j] + spread
                fav = highs[j] if d == 1 else lows[j] + spread
                if d * (stop - adv) >= 0:
                    exit_px = (min(opens[j], stop) - cfg.slippage) if d == 1 else (max(opens[j] + spread, stop) + cfg.slippage)
                    all_mc_rs.append(d * (exit_px - entry) / risk)
                    last_exit = j
                    break
                if d * (fav - target) >= 0:
                    exit_px = (max(opens[j], target) - cfg.slippage) if d == 1 else (min(opens[j] + spread, target) + cfg.slippage)
                    all_mc_rs.append(d * (exit_px - entry) / risk)
                    last_exit = j
                    break
                if not be_act and not locked and cfg.breakeven_trigger_r > 0:
                    if d * (fav - (entry + d * risk * cfg.breakeven_trigger_r)) >= 0:
                        stop = entry + d * risk * cfg.breakeven_lock_r
                        be_act = True
                if not locked and cfg.profit_lock_trigger_r > 0:
                    if d * (fav - (entry + d * risk * cfg.profit_lock_trigger_r)) >= 0:
                        stop = entry + d * risk * cfg.profit_lock_lock_r
                        locked = True
    return all_mc_rs


def main():
    data_dir = Path("data")
    dfs = {sym: load_candles(data_dir, sym, "M1", source="dukascopy") for sym in SYMBOLS}

    base = FiboDynamicZoneConfig(
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

    print("=" * 125)
    print("FRENTE A & B: PONTO DE ENTRADA NA ZONA [61.8%-79.0%] E ALVO ESTRUTURAL (0% FIBO vs 3R)")
    print("=" * 125)
    print(
        f"{'Variante':<34} | {'Total 6 Ativos':<30} | {'Cesta 4 (EUR+XAU+US30+BRENT)':<32} | {'IS (21-24) / OOS (25-26) Cesta 4'}"
    )
    print("-" * 125)

    ab_variants = [
        # Frente A: Nível de Entrada dentro da Zona [61.8% - 79.0%] com Stop 88.6% e 92.0%
        ("A1_Entry618_Stop886_2Stage", base),
        ("A2_Entry650_Stop886_2Stage", replace(base, fibo_entry=0.650)),
        ("A3_Entry660_Stop886_2Stage", replace(base, fibo_entry=0.660)),
        ("A4_Entry705_Stop886_2Stage", replace(base, fibo_entry=0.705)),
        ("A5_Entry618_Stop920_2Stage", replace(base, fibo_stop=0.920)),
        ("A6_Entry650_Stop920_2Stage", replace(base, fibo_entry=0.650, fibo_stop=0.920)),
        ("A7_Entry660_Stop920_2Stage", replace(base, fibo_entry=0.660, fibo_stop=0.920)),
        ("A8_Entry705_Stop920_2Stage", replace(base, fibo_entry=0.705, fibo_stop=0.920)),
        # Frente B: Alvo Estrutural no Topo/Fundo (0% Fibo) e Parcial no 0% Fibo + Runner 3R
        ("B1_Entry618_Stop886_Target0Pct", replace(base, target_mode="structural_0")),
        ("B2_Entry650_Stop886_Target0Pct", replace(base, fibo_entry=0.650, target_mode="structural_0")),
        ("B3_Entry618_Stop886_Part0_Run3R", replace(base, target_mode="partial_0_runner_3r")),
        ("B4_Entry650_Stop886_Part0_Run3R", replace(base, fibo_entry=0.650, target_mode="partial_0_runner_3r")),
        ("B5_Entry650_Stop920_Part0_Run3R", replace(base, fibo_entry=0.650, fibo_stop=0.920, target_mode="partial_0_runner_3r")),
    ]

    for vname, vcfg in ab_variants:
        all_rs, b4_rs, b4_is, b4_oos = [], [], [], []
        for sym in SYMBOLS:
            cfg = replace(vcfg, slippage=SLIPPAGES[sym])
            trades = FiboDynamicZoneStrategy(cfg).run_backtest(dfs[sym], symbol=sym, spread=SPREADS[sym])
            for t in trades:
                all_rs.append(t.r_multiple)
                if sym in BASKET_4:
                    b4_rs.append(t.r_multiple)
                    if t.entry_time < OOS_START:
                        b4_is.append(t.r_multiple)
                    else:
                        b4_oos.append(t.r_multiple)

        na, wra, tota, _, _, ta, pfa, dda = summarize(all_rs)
        nb, wrb, totb, _, _, tb, pfb, ddb = summarize(b4_rs)
        nis, _, totis, _, _, _, pfis, _ = summarize(b4_is)
        noos, _, totoos, _, _, _, pfoos, _ = summarize(b4_oos)
        print(
            f"{vname:<34} | {na:3d}tr {tota:+6.1f}R WR{wra:4.1f}% PF{pfa:4.2f} t{ta:+4.2f} | "
            f"{nb:3d}tr {totb:+6.1f}R WR{wrb:4.1f}% PF{pfb:4.2f} t{tb:+4.2f} DD{ddb:3.1f}R | "
            f"IS:{totis:+5.1f}R(PF{pfis:4.2f}) / OOS:{totoos:+5.1f}R(PF{pfoos:4.2f})"
        )

    # =========================================================================
    # FRENTE C: HOLDOUT CEGO (GER40, SPX500, NAS100 PRE-2021), ZERO-COST E RANDOM CONTROL
    # =========================================================================
    print("\n" + "=" * 125)
    print("FRENTE C.1: TESTE CEGO NAS BASES DE HOLDOUT INTOCADAS (GER40, SPX500, NAS100 PRÉ-2021)")
    print("=" * 125)
    holdout_files = [
        ("GER40", Path("data/holdout/GER40_M1.parquet")),
        ("SPX500", Path("data/holdout/SPX500_M1.parquet")),
        ("NAS100_PRE21", Path("data/holdout/NAS100_M1.parquet")),
    ]
    for h_sym, h_path in holdout_files:
        if not h_path.exists():
            continue
        df_h = pd.read_parquet(h_path)
        if not isinstance(df_h.index, pd.DatetimeIndex):
            if "timestamp" in df_h.columns:
                df_h = df_h.set_index("timestamp")
            elif "time" in df_h.columns:
                df_h = df_h.set_index("time")
        if df_h.index.tz is None:
            df_h.index = df_h.index.tz_localize("UTC")
        base_sym = "NAS100" if "NAS100" in h_sym else h_sym
        for h_var_name, h_cfg in [
            ("Stop886_Entry618_2Stage", base),
            ("Stop920_Entry618_2Stage", replace(base, fibo_stop=0.920)),
            ("Stop886_Entry650_2Stage", replace(base, fibo_entry=0.650)),
        ]:
            trades_h = FiboDynamicZoneStrategy(replace(h_cfg, slippage=SLIPPAGES[base_sym])).run_backtest(
                df_h, symbol=h_sym, spread=SPREADS[base_sym]
            )
            nh, wrh, toth, mrh, seh, th, pfh, ddh = summarize([t.r_multiple for t in trades_h])
            print(
                f"  Holdout {h_sym:<12} [{h_var_name:<24}]: {nh:3d} tr | WR {wrh:5.1f}% | "
                f"Total {toth:+6.1f}R | R/tr {mrh:+.3f}±{seh:.3f} | t={th:+5.2f} | PF {pfh:4.2f} | MaxDD {ddh:4.1f}R"
            )

    print("\n" + "=" * 125)
    print("FRENTE C.2: AUDITORIA DE ALPHA REAL vs. CONTROLE DE ENTRADA ALEATÓRIA E RODADA SEM CUSTO (AGENTS.md)")
    print("=" * 125)
    real_rs_b4, zero_cost_rs_b4, rand_rs_b4 = [], [], []
    for sym in BASKET_4:
        cfg_real = replace(base, slippage=SLIPPAGES[sym])
        trades_real = FiboDynamicZoneStrategy(cfg_real).run_backtest(dfs[sym], symbol=sym, spread=SPREADS[sym])
        real_rs_b4.extend([t.r_multiple for t in trades_real])

        cfg_zero = replace(base, slippage=0.0, commission_per_unit=0.0)
        trades_zero = FiboDynamicZoneStrategy(cfg_zero).run_backtest(dfs[sym], symbol=sym, spread=0.000001)
        zero_cost_rs_b4.extend([t.r_multiple for t in trades_zero])

        mc_rs = run_random_control(dfs[sym], cfg_real, SPREADS[sym], len(trades_real))
        rand_rs_b4.extend(mc_rs)

    nr, wrr, totr, mrr, ser, tr_s, pfr, ddr = summarize(real_rs_b4)
    nz, wrz, totz, mrz, sez, tz_s, pfz, ddz = summarize(zero_cost_rs_b4)
    nmc, wrmc, _, mrmc, semc, tmc_s, pfmc, _ = summarize(rand_rs_b4)

    print(f"  1) Rodada Sem Custo (Zero-Cost Cesta 4) : {nz:3d} tr | WR {wrz:5.1f}% | Total {totz:+6.1f}R | R/tr {mrz:+.3f}±{sez:.3f} | t={tz_s:+5.2f} | PF {pfz:4.2f}")
    print(f"  2) Estratégia Real Com Custos (Cesta 4) : {nr:3d} tr | WR {wrr:5.1f}% | Total {totr:+6.1f}R | R/tr {mrr:+.3f}±{ser:.3f} | t={tr_s:+5.2f} | PF {pfr:4.2f}")
    print(f"  3) Controle Entrada Aleatória (20x MC)  : {nmc:4d} tr | WR {wrmc:5.1f}% | Equiv {mrmc*nr:+6.1f}R | R/tr {mrmc:+.3f}±{semc:.3f} | t={tmc_s:+5.2f} | PF {pfmc:4.2f}")
    diff_alpha = mrr - mrmc
    print(f"  --> Alpha Líquido do Gatilho Fibo sobre o Regime Macro 30°: {diff_alpha:+.3f} R/trade (Erro Padrão Strategia: ±{ser:.3f} R/trade)")


if __name__ == "__main__":
    main()

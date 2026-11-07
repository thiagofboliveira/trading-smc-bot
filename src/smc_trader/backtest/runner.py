from dataclasses import dataclass
from typing import Any

import pandas as pd

from smc_trader.analysis import analyze
from smc_trader.backtest.attribution import (
    VariantExecutionSummary,
    analyze_attribution,
    format_attribution_markdown,
)
from smc_trader.backtest.engine import BacktestEngine
from smc_trader.backtest.grid import GridVariant, generate_grid_variants
from smc_trader.backtest.split import generate_walk_forward_windows, split_is_oos
from smc_trader.config import BacktestConfig, ZoneConfig
from smc_trader.data.resample import resample_ohlc
from smc_trader.structure.market_structure import detect_structure
from smc_trader.structure.pivots import find_pivots
from smc_trader.zones.orderblock import Zone


@dataclass
class WalkForwardStep:
    window_id: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_start: pd.Timestamp
    test_end: pd.Timestamp
    best_variant_hash: str
    is_expectancy: float
    is_trades: int
    oos_expectancy: float
    oos_trades: int
    oos_r: float


@dataclass
class WalkForwardSummary:
    steps: list[WalkForwardStep]
    total_oos_trades: int
    combined_oos_r: float
    wfe: float  # Walk-Forward Efficiency (OOS Annual Return / IS Annual Return)


@dataclass
class GridRunResult:
    symbol: str
    summaries: list[VariantExecutionSummary]
    attribution_analysis: dict[str, Any]
    breaker_stats: dict[str, Any]
    markdown_report: str
    walk_forward: WalkForwardSummary | None = None


def _precompute_m1_structures(
    candles_m1: pd.DataFrame, base_config: BacktestConfig
) -> dict[str, Any]:
    """Pré-computa pivôs, CHoCHs e médias M1 uma única vez para acelerar a grade."""
    if candles_m1.empty:
        return {}
    pivots_m1 = find_pivots(candles_m1, k=2)
    events_m1 = detect_structure(candles_m1, pivots_m1)
    m1_chochs = {(e.direction, e.time): e for e in events_m1 if e.kind == "CHoCH"}
    m1_bos = {(e.direction, e.time): e for e in events_m1 if e.kind == "BOS"}
    eng_temp = BacktestEngine(base_config)
    ema80 = eng_temp._prepare_ma_series(
        candles_m1, base_config.confluence.ma_timeframe, "ema", 80
    )
    sma200 = eng_temp._prepare_ma_series(
        candles_m1, base_config.confluence.ma_timeframe, "sma", 200
    )
    return {
        "events": events_m1,
        "chochs": m1_chochs,
        "bos": m1_bos,
        "ema80": ema80,
        "sma200": sma200,
    }


def compute_breaker_stats(
    candles_m15: pd.DataFrame, breakers: list[Zone]
) -> dict[str, Any]:
    """Calcula estatísticas sobre breakers, identificando os que tocam a zona no 1º candle M15 após a criação."""
    total_breakers = len(breakers)
    if total_breakers == 0 or candles_m15.empty:
        return {"total_breakers": 0, "early_mitigated": 0, "early_pct": 0.0}

    early_count = 0
    times = candles_m15.index

    for b in breakers:
        # Encontra o candle M15 em que foi criado
        idx = times.searchsorted(b.created_at)
        if idx < len(times):
            # O 1º candle M15 subsequente à criação
            next_idx = idx + 1 if times[idx] == b.created_at else idx
            if next_idx < len(times):
                c_next = candles_m15.iloc[next_idx]
                touched = False
                if b.direction == "long":
                    if c_next["low"] <= b.high:
                        touched = True
                else:
                    if c_next["high"] >= b.low:
                        touched = True
                if touched:
                    early_count += 1

    return {
        "total_breakers": total_breakers,
        "early_mitigated": early_count,
        "early_pct": (early_count / total_breakers * 100.0)
        if total_breakers > 0
        else 0.0,
    }


def run_grid(
    candles_m1: pd.DataFrame,
    symbol: str = "XAUUSD",
    base_config: BacktestConfig | None = None,
    pivot_k_htf: int = 3,
    min_trades: int = 30,
    run_walk_forward: bool = False,
    is_ratio: float = 0.7,
    variants: list[GridVariant] | None = None,
) -> GridRunResult:
    """Executa a exploração exaustiva da grade de parâmetros SMC."""
    if base_config is None:
        base_config = BacktestConfig()

    if "close_time" not in candles_m1.columns:
        from smc_trader.data.candles import with_close_time

        candles_m1 = with_close_time(candles_m1, "M1")

    # 1. Estrutura macro M15 única para todas as execuções
    candles_m15 = resample_ohlc(candles_m1, "M15")
    # Força detecção de todas as classes de blocos
    zone_cfg = ZoneConfig(
        blocks_filter=["OB", "FVOB", "BB"],
        breaker_require_imbalance=True,
    )
    analysis = analyze(candles_m15, pivot_k_htf, zone_cfg)
    all_zones = analysis.zones + analysis.breakers

    # 2. Estatísticas de Breakers Precoces
    breaker_stats = compute_breaker_stats(candles_m15, analysis.breakers)

    # 3. Divisão cronológica IS / OOS
    is_candles, oos_candles = split_is_oos(candles_m1, is_ratio=is_ratio)
    is_m1_data = _precompute_m1_structures(is_candles, base_config)
    oos_m1_data = _precompute_m1_structures(oos_candles, base_config)

    # 4. Janelas de Walk-Forward se solicitado
    wf_windows = generate_walk_forward_windows(candles_m1) if run_walk_forward else []

    # 5. Geração das variantes da grade
    if variants is None:
        variants = generate_grid_variants(base_config)
    summaries: list[VariantExecutionSummary] = []
    total_var = len(variants)

    for idx, var in enumerate(variants, start=1):
        if idx % 25 == 1 or idx == total_var:
            print(
                f"Progresso da grade: [{idx}/{total_var}] variantes processadas...",
                flush=True,
            )

        # Filtra zonas conforme blocks_filter
        allowed_kinds = set(var.blocks_filter)
        if "BB" in allowed_kinds:
            allowed_kinds.add("BREAKER")

        var_zones = [z for z in all_zones if z.kind in allowed_kinds]

        var_cfg = var.to_backtest_config(base_config)
        engine = BacktestEngine(var_cfg)

        # Execução In-Sample
        is_res = engine.run(
            is_candles, var_zones, symbol=symbol, precomputed_m1=is_m1_data
        )
        # Execução Out-of-Sample
        oos_res = engine.run(
            oos_candles, var_zones, symbol=symbol, precomputed_m1=oos_m1_data
        )

        # Walk-forward por janela (opcional)
        wf_res_metrics: list[dict[str, Any]] = []
        if run_walk_forward:
            for w in wf_windows:
                test_r = engine.run(w.test_df, var_zones, symbol=symbol)
                wf_res_metrics.append(test_r.metrics)

        is_m = is_res.metrics
        oos_m = oos_res.metrics

        is_qual = is_m.get("total_trades", 0) >= min_trades
        oos_prof = oos_m.get("expectancy", 0.0) > 0

        drop_pct: float | None = None
        if is_m.get("expectancy", 0.0) != 0:
            drop_pct = (
                (oos_m.get("expectancy", 0.0) - is_m.get("expectancy", 0.0))
                / abs(is_m.get("expectancy", 0.0))
            ) * 100.0

        summary = VariantExecutionSummary(
            config_hash=var.config_hash,
            blocks_filter="+".join(var.blocks_filter),
            entry_mode=var.entry_mode,
            stop_mode=var.stop_mode,
            trailing_mode=var.trailing_mode,
            confluence_profile=var.confluence_profile,
            is_metrics=is_m,
            oos_metrics=oos_m,
            wf_metrics=wf_res_metrics,
            is_qualified=is_qual,
            oos_profitable=oos_prof,
            performance_drop_pct=drop_pct,
        )
        summaries.append(summary)

    # 6. Atribuição e Ranking
    attr_data = analyze_attribution(summaries, min_trades=min_trades)
    md_report = format_attribution_markdown(
        attr_data, symbol=symbol, breaker_stats=breaker_stats
    )

    # 7. M-02: Walk-Forward Optimization Verdadeiro (otimiza no treino, testa na janela seguinte)
    wf_summary: WalkForwardSummary | None = None
    if run_walk_forward and wf_windows:
        wf_steps: list[WalkForwardStep] = []
        all_oos_trades = []
        total_is_annual_r = 0.0

        for w in wf_windows:
            best_var = None
            best_is_exp = -float("inf")
            best_is_metrics = None

            # Otimização In-Sample na janela de treino w.train_df
            for var in variants:
                allowed_kinds = set(var.blocks_filter)
                if "BB" in allowed_kinds:
                    allowed_kinds.add("BREAKER")
                v_zones = [
                    z
                    for z in all_zones
                    if z.kind in allowed_kinds and z.created_at <= w.train_end
                ]
                v_eng = BacktestEngine(var.to_backtest_config(base_config))
                train_res = v_eng.run(w.train_df, v_zones, symbol=symbol)
                exp = train_res.metrics.get("expectancy", 0.0)
                n_tr = train_res.metrics.get("total_trades", 0)
                if n_tr >= 5 and exp > best_is_exp:
                    best_is_exp = exp
                    best_var = var
                    best_is_metrics = train_res.metrics

            if best_var is None:
                best_var = variants[0]
                allowed_kinds = set(best_var.blocks_filter)
                if "BB" in allowed_kinds:
                    allowed_kinds.add("BREAKER")
                v_zones = [
                    z
                    for z in all_zones
                    if z.kind in allowed_kinds and z.created_at <= w.train_end
                ]
                best_is_metrics = (
                    BacktestEngine(best_var.to_backtest_config(base_config))
                    .run(w.train_df, v_zones, symbol=symbol)
                    .metrics
                )

            # Teste estrito Fora da Amostra (OOS) na janela w.test_df
            allowed_kinds = set(best_var.blocks_filter)
            if "BB" in allowed_kinds:
                allowed_kinds.add("BREAKER")
            v_zones_oos = [
                z
                for z in all_zones
                if z.kind in allowed_kinds and z.created_at <= w.test_end
            ]
            oos_eng = BacktestEngine(best_var.to_backtest_config(base_config))
            oos_res = oos_eng.run(w.test_df, v_zones_oos, symbol=symbol)
            all_oos_trades.extend(oos_res.trades)

            train_days = (w.train_end - w.train_start).total_seconds() / 86400.0
            is_r = best_is_metrics.get("total_r", 0.0)
            is_annual = (is_r / train_days * 365.25) if train_days > 0 else 0.0
            total_is_annual_r += is_annual

            wf_steps.append(
                WalkForwardStep(
                    window_id=w.window_id,
                    train_start=w.train_start,
                    train_end=w.train_end,
                    test_start=w.test_start,
                    test_end=w.test_end,
                    best_variant_hash=best_var.config_hash,
                    is_expectancy=round(best_is_metrics.get("expectancy", 0.0), 3),
                    is_trades=best_is_metrics.get("total_trades", 0),
                    oos_expectancy=round(oos_res.metrics.get("expectancy", 0.0), 3),
                    oos_trades=oos_res.metrics.get("total_trades", 0),
                    oos_r=round(oos_res.metrics.get("total_r", 0.0), 2),
                )
            )

        combined_oos_r = sum(t.r_multiple for t in all_oos_trades)
        total_test_days = sum(
            (w.test_end - w.test_start).total_seconds() / 86400.0 for w in wf_windows
        )
        oos_annual_r = (
            (combined_oos_r / total_test_days * 365.25) if total_test_days > 0 else 0.0
        )
        avg_is_annual = (total_is_annual_r / len(wf_windows)) if wf_windows else 0.0
        wfe = (oos_annual_r / avg_is_annual) if avg_is_annual > 0 else 0.0

        wf_summary = WalkForwardSummary(
            steps=wf_steps,
            total_oos_trades=len(all_oos_trades),
            combined_oos_r=round(combined_oos_r, 2),
            wfe=round(wfe, 3),
        )

        wf_lines = [
            "",
            "## 6. Eficiência de Walk-Forward (WFE — M-02)",
            f"- **Walk-Forward Efficiency (WFE):** `{wf_summary.wfe:.2f}` (Alvo mínimo STANDARDS: `0.70`)",
            f"- **Retorno Anualizado Médio In-Sample (IS):** `{avg_is_annual:+.1f}R/ano`",
            f"- **Retorno Anualizado Realizado Out-of-Sample (OOS):** `{oos_annual_r:+.1f}R/ano`",
            f"- **Total de Trades OOS nas janelas:** `{wf_summary.total_oos_trades}`",
            "",
            "| Janela | Treino (IS) | Teste (OOS) | Variante Escolhida | IS Exp | OOS Exp | OOS Trades | OOS R |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for s in wf_steps:
            tr_str = f"{s.train_start.strftime('%Y-%m-%d')} a {s.train_end.strftime('%Y-%m-%d')}"
            ts_str = f"{s.test_start.strftime('%Y-%m-%d')} a {s.test_end.strftime('%Y-%m-%d')}"
            wf_lines.append(
                f"| {s.window_id} | {tr_str} | {ts_str} | `{s.best_variant_hash}` | "
                f"{s.is_expectancy:+.2f}R | {s.oos_expectancy:+.2f}R | {s.oos_trades} | {s.oos_r:+.1f}R |"
            )
        md_report += "\n".join(wf_lines)

    return GridRunResult(
        symbol=symbol,
        summaries=summaries,
        attribution_analysis=attr_data,
        breaker_stats=breaker_stats,
        markdown_report=md_report,
        walk_forward=wf_summary,
    )

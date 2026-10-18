import json
import time
from pathlib import Path
from typing import Any
import pandas as pd

from smc_trader.backtest.runner import run_grid
from smc_trader.config import load_config
from smc_trader.data.store import load_candles


def run_cross_asset_study(
    symbols: list[str] | None = None,
    start_date: str = "2026-08-15",
    end_date: str = "2026-10-16",
    min_trades: int = 5,
    out_dir: Path = Path("out/study"),
) -> dict[str, Any]:
    """Executa a grade sistemática em múltiplos ativos em busca da melhor estratégia SMC."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_config(Path("config/default.yaml"))

    if symbols is None:
        symbols = ["XAUUSD", "EURUSD", "NAS100"]

    start_dt = pd.Timestamp(start_date, tz="UTC")
    end_dt = pd.Timestamp(end_date, tz="UTC")

    all_results: dict[str, Any] = {}
    best_by_symbol: dict[str, Any] = {}

    print(f"================================================================")
    print(f"🚀 INICIANDO ESTUDO DE OTIMIZAÇÃO SMC MULTI-ATIVO")
    print(f"Período: {start_date} até {end_date} | Ativos: {', '.join(symbols)}")
    print(f"================================================================\n")

    t_global_0 = time.time()

    for idx, sym in enumerate(symbols, start=1):
        t0 = time.time()
        print(f"\n--- [{idx}/{len(symbols)}] OTIMIZANDO ATIVO: {sym} ---")
        try:
            c_m1 = load_candles(cfg.data.root, sym, "M1", start_dt, end_dt)
        except Exception as e:
            print(f"⚠️ Erro ao carregar candles para {sym}: {e}")
            continue

        if c_m1.empty:
            print(f"⚠️ Nenhum candle encontrado para {sym}")
            continue

        print(f"Dados carregados: {len(c_m1):,} candles M1. Rodando 234 variantes com split IS/OOS...")
        grid_res = run_grid(
            candles_m1=c_m1,
            symbol=sym,
            base_config=cfg.backtest,
            pivot_k_htf=cfg.structure.pivot_k_htf,
            min_trades=min_trades,
            run_walk_forward=False,
        )

        analysis = grid_res.attribution_analysis
        ranking = analysis.get("ranking", [])
        total_var = analysis.get("total_variants", 0)
        robust_var = analysis.get("robust_variants", 0)

        # Salva Markdown individual do ativo
        md_file = out_dir / f"grid_{sym}.md"
        with open(md_file, "w", encoding="utf-8") as f:
            f.write(grid_res.markdown_report)

        # Salva JSON individual
        json_file = out_dir / f"grid_{sym}.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json_payload = {
                "symbol": sym,
                "total_candles": len(c_m1),
                "total_variants": total_var,
                "robust_variants": robust_var,
                "breaker_stats": grid_res.breaker_stats,
                "attribution_by_factor": analysis.get("attribution_by_factor", {}),
                "ranking": [
                    {
                        "config_hash": s.config_hash,
                        "blocks_filter": s.blocks_filter,
                        "entry_mode": s.entry_mode,
                        "stop_mode": s.stop_mode,
                        "trailing_mode": s.trailing_mode,
                        "confluence_profile": s.confluence_profile,
                        "is_metrics": s.is_metrics,
                        "oos_metrics": s.oos_metrics,
                        "performance_drop_pct": s.performance_drop_pct,
                    }
                    for s in ranking[:15]
                ],
            }
            json.dump(json_payload, f, indent=2, ensure_ascii=False)

        best = ranking[0] if ranking else None
        if best:
            best_by_symbol[sym] = {
                "config_hash": best.config_hash,
                "blocks_filter": best.blocks_filter,
                "entry_mode": best.entry_mode,
                "stop_mode": best.stop_mode,
                "trailing_mode": best.trailing_mode,
                "confluence_profile": best.confluence_profile,
                "is_expectancy": best.is_metrics.get("expectancy", 0.0),
                "oos_expectancy": best.oos_metrics.get("expectancy", 0.0),
                "oos_win_rate": best.oos_metrics.get("win_rate", 0.0),
                "oos_profit_factor": best.oos_metrics.get("profit_factor", 0.0),
                "oos_drawdown": best.oos_metrics.get("max_drawdown_r", 0.0),
                "oos_trades": best.oos_metrics.get("total_trades", 0),
            }
            print(f"✅ Melhor estratégia [{sym}] ({best.config_hash}):")
            print(f"   Bloco: {best.blocks_filter} | Entrada: {best.entry_mode} | Stop: {best.stop_mode} | Trailing: {best.trailing_mode}")
            print(f"   Expectativa OOS: {best.oos_metrics.get('expectancy', 0.0):+.2f}R | Acerto: {best.oos_metrics.get('win_rate', 0.0):.1f}% | PF: {best.oos_metrics.get('profit_factor', 0.0):.2f}")
        else:
            print(f"⚠️ Nenhuma variante com expectativa OOS > 0 em {sym}")

        all_results[sym] = {
            "best": best_by_symbol.get(sym),
            "total_variants": total_var,
            "robust_variants": robust_var,
            "breaker_stats": grid_res.breaker_stats,
            "elapsed_sec": round(time.time() - t0, 1),
        }
        print(f"Tempo decorrido para {sym}: {time.time() - t0:.1f}s")

    total_elapsed = time.time() - t_global_0
    print(f"\n================================================================")
    print(f"🏁 ESTUDO CONCLUÍDO EM {total_elapsed / 60:.1f} MINUTOS!")
    print(f"================================================================\n")

    # Salva sumário consolidado
    summary_path = out_dir / "summary_cross_asset.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "period": {"start": start_date, "end": end_date},
                "total_elapsed_sec": round(total_elapsed, 1),
                "best_by_symbol": best_by_symbol,
                "details": all_results,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    return {"best_by_symbol": best_by_symbol, "all_results": all_results, "elapsed_sec": total_elapsed}


if __name__ == "__main__":
    run_cross_asset_study()

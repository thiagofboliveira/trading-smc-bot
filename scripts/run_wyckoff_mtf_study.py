"""Estudo Quantitativo Multi-Ativo e Multi-Timeframe: SMC + Wyckoff.

Testa 7 ativos: XAUUSD, BRENT, NAS100, DAX40, EURUSD, GBPUSD, USDJPY
Em 4 pares de timeframes:
  - H4 -> M5
  - H1 -> M5
  - H1 -> M1
  - M15 -> M1
Comparações de estratégia:
  1. SMC Padrão (Sem filtro estrito de sweep)
  2. Wyckoff Spring/UTAD (Apenas zonas com swept_liquidity=True)
  3. Wyckoff + Breakers com Sweep
  4. Wyckoff + Trailing Estrutural BOS (ativação 1R)
"""
import time
from pathlib import Path
from typing import Any
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
import pandas as pd

from smc_trader.analysis import analyze
from smc_trader.backtest.engine import BacktestEngine
from smc_trader.config import BacktestConfig, ZoneConfig, load_config
from smc_trader.data.resample import resample_ohlc
from smc_trader.data.store import load_candles


def run_study():
    data_root = Path("data")
    out_dir = Path("out")
    out_dir.mkdir(parents=True, exist_ok=True)
    excel_path = out_dir / "estudo_wyckoff_multiativo.xlsx"
    md_path = out_dir / "estudo_wyckoff_resumo.md"

    symbols = ["XAUUSD", "BRENT", "NAS100", "DAX40", "EURUSD", "GBPUSD", "USDJPY"]
    tf_pairs = [
        ("M15", "M1"),
        ("H1", "M1"),
        ("H1", "M5"),
        ("H4", "M5"),
    ]

    cfg_global = load_config(Path("config/default.yaml"))
    results_list: list[dict[str, Any]] = []

    print("=" * 70)
    print("🚀 INICIANDO ESTUDO QUANTITATIVO MULTI-ATIVO WYCKOFF + SMC")
    print(f"Ativos: {', '.join(symbols)}")
    print(f"Pares de Timeframes: {tf_pairs}")
    print("=" * 70)

    t_start = time.time()

    for sym in symbols:
        print(f"\n📂 Carregando dados M1 para {sym}...")
        try:
            c_m1 = load_candles(data_root, sym, "M1")
        except Exception as e:
            print(f"  ❌ Erro ao carregar {sym}: {e}")
            continue

        if c_m1.empty:
            print(f"  ⚠️ Dados vazios para {sym}")
            continue

        print(f"  ✅ {len(c_m1):,} candles M1 carregados para {sym}")

        # Pré-computa candles M5 para quando for micro M5
        c_m5 = resample_ohlc(c_m1, "M5")

        for tf_macro, tf_micro in tf_pairs:
            print(f"  ⏱️ Testando par [{tf_macro} -> {tf_micro}] em {sym}...")

            # 1. Resample Macro
            if tf_macro == "M15":
                c_macro = resample_ohlc(c_m1, "M15")
            elif tf_macro == "H1":
                c_macro = resample_ohlc(c_m1, "H1")
            elif tf_macro == "H4":
                c_macro = resample_ohlc(c_m1, "H4")
            else:
                c_macro = resample_ohlc(c_m1, tf_macro)

            if len(c_macro) < 30:
                print(f"    ⚠️ Candles macro insuficientes ({len(c_macro)})")
                continue

            # 2. Resample Micro
            c_micro = c_m1 if tf_micro == "M1" else c_m5

            # 3. Análise Macro
            zone_cfg = ZoneConfig(blocks_filter=["OB", "FVOB", "BB"])
            analysis = analyze(c_macro, k=3, zones_cfg=zone_cfg)
            all_zones = analysis.zones + analysis.breakers

            # Zonas filtradas por Wyckoff (exige varrida prévia de liquidez = Spring / UTAD)
            wyckoff_zones = [z for z in all_zones if z.swept_liquidity]
            wyckoff_obs_only = [z for z in analysis.zones if z.swept_liquidity]

            # 4. Variantes de Estratégia
            strategies = [
                {
                    "name": "SMC Padrão (Sem filtro sweep)",
                    "zones": all_zones,
                    "cfg": BacktestConfig(
                        entry_mode="confirmation",
                        stop_mode="swing",
                        target_mode="fixed_r",
                        target_r=3.0,
                    ),
                },
                {
                    "name": "Wyckoff Spring/UTAD (Sweep Obrigatório)",
                    "zones": wyckoff_obs_only,
                    "cfg": BacktestConfig(
                        entry_mode="confirmation",
                        stop_mode="swing",
                        target_mode="fixed_r",
                        target_r=3.0,
                    ),
                },
                {
                    "name": "Wyckoff + Breakers com Sweep",
                    "zones": wyckoff_zones,
                    "cfg": BacktestConfig(
                        entry_mode="confirmation",
                        stop_mode="swing",
                        target_mode="fixed_r",
                        target_r=3.0,
                    ),
                },
                {
                    "name": "Wyckoff + Trailing BOS (Ativação 1R)",
                    "zones": wyckoff_zones,
                    "cfg": BacktestConfig(
                        entry_mode="confirmation",
                        stop_mode="swing",
                        target_mode="fixed_r",
                        target_r=3.0,
                        trailing={"mode": "bos", "activation": "either"},
                    ),
                },
            ]

            for strat in strategies:
                strat_name = strat["name"]
                strat_zones = strat["zones"]
                strat_cfg = strat["cfg"]

                if not strat_zones:
                    continue

                engine = BacktestEngine(strat_cfg)
                res = engine.run(c_micro, strat_zones, symbol=sym)
                m = res.metrics
                trades = res.trades

                total_t = m.get("total_trades", len(trades))
                if total_t == 0:
                    continue

                win_r = m.get("win_rate", 0.0)
                exp_r = m.get("expectancy", 0.0)
                avg_r = m.get("avg_r", 0.0)
                pf = m.get("profit_factor", 0.0)
                dd_r = m.get("max_drawdown_r", 0.0)
                pnl = m.get("total_pnl", 0.0)

                # Critério de Meta: Taxa de Acerto entre 35% e 45%+ com R:R 1:3 e PF > 1.2
                meets_goal = (win_r >= 35.0) and (pf >= 1.2) and (exp_r > 0.15)

                results_list.append(
                    {
                        "symbol": sym,
                        "tf_pair": f"{tf_macro}/{tf_micro}",
                        "tf_macro": tf_macro,
                        "tf_micro": tf_micro,
                        "strategy": strat_name,
                        "total_trades": total_t,
                        "win_trades": m.get("win_trades", 0),
                        "loss_trades": m.get("loss_trades", 0),
                        "win_rate": round(win_r, 2),
                        "avg_r": round(avg_r, 2),
                        "expectancy": round(exp_r, 2),
                        "profit_factor": round(pf, 2),
                        "max_drawdown_r": round(dd_r, 2),
                        "total_pnl": round(pnl, 2),
                        "meets_goal": meets_goal,
                    }
                )

    print(f"\n✅ Todos os testes concluídos em {time.time() - t_start:.1f}s! Total de combinações testadas: {len(results_list)}")

    # Gerar Relatório Excel
    _export_study_excel(results_list, excel_path)
    # Gerar Resumo Markdown
    _export_study_markdown(results_list, md_path)

    print(f"📊 Relatório Excel gravado em: {excel_path}")
    print(f"📝 Resumo Markdown gravado em: {md_path}")
    return results_list


def _export_study_excel(results: list[dict[str, Any]], excel_path: Path):
    wb = openpyxl.Workbook()
    ws_rank = wb.active
    ws_rank.title = "Ranking & Campeões"

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    fill_blue = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    fill_green = PatternFill(start_color="166534", end_color="166534", fill_type="solid")
    fill_highlight = PatternFill(start_color="DCFCE7", end_color="DCFCE7", fill_type="solid")
    font_bold_green = Font(name="Calibri", size=10, bold=True, color="166534")
    thin_border = Border(
        left=Side(style="thin", color="E5E7EB"),
        right=Side(style="thin", color="E5E7EB"),
        top=Side(style="thin", color="E5E7EB"),
        bottom=Side(style="thin", color="E5E7EB"),
    )

    headers = [
        "Ativo",
        "Par Timeframe",
        "Estratégia",
        "Trades",
        "Gains",
        "Stops",
        "Taxa de Acerto (%)",
        "R Médio",
        "Expectativa (R)",
        "Profit Factor",
        "Max Drawdown (R)",
        "Lucro Total ($)",
        "Atinge Meta (35-40%+ com 1:3)?",
    ]

    ws_rank.append(headers)
    for c_idx in range(1, len(headers) + 1):
        cell = ws_rank.cell(row=1, column=c_idx)
        cell.font = header_font
        cell.fill = fill_blue
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = thin_border

    # Ordenar por: primeiro as que batem a meta, depois por Expectativa decrescente
    sorted_results = sorted(results, key=lambda x: (x["meets_goal"], x["expectancy"], x["profit_factor"]), reverse=True)

    for r in sorted_results:
        row_vals = [
            r["symbol"],
            r["tf_pair"],
            r["strategy"],
            r["total_trades"],
            r["win_trades"],
            r["loss_trades"],
            f"{r['win_rate']:.1f}%",
            f"{r['avg_r']:+.2f}R",
            f"{r['expectancy']:+.2f}R",
            r["profit_factor"],
            f"{r['max_drawdown_r']:.2f}R",
            f"${r['total_pnl']:,.2f}",
            "SIM ⭐" if r["meets_goal"] else "NÃO",
        ]
        ws_rank.append(row_vals)
        curr_row = ws_rank.max_row
        for col_idx in range(1, len(row_vals) + 1):
            c = ws_rank.cell(row=curr_row, column=col_idx)
            c.border = thin_border
            c.font = Font(name="Calibri", size=10)
            c.alignment = Alignment(horizontal="right" if col_idx in [4, 5, 6, 7, 8, 9, 10, 11, 12] else "center", vertical="center")
            if r["meets_goal"]:
                if col_idx == 13:
                    c.fill = fill_highlight
                    c.font = font_bold_green

    for col in ws_rank.columns:
        max_l = max(len(str(cell.value or "")) for cell in col)
        col_let = get_column_letter(col[0].column)
        ws_rank.column_dimensions[col_let].width = max(max_l + 3, 12)

    # --- ABA 2: RESUMO POR ATIVO ---
    ws_assets = wb.create_sheet(title="Melhor Setup por Ativo")
    ws_assets.append(["Ativo", "Melhor Timeframe", "Melhor Estratégia", "Taxa de Acerto", "Expectativa (R)", "Profit Factor", "Trades"])
    for c_idx in range(1, 8):
        cell = ws_assets.cell(row=1, column=c_idx)
        cell.font = header_font
        cell.fill = fill_green
        cell.alignment = Alignment(horizontal="center", vertical="center")

    symbols_list = sorted(list(set(r["symbol"] for r in results)))
    for sym in symbols_list:
        sym_res = [r for r in results if r["symbol"] == sym]
        if not sym_res:
            continue
        best = max(sym_res, key=lambda x: (x["expectancy"], x["profit_factor"]))
        ws_assets.append([
            best["symbol"],
            best["tf_pair"],
            best["strategy"],
            f"{best['win_rate']:.1f}%",
            f"{best['expectancy']:+.2f}R",
            best["profit_factor"],
            best["total_trades"],
        ])
        curr_row = ws_assets.max_row
        for col_idx in range(1, 8):
            c = ws_assets.cell(row=curr_row, column=col_idx)
            c.border = thin_border
            c.font = Font(name="Calibri", size=10)
            c.alignment = Alignment(horizontal="right" if col_idx in [4, 5, 6, 7] else "center", vertical="center")

    for col in ws_assets.columns:
        max_l = max(len(str(cell.value or "")) for cell in col)
        col_let = get_column_letter(col[0].column)
        ws_assets.column_dimensions[col_let].width = max(max_l + 3, 14)

    wb.save(str(excel_path))


def _export_study_markdown(results: list[dict[str, Any]], md_path: Path):
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Relatório Executivo: Estudo Multi-Ativo & Multi-Timeframe (Wyckoff + SMC)\n\n")
        f.write("Meta: Taxa de acerto entre 35% e 40%+ com R:R 1:3 e Expectativa positiva.\n\n")
        f.write("## 🏆 Campeões que Bateram a Meta\n\n")
        f.write("| Ativo | Timeframes | Estratégia | Taxa de Acerto | Expectativa | Profit Factor | Trades |\n")
        f.write("| :--- | :---: | :--- | :---: | :---: | :---: | :---: |\n")

        champions = [r for r in results if r["meets_goal"]]
        champions = sorted(champions, key=lambda x: (x["expectancy"], x["win_rate"]), reverse=True)

        for c in champions:
            f.write(f"| **{c['symbol']}** | `{c['tf_pair']}` | {c['strategy']} | **{c['win_rate']:.1f}%** | **{c['expectancy']:+.2f}R** | **{c['profit_factor']:.2f}** | {c['total_trades']} |\n")

        f.write("\n\n## 📊 Melhor Combinação Isolada por Ativo\n\n")
        f.write("| Ativo | Par Timeframe | Estratégia | Taxa Acerto | Expectativa | Profit Factor | Trades |\n")
        f.write("| :--- | :---: | :--- | :---: | :---: | :---: | :---: |\n")

        symbols_list = sorted(list(set(r["symbol"] for r in results)))
        for sym in symbols_list:
            sym_res = [r for r in results if r["symbol"] == sym]
            if not sym_res:
                continue
            best = max(sym_res, key=lambda x: (x["expectancy"], x["profit_factor"]))
            f.write(f"| **{best['symbol']}** | `{best['tf_pair']}` | {best['strategy']} | {best['win_rate']:.1f}% | {best['expectancy']:+.2f}R | {best['profit_factor']:.2f} | {best['total_trades']} |\n")


if __name__ == "__main__":
    run_study()

"""Execução do Backtest Institucional de 1 Ano Completo para todos os 7 Ativos.

Modelos Avaliados:
  1. [SMC-DayFlow] M15 -> M1 com OB puro (sem BB)
  2. [Wyckoff-Sniper] H1 -> M1 com Sweep Obrigatório (Spring / UTAD)
"""
import datetime
import os
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
import pandas as pd

from smc_trader.analysis import analyze
from smc_trader.backtest.engine import BacktestEngine
from smc_trader.config import BacktestConfig, ZoneConfig, load_config
from smc_trader.data.resample import resample_ohlc
from smc_trader.data.store import load_candles
from smc_trader.structure.market_structure import detect_structure
from smc_trader.structure.pivots import find_pivots


def build_audit_excel(summary_rows: list[dict], monthly_rows: list[dict], trades_rows: list[dict], out_path: Path):
    wb = openpyxl.Workbook()
    
    header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    green_font = Font(name="Calibri", size=10, color="006100", bold=True)
    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    red_font = Font(name="Calibri", size=10, color="9C0006")
    
    thin_border = Border(
        left=Side(style='thin', color='D9D9D9'),
        right=Side(style='thin', color='D9D9D9'),
        top=Side(style='thin', color='D9D9D9'),
        bottom=Side(style='thin', color='D9D9D9')
    )
    
    # Sheet 1: Resumo Geral
    ws1 = wb.active
    ws1.title = "Resumo Anual (1 Ano)"
    
    headers1 = [
        "Ativo", "Modelo", "Timeframes", "Trades", "Ganhos (3R)", "Loss (-1R)",
        "Win Rate %", "Payoff", "Expectativa (R)", "Retorno Total (R)", "Profit Factor", "Max Drawdown (R)", "Retorno Conta (% c/ 1% risco)"
    ]
    ws1.append(headers1)
    for col_idx in range(1, len(headers1) + 1):
        cell = ws1.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    ws1.row_dimensions[1].height = 25
    
    for r_idx, r in enumerate(summary_rows, start=2):
        ws1.append([
            r["symbol"], r["model"], r["timeframes"], r["trades"], r["wins"], r["losses"],
            f"{r['win_rate']:.1f}%", f"1:{r['payoff']:.1f}", f"{r['expectancy']:+.2f}R",
            f"{r['net_r']:+.2f}R", f"{r['profit_factor']:.2f}" if r['profit_factor'] != float('inf') else "Inf",
            f"{r['max_dd_r']:.2f}R", f"{r['net_r'] * 1.0:+.1f}%"
        ])
        for c in range(1, len(headers1) + 1):
            cell = ws1.cell(row=r_idx, column=c)
            cell.font = data_font
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center")
        
        # Colorir retorno
        ret_cell = ws1.cell(row=r_idx, column=10)
        if r['net_r'] > 0:
            ret_cell.fill = green_fill
            ret_cell.font = green_font
        else:
            ret_cell.fill = red_fill
            ret_cell.font = red_font

    # Sheet 2: Breakdown Mensal
    ws2 = wb.create_sheet(title="Desempenho Mensal (R)")
    if monthly_rows:
        df_month = pd.DataFrame(monthly_rows)
        pivot = df_month.pivot_table(index=["symbol", "model"], columns="month", values="pnl_r", aggfunc="sum").fillna(0.0)
        pivot["TOTAL"] = pivot.sum(axis=1)
        
        m_headers = ["Ativo", "Modelo"] + list(pivot.columns)
        ws2.append(m_headers)
        for c_idx in range(1, len(m_headers) + 1):
            cell = ws2.cell(row=1, column=c_idx)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")
        ws2.row_dimensions[1].height = 25
        
        for r_i, (idx_tuple, row_vals) in enumerate(pivot.iterrows(), start=2):
            sym, mod = idx_tuple
            row_data = [sym, mod] + [f"{v:+.2f}R" for v in row_vals]
            ws2.append(row_data)
            for c_i in range(1, len(m_headers) + 1):
                cell = ws2.cell(row=r_i, column=c_i)
                cell.font = data_font
                cell.border = thin_border
                cell.alignment = Alignment(horizontal="center")
                if c_i >= 3:
                    val_num = row_vals.iloc[c_i - 3]
                    if val_num > 0:
                        cell.font = Font(name="Calibri", size=10, color="006100", bold=True)
                    elif val_num < 0:
                        cell.font = Font(name="Calibri", size=10, color="9C0006")

    # Sheet 3: Detalhe das Operações
    ws3 = wb.create_sheet(title="Histórico de Trades")
    t_headers = ["ID", "Ativo", "Modelo", "Data Entrada", "Data Saída", "Direção", "Preço Entrada", "Stop Loss", "Take Profit", "Resultado", "PnL (R)", "Duração (min)"]
    ws3.append(t_headers)
    for c_idx in range(1, len(t_headers) + 1):
        cell = ws3.cell(row=1, column=c_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
    ws3.row_dimensions[1].height = 25
    
    for t_i, t in enumerate(trades_rows, start=2):
        ws3.append([
            t["id"], t["symbol"], t["model"], t["entry_time"], t["exit_time"], t["direction"],
            t["entry_price"], t["stop_loss"], t["take_profit"], t["result"], f"{t['pnl_r']:+.2f}R", t["duration_min"]
        ])
        for c_i in range(1, len(t_headers) + 1):
            cell = ws3.cell(row=t_i, column=c_i)
            cell.font = data_font
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center")
        res_cell = ws3.cell(row=t_i, column=10)
        if t["result"] == "GAIN":
            res_cell.fill = green_fill
            res_cell.font = green_font
        elif t["result"] == "LOSS":
            res_cell.fill = red_fill
            res_cell.font = red_font

    # Ajusta largura das colunas
    for ws in [ws1, ws2, ws3]:
        for col in ws.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = max(max_len + 3, 12)

    wb.save(out_path)
    print(f"📊 Relatório Excel Anual salvo em: {out_path}")


def main():
    data_root = Path("data")
    out_dir = Path("out")
    out_dir.mkdir(parents=True, exist_ok=True)
    excel_path = out_dir / "auditoria_anual_1ano_multiativo.xlsx"
    txt_path = out_dir / "auditoria_anual_1ano_resumo.txt"

    symbols = ["BRENT", "XAUUSD", "NAS100", "DAX40", "EURUSD", "GBPUSD", "USDJPY"]
    target_syms = sys.argv[1:] if len(sys.argv) > 1 else symbols

    cfg_global = load_config(Path("config/default.yaml"))
    
    models_to_test = [
        {
            "id": "smc_dayflow",
            "name": "SMC-DayFlow (OB Puro)",
            "macro_tf": "M15",
            "micro_tf": "M1",
            "blocks_filter": ["OB"],
            "require_sweep": False,
        },
        {
            "id": "wyckoff_sniper",
            "name": "Wyckoff-Sniper (Sweep)",
            "macro_tf": "H1",
            "micro_tf": "M1",
            "blocks_filter": ["OB", "BB"],
            "require_sweep": True,
        }
    ]

    summary_rows = []
    monthly_rows = []
    trades_rows = []

    print("\n" + "=" * 80)
    print("🌟 INICIANDO AUDITORIA ANUAL (1 ANO COMPLETO) - 7 ATIVOS")
    print(f"Ativos na fila: {target_syms}")
    print(f"Período: Novembro/2025 a Novembro/2026")
    print("=" * 80)

    t0_all = time.time()

    for sym in target_syms:
        print(f"\n📂 [{sym}] Carregando candles M1 do disco...")
        try:
            c_m1 = load_candles(data_root, sym, "M1")
        except Exception as e:
            print(f"  ❌ Erro ao ler candles de {sym}: {e}")
            continue

        if c_m1.empty:
            print(f"  ⚠️ Sem dados para {sym}")
            continue

        d_min = c_m1.index.min().strftime('%Y-%m-%d')
        d_max = c_m1.index.max().strftime('%Y-%m-%d')
        print(f"  ✅ {sym}: {len(c_m1):,} candles M1 ({d_min} a {d_max})")

        # Precomputa M1 pivots e estrutura uma única vez para o ativo
        print(f"  ⚡ Pré-calculando pivôs e estrutura M1 para aceleração...")
        t_pre = time.time()
        pivots_m1 = find_pivots(c_m1, k=2)
        events_m1 = detect_structure(c_m1, pivots_m1)
        precomputed_m1 = {
            "events": events_m1,
            "chochs": {(e.direction, e.time): e for e in events_m1 if e.kind == "CHoCH"},
            "bos": {(e.direction, e.time): e for e in events_m1 if e.kind == "BOS"},
        }
        print(f"  ⚡ Concluído em {time.time() - t_pre:.1f}s!")

        # Cache dos timeframes macro
        c_m15 = resample_ohlc(c_m1, "M15")
        c_h1 = resample_ohlc(c_m1, "H1")

        for m_cfg in models_to_test:
            mod_name = m_cfg["name"]
            macro_tf = m_cfg["macro_tf"]
            c_macro = c_m15 if macro_tf == "M15" else c_h1

            # Análise Estrutural e Zonas Macro
            zone_cfg = ZoneConfig(blocks_filter=m_cfg["blocks_filter"])
            analysis = analyze(c_macro, k=3, zones_cfg=zone_cfg)
            
            # Filtro de zonas
            zones = analysis.zones if m_cfg["blocks_filter"] == ["OB"] else analysis.zones + analysis.breakers
            if m_cfg["require_sweep"]:
                zones = [z for z in zones if z.swept_liquidity]

            # Config do Backtest
            bt_cfg = BacktestConfig(
                entry_mode="confirmation",
                stop_mode="swing",
                target_mode="fixed_r",
                target_r=3.0,
                costs=cfg_global.backtest.costs,
                session=cfg_global.backtest.session,
                limits=cfg_global.backtest.limits,
            )

            engine = BacktestEngine(bt_cfg)
            res = engine.run(c_m1, zones, symbol=sym, precomputed_m1=precomputed_m1)

            t_list = res.trades
            n_trades = len(t_list)
            if n_trades == 0:
                print(f"  [{sym}] {mod_name} ({macro_tf}/M1): 0 trades gerados.")
                continue

            wins = [t for t in t_list if t.r_multiple > 0]
            losses = [t for t in t_list if t.r_multiple <= 0]
            n_wins = len(wins)
            n_losses = len(losses)
            wr = (n_wins / n_trades) * 100
            net_r = sum(t.r_multiple for t in t_list)
            exp_r = net_r / n_trades

            gross_gain = sum(t.r_multiple for t in wins)
            gross_loss = abs(sum(t.r_multiple for t in losses))
            pf = (gross_gain / gross_loss) if gross_loss > 0 else float('inf')

            # Max Drawdown
            equity_curve = np.cumsum([t.r_multiple for t in t_list])
            running_max = np.maximum.accumulate(equity_curve)
            dd_series = running_max - equity_curve
            max_dd = float(np.max(dd_series)) if len(dd_series) > 0 else 0.0

            summary_rows.append({
                "symbol": sym,
                "model": mod_name,
                "timeframes": f"{macro_tf}/M1",
                "trades": n_trades,
                "wins": n_wins,
                "losses": n_losses,
                "win_rate": wr,
                "payoff": 3.0,
                "expectancy": exp_r,
                "net_r": net_r,
                "profit_factor": pf,
                "max_dd_r": max_dd,
            })

            print(f"  🎯 [{sym}] {mod_name:24} | {n_trades:3} trades | WR: {wr:4.1f}% | Retorno: {net_r:+6.2f}R | Exp: {exp_r:+.2f}R | PF: {pf:4.2f} | MaxDD: {max_dd:.2f}R")

            # Agrupamento Mensal
            for t in t_list:
                m_str = t.entry_time.strftime("%Y-%m")
                monthly_rows.append({
                    "symbol": sym,
                    "model": mod_name,
                    "month": m_str,
                    "pnl_r": t.r_multiple,
                })

                # Registro de trade individual
                duration_m = (t.exit_time - t.entry_time).total_seconds() / 60.0 if t.exit_time else 0
                trades_rows.append({
                    "id": f"{sym}_{t.entry_time.strftime('%Y%m%d_%H%M')}",
                    "symbol": sym,
                    "model": mod_name,
                    "entry_time": t.entry_time.strftime("%Y-%m-%d %H:%M"),
                    "exit_time": t.exit_time.strftime("%Y-%m-%d %H:%M") if t.exit_time else "-",
                    "direction": t.direction,
                    "entry_price": round(t.entry_price, 5),
                    "stop_loss": round(t.stop_loss, 5),
                    "take_profit": round(t.take_profit, 5),
                    "result": "GAIN" if t.r_multiple > 0 else "LOSS",
                    "pnl_r": round(t.r_multiple, 2),
                    "duration_min": round(duration_m, 1),
                })

    # Gravar Excel
    build_audit_excel(summary_rows, monthly_rows, trades_rows, excel_path)

    # Gravar Resumo TXT
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write("RELATÓRIO CONSOLIDADO: AUDITORIA ANUAL DE 1 ANO (7 ATIVOS)\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Data de Execução: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Período Avaliado: 01/11/2025 a 04/11/2026 (12 Meses de Candles M1 Reais)\n\n")
        
        f.write("TABELA CONSOLIDADA DE PERFORMANCE:\n")
        f.write(f"{'Ativo':8} | {'Modelo':24} | {'Trades':6} | {'Win Rate':9} | {'Expectativa':12} | {'Retorno (R)':12} | {'Profit Factor':13} | {'Max DD (R)':10}\n")
        f.write("-" * 110 + "\n")
        for s in summary_rows:
            f.write(f"{s['symbol']:8} | {s['model']:24} | {s['trades']:6} | {s['win_rate']:8.1f}% | {s['expectancy']:+11.2f}R | {s['net_r']:+11.2f}R | {s['profit_factor']:13.2f} | {s['max_dd_r']:10.2f}R\n")
        
        # Totais por Modelo
        f.write("\n" + "=" * 80 + "\n")
        f.write("TOTAIS CONSOLIDADOS POR MODELO (PORTFÓLIO 7 ATIVOS):\n")
        f.write("=" * 80 + "\n")
        for m_cfg in models_to_test:
            mod_name = m_cfg["name"]
            sub = [s for s in summary_rows if s["model"] == mod_name]
            if sub:
                tot_trades = sum(x["trades"] for x in sub)
                tot_r = sum(x["net_r"] for x in sub)
                avg_wr = np.mean([x["win_rate"] for x in sub])
                avg_exp = tot_r / tot_trades if tot_trades > 0 else 0
                f.write(f"[{mod_name}]\n")
                f.write(f"  - Total Trades: {tot_trades}\n")
                f.write(f"  - Lucro Líquido Acumulado: {tot_r:+.2f}R ({tot_r:+.1f}% de retorno com 1% de risco)\n")
                f.write(f"  - Win Rate Médio: {avg_wr:.1f}%\n")
                f.write(f"  - Expectativa Média por Trade: {avg_exp:+.2f}R\n\n")

    print(f"📄 Resumo TXT salvo em: {txt_path}")
    print(f"🏁 Auditoria concluída em {(time.time() - t0_all)/60:.1f} minutos!")


if __name__ == "__main__":
    main()

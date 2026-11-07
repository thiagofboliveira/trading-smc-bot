"""Módulo de exportação profissional de resultados de backtest.

Gera:
1. Pasta nomeada `{SYMBOL}_{YYYYMMDD_HHMMSS}`
2. Imagens PNG macro (M15 com estrutura, OB, BB, BOS/CHoCH) e micro (M1 com entrada, SL, TP, confirmação)
3. Arquivo de texto (.txt) descritivo
4. Planilha Excel (.xlsx) completa com 2 abas:
   - Aba 1: 'Operações' (detalhamento linha por linha com status GAIN/STOP, saldo acumulado)
   - Aba 2: 'Análise Estatística & ROI' (taxa de acerto, expectativa, profit factor, drawdown, ROI)
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import openpyxl
import pandas as pd
from matplotlib import patches
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from smc_trader.analysis import Analysis
from smc_trader.backtest.types import BacktestResult, Trade


def _plot_candlesticks(
    ax, df: pd.DataFrame, up_color="#26a69a", down_color="#ef5350", width=0.6
):
    """Desenha velas japonesas de forma eficiente no eixo matplotlib."""
    if df.empty:
        return

    x = np.arange(len(df))
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values

    up = closes >= opens
    down = ~up

    # Pavios
    ax.vlines(x, lows, highs, color="#787b86", linewidth=1.0, alpha=0.9)

    # Corpos
    body_low = np.minimum(opens, closes)
    body_high = np.maximum(opens, closes)
    body_height = np.maximum(body_high - body_low, (highs - lows) * 0.02)

    # Velas de alta
    if np.any(up):
        for xi, bl, bh in zip(x[up], body_low[up], body_height[up]):
            rect = patches.Rectangle(
                (xi - width / 2, bl), width, bh, facecolor=up_color, edgecolor=up_color
            )
            ax.add_patch(rect)

    # Velas de baixa
    if np.any(down):
        for xi, bl, bh in zip(x[down], body_low[down], body_height[down]):
            rect = patches.Rectangle(
                (xi - width / 2, bl),
                width,
                bh,
                facecolor=down_color,
                edgecolor=down_color,
            )
            ax.add_patch(rect)


def generate_trade_charts(
    trade: Trade,
    trade_idx: int,
    c_m15: pd.DataFrame,
    c_m1: pd.DataFrame,
    analysis: Analysis,
    out_trade_dir: Path,
):
    """Gera 2 imagens PNG: 01_macro_chart.png e 02_micro_chart.png para o trade específico."""
    out_trade_dir.mkdir(parents=True, exist_ok=True)

    # --- 1. GRÁFICO MACRO (M15) ---
    fig_macro, ax_m = plt.subplots(figsize=(14, 7), dpi=130)
    fig_macro.patch.set_facecolor("#0d1117")
    ax_m.set_facecolor("#0d1117")

    # Janela de visualização macro: 80 candles antes da entrada até 20 candles após a saída
    t_start = trade.entry_time - pd.Timedelta(hours=20)
    t_end = trade.exit_time + pd.Timedelta(hours=6)
    sub_m15 = c_m15.loc[(c_m15.index >= t_start) & (c_m15.index <= t_end)]
    if len(sub_m15) < 10:
        sub_m15 = c_m15.loc[c_m15.index <= t_end].tail(60)

    time_map_m15 = {ts: idx for idx, ts in enumerate(sub_m15.index)}
    _plot_candlesticks(ax_m, sub_m15)

    # Desenhar Order Blocks relevantes na janela
    for z in analysis.zones:
        if z.created_at <= t_end and (z.end_time is None or z.end_time >= t_start):
            x_start = time_map_m15.get(z.created_at, 0)
            x_end = (
                time_map_m15.get(z.end_time, len(sub_m15) - 1)
                if z.end_time
                else len(sub_m15) - 1
            )
            if x_end >= x_start:
                color = "#26a69a" if z.direction == "long" else "#ef5350"
                rect = patches.Rectangle(
                    (x_start, z.low),
                    max(1, x_end - x_start),
                    z.high - z.low,
                    linewidth=1,
                    edgecolor=color,
                    facecolor=color,
                    alpha=0.18,
                )
                ax_m.add_patch(rect)
                ax_m.text(
                    x_start,
                    z.high,
                    f" {z.kind} ({z.direction})",
                    color=color,
                    fontsize=8,
                    va="bottom",
                )

    # Desenhar Breakers na janela
    for b in analysis.breakers:
        if b.created_at <= t_end and (b.end_time is None or b.end_time >= t_start):
            x_start = time_map_m15.get(b.created_at, 0)
            x_end = (
                time_map_m15.get(b.end_time, len(sub_m15) - 1)
                if b.end_time
                else len(sub_m15) - 1
            )
            if x_end >= x_start:
                color = "#ab47bc" if b.direction == "long" else "#ffa726"
                rect = patches.Rectangle(
                    (x_start, b.low),
                    max(1, x_end - x_start),
                    b.high - b.low,
                    linewidth=1.2,
                    linestyle="--",
                    edgecolor=color,
                    facecolor=color,
                    alpha=0.18,
                )
                ax_m.add_patch(rect)
                ax_m.text(
                    x_start,
                    b.high,
                    f" BB ({b.direction})",
                    color=color,
                    fontsize=8,
                    va="bottom",
                )

    # Marcar a entrada e saída no gráfico macro
    closest_m15_entry = sub_m15.index.asof(trade.entry_time)
    closest_m15_exit = sub_m15.index.asof(trade.exit_time)
    if closest_m15_entry in time_map_m15:
        idx_e = time_map_m15[closest_m15_entry]
        is_buy = trade.direction == "buy"
        marker = "^" if is_buy else "v"
        m_color = "#00e676" if is_buy else "#ff1744"
        ax_m.scatter(
            [idx_e],
            [trade.entry_price],
            marker=marker,
            color=m_color,
            s=150,
            zorder=5,
            label=f"Entrada {trade.direction.upper()}",
        )

    if closest_m15_exit in time_map_m15:
        idx_x = time_map_m15[closest_m15_exit]
        is_gain = trade.r_multiple > 0
        x_marker = "*" if is_gain else "X"
        x_color = "#ffd700" if is_gain else "#ff5252"
        ax_m.scatter(
            [idx_x],
            [trade.exit_price],
            marker=x_marker,
            color=x_color,
            s=130,
            zorder=5,
            label=f"Saída ({trade.exit_reason.upper()})",
        )

    # Formatar eixos macro
    n_ticks = min(8, len(sub_m15))
    step = max(1, len(sub_m15) // n_ticks)
    tick_indices = list(range(0, len(sub_m15), step))
    tick_labels = [sub_m15.index[i].strftime("%d/%m %H:%M") for i in tick_indices]
    ax_m.set_xticks(tick_indices)
    ax_m.set_xticklabels(tick_labels, color="#8b949e", fontsize=8)
    ax_m.tick_params(colors="#8b949e")
    ax_m.grid(color="#21262d", linestyle="--", alpha=0.6)
    for spine in ax_m.spines.values():
        spine.set_color("#30363d")

    status_str = "GAIN" if trade.r_multiple > 0 else "STOP"
    ax_m.set_title(
        f"MACRO (M15) — Trade #{trade_idx:03d} | {trade.direction.upper()} | {status_str} ({trade.r_multiple:+.2f}R) | Zona: {trade.zone_kind}",
        color="#f0f6fc",
        fontsize=12,
        fontweight="bold",
        pad=12,
    )
    ax_m.legend(
        facecolor="#161b22", edgecolor="#30363d", labelcolor="#c9d1d9", loc="upper left"
    )
    plt.tight_layout()
    macro_png = out_trade_dir / "01_macro_chart.png"
    fig_macro.savefig(macro_png, facecolor=fig_macro.get_facecolor(), edgecolor="none")
    plt.close(fig_macro)

    # --- 2. GRÁFICO MICRO (M1) ---
    fig_micro, ax_u = plt.subplots(figsize=(14, 7), dpi=130)
    fig_micro.patch.set_facecolor("#0d1117")
    ax_u.set_facecolor("#0d1117")

    # Janela micro: 30 candles M1 antes da entrada até 15 candles após a saída
    u_start = trade.entry_time - pd.Timedelta(minutes=30)
    u_end = trade.exit_time + pd.Timedelta(minutes=15)
    sub_m1 = c_m1.loc[(c_m1.index >= u_start) & (c_m1.index <= u_end)]
    if len(sub_m1) < 5:
        sub_m1 = c_m1.loc[c_m1.index <= u_end].tail(60)

    time_map_m1 = {ts: idx for idx, ts in enumerate(sub_m1.index)}
    _plot_candlesticks(ax_u, sub_m1, width=0.7)

    # Linhas de Entry, Stop Loss e Take Profit no Micro
    idx_entry = time_map_m1.get(trade.entry_time, 0)
    idx_exit = time_map_m1.get(trade.exit_time, len(sub_m1) - 1)

    # Linha de Entrada
    ax_u.hlines(
        trade.entry_price,
        idx_entry,
        idx_exit,
        color="#58a6ff",
        linestyle="-",
        linewidth=1.5,
        label=f"Entrada: {trade.entry_price:.2f}",
    )
    # Linha de Stop Loss
    ax_u.hlines(
        trade.stop_loss,
        idx_entry,
        idx_exit,
        color="#ff5252",
        linestyle="--",
        linewidth=1.5,
        label=f"Stop Loss: {trade.stop_loss:.2f}",
    )
    # Linha de Take Profit
    if trade.take_profit:
        ax_u.hlines(
            trade.take_profit,
            idx_entry,
            idx_exit,
            color="#00e676",
            linestyle="--",
            linewidth=1.5,
            label=f"Take Profit: {trade.take_profit:.2f}",
        )

    # Marcador de Entrada Micro
    is_buy = trade.direction == "buy"
    ax_u.scatter(
        [idx_entry],
        [trade.entry_price],
        marker="^" if is_buy else "v",
        color="#00e676" if is_buy else "#ff1744",
        s=180,
        zorder=6,
    )
    # Marcador de Saída Micro
    is_gain = trade.r_multiple > 0
    ax_u.scatter(
        [idx_exit],
        [trade.exit_price],
        marker="*" if is_gain else "X",
        color="#ffd700" if is_gain else "#ff5252",
        s=160,
        zorder=6,
    )

    # Formatar eixos micro
    n_ticks_u = min(10, len(sub_m1))
    step_u = max(1, len(sub_m1) // n_ticks_u)
    tick_indices_u = list(range(0, len(sub_m1), step_u))
    tick_labels_u = [sub_m1.index[i].strftime("%H:%M") for i in tick_indices_u]
    ax_u.set_xticks(tick_indices_u)
    ax_u.set_xticklabels(tick_labels_u, color="#8b949e", fontsize=8)
    ax_u.tick_params(colors="#8b949e")
    ax_u.grid(color="#21262d", linestyle="--", alpha=0.6)
    for spine in ax_u.spines.values():
        spine.set_color("#30363d")

    ax_u.set_title(
        f"MICRO (M1) — Execução Trade #{trade_idx:03d} | Entrada: {trade.entry_time.strftime('%d/%m %H:%M')} | Saída: {trade.exit_time.strftime('%H:%M')} ({trade.exit_reason.upper()})",
        color="#f0f6fc",
        fontsize=12,
        fontweight="bold",
        pad=12,
    )
    ax_u.legend(
        facecolor="#161b22", edgecolor="#30363d", labelcolor="#c9d1d9", loc="upper left"
    )
    plt.tight_layout()
    micro_png = out_trade_dir / "02_micro_chart.png"
    fig_micro.savefig(micro_png, facecolor=fig_micro.get_facecolor(), edgecolor="none")
    plt.close(fig_micro)

    # --- 3. ARQUIVO TXT COM DETALHES DO TRADE ---
    txt_file = out_trade_dir / f"trade_{trade_idx:03d}_detalhes.txt"
    tp_str = f"{trade.take_profit:.3f}" if trade.take_profit is not None else "N/A"
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write(f"DETALHES DA OPERAÇÃO #{trade_idx:03d}\n")
        f.write("=" * 60 + "\n")
        f.write(f"Ativo:               {trade.symbol}\n")
        f.write(f"Direção:             {trade.direction.upper()}\n")
        f.write(f"Status Final:        {'GAIN ✅' if is_gain else 'STOP ❌'}\n")
        f.write(
            f"Data/Hora Entrada:   {trade.entry_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        )
        f.write(
            f"Data/Hora Saída:     {trade.exit_time.strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        )
        f.write(f"Preço de Entrada:    {trade.entry_price:.3f}\n")
        f.write(f"Stop Loss:           {trade.stop_loss:.3f}\n")
        f.write(f"Take Profit:         {tp_str}\n")
        f.write(f"Preço de Saída:      {trade.exit_price:.3f}\n")
        f.write(f"Motivo da Saída:     {trade.exit_reason.upper()}\n")
        initial_risk = abs(trade.entry_price - trade.stop_loss)
        f.write(f"Risco Inicial:       {initial_risk:.3f}\n")
        f.write(f"Resultado (R):       {trade.r_multiple:+.2f}R\n")
        f.write(f"Lucro/Prejuízo ($):  ${trade.pnl:+.2f} USD\n")
        f.write(f"Custos/Spread ($):   ${trade.costs:.2f} USD\n")
        f.write(f"Zona de Origem:      {trade.zone_kind}\n")
        f.write(f"Modo de Gatilho:     {trade.entry_mode}\n")
        f.write("=" * 60 + "\n")


def export_backtest_package(
    symbol: str,
    result: BacktestResult,
    c_m1: pd.DataFrame,
    c_m15: pd.DataFrame,
    analysis: Analysis,
    base_dir: Path = Path("out/backtests"),
    initial_capital: float = 10000.0,
) -> Path:
    """Exporta o pacote completo com imagens macro/micro por trade, TXT geral e XLSX com 2 abas."""
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    folder_name = f"{symbol}_{timestamp_str}"
    target_dir = base_dir / folder_name
    trades_dir = target_dir / "trades"
    trades_dir.mkdir(parents=True, exist_ok=True)

    trades = result.trades
    metrics = result.metrics

    print(f"\n📁 Criando pacote de auditoria em: {target_dir}")

    # 1. Gerar imagens e txt para cada trade
    print(f"🖼️ Gerando gráficos macro e micro para {len(trades)} operações...")
    for idx, t in enumerate(trades, 1):
        status = "GAIN" if t.r_multiple > 0 else "STOP"
        t_folder = trades_dir / f"trade_{idx:03d}_{t.direction.upper()}_{status}"
        generate_trade_charts(t, idx, c_m15, c_m1, analysis, t_folder)

    # 2. Gerar arquivo TXT resumo do período
    txt_geral = target_dir / f"resumo_backtest_{symbol}.txt"
    with open(txt_geral, "w", encoding="utf-8") as f:
        f.write("=" * 70 + "\n")
        f.write(f"RELATÓRIO GERAL DE BACKTEST INSTITUCIONAL SMC — {symbol}\n")
        f.write(f"Gerado em: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 70 + "\n\n")
        f.write("MÉTRICAS PRINCIPAIS:\n")
        f.write(f"  Total de Operações:        {metrics.get('total_trades', 0)}\n")
        f.write(f"  Operações Vencedoras:      {metrics.get('win_trades', 0)}\n")
        f.write(f"  Operações Perdedoras:      {metrics.get('loss_trades', 0)}\n")
        f.write(f"  Taxa de Acerto (Win Rate): {metrics.get('win_rate', 0):.2f}%\n")
        f.write(f"  R Médio por Trade:         {metrics.get('avg_r', 0):+.2f}R\n")
        f.write(f"  Expectativa Matemática:    {metrics.get('expectancy', 0):+.2f}R\n")
        f.write(f"  Profit Factor:             {metrics.get('profit_factor', 0):.2f}\n")
        f.write(
            f"  Drawdown Máximo (R):       {metrics.get('max_drawdown_r', 0):.2f}R\n"
        )
        f.write(
            f"  Lucro Líquido Total ($):   ${metrics.get('total_pnl', 0):+.2f} USD\n\n"
        )
        f.write("-" * 70 + "\n")
        f.write("DETALHAMENTO MENSAL:\n")
        f.writelines(f"  Mês {month}: {m_data.get('trades')} trades | Taxa de Acerto: {m_data.get('win_rate', 0):.1f}% | R Total: {m_data.get('r_multiple', 0):+.2f}R\n" for month, m_data in metrics.get("monthly", {}).items())
        f.write("=" * 70 + "\n")

    # 3. Gerar Planilha Excel (.xlsx) com 2 Abas Profissionais
    excel_path = target_dir / f"backtest_resultado_{symbol}.xlsx"
    _create_excel_report(excel_path, symbol, trades, metrics, initial_capital)

    # 4. Gerar Manifesto Estruturado JSON (permite consulta instantânea na interface Web)
    cum_r = 0.0
    equity_curve = []
    trades_data = []
    for idx, t in enumerate(trades, 1):
        cum_r += t.r_multiple
        status = "GAIN" if t.r_multiple > 0 else "STOP"
        t_folder_name = f"trade_{idx:03d}_{t.direction.upper()}_{status}"
        trades_data.append(
            {
                "id": idx,
                "trade_id": t.id,
                "symbol": t.symbol,
                "direction": t.direction,
                "status": status,
                "is_gain": t.r_multiple > 0,
                "entry_time": t.entry_time.isoformat(),
                "exit_time": t.exit_time.isoformat(),
                "entry_price": round(t.entry_price, 3),
                "stop_loss": round(t.stop_loss, 3),
                "take_profit": round(t.take_profit, 3)
                if t.take_profit is not None
                else None,
                "exit_price": round(t.exit_price, 3),
                "exit_reason": t.exit_reason.upper(),
                "r_multiple": round(t.r_multiple, 2),
                "pnl": round(t.pnl, 2),
                "costs": round(t.costs, 2),
                "zone_kind": t.zone_kind,
                "entry_mode": t.entry_mode,
                "macro_img": f"/api/files/{folder_name}/trades/{t_folder_name}/01_macro_chart.png",
                "micro_img": f"/api/files/{folder_name}/trades/{t_folder_name}/02_micro_chart.png",
                "txt_url": f"/api/files/{folder_name}/trades/{t_folder_name}/trade_{idx:03d}_detalhes.txt",
            }
        )
        equity_curve.append(
            {
                "time": t.exit_time.isoformat(),
                "cum_r": round(cum_r, 2),
                "pnl": round(t.pnl, 2),
            }
        )

    manifest = {
        "id": folder_name,
        "symbol": symbol,
        "timestamp": timestamp_str,
        "created_at": datetime.now().isoformat(),
        "metrics": metrics,
        "initial_capital": initial_capital,
        "excel_file": f"backtest_resultado_{symbol}.xlsx",
        "excel_url": f"/api/files/{folder_name}/backtest_resultado_{symbol}.xlsx",
        "txt_file": f"resumo_backtest_{symbol}.txt",
        "txt_url": f"/api/files/{folder_name}/resumo_backtest_{symbol}.txt",
        "equity_curve": equity_curve,
        "trades": trades_data,
    }
    with open(target_dir / "audit_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print(f"📊 Planilha Excel gerada: {excel_path}")
    print(f"📝 Resumo TXT gerado: {txt_geral}")
    print(f"📑 Manifesto JSON gerado: {target_dir / 'audit_manifest.json'}")
    print("✅ Pacote de validação concluído com sucesso!")
    return target_dir


def load_or_create_manifest(target_dir: Path) -> dict[str, Any]:
    """Carrega o manifesto audit_manifest.json ou reconstrói a partir dos arquivos em disco."""
    manifest_path = target_dir / "audit_manifest.json"
    if manifest_path.exists():
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    # Reconstrói a partir do disco
    folder_name = target_dir.name
    parts = folder_name.split("_")
    symbol = parts[0] if parts else "UNKNOWN"
    ts_str = "_".join(parts[1:]) if len(parts) > 1 else ""

    excel_file = f"backtest_resultado_{symbol}.xlsx"
    txt_file = f"resumo_backtest_{symbol}.txt"

    # Lê resumo TXT se existir
    metrics: dict[str, Any] = {
        "total_trades": 0,
        "win_trades": 0,
        "loss_trades": 0,
        "win_rate": 0.0,
        "expectancy": 0.0,
        "profit_factor": 0.0,
        "total_pnl": 0.0,
    }
    txt_path = target_dir / txt_file
    if txt_path.exists():
        txt_content = txt_path.read_text(encoding="utf-8")
        m_tot = re.search(r"Total de Operações:\s+(\d+)", txt_content)
        m_win = re.search(r"Operações Vencedoras:\s+(\d+)", txt_content)
        m_loss = re.search(r"Operações Perdedoras:\s+(\d+)", txt_content)
        m_wr = re.search(r"Taxa de Acerto \(Win Rate\):\s+([\d\.]+)%", txt_content)
        m_exp = re.search(r"Expectativa Matemática:\s+([+-]?[\d\.]+)R", txt_content)
        m_pf = re.search(r"Profit Factor:\s+([\d\.]+)", txt_content)
        m_pnl = re.search(
            r"Lucro Líquido Total \(\$\):\s+\$([+-]?[\d\.]+)", txt_content
        )
        if m_tot:
            metrics["total_trades"] = int(m_tot.group(1))
        if m_win:
            metrics["win_trades"] = int(m_win.group(1))
        if m_loss:
            metrics["loss_trades"] = int(m_loss.group(1))
        if m_wr:
            metrics["win_rate"] = float(m_wr.group(1))
        if m_exp:
            metrics["expectancy"] = float(m_exp.group(1))
        if m_pf:
            metrics["profit_factor"] = float(m_pf.group(1))
        if m_pnl:
            metrics["total_pnl"] = float(m_pnl.group(1))

    # Coleta trades da pasta trades/
    trades_dir = target_dir / "trades"
    trades_data = []
    equity_curve = []
    cum_r = 0.0

    if trades_dir.exists():
        for t_dir in sorted(trades_dir.iterdir()):
            if not t_dir.is_dir():
                continue
            idx = len(trades_data) + 1
            t_txt = list(t_dir.glob("trade_*_detalhes.txt"))
            t_info: dict[str, Any] = {
                "id": idx,
                "symbol": symbol,
                "direction": "long" if "LONG" in t_dir.name else "short",
                "status": "GAIN" if "GAIN" in t_dir.name else "STOP",
                "is_gain": "GAIN" in t_dir.name,
                "r_multiple": 3.0 if "GAIN" in t_dir.name else -1.0,
                "pnl": 0.0,
                "entry_time": "",
                "exit_time": "",
                "entry_price": 0.0,
                "stop_loss": 0.0,
                "take_profit": 0.0,
                "exit_price": 0.0,
                "exit_reason": "TP" if "GAIN" in t_dir.name else "SL",
                "zone_kind": "OB",
                "entry_mode": "confirmation",
                "macro_img": f"/api/files/{folder_name}/trades/{t_dir.name}/01_macro_chart.png",
                "micro_img": f"/api/files/{folder_name}/trades/{t_dir.name}/02_micro_chart.png",
                "txt_url": f"/api/files/{folder_name}/trades/{t_dir.name}/{t_txt[0].name}"
                if t_txt
                else "",
            }

            if t_txt:
                lines = t_txt[0].read_text(encoding="utf-8").splitlines()
                for line in lines:
                    if ":" not in line:
                        continue
                    k, v = line.split(":", 1)
                    k = k.strip()
                    v = v.strip()
                    if k == "Data/Hora Entrada":
                        t_info["entry_time"] = v
                    elif k == "Data/Hora Saída":
                        t_info["exit_time"] = v
                    elif k == "Preço de Entrada":
                        t_info["entry_price"] = float(v) if v != "N/A" else 0.0
                    elif k == "Stop Loss":
                        t_info["stop_loss"] = float(v) if v != "N/A" else 0.0
                    elif k == "Take Profit":
                        t_info["take_profit"] = float(v) if v != "N/A" else None
                    elif k == "Preço de Saída":
                        t_info["exit_price"] = float(v) if v != "N/A" else 0.0
                    elif k == "Motivo da Saída":
                        t_info["exit_reason"] = v
                    elif k == "Resultado (R)":
                        m_r = re.search(r"([+-]?[\d\.]+)R", v)
                        if m_r:
                            t_info["r_multiple"] = float(m_r.group(1))
                    elif k == "Lucro/Prejuízo ($)":
                        m_p = re.search(r"\$([+-]?[\d\.]+)", v)
                        if m_p:
                            t_info["pnl"] = float(m_p.group(1))
                    elif k == "Zona de Origem":
                        t_info["zone_kind"] = v
                    elif k == "Modo de Gatilho":
                        t_info["entry_mode"] = v

            cum_r += t_info["r_multiple"]
            trades_data.append(t_info)
            equity_curve.append(
                {
                    "time": t_info["exit_time"] or f"Trade {idx}",
                    "cum_r": round(cum_r, 2),
                    "pnl": round(t_info["pnl"], 2),
                }
            )

    if not metrics["total_trades"] and trades_data:
        metrics["total_trades"] = len(trades_data)
        metrics["win_trades"] = sum(1 for t in trades_data if t["is_gain"])
        metrics["loss_trades"] = sum(1 for t in trades_data if not t["is_gain"])
        metrics["win_rate"] = round((metrics["win_trades"] / len(trades_data)) * 100, 2)
        metrics["expectancy"] = round(cum_r / len(trades_data), 2)

    manifest = {
        "id": folder_name,
        "symbol": symbol,
        "timestamp": ts_str,
        "created_at": datetime.now().isoformat(),
        "metrics": metrics,
        "excel_file": excel_file,
        "excel_url": f"/api/files/{folder_name}/{excel_file}",
        "txt_file": txt_file,
        "txt_url": f"/api/files/{folder_name}/{txt_file}",
        "equity_curve": equity_curve,
        "trades": trades_data,
    }

    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

    return manifest


def list_audit_packages(base_dir: Path = Path("out/backtests")) -> list[dict[str, Any]]:
    """Varre o disco local como banco de dados e retorna todos os pacotes de backtest disponíveis."""
    if not base_dir.exists():
        return []

    results = []
    for folder in sorted(base_dir.iterdir(), reverse=True):
        if not folder.is_dir():
            continue
        manifest = load_or_create_manifest(folder)
        m = manifest.get("metrics", {})
        results.append(
            {
                "id": manifest.get("id", folder.name),
                "symbol": manifest.get("symbol", "UNKNOWN"),
                "timestamp": manifest.get("timestamp", ""),
                "created_at": manifest.get("created_at", ""),
                "total_trades": m.get("total_trades", len(manifest.get("trades", []))),
                "win_rate": m.get("win_rate", 0.0),
                "expectancy": m.get("expectancy", 0.0),
                "profit_factor": m.get("profit_factor", 0.0),
                "total_pnl": m.get("total_pnl", 0.0),
                "excel_url": manifest.get("excel_url", ""),
                "txt_url": manifest.get("txt_url", ""),
            }
        )

    return results


def _create_excel_report(
    excel_path: Path,
    symbol: str,
    trades: list[Trade],
    metrics: dict[str, Any],
    initial_capital: float,
):
    """Cria a planilha Excel com as duas abas estilizadas."""
    wb = openpyxl.Workbook()
    # Remove aba padrão inicial
    default_sheet = wb.active

    # --- ABA 1: OPERAÇÕES ---
    ws_trades = wb.create_sheet(title="Operações")
    wb.remove(default_sheet)

    headers_trades = [
        "Trade #",
        "Ativo",
        "Data/Hora Entrada (UTC)",
        "Data/Hora Saída (UTC)",
        "Direção",
        "Zona SMC",
        "Gatilho",
        "Preço Entrada",
        "Stop Loss",
        "Take Profit",
        "Preço Saída",
        "Status",
        "Motivo Saída",
        "Resultado (R)",
        "Lucro/Prejuízo ($)",
        "Custos ($)",
        "Saldo Acumulado (R)",
        "Saldo Acumulado ($)",
    ]

    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    header_fill = PatternFill(
        start_color="1F2937", end_color="1F2937", fill_type="solid"
    )
    center_align = Alignment(horizontal="center", vertical="center")
    right_align = Alignment(horizontal="right", vertical="center")
    thin_border = Border(
        left=Side(style="thin", color="E5E7EB"),
        right=Side(style="thin", color="E5E7EB"),
        top=Side(style="thin", color="E5E7EB"),
        bottom=Side(style="thin", color="E5E7EB"),
    )

    ws_trades.append(headers_trades)
    for col_idx in range(1, len(headers_trades) + 1):
        cell = ws_trades.cell(row=1, column=col_idx)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_align
        cell.border = thin_border

    cum_r = 0.0
    cum_cash = initial_capital

    gain_fill = PatternFill(
        start_color="DCFCE7", end_color="DCFCE7", fill_type="solid"
    )  # Verde suave
    stop_fill = PatternFill(
        start_color="FEE2E2", end_color="FEE2E2", fill_type="solid"
    )  # Vermelho suave
    gain_font = Font(name="Calibri", size=10, bold=True, color="166534")
    stop_font = Font(name="Calibri", size=10, bold=True, color="991B1B")

    for idx, t in enumerate(trades, 1):
        cum_r += t.r_multiple
        cum_cash += t.pnl
        is_gain = t.r_multiple > 0
        status_text = "GAIN" if is_gain else "STOP"

        row_data = [
            idx,
            symbol,
            t.entry_time.strftime("%Y-%m-%d %H:%M"),
            t.exit_time.strftime("%Y-%m-%d %H:%M"),
            t.direction.upper(),
            t.zone_kind,
            t.entry_mode,
            round(t.entry_price, 3),
            round(t.stop_loss, 3),
            round(t.take_profit, 3) if t.take_profit else "N/A",
            round(t.exit_price, 3),
            status_text,
            t.exit_reason.upper(),
            round(t.r_multiple, 2),
            round(t.pnl, 2),
            round(t.costs, 2),
            round(cum_r, 2),
            round(cum_cash, 2),
        ]
        ws_trades.append(row_data)
        current_row = ws_trades.max_row

        # Estilizar células da linha
        for col_idx in range(1, len(row_data) + 1):
            c = ws_trades.cell(row=current_row, column=col_idx)
            c.border = thin_border
            c.font = Font(name="Calibri", size=10)
            c.alignment = (
                right_align
                if col_idx in [1, 8, 9, 10, 11, 14, 15, 16, 17, 18]
                else center_align
            )

            # Colorir coluna de Status
            if col_idx == 12:
                c.fill = gain_fill if is_gain else stop_fill
                c.font = gain_font if is_gain else stop_font

    # Ajustar largura das colunas
    for col in ws_trades.columns:
        max_len = max(len(str(cell.value or "")) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws_trades.column_dimensions[col_letter].width = max(max_len + 3, 12)

    # --- ABA 2: ANÁLISE ESTATÍSTICA & ROI ---
    ws_stats = wb.create_sheet(title="Análise Estatística & ROI")

    ws_stats.column_dimensions["A"].width = 35
    ws_stats.column_dimensions["B"].width = 25

    title_font = Font(name="Calibri", size=14, bold=True, color="1E3A8A")
    sec_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    sec_fill = PatternFill(start_color="3B82F6", end_color="3B82F6", fill_type="solid")

    ws_stats["A1"] = f"RELATÓRIO ESTATÍSTICO DE DESEMPENHO — {symbol}"
    ws_stats["A1"].font = title_font

    total_trades = metrics.get("total_trades", len(trades))
    wins = metrics.get("win_trades", sum(1 for t in trades if t.r_multiple > 0))
    losses = metrics.get("loss_trades", sum(1 for t in trades if t.r_multiple <= 0))
    win_rate = metrics.get(
        "win_rate", (wins / total_trades * 100) if total_trades else 0
    )
    total_pnl = metrics.get("total_pnl", sum(t.pnl for t in trades))
    final_capital = initial_capital + total_pnl
    roi_pct = ((final_capital - initial_capital) / initial_capital) * 100

    # Sequências máximas
    max_consec_wins = 0
    max_consec_losses = 0
    curr_wins = 0
    curr_losses = 0
    for t in trades:
        if t.r_multiple > 0:
            curr_wins += 1
            curr_losses = 0
            max_consec_wins = max(max_consec_wins, curr_wins)
        else:
            curr_losses += 1
            curr_wins = 0
            max_consec_losses = max(max_consec_losses, curr_losses)

    stats_data = [
        ("", ""),
        ("RESUMO GERAL", ""),
        ("Capital Inicial ($)", f"${initial_capital:,.2f}"),
        ("Capital Final ($)", f"${final_capital:,.2f}"),
        ("Lucro Líquido ($)", f"${total_pnl:,.2f}"),
        ("Retorno sobre Investimento (ROI)", f"{roi_pct:+.2f}%"),
        ("", ""),
        ("DESEMPENHO OPERACIONAL", ""),
        ("Total de Operações", total_trades),
        ("Operações Vencedoras (Gains)", wins),
        ("Operações Perdedoras (Stops)", losses),
        ("Taxa de Acerto (Win Rate)", f"{win_rate:.2f}%"),
        ("Relação Risco:Retorno Alvo", "1:3 (3.0R)"),
        ("R Médio por Operação", f"{metrics.get('avg_r', 0):+.2f}R"),
        ("Expectativa Matemática por Trade", f"{metrics.get('expectancy', 0):+.2f}R"),
        ("Profit Factor", f"{metrics.get('profit_factor', 0):.2f}"),
        ("Drawdown Máximo (em R)", f"{metrics.get('max_drawdown_r', 0):.2f}R"),
        ("Maior Sequência de Gains", f"{max_consec_wins} trades"),
        ("Maior Sequência de Stops", f"{max_consec_losses} trades"),
    ]

    for item in stats_data:
        ws_stats.append(item)
        r = ws_stats.max_row
        if item[0] in ["RESUMO GERAL", "DESEMPENHO OPERACIONAL"]:
            ws_stats.cell(row=r, column=1).font = sec_font
            ws_stats.cell(row=r, column=1).fill = sec_fill
            ws_stats.cell(row=r, column=2).fill = sec_fill
        elif item[0] != "":
            ws_stats.cell(row=r, column=1).font = Font(
                name="Calibri", size=11, bold=True
            )
            ws_stats.cell(row=r, column=2).font = Font(name="Calibri", size=11)
            ws_stats.cell(row=r, column=1).border = thin_border
            ws_stats.cell(row=r, column=2).border = thin_border

    wb.save(str(excel_path))

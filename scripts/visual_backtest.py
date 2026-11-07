"""Gera gráfico visual completo de validação do backtest com marcações de trades, zonas e estrutura."""
from pathlib import Path
import json
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from smc_trader.analysis import analyze
from smc_trader.backtest.engine import BacktestEngine
from smc_trader.config import BacktestConfig, ZoneConfig
from smc_trader.data.resample import resample_ohlc
from smc_trader.data.store import load_candles
from smc_trader.viz.chart import build_chart

def main():
    data_root = Path("data")
    symbol = "XAUUSD"
    out_dir = Path("out")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / "backtest_visual_xauusd.html"

    print("Carregando candles M1...")
    c_m1 = load_candles(data_root, symbol, "M1")
    if c_m1.empty:
        print("Erro: sem dados M1!")
        return

    print(f"Total de candles M1 carregados: {len(c_m1)}")
    c_m15 = resample_ohlc(c_m1, "M15")
    print(f"Candles M15 reamostrados: {len(c_m15)}")

    # Análise SMC
    zone_cfg = ZoneConfig(blocks_filter=["OB", "FVOB", "BB"])
    analysis = analyze(c_m15, 3, zone_cfg)
    all_zones = analysis.zones + analysis.breakers
    print(f"Zonas detectadas: {len(analysis.zones)} OBs, {len(analysis.breakers)} Breakers")

    # Configuração da melhor estratégia do backtest:
    # OB + Confirmação CHoCH M1 + Stop Swing + Alvo 3R
    cfg = BacktestConfig(
        entry_mode="confirmation",
        stop_mode="swing",
        target_mode="fixed_r",
        target_r=3.0,
        limits={"enabled": True, "max_trades_per_day": 3, "max_stops_per_day": 2, "max_gains_per_day": 1}
    )
    engine = BacktestEngine(cfg)
    print("Executando backtest orientado a eventos...")
    result = engine.run(c_m1, all_zones, symbol=symbol)
    trades = result.trades
    metrics = result.metrics

    print("\n" + "=" * 50)
    print("MÉTRICAS DO BACKTEST:")
    for k, v in metrics.items():
        print(f"  {k}: {v}")
    print("=" * 50)

    # Construir figura com 2 subplots: [1] Gráfico de Preço e Zonas SMC / Trades, [2] Curva de Patrimônio (R acumulado)
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.75, 0.25],
        subplot_titles=(
            f"<b>{symbol} (M15) — Análise Institucional SMC & Entradas Validadas</b>",
            "<b>Curva de Patrimônio Acumulado (R)</b>"
        )
    )

    # 1. Candlesticks M15
    fig.add_trace(
        go.Candlestick(
            x=c_m15.index,
            open=c_m15["open"],
            high=c_m15["high"],
            low=c_m15["low"],
            close=c_m15["close"],
            name="Candles M15",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
            increasing_fillcolor="#26a69a",
            decreasing_fillcolor="#ef5350",
        ),
        row=1, col=1
    )

    # 2. Pivôs de Estrutura
    pivots = analysis.pivots
    sel_highs = pivots[pivots["kind"] == "high"]
    sel_lows = pivots[pivots["kind"] == "low"]

    fig.add_trace(
        go.Scatter(
            x=sel_highs["time"],
            y=sel_highs["price"],
            mode="markers",
            marker=dict(symbol="triangle-down", size=7, color="#ef5350"),
            name="Topo Estrutural (Swing High)",
            hoverinfo="x+y+name"
        ),
        row=1, col=1
    )
    fig.add_trace(
        go.Scatter(
            x=sel_lows["time"],
            y=sel_lows["price"],
            mode="markers",
            marker=dict(symbol="triangle-up", size=7, color="#26a69a"),
            name="Fundo Estrutural (Swing Low)",
            hoverinfo="x+y+name"
        ),
        row=1, col=1
    )

    # 3. Quebras de Estrutura (BOS / CHoCH)
    for e in analysis.events:
        c_color = "#26a69a" if e.direction == "up" else "#ef5350"
        fig.add_trace(
            go.Scatter(
                x=[e.level_time, e.time],
                y=[e.level, e.level],
                mode="lines",
                line=dict(color=c_color, width=1.2, dash="dot"),
                showlegend=False,
                hoverinfo="skip"
            ),
            row=1, col=1
        )
        fig.add_annotation(
            x=e.time,
            y=e.level,
            text=f"{e.kind} {'↑' if e.direction == 'up' else '↓'}",
            showarrow=False,
            yshift=10 if e.direction == "up" else -10,
            font=dict(size=10, color=c_color),
            row=1, col=1
        )

    # 4. Zonas (Order Blocks e Breakers)
    last_close = c_m15["close_time"].iloc[-1] if len(c_m15) else None
    for z in analysis.zones:
        fill = "rgba(38, 166, 154, 0.20)" if z.direction == "long" else "rgba(239, 83, 80, 0.20)"
        line_c = "#26a69a" if z.direction == "long" else "#ef5350"
        x_end = z.end_time if z.end_time is not None else last_close
        fig.add_shape(
            type="rect",
            xref="x", yref="y",
            x0=z.created_at, x1=x_end,
            y0=z.low, y1=z.high,
            fillcolor=fill,
            line=dict(color=line_c, width=1),
            layer="below",
            row=1, col=1
        )

    for b in analysis.breakers:
        fill = "rgba(171, 71, 188, 0.20)" if b.direction == "long" else "rgba(255, 167, 38, 0.20)"
        line_c = "#ab47bc" if b.direction == "long" else "#ffa726"
        x_end = b.end_time if b.end_time is not None else last_close
        fig.add_shape(
            type="rect",
            xref="x", yref="y",
            x0=b.created_at, x1=x_end,
            y0=b.low, y1=b.high,
            fillcolor=fill,
            line=dict(color=line_c, width=1, dash="dash"),
            layer="below",
            row=1, col=1
        )

    # 5. Marcações de Trades Validados
    buy_entries_x, buy_entries_y, buy_text = [], [], []
    sell_entries_x, sell_entries_y, sell_text = [], [], []
    win_exits_x, win_exits_y, win_text = [], [], []
    loss_exits_x, loss_exits_y, loss_text = [], [], []

    cum_r = 0.0
    equity_x, equity_y = [c_m15.index[0]], [0.0]

    for idx, t in enumerate(trades, 1):
        cum_r += t.r_multiple
        equity_x.append(t.exit_time)
        equity_y.append(cum_r)

        is_win = t.r_multiple > 0
        status_label = "✅ GAIN" if is_win else "❌ LOSS"
        hover_entry = (
            f"<b>Trade #{idx} — {t.direction.upper()} ({status_label})</b><br>"
            f"Entrada: {t.entry_time.strftime('%Y-%m-%d %H:%M')}<br>"
            f"Preço Entrada: {t.entry_price:.2f}<br>"
            f"Stop Loss: {t.stop_loss:.2f}<br>"
            f"Take Profit: {t.take_profit:.2f}<br>"
            f"Zona: {t.zone_kind} ({t.entry_mode})<br>"
            f"Resultado: {t.r_multiple:+.2f}R"
        )
        hover_exit = (
            f"<b>Saída Trade #{idx}</b><br>"
            f"Saída: {t.exit_time.strftime('%Y-%m-%d %H:%M')}<br>"
            f"Preço Saída: {t.exit_price:.2f}<br>"
            f"Motivo: {t.exit_reason.upper()}<br>"
            f"Resultado: {t.r_multiple:+.2f}R"
        )

        if t.direction == "buy":
            buy_entries_x.append(t.entry_time)
            buy_entries_y.append(t.entry_price)
            buy_text.append(hover_entry)
        else:
            sell_entries_x.append(t.entry_time)
            sell_entries_y.append(t.entry_price)
            sell_text.append(hover_entry)

        if is_win:
            win_exits_x.append(t.exit_time)
            win_exits_y.append(t.exit_price)
            win_text.append(hover_exit)
        else:
            loss_exits_x.append(t.exit_time)
            loss_exits_y.append(t.exit_price)
            loss_text.append(hover_exit)

        # Linha conectando entrada até a saída
        fig.add_trace(
            go.Scatter(
                x=[t.entry_time, t.exit_time],
                y=[t.entry_price, t.exit_price],
                mode="lines",
                line=dict(color="#26a69a" if is_win else "#ef5350", width=1.5, dash="dash"),
                showlegend=False,
                hoverinfo="skip"
            ),
            row=1, col=1
        )

        # Linhas horizontais de SL e TP
        fig.add_trace(
            go.Scatter(
                x=[t.entry_time, t.exit_time],
                y=[t.stop_loss, t.stop_loss],
                mode="lines",
                line=dict(color="#ef5350", width=1, dash="dot"),
                showlegend=False,
                hoverinfo="skip"
            ),
            row=1, col=1
        )
        if t.take_profit:
            fig.add_trace(
                go.Scatter(
                    x=[t.entry_time, t.exit_time],
                    y=[t.take_profit, t.take_profit],
                    mode="lines",
                    line=dict(color="#26a69a", width=1, dash="dot"),
                    showlegend=False,
                    hoverinfo="skip"
                ),
                row=1, col=1
            )

    # Adicionar marcadores de compra/venda
    if buy_entries_x:
        fig.add_trace(
            go.Scatter(
                x=buy_entries_x, y=buy_entries_y,
                mode="markers",
                marker=dict(symbol="arrow-up", size=14, color="#00e676", line=dict(color="#ffffff", width=1)),
                name="Entrada COMPRA (Buy)",
                text=buy_text,
                hoverinfo="text"
            ),
            row=1, col=1
        )

    if sell_entries_x:
        fig.add_trace(
            go.Scatter(
                x=sell_entries_x, y=sell_entries_y,
                mode="markers",
                marker=dict(symbol="arrow-down", size=14, color="#ff1744", line=dict(color="#ffffff", width=1)),
                name="Entrada VENDA (Sell)",
                text=sell_text,
                hoverinfo="text"
            ),
            row=1, col=1
        )

    if win_exits_x:
        fig.add_trace(
            go.Scatter(
                x=win_exits_x, y=win_exits_y,
                mode="markers",
                marker=dict(symbol="star", size=12, color="#ffd700"),
                name="Saída GAIN (Take Profit)",
                text=win_text,
                hoverinfo="text"
            ),
            row=1, col=1
        )

    if loss_exits_x:
        fig.add_trace(
            go.Scatter(
                x=loss_exits_x, y=loss_exits_y,
                mode="markers",
                marker=dict(symbol="x", size=10, color="#ff5252"),
                name="Saída LOSS (Stop Loss)",
                text=loss_text,
                hoverinfo="text"
            ),
            row=1, col=1
        )

    # 6. Curva de Patrimônio no Subplot 2
    fig.add_trace(
        go.Scatter(
            x=equity_x, y=equity_y,
            mode="lines+markers",
            line=dict(color="#00e5ff", width=2.5),
            marker=dict(size=4),
            name="Curva de Patrimônio (R)",
            hovertemplate="Data: %{x}<br>R Acumulado: %{y:.2f}R<extra></extra>"
        ),
        row=2, col=1
    )

    # Layout dark institutional
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#0d1117",
        plot_bgcolor="#0d1117",
        height=950,
        margin=dict(l=50, r=50, t=70, b=50),
        xaxis_rangeslider_visible=False,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="center",
            x=0.5,
            bgcolor="rgba(22, 27, 34, 0.8)",
            bordercolor="#30363d",
            borderwidth=1
        ),
        hovermode="closest",
    )
    fig.update_yaxes(title_text="Preço (USD)", row=1, col=1, gridcolor="#21262d")
    fig.update_yaxes(title_text="R Múltiplo", row=2, col=1, gridcolor="#21262d")
    fig.update_xaxes(gridcolor="#21262d")

    fig.write_html(str(out_file), include_plotlyjs="cdn")
    print(f"\n✅ Relatório visual gerado com sucesso em: {out_file.resolve()}")

if __name__ == "__main__":
    main()

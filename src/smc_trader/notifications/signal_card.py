"""Gerador de imagem de sinal para Telegram e interface (SPEC_PRODUTO.md 5.4 / E4-2).

Produz snapshot visual dos últimos candles com faixas de entrada, stop e alvo
renderizados via matplotlib.
"""

from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.use("Agg")  # Headless backend para servidor


def render_signal_card(
    df_candles: pd.DataFrame,
    entry_price: float,
    stop_loss: float,
    take_profit: float | None,
    direction: str,
    title: str = "Sinal SMC Trader",
    out_path: Path | str = "out/signal.png",
) -> Path:
    """Gera cartão gráfico em PNG com os candles recentes e níveis operacionais."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Considera os últimos ~60 candles
    df = df_candles.tail(60).copy()
    if df.empty:
        raise ValueError("DataFrame de candles vazio para renderização de sinal.")

    # Converte índices para números matplotlib
    fig, ax = plt.subplots(figsize=(10, 5), dpi=150)
    fig.patch.set_facecolor("#1e222d")
    ax.set_facecolor("#1e222d")

    # Desenha candlesticks
    for i, (ts, row) in enumerate(df.iterrows()):
        o, h, low_val, c = row["open"], row["high"], row["low"], row["close"]
        color = "#26a69a" if c >= o else "#ef5350"
        # Pavio
        ax.plot([i, i], [low_val, h], color=color, linewidth=1.0)
        # Corpo
        lower = min(o, c)
        height = max(abs(c - o), 0.05)
        rect = plt.Rectangle(
            (i - 0.35, lower),
            0.7,
            height,
            color=color,
            alpha=0.9,
        )
        ax.add_patch(rect)

    # Linhas de entrada, stop e alvo
    n_bars = len(df)
    ax.axhline(entry_price, color="#2962ff", linestyle="--", linewidth=1.5, label=f"Entrada: {entry_price:,.2f}")
    ax.axhline(stop_loss, color="#f44336", linestyle="-", linewidth=1.5, label=f"Stop: {stop_loss:,.2f}")
    if take_profit is not None:
        ax.axhline(take_profit, color="#4caf50", linestyle="-", linewidth=1.5, label=f"Alvo: {take_profit:,.2f}")

    # Risco / Retorno
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price) if take_profit else 0.0
    rr_str = f"1:{reward / risk:.1f}" if (risk > 0 and reward > 0) else "N/A"

    ax.set_title(
        f"{title} | {direction.upper()} | R:R {rr_str}",
        color="#ffffff",
        fontsize=12,
        fontweight="bold",
        pad=10,
    )
    ax.tick_params(colors="#787b86", labelsize=9)
    ax.grid(True, color="#2a2e39", linestyle=":", alpha=0.6)
    ax.legend(
        facecolor="#2a2e39",
        edgecolor="#363a45",
        labelcolor="#ffffff",
        loc="upper left",
        fontsize=9,
    )

    # Eixo X resumido
    step = max(1, n_bars // 6)
    ticks = list(range(0, n_bars, step))
    tick_labels = [df.index[t].strftime("%H:%M") for t in ticks]
    ax.set_xticks(ticks)
    ax.set_xticklabels(tick_labels, rotation=0)

    plt.tight_layout()
    plt.savefig(p, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    return p

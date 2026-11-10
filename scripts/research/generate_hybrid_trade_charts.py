"""Gera gráficos institucionais de alta resolução para 2 operações vencedoras e 2 perdedoras
do Modelo Híbrido SMC (Indução + Fibo 61.8% + RSI + Bandas de Bollinger) no NAS100 (M15).
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from scripts.research.test_smc_hybrid_inducement_fibo_rsi_bb import compute_bollinger, compute_rsi
from smc_trader.data.resample import resample_ohlc
from smc_trader.data.store import load_candles

ARTIFACT_DIR = Path("/home/thiagooliveira/.gemini/antigravity-cli/brain/9d956e0b-d7fe-4cf8-8642-d550d7af6a39")
DATA_DIR = Path("data")


def draw_candlesticks(ax, df_sub, width=0.6):
    for idx, (_, row) in enumerate(df_sub.iterrows()):
        o, h, lo, c = row["open"], row["high"], row["low"], row["close"]
        color = "#26a69a" if c >= o else "#ef5350"
        # Sombra
        ax.vlines(idx, lo, h, color=color, linewidth=1.2, zorder=2)
        # Corpo
        body_bottom = min(o, c)
        body_height = max(abs(c - o), 0.5)
        rect = patches.Rectangle(
            (idx - width / 2, body_bottom),
            width,
            body_height,
            facecolor=color,
            edgecolor=color,
            zorder=3,
        )
        ax.add_patch(rect)


def plot_trade_chart(
    df_m15: pd.DataFrame,
    start_str: str,
    end_str: str,
    trade_info: dict,
    output_path: Path,
):
    sub = df_m15.loc[start_str:end_str].copy()
    if len(sub) == 0:
        print(f"Erro: Sub-dataframe vazio para {start_str} até {end_str}")
        return

    sub["rsi"] = compute_rsi(sub["close"], period=14)
    sub["sma20"], sub["bb_upper"], sub["bb_lower"] = compute_bollinger(sub["close"], window=20, num_std=2.0)

    fig, (ax_main, ax_rsi) = plt.subplots(
        2, 1, figsize=(16, 9), dpi=150, gridspec_kw={"height_ratios": [3.2, 1.0]}, sharex=True
    )
    fig.patch.set_facecolor("#131722")
    ax_main.set_facecolor("#131722")
    ax_rsi.set_facecolor("#131722")

    # 1. Candlesticks
    draw_candlesticks(ax_main, sub)

    # 2. Bandas de Bollinger
    xs = np.arange(len(sub))
    ax_main.plot(xs, sub["bb_upper"], color="#3b82f6", linestyle="--", linewidth=1.1, alpha=0.7, label="Bollinger Upper (2σ)")
    ax_main.plot(xs, sub["sma20"], color="#94a3b8", linestyle=":", linewidth=1.0, alpha=0.6, label="SMA 20")
    ax_main.plot(xs, sub["bb_lower"], color="#3b82f6", linestyle="--", linewidth=1.1, alpha=0.7, label="Bollinger Lower (2σ)")
    ax_main.fill_between(xs, sub["bb_upper"], sub["bb_lower"], color="#3b82f6", alpha=0.04)

    # Níveis da Operação
    entry_p = trade_info["entry_price"]
    stop_p = trade_info["stop_price"]
    target_p = trade_info["target_price"]
    entry_t = trade_info["entry_time"]
    exit_t = trade_info["exit_time"]
    is_win = trade_info["win"]
    direction = trade_info["direction"].upper()

    # Linhas de Entry, Stop e Target
    ax_main.axhline(entry_p, color="#38bdf8", linestyle="-", linewidth=1.4, alpha=0.9, label=f"Entrada: {entry_p:.2f}")
    ax_main.axhline(stop_p, color="#f43f5e", linestyle="-.", linewidth=1.4, alpha=0.9, label=f"Stop Loss: {stop_p:.2f}")
    ax_main.axhline(target_p, color="#10b981", linestyle="--", linewidth=1.4, alpha=0.9, label=f"Take Profit (2R): {target_p:.2f}")

    # Localiza índices de entrada e saída no gráfico
    times = [t.strftime("%d/%m %H:%M") for t in sub.index]
    entry_idx = None
    exit_idx = None

    for i, t in enumerate(sub.index):
        if t == entry_t:
            entry_idx = i
        if t == exit_t:
            exit_idx = i

    if entry_idx is not None:
        marker = "^" if direction == "LONG" else "v"
        m_color = "#38bdf8"
        ax_main.scatter(
            [entry_idx],
            [entry_p],
            marker=marker,
            color=m_color,
            s=160,
            zorder=6,
            label=f"Disparo ({direction})",
        )
        ax_main.annotate(
            f"ENTRADA {direction}\n{entry_t.strftime('%d/%m/%Y %H:%M')} UTC",
            xy=(entry_idx, entry_p),
            xytext=(entry_idx, entry_p + (entry_p * 0.0025 if direction == "LONG" else -entry_p * 0.0025)),
            color="#38bdf8",
            fontweight="bold",
            fontsize=9,
            ha="center",
            arrowprops=dict(arrowstyle="->", color="#38bdf8", lw=1.2),
            bbox=dict(boxstyle="round,pad=0.2", facecolor="#0f172a", edgecolor="#38bdf8", alpha=0.9),
        )

    if exit_idx is not None:
        exit_p = trade_info["exit_price"]
        res_text = f"TAKE PROFIT (+2.0R)\n{exit_t.strftime('%d/%m/%Y %H:%M')} UTC" if is_win else f"STOP LOSS ({trade_info['r_multiple']:.2f}R)\n{exit_t.strftime('%d/%m/%Y %H:%M')} UTC"
        res_color = "#10b981" if is_win else "#f43f5e"

        ax_main.scatter([exit_idx], [exit_p], marker="x", color=res_color, s=140, linewidth=2.5, zorder=6)
        ax_main.annotate(
            res_text,
            xy=(exit_idx, exit_p),
            xytext=(exit_idx, exit_p - (exit_p * 0.0025 if direction == "LONG" else -exit_p * 0.0025)),
            color=res_color,
            fontweight="bold",
            fontsize=9,
            ha="center",
            arrowprops=dict(arrowstyle="->", color=res_color, lw=1.2),
            bbox=dict(boxstyle="round,pad=0.2", facecolor="#0f172a", edgecolor=res_color, alpha=0.9),
        )

    # 3. Subplot do RSI
    ax_rsi.plot(xs, sub["rsi"], color="#f59e0b", linewidth=1.5, label="RSI(14)")
    ax_rsi.axhline(70, color="#f43f5e", linestyle=":", linewidth=1.0, alpha=0.7)
    ax_rsi.axhline(65, color="#f43f5e", linestyle="--", linewidth=1.0, alpha=0.8, label="Sobrecompra (65)")
    ax_rsi.axhline(50, color="#64748b", linestyle=":", linewidth=0.8, alpha=0.5)
    ax_rsi.axhline(35, color="#10b981", linestyle="--", linewidth=1.0, alpha=0.8, label="Sobrevenda (35)")
    ax_rsi.axhline(30, color="#10b981", linestyle=":", linewidth=1.0, alpha=0.7)
    ax_rsi.fill_between(xs, 65, 35, color="#64748b", alpha=0.08)
    ax_rsi.set_ylim(15, 85)
    ax_rsi.set_ylabel("RSI (14)", color="#d1d4dc", fontsize=9)

    # Formatação e Labels
    ax_main.set_title(
        f"MODELO HÍBRIDO SMC (Fibo 61.8% + Indução + RSI + Bollinger) | {trade_info['symbol']} (M15)\n"
        f"Operação: {direction} | Resultado: {'WIN (+2.0R)' if is_win else 'LOSS (' + str(round(trade_info['r_multiple'], 2)) + 'R)'} | Entrada: {entry_t.strftime('%d/%m/%Y %H:%M')} UTC",
        color="#f8fafc",
        fontsize=12,
        fontweight="bold",
        pad=12,
    )

    ax_main.set_ylabel("Preço", color="#d1d4dc", fontsize=10)
    ax_main.yaxis.tick_right()
    ax_main.yaxis.set_label_position("right")
    ax_rsi.yaxis.tick_right()
    ax_rsi.yaxis.set_label_position("right")

    ax_main.grid(True, color="#1e293b", linestyle="--", alpha=0.5)
    ax_rsi.grid(True, color="#1e293b", linestyle="--", alpha=0.5)

    ax_rsi.set_xticks(range(len(times)))
    ax_rsi.set_xticklabels(times, rotation=45, color="#94a3b8", fontsize=8)
    ax_main.tick_params(colors="#94a3b8")
    ax_rsi.tick_params(colors="#94a3b8")

    # Legenda
    ax_main.legend(loc="upper left", facecolor="#0f172a", edgecolor="#334155", labelcolor="#cbd5e1", fontsize=8)
    ax_rsi.legend(loc="upper left", facecolor="#0f172a", edgecolor="#334155", labelcolor="#cbd5e1", fontsize=8)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close()
    print(f"Gráfico salvo com sucesso: {output_path}")


def main():
    print("Carregando base M1 e gerando gráficos dos 4 trades selecionados...")
    df_m1 = load_candles(DATA_DIR, "NAS100", "M1", source="dukascopy")
    df_m15 = resample_ohlc(df_m1, "M15")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

    # 1. WIN 1: COMPRA (LONG) - 25/03/2022 às 14:00 UTC
    t1 = {
        "symbol": "NAS100",
        "direction": "long",
        "entry_time": pd.Timestamp("2022-03-25 14:00:00+0000", tz="UTC"),
        "exit_time": pd.Timestamp("2022-03-25 14:30:00+0000", tz="UTC"),
        "entry_price": 14725.327,
        "stop_price": 14696.339,
        "target_price": 14783.303,
        "exit_price": 14783.303,
        "win": True,
        "r_multiple": 2.0,
    }
    plot_trade_chart(
        df_m15,
        "2022-03-25 08:00",
        "2022-03-25 18:00",
        t1,
        ARTIFACT_DIR / "operacao_win_1_compra_nas100.png",
    )

    # 2. WIN 2: VENDA (SHORT) - 07/12/2021 às 13:45 UTC
    t2 = {
        "symbol": "NAS100",
        "direction": "short",
        "entry_time": pd.Timestamp("2021-12-07 13:45:00+0000", tz="UTC"),
        "exit_time": pd.Timestamp("2021-12-07 14:15:00+0000", tz="UTC"),
        "entry_price": 16147.529,
        "stop_price": 16170.089,
        "target_price": 16102.409,
        "exit_price": 16102.409,
        "win": True,
        "r_multiple": 2.0,
    }
    plot_trade_chart(
        df_m15,
        "2021-12-07 09:00",
        "2021-12-07 17:00",
        t2,
        ARTIFACT_DIR / "operacao_win_2_venda_nas100.png",
    )

    # 3. LOSS 1: COMPRA (LONG) - 09/11/2021 às 16:15 UTC
    t3 = {
        "symbol": "NAS100",
        "direction": "long",
        "entry_time": pd.Timestamp("2021-11-09 16:15:00+0000", tz="UTC"),
        "exit_time": pd.Timestamp("2021-11-09 17:00:00+0000", tz="UTC"),
        "entry_price": 16238.319,
        "stop_price": 16198.159,
        "target_price": 16318.639,
        "exit_price": 16197.159,
        "win": False,
        "r_multiple": -1.02,
    }
    plot_trade_chart(
        df_m15,
        "2021-11-09 11:00",
        "2021-11-09 19:30",
        t3,
        ARTIFACT_DIR / "operacao_loss_1_compra_nas100.png",
    )

    # 4. LOSS 2: VENDA (SHORT) - 29/11/2021 às 23:30 UTC
    t4 = {
        "symbol": "NAS100",
        "direction": "short",
        "entry_time": pd.Timestamp("2021-11-29 23:30:00+0000", tz="UTC"),
        "exit_time": pd.Timestamp("2021-11-29 23:30:00+0000", tz="UTC"),
        "entry_price": 16436.019,
        "stop_price": 16442.697,
        "target_price": 16422.663,
        "exit_price": 16443.697,
        "win": False,
        "r_multiple": -1.15,
    }
    plot_trade_chart(
        df_m15,
        "2021-11-29 18:00",
        "2021-11-30 04:00",
        t4,
        ARTIFACT_DIR / "operacao_loss_2_venda_nas100.png",
    )


if __name__ == "__main__":
    main()

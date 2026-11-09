"""Ferramenta de Auditoria Visual de Trades (Trade Inspector).

Gera:
1. Planilhas CSV completas com todas as operações (preço de entrada, stop, alvo, motivo de saída, retorno em R, horários).
2. Gráficos interativos em HTML (Plotly) para inspecionar candle a candle qualquer operação:
   - Estrutura Macro (H1) e Micro (M15)
   - Zonas de Fibo OTE (61.8% a 78.6%)
   - Médias Móveis (MME 8, MME 20)
   - Entrada exata, Stop Loss, Alvo e Ponto de Saída com anotações visuais.
"""

from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go

SPREADS = {"NAS100": 1.5, "US30": 2.0}
SLIPPAGES = {"NAS100": 1.0, "US30": 1.0}


def run_smc_inspector(symbol: str = "NAS100") -> tuple[pd.DataFrame, list[dict]]:
    """Gera trades da estratégia SMC Macro H1 + Micro CHoCH M15 de forma causal e rápida."""
    p = Path(f"data/{symbol}_M1_dukascopy.parquet")
    df_m1 = pd.read_parquet(p)

    df_m15 = df_m1.resample("15min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna()

    df_h1 = df_m1.resample("1h").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna()

    # MME 8 e MME 20 causais no M15
    df_m15["mme8"] = df_m15["close"].shift(1).ewm(span=8, adjust=False).mean()
    df_m15["mme20"] = df_m15["close"].shift(1).ewm(span=20, adjust=False).mean()

    # Pivôs H1 causais (k=2)
    highs_h1 = df_h1["high"].to_numpy(dtype=float)
    lows_h1 = df_h1["low"].to_numpy(dtype=float)
    ts_h1 = df_h1.index

    pivots_h1 = []
    for i in range(2, len(df_h1) - 2):
        if highs_h1[i] > highs_h1[i-1] and highs_h1[i] > highs_h1[i-2] and highs_h1[i] > highs_h1[i+1] and highs_h1[i] > highs_h1[i+2]:
            pivots_h1.append({"kind": "high", "price": highs_h1[i], "time": ts_h1[i], "confirmed_time": ts_h1[i+2]})
        if lows_h1[i] < lows_h1[i-1] and lows_h1[i] < lows_h1[i-2] and lows_h1[i] < lows_h1[i+1] and lows_h1[i] < lows_h1[i+2]:
            pivots_h1.append({"kind": "low", "price": lows_h1[i], "time": ts_h1[i], "confirmed_time": ts_h1[i+2]})

    # Pivôs M15 causais (k=2)
    highs_m15 = df_m15["high"].to_numpy(dtype=float)
    lows_m15 = df_m15["low"].to_numpy(dtype=float)
    opens_m15 = df_m15["open"].to_numpy(dtype=float)
    closes_m15 = df_m15["close"].to_numpy(dtype=float)
    ts_m15 = df_m15.index

    pivots_m15 = []
    for i in range(2, len(df_m15) - 2):
        if highs_m15[i] > highs_m15[i-1] and highs_m15[i] > highs_m15[i-2] and highs_m15[i] > highs_m15[i+1] and highs_m15[i] > highs_m15[i+2]:
            pivots_m15.append({"kind": "high", "price": highs_m15[i], "time": ts_m15[i], "confirmed_time": ts_m15[i+2]})
        if lows_m15[i] < lows_m15[i-1] and lows_m15[i] < lows_m15[i-2] and lows_m15[i] < lows_m15[i+1] and lows_m15[i] < lows_m15[i+2]:
            pivots_m15.append({"kind": "low", "price": lows_m15[i], "time": ts_m15[i], "confirmed_time": ts_m15[i+2]})

    spread = SPREADS[symbol]
    slip = SLIPPAGES[symbol]

    p_h1_idx = 0
    num_p_h1 = len(pivots_h1)
    last_high_h1 = None
    last_low_h1 = None

    p_m15_idx = 0
    num_p_m15 = len(pivots_m15)
    last_micro_high = None
    last_micro_low = None

    trades = []
    open_pos = None

    for i in range(50, len(df_m15) - 1):
        cur_t = ts_m15[i]

        while p_h1_idx < num_p_h1 and pivots_h1[p_h1_idx]["confirmed_time"] <= cur_t:
            p = pivots_h1[p_h1_idx]
            if p["kind"] == "high":
                last_high_h1 = p
            else:
                last_low_h1 = p
            p_h1_idx += 1

        while p_m15_idx < num_p_m15 and pivots_m15[p_m15_idx]["confirmed_time"] <= cur_t:
            p = pivots_m15[p_m15_idx]
            if p["kind"] == "high":
                last_micro_high = p
            else:
                last_micro_low = p
            p_m15_idx += 1

        # 1. Gestão
        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_sl = lows_m15[i] <= pos["stop_price"] if d == 1 else highs_m15[i] + spread >= pos["stop_price"]
            hit_tp = highs_m15[i] >= pos["target_price"] if d == 1 else lows_m15[i] <= pos["target_price"]

            if hit_sl:
                exit_p = min(pos["stop_price"], opens_m15[i]) - slip if d == 1 else max(pos["stop_price"], opens_m15[i] + spread) + slip
                r = (exit_p - pos["entry_price"]) / pos["risk"] if d == 1 else (pos["entry_price"] - exit_p) / pos["risk"]
                trades.append({
                    "trade_id": len(trades) + 1,
                    "symbol": symbol,
                    "strategy": "SMC_MACRO_H1_MICRO_M15",
                    "direction": pos["direction"],
                    "entry_time": pos["entry_time"],
                    "exit_time": cur_t,
                    "entry_idx": pos["entry_idx"],
                    "exit_idx": i,
                    "entry_price": pos["entry_price"],
                    "stop_price": pos["stop_price"],
                    "target_price": pos["target_price"],
                    "exit_price": exit_p,
                    "exit_reason": "STOP_LOSS",
                    "risk_pts": round(pos["risk"], 1),
                    "r_multiple": round(float(r), 2),
                    "win": bool(r > 0),
                    "fibo_618": pos.get("fibo_618", 0.0),
                    "fibo_786": pos.get("fibo_786", 0.0),
                })
                open_pos = None
                continue

            elif hit_tp:
                exit_p = pos["target_price"]
                r = (exit_p - pos["entry_price"]) / pos["risk"] if d == 1 else (pos["entry_price"] - exit_p) / pos["risk"]
                trades.append({
                    "trade_id": len(trades) + 1,
                    "symbol": symbol,
                    "strategy": "SMC_MACRO_H1_MICRO_M15",
                    "direction": pos["direction"],
                    "entry_time": pos["entry_time"],
                    "exit_time": cur_t,
                    "entry_idx": pos["entry_idx"],
                    "exit_idx": i,
                    "entry_price": pos["entry_price"],
                    "stop_price": pos["stop_price"],
                    "target_price": pos["target_price"],
                    "exit_price": exit_p,
                    "exit_reason": "TAKE_PROFIT",
                    "risk_pts": round(pos["risk"], 1),
                    "r_multiple": round(float(r), 2),
                    "win": bool(r > 0),
                    "fibo_618": pos.get("fibo_618", 0.0),
                    "fibo_786": pos.get("fibo_786", 0.0),
                })
                open_pos = None
                continue

        # 2. Setup
        if open_pos is None and last_high_h1 and last_low_h1 and last_micro_high and last_micro_low:
            is_macro_bull = last_high_h1["time"] > last_low_h1["time"] and last_high_h1["price"] > last_low_h1["price"]
            is_macro_bear = last_low_h1["time"] > last_high_h1["time"] and last_low_h1["price"] < last_high_h1["price"]

            if is_macro_bull:
                p_low = last_low_h1["price"]
                p_high = last_high_h1["price"]
                rng = p_high - p_low
                fibo_618 = p_high - (0.618 * rng)
                fibo_786 = p_high - (0.786 * rng)

                in_poi = (lows_m15[i - 1] <= fibo_618) and (closes_m15[i - 1] >= fibo_786)
                micro_valid = (last_micro_high["time"] > last_high_h1["time"]) and (last_micro_low["time"] > last_high_h1["time"])

                if in_poi and micro_valid:
                    choch = (closes_m15[i - 1] > last_micro_high["price"]) and (closes_m15[i - 2] <= last_micro_high["price"])
                    if choch:
                        entry_p = opens_m15[i] + spread + slip
                        stop_p = last_micro_low["price"] - slip
                        risk = entry_p - stop_p
                        if risk > spread * 3 and risk < 200:
                            target_p = p_high  # Extremo Macro
                            if (target_p - entry_p) / risk >= 1.5:
                                open_pos = {
                                    "direction": "long", "entry_time": cur_t, "entry_idx": i,
                                    "entry_price": entry_p, "stop_price": stop_p, "target_price": target_p,
                                    "risk": risk, "fibo_618": fibo_618, "fibo_786": fibo_786
                                }
                                if lows_m15[i] <= stop_p:
                                    exit_p = min(stop_p, opens_m15[i]) - slip
                                    r = (exit_p - entry_p) / risk
                                    trades.append({
                                        "trade_id": len(trades) + 1, "symbol": symbol, "strategy": "SMC_MACRO_H1_MICRO_M15",
                                        "direction": "long", "entry_time": cur_t, "exit_time": cur_t,
                                        "entry_idx": i, "exit_idx": i, "entry_price": entry_p,
                                        "stop_price": stop_p, "target_price": target_p, "exit_price": exit_p,
                                        "exit_reason": "STOP_ENTRY_BAR", "risk_pts": round(risk, 1),
                                        "r_multiple": round(float(r), 2), "win": False,
                                        "fibo_618": fibo_618, "fibo_786": fibo_786
                                    })
                                    open_pos = None

            elif is_macro_bear:
                p_low = last_low_h1["price"]
                p_high = last_high_h1["price"]
                rng = p_high - p_low
                fibo_618 = p_low + (0.618 * rng)
                fibo_786 = p_low + (0.786 * rng)

                in_poi = (highs_m15[i - 1] >= fibo_618) and (closes_m15[i - 1] <= fibo_786)
                micro_valid = (last_micro_low["time"] > last_low_h1["time"]) and (last_micro_high["time"] > last_low_h1["time"])

                if in_poi and micro_valid:
                    choch = (closes_m15[i - 1] < last_micro_low["price"]) and (closes_m15[i - 2] >= last_micro_low["price"])
                    if choch:
                        entry_p = opens_m15[i] - slip
                        stop_p = last_micro_high["price"] + spread + slip
                        risk = stop_p - entry_p
                        if risk > spread * 3 and risk < 200:
                            target_p = p_low
                            if (entry_p - target_p) / risk >= 1.5:
                                open_pos = {
                                    "direction": "short", "entry_time": cur_t, "entry_idx": i,
                                    "entry_price": entry_p, "stop_price": stop_p, "target_price": target_p,
                                    "risk": risk, "fibo_618": fibo_618, "fibo_786": fibo_786
                                }
                                if highs_m15[i] + spread >= stop_p:
                                    exit_p = max(stop_p, opens_m15[i] + spread) + slip
                                    r = (entry_p - exit_p) / risk
                                    trades.append({
                                        "trade_id": len(trades) + 1, "symbol": symbol, "strategy": "SMC_MACRO_H1_MICRO_M15",
                                        "direction": "short", "entry_time": cur_t, "exit_time": cur_t,
                                        "entry_idx": i, "exit_idx": i, "entry_price": entry_p,
                                        "stop_price": stop_p, "target_price": target_p, "exit_price": exit_p,
                                        "exit_reason": "STOP_ENTRY_BAR", "risk_pts": round(risk, 1),
                                        "r_multiple": round(float(r), 2), "win": False,
                                        "fibo_618": fibo_618, "fibo_786": fibo_786
                                    })
                                    open_pos = None

    return df_m15, trades


def plot_interactive_trade(df: pd.DataFrame, trade: dict, out_file: Path):
    """Gera visualização gráfica profissional e interativa via Plotly para auditoria candle a candle."""
    e_idx = trade["entry_idx"]
    x_idx = trade["exit_idx"]

    # Visualizar 35 candles antes e 20 depois
    start_idx = max(0, e_idx - 35)
    end_idx = min(len(df), x_idx + 25)
    sub = df.iloc[start_idx:end_idx]

    fig = go.Figure()

    # Candles
    fig.add_trace(go.Candlestick(
        x=sub.index, open=sub["open"], high=sub["high"], low=sub["low"], close=sub["close"],
        name="Candles",
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
    ))

    # Médias
    if "mme8" in sub.columns:
        fig.add_trace(go.Scatter(x=sub.index, y=sub["mme8"], name="MME 8", line=dict(color="#f39c12", width=1.5)))
    if "mme20" in sub.columns:
        fig.add_trace(go.Scatter(x=sub.index, y=sub["mme20"], name="MME 20", line=dict(color="#2980b9", width=1.5)))

    # Fibo POI (se houver)
    if trade.get("fibo_618", 0) > 0 and trade.get("fibo_786", 0) > 0:
        y0 = min(trade["fibo_618"], trade["fibo_786"])
        y1 = max(trade["fibo_618"], trade["fibo_786"])
        fig.add_hrect(
            y0=y0, y1=y1, fillcolor="#f1c40f", opacity=0.15,
            layer="below", line_width=1,
            annotation_text="POI Fibo (61.8% - 78.6%)", annotation_position="top left"
        )

    # Níveis Operacionais
    t_in = trade["entry_time"]
    t_out = trade["exit_time"]

    fig.add_shape(type="line", x0=t_in, y0=trade["entry_price"], x1=t_out, y1=trade["entry_price"], line=dict(color="#27ae60", width=2, dash="dash"))
    fig.add_shape(type="line", x0=t_in, y0=trade["stop_price"], x1=t_out, y1=trade["stop_price"], line=dict(color="#c0392b", width=2, dash="dash"))
    fig.add_shape(type="line", x0=t_in, y0=trade["target_price"], x1=t_out, y1=trade["target_price"], line=dict(color="#2980b9", width=2, dash="dash"))

    res_color = "#27ae60" if trade["win"] else "#c0392b"
    res_label = f"+{trade['r_multiple']}R (WIN)" if trade["win"] else f"{trade['r_multiple']}R (LOSS)"

    fig.add_annotation(
        x=t_in, y=trade["entry_price"], text=f"<b>ENTRADA {trade['direction'].upper()}</b><br>{trade['entry_price']:.1f}",
        showarrow=True, arrowhead=2, arrowcolor="#27ae60", bgcolor="#ffffff", bordercolor="#27ae60"
    )
    fig.add_annotation(
        x=t_out, y=trade["exit_price"], text=f"<b>SAÍDA: {trade['exit_reason']}</b><br>{res_label}<br>{trade['exit_price']:.1f}",
        showarrow=True, arrowhead=2, arrowcolor=res_color, bgcolor="#ffffff", bordercolor=res_color
    )

    fig.update_layout(
        title=(
            f"<b>Trade #{trade['trade_id']} | {trade['strategy']} | {trade['symbol']} {trade['direction'].upper()}</b><br>"
            f"Resultado: <span style='color:{res_color}'>{res_label}</span> ({trade['exit_reason']}) | "
            f"Risco: {trade['risk_pts']} pts | Entrada: {t_in.strftime('%Y-%m-%d %H:%M')} | Saída: {t_out.strftime('%Y-%m-%d %H:%M')}"
        ),
        xaxis_title="Data / Hora", yaxis_title="Preço",
        template="plotly_dark", xaxis_rangeslider_visible=False,
        height=680, margin=dict(l=50, r=50, t=90, b=50)
    )

    out_file.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(out_file))


def run_fibo_mm8_inspector(symbol: str = "NAS100") -> tuple[pd.DataFrame, list[dict]]:
    """Gera trades da estratégia Fibo + Trap na MME 8 com condução de média no M15."""
    p = Path(f"data/{symbol}_M1_dukascopy.parquet")
    df_m1 = pd.read_parquet(p)
    df_m15 = df_m1.resample("15min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna()

    opens = df_m15["open"].to_numpy(dtype=float)
    highs = df_m15["high"].to_numpy(dtype=float)
    lows = df_m15["low"].to_numpy(dtype=float)
    closes = df_m15["close"].to_numpy(dtype=float)
    ts = df_m15.index

    # Indicadores causais em i-1
    df_m15["mme8"] = df_m15["close"].shift(1).ewm(span=8, adjust=False).mean()
    df_m15["mme20"] = df_m15["close"].shift(1).ewm(span=20, adjust=False).mean()
    df_m15["mme80"] = df_m15["close"].shift(1).ewm(span=80, adjust=False).mean()
    df_m15["mme200"] = df_m15["close"].shift(1).ewm(span=200, adjust=False).mean()

    mme8 = df_m15["mme8"].to_numpy(dtype=float)
    mme80 = df_m15["mme80"].to_numpy(dtype=float)
    mme200 = df_m15["mme200"].to_numpy(dtype=float)

    spread = SPREADS[symbol]
    slip = SLIPPAGES[symbol]

    trades = []
    open_pos = None

    for i in range(210, len(df_m15) - 1):
        cur_t = ts[i]

        # 1. Gestão de posição aberta
        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_sl = lows[i] <= pos["stop_price"] if d == 1 else highs[i] + spread >= pos["stop_price"]
            exit_by_ma = (closes[i - 1] < mme8[i - 1]) if d == 1 else (closes[i - 1] > mme8[i - 1])

            if hit_sl:
                exit_p = min(pos["stop_price"], opens[i]) - slip if d == 1 else max(pos["stop_price"], opens[i] + spread) + slip
                r = (exit_p - pos["entry_price"]) / pos["risk"] if d == 1 else (pos["entry_price"] - exit_p) / pos["risk"]
                trades.append({
                    "trade_id": len(trades) + 1,
                    "symbol": symbol,
                    "strategy": "FIBO_TRAP_MME8",
                    "direction": pos["direction"],
                    "entry_time": pos["entry_time"],
                    "exit_time": cur_t,
                    "entry_idx": pos["entry_idx"],
                    "exit_idx": i,
                    "entry_price": pos["entry_price"],
                    "stop_price": pos["stop_price"],
                    "target_price": pos["target_price"],
                    "exit_price": exit_p,
                    "exit_reason": "STOP_LOSS",
                    "risk_pts": round(pos["risk"], 1),
                    "r_multiple": round(float(r), 2),
                    "win": bool(r > 0),
                    "fibo_618": pos.get("fibo_618", 0.0),
                    "fibo_786": pos.get("fibo_786", 0.0),
                })
                open_pos = None
                continue

            elif exit_by_ma and i > pos["entry_idx"]:
                exit_p = opens[i] - slip if d == 1 else opens[i] + spread + slip
                r = (exit_p - pos["entry_price"]) / pos["risk"] if d == 1 else (pos["entry_price"] - exit_p) / pos["risk"]
                trades.append({
                    "trade_id": len(trades) + 1,
                    "symbol": symbol,
                    "strategy": "FIBO_TRAP_MME8",
                    "direction": pos["direction"],
                    "entry_time": pos["entry_time"],
                    "exit_time": cur_t,
                    "entry_idx": pos["entry_idx"],
                    "exit_idx": i,
                    "entry_price": pos["entry_price"],
                    "stop_price": pos["stop_price"],
                    "target_price": pos["target_price"],
                    "exit_price": exit_p,
                    "exit_reason": "TRAILING_MME8",
                    "risk_pts": round(pos["risk"], 1),
                    "r_multiple": round(float(r), 2),
                    "win": bool(r > 0),
                    "fibo_618": pos.get("fibo_618", 0.0),
                    "fibo_786": pos.get("fibo_786", 0.0),
                })
                open_pos = None
                continue

        # 2. Setup: Tendência alinhada + Trap na MME 8 + Retração de Fibo
        if open_pos is None:
            trend_bull = closes[i - 1] > mme80[i - 1] > mme200[i - 1]
            trend_bear = closes[i - 1] < mme80[i - 1] < mme200[i - 1]

            # Fibo das últimas 20 barras
            recent_high = np.max(highs[i - 20 : i - 1])
            recent_low = np.min(lows[i - 20 : i - 1])
            rng = recent_high - recent_low
            if rng < spread * 6 or rng > 300:
                continue

            if trend_bull:
                fibo_618 = recent_high - (0.618 * rng)
                fibo_786 = recent_high - (0.786 * rng)
                # Trap na MME 8 dentro da zona OTE de Fibo
                in_fibo = lows[i - 1] <= fibo_618 and closes[i - 1] >= fibo_786
                trap_mme8 = lows[i - 1] < lows[i - 2] and closes[i - 1] > mme8[i - 1] and closes[i - 1] > opens[i - 1]

                if in_fibo and trap_mme8:
                    trig_p = highs[i - 1]
                    if highs[i] >= trig_p:
                        entry_p = max(trig_p, opens[i]) + spread + slip
                        stop_p = lows[i - 1] - slip
                        risk = entry_p - stop_p
                        if risk > spread * 3 and risk < 150:
                            target_p = recent_high + (0.618 * rng)  # Expansão de Fibo 161.8%
                            open_pos = {
                                "direction": "long", "entry_time": cur_t, "entry_idx": i,
                                "entry_price": entry_p, "stop_price": stop_p, "target_price": target_p,
                                "risk": risk, "fibo_618": fibo_618, "fibo_786": fibo_786
                            }
                            if lows[i] <= stop_p:
                                exit_p = min(stop_p, opens[i]) - slip
                                r = (exit_p - entry_p) / risk
                                trades.append({
                                    "trade_id": len(trades) + 1, "symbol": symbol, "strategy": "FIBO_TRAP_MME8",
                                    "direction": "long", "entry_time": cur_t, "exit_time": cur_t,
                                    "entry_idx": i, "exit_idx": i, "entry_price": entry_p,
                                    "stop_price": stop_p, "target_price": target_p, "exit_price": exit_p,
                                    "exit_reason": "STOP_ENTRY_BAR", "risk_pts": round(risk, 1),
                                    "r_multiple": round(float(r), 2), "win": False,
                                    "fibo_618": fibo_618, "fibo_786": fibo_786
                                })
                                open_pos = None

            elif trend_bear:
                fibo_618 = recent_low + (0.618 * rng)
                fibo_786 = recent_low + (0.786 * rng)
                in_fibo = highs[i - 1] >= fibo_618 and closes[i - 1] <= fibo_786
                trap_mme8 = highs[i - 1] > highs[i - 2] and closes[i - 1] < mme8[i - 1] and closes[i - 1] < opens[i - 1]

                if in_fibo and trap_mme8:
                    trig_p = lows[i - 1]
                    if lows[i] <= trig_p:
                        entry_p = min(trig_p, opens[i]) - slip
                        stop_p = highs[i - 1] + spread + slip
                        risk = stop_p - entry_p
                        if risk > spread * 3 and risk < 150:
                            target_p = recent_low - (0.618 * rng)
                            open_pos = {
                                "direction": "short", "entry_time": cur_t, "entry_idx": i,
                                "entry_price": entry_p, "stop_price": stop_p, "target_price": target_p,
                                "risk": risk, "fibo_618": fibo_618, "fibo_786": fibo_786
                            }
                            if highs[i] + spread >= stop_p:
                                exit_p = max(stop_p, opens[i] + spread) + slip
                                r = (entry_p - exit_p) / risk
                                trades.append({
                                    "trade_id": len(trades) + 1, "symbol": symbol, "strategy": "FIBO_TRAP_MME8",
                                    "direction": "short", "entry_time": cur_t, "exit_time": cur_t,
                                    "entry_idx": i, "exit_idx": i, "entry_price": entry_p,
                                    "stop_price": stop_p, "target_price": target_p, "exit_price": exit_p,
                                    "exit_reason": "STOP_ENTRY_BAR", "risk_pts": round(risk, 1),
                                    "r_multiple": round(float(r), 2), "win": False,
                                    "fibo_618": fibo_618, "fibo_786": fibo_786
                                })
                                open_pos = None

    return df_m15, trades


def main():
    out_dir = Path("out/trade_inspector")
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=====================================================================")
    print("FERRAMENTA DE AUDITORIA VISUAL DE TRADES (SMC & FIBO + MM8)")
    print("=====================================================================")

    # 1. Estratégia SMC Macro H1 + Micro CHoCH M15
    print("\n1. Processando SMC Macro H1 + Micro CHoCH M15 (NAS100)...")
    df_m15_smc, trades_smc = run_smc_inspector("NAS100")
    df_csv_smc = pd.DataFrame(trades_smc)
    csv_file_smc = out_dir / "trades_smc_macro_h1_micro_nas100.csv"
    df_csv_smc.to_csv(csv_file_smc, index=False)
    print(f"   -> {len(trades_smc)} trades salvos em: {csv_file_smc}")

    wins_smc = [t for t in trades_smc if t["win"]]
    losses_smc = [t for t in trades_smc if not t["win"]]
    sample_smc = wins_smc[:2] + losses_smc[:2]

    for t in sample_smc:
        fname = f"smc_trade_{t['trade_id']:03d}_{'WIN' if t['win'] else 'LOSS'}_{t['exit_reason']}.html"
        html_file = out_dir / fname
        plot_interactive_trade(df_m15_smc, t, html_file)
        print(f"   -> Gráfico interativo: {html_file.name}")

    # 2. Estratégia Fibo OTE + Trap MME 8 / Condução
    print("\n2. Processando Fibo OTE + Trap MME 8 com Condução (NAS100)...")
    df_m15_fibo, trades_fibo = run_fibo_mm8_inspector("NAS100")
    df_csv_fibo = pd.DataFrame(trades_fibo)
    csv_file_fibo = out_dir / "trades_fibo_trap_mme8_nas100.csv"
    df_csv_fibo.to_csv(csv_file_fibo, index=False)
    print(f"   -> {len(trades_fibo)} trades salvos em: {csv_file_fibo}")

    wins_fibo = [t for t in trades_fibo if t["win"]]
    losses_fibo = [t for t in trades_fibo if not t["win"]]
    sample_fibo = wins_fibo[:2] + losses_fibo[:2]

    for t in sample_fibo:
        fname = f"fibo_mm8_trade_{t['trade_id']:03d}_{'WIN' if t['win'] else 'LOSS'}_{t['exit_reason']}.html"
        html_file = out_dir / fname
        plot_interactive_trade(df_m15_fibo, t, html_file)
        print(f"   -> Gráfico interativo: {html_file.name}")

    print("\nAuditoria visual concluída com sucesso!")
    print(f"Todos os arquivos gerados estão na pasta: {out_dir.resolve()}")


if __name__ == "__main__":
    main()

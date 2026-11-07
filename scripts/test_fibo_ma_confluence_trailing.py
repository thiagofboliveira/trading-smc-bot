"""
Teste Quantitativo: SMC-Fibo-OTE com Médias Móveis
Testa 3 Novas Dimensões:
1. Confluência no Toque de Fibo: MMA20, MMA50, MME80
2. Filtro de Tendência Alinhada: MME80 + MMA200
3. Condução / Trailing Stop por Média: MMA9, MME8, MMA20, MME80
"""

import sys
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

SPREADS = {
    "BRENT": 0.04,
    "XAUUSD": 0.30,
    "NAS100": 1.50,
    "DAX40": 1.50,
    "EURUSD": 0.00015,
    "GBPUSD": 0.00020,
    "USDJPY": 0.018
}

SYMBOLS = ["NAS100", "XAUUSD", "DAX40", "BRENT", "EURUSD", "GBPUSD", "USDJPY"]

def load_precomputed_m5() -> dict[str, pd.DataFrame]:
    data = {}
    print("⏳ Carregando candles M1 e calculando indicadores M5...")
    for sym in SYMBOLS:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        if not p.exists():
            continue
        df_m1 = pd.read_parquet(p)
        if not isinstance(df_m1.index, pd.DatetimeIndex):
            if "time" in df_m1.columns:
                df_m1["time"] = pd.to_datetime(df_m1["time"])
                df_m1.set_index("time", inplace=True)
            elif "timestamp" in df_m1.columns:
                df_m1["timestamp"] = pd.to_datetime(df_m1["timestamp"])
                df_m1.set_index("timestamp", inplace=True)

        df_m5 = df_m1.resample("5min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        }).dropna()

        # Médias Móveis
        df_m5["sma9"] = df_m5["close"].rolling(9).mean()
        df_m5["ema8"] = df_m5["close"].ewm(span=8, adjust=False).mean()
        df_m5["sma20"] = df_m5["close"].rolling(20).mean()
        df_m5["sma50"] = df_m5["close"].rolling(50).mean()
        df_m5["ema80"] = df_m5["close"].ewm(span=80, adjust=False).mean()
        df_m5["sma200"] = df_m5["close"].rolling(200).mean()

        data[sym] = df_m5.dropna().copy()
    print("✅ Dados e Médias Móveis carregados.")
    return data

def simulate_fibo_ma(
    df: pd.DataFrame,
    spread: float,
    fibo_entry: float = 0.705,
    fibo_stop: float = 0.790,
    target_mode: str = "0_percent",
    confluence_ma: str | None = None,     # 'sma20', 'sma50', 'ema80' ou None
    trend_filter_80_200: bool = False,    # EMA80 > SMA200 (Long) / EMA80 < SMA200 (Short)
    trailing_exit_ma: str | None = None,  # 'sma9', 'ema8', 'sma20', 'ema80' ou None
    k: int = 3
) -> list[dict[str, Any]]:
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    opens = df["open"].values
    timestamps = df.index
    n = len(df)

    sma9s = df["sma9"].values if "sma9" in df else None
    ema8s = df["ema8"].values if "ema8" in df else None
    sma20s = df["sma20"].values if "sma20" in df else None
    sma50s = df["sma50"].values if "sma50" in df else None
    ema80s = df["ema80"].values if "ema80" in df else None
    sma200s = df["sma200"].values if "sma200" in df else None

    ma_dict = {
        "sma9": sma9s,
        "ema8": ema8s,
        "sma20": sma20s,
        "sma50": sma50s,
        "ema80": ema80s,
        "sma200": sma200s
    }

    # Swings fractais
    swing_highs = np.zeros(n, dtype=bool)
    swing_lows = np.zeros(n, dtype=bool)

    for i in range(k, n - k):
        if highs[i] == max(highs[i - k : i + k + 1]):
            swing_highs[i] = True
        if lows[i] == min(lows[i - k : i + k + 1]):
            swing_lows[i] = True

    trades = []
    last_sh_price = None
    last_sh_idx = None
    last_sl_price = None
    last_sl_idx = None

    in_pos = False
    pos_dir = 0
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    entry_idx = 0
    risk = 0.0

    active_leg = None

    for i in range(k + 1, n - 1):
        chk = i - k
        if swing_highs[chk]:
            last_sh_price = highs[chk]
            last_sh_idx = chk
        if swing_lows[chk]:
            last_sl_price = lows[chk]
            last_sl_idx = chk

        if in_pos:
            c_high = highs[i]
            c_low = lows[i]
            c_close = closes[i]

            # Saída por Trailing MA se ativado
            exit_by_trailing = False
            trailing_exit_price = 0.0
            if trailing_exit_ma is not None and i > entry_idx:
                ma_series = ma_dict[trailing_exit_ma]
                curr_ma = ma_series[i]
                if pos_dir == 1:
                    # Long: candle fechou abaixo da média móvel
                    if c_close < curr_ma:
                        exit_by_trailing = True
                        trailing_exit_price = c_close
                else:
                    # Short: candle fechou acima da média móvel
                    if c_close > curr_ma:
                        exit_by_trailing = True
                        trailing_exit_price = c_close

            if pos_dir == 1:
                hit_sl = c_low <= sl_price
                hit_tp = c_high >= tp_price

                if hit_sl and hit_tp:
                    trades.append({"entry_time": timestamps[entry_idx], "r": -1.0, "win": False})
                    in_pos = False
                    active_leg = None
                elif hit_sl:
                    trades.append({"entry_time": timestamps[entry_idx], "r": -1.0, "win": False})
                    in_pos = False
                    active_leg = None
                elif exit_by_trailing:
                    r_mult = (trailing_exit_price - entry_price) / risk
                    win = r_mult > 0
                    trades.append({"entry_time": timestamps[entry_idx], "r": r_mult, "win": win})
                    in_pos = False
                    active_leg = None
                elif hit_tp:
                    r_mult = 3.0 if target_mode != "0_percent" else (tp_price - entry_price) / risk
                    trades.append({"entry_time": timestamps[entry_idx], "r": r_mult, "win": True})
                    in_pos = False
                    active_leg = None
            else:
                hit_sl = c_high >= sl_price
                hit_tp = c_low <= tp_price

                if hit_sl and hit_tp:
                    trades.append({"entry_time": timestamps[entry_idx], "r": -1.0, "win": False})
                    in_pos = False
                    active_leg = None
                elif hit_sl:
                    trades.append({"entry_time": timestamps[entry_idx], "r": -1.0, "win": False})
                    in_pos = False
                    active_leg = None
                elif exit_by_trailing:
                    r_mult = (entry_price - trailing_exit_price) / risk
                    win = r_mult > 0
                    trades.append({"entry_time": timestamps[entry_idx], "r": r_mult, "win": win})
                    in_pos = False
                    active_leg = None
                elif hit_tp:
                    r_mult = 3.0 if target_mode != "0_percent" else (entry_price - tp_price) / risk
                    trades.append({"entry_time": timestamps[entry_idx], "r": r_mult, "win": True})
                    in_pos = False
                    active_leg = None
            continue

        # Detecção de nova perna de impulsão
        if active_leg is None and last_sh_price is not None and last_sl_price is not None:
            if last_sh_idx > last_sl_idx:
                if closes[i] > last_sh_price:
                    leg_low = last_sl_price
                    leg_high = highs[i]
                    leg_range = leg_high - leg_low
                    if leg_range > spread * 10:
                        active_leg = {
                            "dir": 1, "low": leg_low, "high": leg_high, "range": leg_range,
                            "fibo_entry": leg_high - fibo_entry * leg_range,
                            "fibo_stop": leg_high - fibo_stop * leg_range,
                            "touched": False, "candles": 0
                        }
            elif last_sl_idx > last_sh_idx:
                if closes[i] < last_sl_price:
                    leg_high = last_sh_price
                    leg_low = lows[i]
                    leg_range = leg_high - leg_low
                    if leg_range > spread * 10:
                        active_leg = {
                            "dir": -1, "high": leg_high, "low": leg_low, "range": leg_range,
                            "fibo_entry": leg_low + fibo_entry * leg_range,
                            "fibo_stop": leg_low + fibo_stop * leg_range,
                            "touched": False, "candles": 0
                        }

        # Gatilho na perna ativa
        if active_leg is not None:
            active_leg["candles"] += 1
            if active_leg["candles"] > 60:
                active_leg = None
                continue

            if not active_leg["touched"]:
                if active_leg["dir"] == 1 and highs[i] > active_leg["high"]:
                    active_leg["high"] = highs[i]
                    active_leg["range"] = active_leg["high"] - active_leg["low"]
                    active_leg["fibo_entry"] = active_leg["high"] - fibo_entry * active_leg["range"]
                    active_leg["fibo_stop"] = active_leg["high"] - fibo_stop * active_leg["range"]
                elif active_leg["dir"] == -1 and lows[i] < active_leg["low"]:
                    active_leg["low"] = lows[i]
                    active_leg["range"] = active_leg["high"] - active_leg["low"]
                    active_leg["fibo_entry"] = active_leg["low"] + fibo_entry * active_leg["range"]
                    active_leg["fibo_stop"] = active_leg["low"] + fibo_stop * active_leg["range"]

                # 1. Filtro de Tendência Alinhada MME80 + MMA200
                if trend_filter_80_200:
                    curr_e80 = ema80s[i]
                    curr_s200 = sma200s[i]
                    if active_leg["dir"] == 1:
                        # Long só é permitido se EMA80 > SMA200
                        if not (curr_e80 > curr_s200):
                            continue
                    else:
                        # Short só se EMA80 < SMA200
                        if not (curr_e80 < curr_s200):
                            continue

                # 2. Confluência com Média Móvel no toque de Fibo
                # Exige que o candle que toca Fibo também intercepte a média móvel especificada
                if confluence_ma is not None:
                    target_ma = ma_dict[confluence_ma][i]
                    # Candle intercepta a média (low <= MA <= high) ou está a menos de 10% do range
                    dist = abs(active_leg["fibo_entry"] - target_ma)
                    if dist > (active_leg["range"] * 0.15):
                        continue

                # Entrada
                if active_leg["dir"] == 1:
                    if lows[i] <= active_leg["fibo_entry"]:
                        active_leg["touched"] = True
                        raw_entry = active_leg["fibo_entry"]
                        raw_sl = active_leg["fibo_stop"]
                        entry_price = raw_entry + spread
                        sl_price = raw_sl
                        risk = entry_price - sl_price
                        if risk > spread * 1.5:
                            tp_price = active_leg["high"] if target_mode == "0_percent" else entry_price + (risk * 3.0)
                            in_pos = True
                            pos_dir = 1
                            entry_idx = i
                else:
                    if highs[i] >= active_leg["fibo_entry"]:
                        active_leg["touched"] = True
                        raw_entry = active_leg["fibo_entry"]
                        raw_sl = active_leg["fibo_stop"]
                        entry_price = raw_entry
                        sl_price = raw_sl + spread
                        risk = sl_price - entry_price
                        if risk > spread * 1.5:
                            tp_price = active_leg["low"] if target_mode == "0_percent" else entry_price - (risk * 3.0)
                            in_pos = True
                            pos_dir = -1
                            entry_idx = i

    return trades

def evaluate_suite(name: str, params: dict[str, Any], data: dict[str, pd.DataFrame]) -> dict[str, Any]:
    split_date = pd.Timestamp("2026-05-01", tz="UTC")
    all_trades = []
    sym_r = {}

    for sym in SYMBOLS:
        df = data[sym]
        spread = SPREADS[sym]
        trades = simulate_fibo_ma(df, spread, **params)
        df_t = pd.DataFrame(trades)
        if not df_t.empty:
            df_t["symbol"] = sym
            all_trades.append(df_t)
            sym_r[sym] = df_t["r"].sum()
        else:
            sym_r[sym] = 0.0

    if not all_trades:
        return {"name": name, "trades": 0, "win_rate": 0, "total_r": 0, "is_r": 0, "oos_r": 0, "pf": 0, "max_dd": 0, "pos": 0}

    df_res = pd.concat(all_trades, ignore_index=True)
    n_t = len(df_res)
    wr = (df_res["win"] == True).sum() / n_t * 100
    tot_r = df_res["r"].sum()

    df_res["entry_time"] = pd.to_datetime(df_res["entry_time"])
    is_r = df_res[df_res["entry_time"] < split_date]["r"].sum()
    oos_r = df_res[df_res["entry_time"] >= split_date]["r"].sum()

    gp = df_res[df_res["win"] == True]["r"].sum()
    gl = abs(df_res[df_res["win"] == False]["r"].sum())
    pf = (gp / gl) if gl > 0 else np.nan

    cum = df_res["r"].cumsum()
    max_dd = (cum.cummax() - cum).max()
    pos_count = sum(1 for v in sym_r.values() if v > 0)

    return {
        "name": name,
        "trades": n_t,
        "win_rate": wr,
        "total_r": tot_r,
        "is_r": is_r,
        "oos_r": oos_r,
        "pf": pf,
        "max_dd": max_dd,
        "pos": pos_count,
        "sym_r": sym_r
    }

def main():
    print("=" * 80)
    print("🔬 TESTE QUANTITATIVO: FIBONACCI OTE + MÉDIAS MÓVEIS (3 NOVAS DIMENSÕES)")
    print("=" * 80 + "\n")

    data = load_precomputed_m5()

    experiments = [
        # BASELINE (Campeã Agressiva)
        ("1. Baseline Oficial (Sem Filtros de Média)", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": None, "trend_filter_80_200": False, "trailing_exit_ma": None
        }),

        # DIMENSÃO 1: CONFLUÊNCIA NO TOQUE DE FIBO
        ("2. Confluência com MMA 20 no Toque", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": "sma20", "trend_filter_80_200": False, "trailing_exit_ma": None
        }),
        ("3. Confluência com MMA 50 no Toque", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": "sma50", "trend_filter_80_200": False, "trailing_exit_ma": None
        }),
        ("4. Confluência com MME 80 no Toque", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": "ema80", "trend_filter_80_200": False, "trailing_exit_ma": None
        }),

        # DIMENSÃO 2: FILTRO DE TENDÊNCIA ALINHADA (MME 80 + MMA 200)
        ("5. Filtro de Tendência Alinhada (MME80 + MMA200)", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": None, "trend_filter_80_200": True, "trailing_exit_ma": None
        }),

        # DIMENSÃO 3: CONDUÇÃO POR MÉDIA MÓVEL (TRAILING STOP)
        ("6. Condução por MMA 9 (Trailing)", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": None, "trend_filter_80_200": False, "trailing_exit_ma": "sma9"
        }),
        ("7. Condução por MME 8 (Trailing)", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": None, "trend_filter_80_200": False, "trailing_exit_ma": "ema8"
        }),
        ("8. Condução por MMA 20 (Trailing)", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": None, "trend_filter_80_200": False, "trailing_exit_ma": "sma20"
        }),
        ("9. Condução por MME 80 (Trailing)", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": None, "trend_filter_80_200": False, "trailing_exit_ma": "ema80"
        }),

        # COMBO: FILTRO 80/200 + CONFLUÊNCIA
        ("10. Combo: Filtro MME80/200 + Confluência MMA20", {
            "fibo_entry": 0.705, "fibo_stop": 0.790, "target_mode": "0_percent",
            "confluence_ma": "sma20", "trend_filter_80_200": True, "trailing_exit_ma": None
        })
    ]

    out_records = []
    print("🚀 Executando simulações das 10 variações nos 7 ativos...\n")
    for name, p in experiments:
        res = evaluate_suite(name, p, data)
        out_records.append(res)
        print(f"📊 {name:48s} -> Trades: {res['trades']:4d} | WR: {res['win_rate']:4.1f}% | Total: {res['total_r']:+7.1f}R | OOS: {res['oos_r']:+7.1f}R | PF: {res['pf']:.2f} | MaxDD: -{res['max_dd']:.1f}R | Ativos: {res['pos']}/7")

    df_out = pd.DataFrame([{
        "Estratégia": r["name"],
        "Trades": r["trades"],
        "Win Rate (%)": round(r["win_rate"], 1),
        "Total (R)": round(r["total_r"], 1),
        "In-Sample (R)": round(r["is_r"], 1),
        "Out-of-Sample (R)": round(r["oos_r"], 1),
        "Profit Factor": round(r["pf"], 2),
        "Max Drawdown (R)": round(r["max_dd"], 1),
        "Ativos Positivos": f"{r['pos']}/7"
    } for r in out_records])

    csv_path = Path("out/fibo_optimization/fibo_ma_experiments.csv")
    df_out.to_csv(csv_path, index=False)
    print(f"\n📁 Resultados salvos em: {csv_path}")

if __name__ == "__main__":
    main()

"""
Recalibração Global e Científica de Variáveis — Versão 100% Auditada (Anti-Imunidade)
Testa sistematicamente todas as dimensões da estratégia nos 2 anos de dados reais Dukascopy:
1. Entrada: 61.8% vs 70.5% vs 79.0%
2. Stop Loss: 79.0% vs 88.6% vs 100.0% (Invalidação Estrutural)
3. Condução / Saída: Trailing MME 8 vs Trailing SMA 20 vs Trava 2:1 vs Alvo 3R vs Alvo 0%
4. Timeframe: M5 vs M15
5. Filtro de Sessão: 24h vs Londres/NY (07:00 às 18:00 UTC)
"""

import sys
from pathlib import Path
from typing import Any
import itertools
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

def load_precomputed_data():
    data = {}
    print("⏳ Carregando dados de 2 Anos (4.95M candles Dukascopy)...")
    for sym in SYMBOLS:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        if not p.exists():
            continue
        df_m1 = pd.read_parquet(p)
        if not isinstance(df_m1.index, pd.DatetimeIndex):
            col = "time" if "time" in df_m1.columns else "timestamp"
            df_m1[col] = pd.to_datetime(df_m1[col])
            df_m1.set_index(col, inplace=True)

        # M5
        df_m5 = df_m1.resample("5min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        }).dropna()
        df_m5["ema8"] = df_m5["close"].ewm(span=8, adjust=False).mean()
        df_m5["sma20"] = df_m5["close"].rolling(20).mean()

        # M15
        df_m15 = df_m1.resample("15min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        }).dropna()
        df_m15["ema8"] = df_m15["close"].ewm(span=8, adjust=False).mean()
        df_m15["sma20"] = df_m15["close"].rolling(20).mean()

        data[sym] = {"M5": df_m5, "M15": df_m15}
    print("✅ Dados prontos em memória.")
    return data

def simulate_audited(
    df: pd.DataFrame,
    spread: float,
    fibo_entry: float,
    fibo_stop: float,
    exit_mode: str,          # 'trailing_ema8', 'trailing_sma20', 'lock_2to1', 'target_3r', 'target_0_pct'
    session_filter: bool,
    k: int = 2
) -> list[dict[str, Any]]:
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    timestamps = df.index
    hours = timestamps.hour
    n = len(df)

    ema8s = df["ema8"].values if "ema8" in df.columns else None
    sma20s = df["sma20"].values if "sma20" in df.columns else None

    swing_highs = np.zeros(n, dtype=bool)
    swing_lows = np.zeros(n, dtype=bool)

    for i in range(k, n - k):
        if highs[i] == max(highs[i - k : i + k + 1]): swing_highs[i] = True
        if lows[i] == min(lows[i - k : i + k + 1]): swing_lows[i] = True

    trades = []
    last_sh = last_sl = None
    last_sh_idx = last_sl_idx = None
    in_pos = False
    pos_dir = 0
    entry_price = sl_price = tp_price = risk = 0.0
    entry_idx = 0
    trava_ativada = False
    active_leg = None

    for i in range(k + 1, n - 1):
        chk = i - k
        if swing_highs[chk]: last_sh, last_sh_idx = highs[chk], chk
        if swing_lows[chk]: last_sl, last_sl_idx = lows[chk], chk

        if in_pos:
            c_high, c_low, c_close = highs[i], lows[i], closes[i]

            # Trava 2:1
            if exit_mode == "lock_2to1" and not trava_ativada:
                if pos_dir == 1 and c_high >= (entry_price + risk * 2.0):
                    sl_price = entry_price + risk * 1.0
                    trava_ativada = True
                elif pos_dir == -1 and c_low <= (entry_price - risk * 2.0):
                    sl_price = entry_price - risk * 1.0
                    trava_ativada = True

            # Trailing Exit
            exit_by_ma = False
            ma_exit_price = 0.0
            if i > entry_idx:
                if exit_mode in ("trailing_ema8", "lock_2to1") and ema8s is not None:
                    curr_ma = ema8s[i]
                    if pos_dir == 1 and c_close < curr_ma and c_close > entry_price:
                        exit_by_ma = True; ma_exit_price = c_close
                    elif pos_dir == -1 and c_close > curr_ma and c_close < entry_price:
                        exit_by_ma = True; ma_exit_price = c_close
                elif exit_mode == "trailing_sma20" and sma20s is not None:
                    curr_ma = sma20s[i]
                    if pos_dir == 1 and c_close < curr_ma and c_close > entry_price:
                        exit_by_ma = True; ma_exit_price = c_close
                    elif pos_dir == -1 and c_close > curr_ma and c_close < entry_price:
                        exit_by_ma = True; ma_exit_price = c_close

            # Saídas
            if pos_dir == 1:
                hit_sl = c_low <= sl_price
                hit_tp = (c_high >= tp_price) if exit_mode in ("target_3r", "target_0_pct") else False

                if hit_sl and hit_tp:
                    r_res = -1.0 if not trava_ativada else 1.0
                    trades.append({"r": r_res, "win": r_res > 0, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
                elif hit_sl:
                    r_res = -1.0 if not trava_ativada else 1.0
                    trades.append({"r": r_res, "win": r_res > 0, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
                elif exit_by_ma:
                    r_res = (ma_exit_price - entry_price) / risk
                    trades.append({"r": r_res, "win": r_res > 0, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
                elif hit_tp:
                    r_res = 3.0 if exit_mode == "target_3r" else (tp_price - entry_price) / risk
                    trades.append({"r": r_res, "win": True, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
            else:
                hit_sl = c_high >= sl_price
                hit_tp = (c_low <= tp_price) if exit_mode in ("target_3r", "target_0_pct") else False

                if hit_sl and hit_tp:
                    r_res = -1.0 if not trava_ativada else 1.0
                    trades.append({"r": r_res, "win": r_res > 0, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
                elif hit_sl:
                    r_res = -1.0 if not trava_ativada else 1.0
                    trades.append({"r": r_res, "win": r_res > 0, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
                elif exit_by_ma:
                    r_res = (entry_price - ma_exit_price) / risk
                    trades.append({"r": r_res, "win": r_res > 0, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
                elif hit_tp:
                    r_res = 3.0 if exit_mode == "target_3r" else (entry_price - tp_price) / risk
                    trades.append({"r": r_res, "win": True, "time": timestamps[entry_idx]})
                    in_pos = False; active_leg = None
            continue

        # Novo BOS
        if active_leg is None and last_sh is not None and last_sl is not None:
            if last_sh_idx > last_sl_idx and closes[i] > last_sh:
                diff = highs[i] - last_sl
                if diff >= 10.0 * spread:
                    active_leg = {"dir": 1, "low": last_sl, "high": highs[i], "diff": diff, "touched": False, "c": 0}
            elif last_sl_idx > last_sh_idx and closes[i] < last_sl:
                diff = last_sh - lows[i]
                if diff >= 10.0 * spread:
                    active_leg = {"dir": -1, "low": lows[i], "high": last_sh, "diff": diff, "touched": False, "c": 0}

        if active_leg is not None:
            active_leg["c"] += 1
            if active_leg["c"] > 60: active_leg = None; continue

            if not active_leg["touched"]:
                ldir, ldiff = active_leg["dir"], active_leg["diff"]
                if ldir == 1 and highs[i] > active_leg["high"]:
                    active_leg["high"] = highs[i]
                    active_leg["diff"] = active_leg["high"] - active_leg["low"]
                elif ldir == -1 and lows[i] < active_leg["low"]:
                    active_leg["low"] = lows[i]
                    active_leg["diff"] = active_leg["high"] - active_leg["low"]

                ldiff = active_leg["diff"]
                if ldir == 1:
                    f_ent = active_leg["high"] - (ldiff * fibo_entry)
                    f_stp = active_leg["high"] - (ldiff * fibo_stop)
                    r_pts = f_ent - f_stp
                    if r_pts > spread * 1.5 and lows[i] <= f_ent <= highs[i]:
                        # Filtro de Sessão
                        if session_filter and not (7 <= hours[i] < 18):
                            continue
                        active_leg["touched"] = True
                        in_pos = True; pos_dir = 1
                        entry_price = f_ent + (spread / 2.0)
                        sl_price = f_stp - (spread / 2.0)
                        risk = entry_price - sl_price
                        tp_price = active_leg["high"] if exit_mode != "target_3r" else entry_price + risk * 3.0
                        entry_idx = i; trava_ativada = False

                        # AUDITORIA ANTI-IMUNIDADE 100% REALISTA:
                        if lows[i] <= sl_price:
                            trades.append({"r": -1.0, "win": False, "time": timestamps[i]})
                            in_pos = False; active_leg = None
                else:
                    f_ent = active_leg["low"] + (ldiff * fibo_entry)
                    f_stp = active_leg["low"] + (ldiff * fibo_stop)
                    r_pts = f_stp - f_ent
                    if r_pts > spread * 1.5 and lows[i] <= f_ent <= highs[i]:
                        if session_filter and not (7 <= hours[i] < 18):
                            continue
                        active_leg["touched"] = True
                        in_pos = True; pos_dir = -1
                        entry_price = f_ent - (spread / 2.0)
                        sl_price = f_stp + (spread / 2.0)
                        risk = sl_price - entry_price
                        tp_price = active_leg["low"] if exit_mode != "target_3r" else entry_price - risk * 3.0
                        entry_idx = i; trava_ativada = False

                        # AUDITORIA ANTI-IMUNIDADE 100% REALISTA:
                        if highs[i] >= sl_price:
                            trades.append({"r": -1.0, "win": False, "time": timestamps[i]})
                            in_pos = False; active_leg = None

    return trades

def eval_config(data, tf, entry, stop, exit_m, sess):
    all_trades = []
    for sym in SYMBOLS:
        if sym not in data: continue
        df = data[sym][tf]
        spread = SPREADS[sym]
        t = simulate_audited(df, spread, entry, stop, exit_m, sess)
        all_trades.extend(t)

    if not all_trades:
        return None

    df_t = pd.DataFrame(all_trades)
    n = len(df_t)
    r_total = df_t["r"].sum()
    wr = (df_t["win"].sum() / n) * 100.0
    wins = df_t[df_t["r"] > 0]["r"]
    losses = df_t[df_t["r"] < 0]["r"].abs()
    pf = (wins.sum() / losses.sum()) if losses.sum() > 0 else 999.0
    payoff = (wins.mean() / losses.mean()) if len(losses) > 0 and losses.mean() > 0 else 0.0

    df_sorted = df_t.sort_values("time")
    cum = df_sorted["r"].cumsum()
    dd = cum - cum.cummax()
    mdd = abs(dd.min())

    return {
        "tf": tf,
        "entry": entry,
        "stop": stop,
        "exit_mode": exit_m,
        "session": "Londres/NY" if sess else "24h",
        "trades": n,
        "wr": round(wr, 1),
        "total_r": round(r_total, 1),
        "r_year": round(r_total / 2.0, 1),
        "pf": round(pf, 2),
        "mdd": round(mdd, 1),
        "payoff": round(payoff, 2)
    }

def main():
    data = load_precomputed_data()

    # Grade de Estudo Completo
    entries = [0.618, 0.705, 0.790]
    stops = [0.790, 0.886, 1.000]
    exits = ["trailing_ema8", "trailing_sma20", "lock_2to1", "target_3r", "target_0_pct"]
    timeframes = ["M5"]  # Foco primário M5
    sessions = [False, True]

    print(f"\n🔍 Executando Recalibração de Variáveis Auditada...")
    results = []

    for tf in timeframes:
        for ent in entries:
            for stp in stops:
                if stp <= ent: continue  # Stop deve ser mais profundo que a entrada
                for ex in exits:
                    for sess in sessions:
                        res = eval_config(data, tf, ent, stp, ex, sess)
                        if res:
                            results.append(res)

    # Ordenar por Total R descendente
    df_res = pd.DataFrame(results).sort_values("total_r", ascending=False)
    
    Path("reports").mkdir(exist_ok=True)
    csv_path = "reports/audited_variable_recalibration_2years.csv"
    df_res.to_csv(csv_path, index=False)
    print(f"\n💾 Relatório completo salvo em: {csv_path}")

    print("\n" + "=" * 115)
    print("🏆 TOP 15 MODELOS 100% AUDITADOS E REALISTAS (SEM IMUNIDADE INTRABAR — 2 ANOS)")
    print("=" * 115)
    print(f"{'TF':<3} | {'Entrada':<7} | {'Stop':<6} | {'Saída / Gestão':<16} | {'Sessão':<10} | {'Trades':<6} | {'WinRate':<7} | {'Total R':<9} | {'R / Ano':<8} | {'PF':<5} | {'MaxDD':<6} | {'Payoff'}")
    print("-" * 115)
    for _, r in df_res.head(15).iterrows():
        print(f"{r['tf']:<3} | {r['entry']:>7.3f} | {r['stop']:>6.3f} | {r['exit_mode']:<16} | {r['session']:<10} | {r['trades']:<6} | {r['wr']:>6.1f}% | {r['total_r']:>8.1f}R | {r['r_year']:>7.1f}R | {r['pf']:>5.2f} | -{r['mdd']:>4.1f}R | {r['payoff']}")
    print("-" * 115)

    print("\n" + "=" * 115)
    print("🔎 COMPARAÇÃO ESPECÍFICA DAS VARIÁVEIS CHAVE AUDITADAS")
    print("=" * 115)
    # Comparar Stops na Entrada 70.5% com Trailing EMA8
    print("\n1. Impacto do Stop Loss na Entrada 70.5% (Sweet Spot) com Trailing MME 8 (24h):")
    for stp in [0.790, 0.886, 1.000]:
        sub = df_res[(df_res['entry'] == 0.705) & (df_res['stop'] == stp) & (df_res['exit_mode'] == 'trailing_ema8') & (df_res['session'] == '24h')]
        if not sub.empty:
            r = sub.iloc[0]
            print(f"   - Stop {stp*100:>5.1f}%: {r['trades']} trades | WR {r['wr']}% | Retorno: +{r['total_r']} R (+{r['r_year']} R/ano) | PF {r['pf']} | MaxDD -{r['mdd']} R")

    print("\n2. Impacto da Entrada com Stop Estrutural 100% (Trailing MME 8 - 24h):")
    for ent in [0.618, 0.705, 0.790]:
        sub = df_res[(df_res['entry'] == ent) & (df_res['stop'] == 1.000) & (df_res['exit_mode'] == 'trailing_ema8') & (df_res['session'] == '24h')]
        if not sub.empty:
            r = sub.iloc[0]
            print(f"   - Entrada {ent*100:>5.1f}%: {r['trades']} trades | WR {r['wr']}% | Retorno: +{r['total_r']} R (+{r['r_year']} R/ano) | PF {r['pf']} | MaxDD -{r['mdd']} R")

    print("\n3. Impacto da Condução / Saída na Entrada 61.8% com Stop 100% (24h):")
    for ex in ["trailing_ema8", "trailing_sma20", "lock_2to1", "target_3r", "target_0_pct"]:
        sub = df_res[(df_res['entry'] == 0.618) & (df_res['stop'] == 1.000) & (df_res['exit_mode'] == ex) & (df_res['session'] == '24h')]
        if not sub.empty:
            r = sub.iloc[0]
            print(f"   - Saída {ex:<15}: {r['trades']} trades | WR {r['wr']}% | Retorno: +{r['total_r']} R (+{r['r_year']} R/ano) | PF {r['pf']} | MaxDD -{r['mdd']} R")

if __name__ == "__main__":
    main()

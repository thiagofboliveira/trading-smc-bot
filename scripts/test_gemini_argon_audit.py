"""
Auditoria Realista das 3 Críticas do Gemini Argon
Compara:
1. Baseline Atual (com continue e trailing MA sem filtro de lucro)
2. Auditoria A: Intrabar Stop Loss (verifica se a própria vela de entrada fura o SL)
3. Auditoria B: Trailing MA apenas no lucro (c_close > entry_price, igual ao Profit NTSL)
4. Auditoria A+B: Modelo Trailing 100% Realista e Auditado
5. Auditoria A+B + Trava 2:1: Modelo Blindado 100% Realista e Auditado
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

SYMBOLS = ["XAUUSD", "NAS100", "DAX40", "BRENT", "EURUSD", "GBPUSD", "USDJPY"]

def load_all_candles():
    raw_m1 = {}
    for sym in SYMBOLS:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if not isinstance(df.index, pd.DatetimeIndex):
            col = "time" if "time" in df.columns else "timestamp"
            df[col] = pd.to_datetime(df[col])
            df.set_index(col, inplace=True)
        raw_m1[sym] = df
    return raw_m1

def run_audited_sim(
    raw_m1,
    check_intrabar_sl: bool = False,
    trailing_only_in_profit: bool = False,
    be_trigger_r: float | None = None,
    be_lock_r: float = 0.0,
    fibo_entry: float = 0.705,
    fibo_stop: float = 0.790,
    k: int = 3
):
    all_trades = []
    intrabar_stops = 0

    for sym in SYMBOLS:
        if sym not in raw_m1:
            continue
        df_m1 = raw_m1[sym]
        spread = SPREADS[sym]

        df = df_m1.resample("5min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        }).dropna()

        df["ema8"] = df["close"].ewm(span=8, adjust=False).mean()

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        timestamps = df.index
        ema8s = df["ema8"].values
        n = len(df)

        swing_highs = np.zeros(n, dtype=bool)
        swing_lows = np.zeros(n, dtype=bool)

        for i in range(k, n - k):
            if highs[i] == max(highs[i - k : i + k + 1]):
                swing_highs[i] = True
            if lows[i] == min(lows[i - k : i + k + 1]):
                swing_lows[i] = True

        last_sh = last_sl = None
        last_sh_idx = last_sl_idx = None
        in_pos = False
        pos_dir = 0
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0
        risk = 0.0
        entry_idx = 0
        be_activated = False
        active_leg = None

        for i in range(k + 1, n - 1):
            chk = i - k
            if swing_highs[chk]: last_sh, last_sh_idx = highs[chk], chk
            if swing_lows[chk]: last_sl, last_sl_idx = lows[chk], chk

            if in_pos:
                c_high = highs[i]
                c_low = lows[i]
                c_close = closes[i]

                # 1. Breakeven / Lock 2:1
                if be_trigger_r is not None and not be_activated:
                    if pos_dir == 1:
                        fav = c_high - entry_price
                        if fav >= (risk * be_trigger_r):
                            sl_price = entry_price + (risk * be_lock_r)
                            be_activated = True
                    else:
                        fav = entry_price - c_low
                        if fav >= (risk * be_trigger_r):
                            sl_price = entry_price - (risk * be_lock_r)
                            be_activated = True

                # 2. Trailing MA
                exit_trailing = False
                trailing_exit_price = 0.0
                if i > entry_idx:
                    curr_ema = ema8s[i]
                    if pos_dir == 1 and c_close < curr_ema:
                        if (not trailing_only_in_profit) or (c_close > entry_price):
                            exit_trailing = True
                            trailing_exit_price = c_close
                    elif pos_dir == -1 and c_close > curr_ema:
                        if (not trailing_only_in_profit) or (c_close < entry_price):
                            exit_trailing = True
                            trailing_exit_price = c_close

                # 3. Outcome
                if pos_dir == 1:
                    hit_sl = c_low <= sl_price
                    hit_tp = c_high >= tp_price
                    if hit_sl and hit_tp:
                        r_res = -1.0 if not be_activated else be_lock_r
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": r_res, "win": r_res > 0})
                        in_pos = False; active_leg = None
                    elif hit_sl:
                        r_res = -1.0 if not be_activated else be_lock_r
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": r_res, "win": r_res > 0})
                        in_pos = False; active_leg = None
                    elif exit_trailing:
                        r_res = (trailing_exit_price - entry_price) / risk
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": r_res, "win": r_res > 0})
                        in_pos = False; active_leg = None
                    elif hit_tp:
                        r_res = (tp_price - entry_price) / risk
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": r_res, "win": True})
                        in_pos = False; active_leg = None
                else:
                    hit_sl = c_high >= sl_price
                    hit_tp = c_low <= tp_price
                    if hit_sl and hit_tp:
                        r_res = -1.0 if not be_activated else be_lock_r
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": r_res, "win": r_res > 0})
                        in_pos = False; active_leg = None
                    elif hit_sl:
                        r_res = -1.0 if not be_activated else be_lock_r
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": r_res, "win": r_res > 0})
                        in_pos = False; active_leg = None
                    elif exit_trailing:
                        r_res = (entry_price - trailing_exit_price) / risk
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": r_res, "win": r_res > 0})
                        in_pos = False; active_leg = None
                    elif hit_tp:
                        r_res = (entry_price - tp_price) / risk
                        all_trades.append({"symbol": sym, "time": timestamps[entry_idx], "r": r_res, "win": True})
                        in_pos = False; active_leg = None
                continue

            # Signal
            if last_sh is not None and last_sl is not None:
                if last_sh_idx > last_sl_idx and closes[i] > last_sh:
                    leg_low = last_sl
                    leg_high = highs[i]
                    diff = leg_high - leg_low
                    if diff >= 10.0 * spread:
                        active_leg = {"dir": 1, "low": leg_low, "high": leg_high, "diff": diff}
                elif last_sl_idx > last_sh_idx and closes[i] < last_sl:
                    leg_high = last_sh
                    leg_low = lows[i]
                    diff = leg_high - leg_low
                    if diff >= 10.0 * spread:
                        active_leg = {"dir": -1, "low": leg_low, "high": leg_high, "diff": diff}

            if active_leg is not None:
                ldir = active_leg["dir"]
                ldiff = active_leg["diff"]
                lhigh = active_leg["high"]
                llow = active_leg["low"]

                if ldir == 1:
                    f_ent = lhigh - (ldiff * fibo_entry)
                    f_stp = lhigh - (ldiff * fibo_stop)
                    r_pts = f_ent - f_stp
                    if r_pts > 0 and lows[i] <= f_ent <= highs[i]:
                        in_pos = True
                        pos_dir = 1
                        entry_price = f_ent + (spread / 2.0)
                        sl_price = f_stp - (spread / 2.0)
                        risk = entry_price - sl_price
                        tp_price = lhigh
                        entry_idx = i
                        be_activated = False

                        # AUDITORIA A: Checagem Intrabar SL na própria barra de entrada!
                        if check_intrabar_sl and lows[i] <= sl_price:
                            intrabar_stops += 1
                            all_trades.append({"symbol": sym, "time": timestamps[i], "r": -1.0, "win": False})
                            in_pos = False
                            active_leg = None
                else:
                    f_ent = llow + (ldiff * fibo_entry)
                    f_stp = llow + (ldiff * fibo_stop)
                    r_pts = f_stp - f_ent
                    if r_pts > 0 and lows[i] <= f_ent <= highs[i]:
                        in_pos = True
                        pos_dir = -1
                        entry_price = f_ent - (spread / 2.0)
                        sl_price = f_stp + (spread / 2.0)
                        risk = sl_price - entry_price
                        tp_price = llow
                        entry_idx = i
                        be_activated = False

                        # AUDITORIA A: Checagem Intrabar SL na própria barra de entrada!
                        if check_intrabar_sl and highs[i] >= sl_price:
                            intrabar_stops += 1
                            all_trades.append({"symbol": sym, "time": timestamps[i], "r": -1.0, "win": False})
                            in_pos = False
                            active_leg = None

    return all_trades, intrabar_stops

def get_stats(trades):
    if not trades:
        return {}
    df = pd.DataFrame(trades)
    n = len(df)
    r_total = df["r"].sum()
    wr = (df["win"].sum() / n) * 100.0
    wins = df[df["r"] > 0]["r"]
    losses = df[df["r"] < 0]["r"].abs()
    w_sum = wins.sum()
    l_sum = losses.sum()
    pf = (w_sum / l_sum) if l_sum > 0 else 999.0
    payoff = (wins.mean() / losses.mean()) if len(losses) > 0 and losses.mean() > 0 else 0.0

    # Max Drawdown em R
    df_sorted = df.sort_values("time")
    cum = df_sorted["r"].cumsum()
    peak = cum.cummax()
    dd = cum - peak
    mdd = abs(dd.min())

    return {
        "trades": n,
        "wr": wr,
        "r_total": r_total,
        "r_year": r_total / 2.0,
        "pf": pf,
        "mdd": mdd,
        "payoff": payoff
    }

def main():
    print("=" * 90)
    print("AUDITORIA COMPLETA GEMINI ARGON: IMPACTO REAL DAS CORREÇÕES NO MOTOR PYTHON")
    print("Base: 2 Anos (01/11/2024 a 04/11/2026) | 4.95 Milhões de Candles Dukascopy M1")
    print("=" * 90 + "\n")

    raw_m1 = load_all_candles()

    scenarios = [
        ("1. Baseline Atual (Trailing MME8)", False, False, None, 0.0),
        ("2. Fix A: Intrabar SL Apenas", True, False, None, 0.0),
        ("3. Fix B: Trailing Só no Lucro Apenas", False, True, None, 0.0),
        ("4. Trailing Auditado (Fix A + B)", True, True, None, 0.0),
        ("5. Blindado Auditado (Fix A + B + Trava 2:1)", True, True, 2.0, 1.0),
    ]

    results = []
    for name, fix_sl, fix_trailing, be_trig, be_lock in scenarios:
        trades, intrabar_cnt = run_audited_sim(
            raw_m1,
            check_intrabar_sl=fix_sl,
            trailing_only_in_profit=fix_trailing,
            be_trigger_r=be_trig,
            be_lock_r=be_lock
        )
        st = get_stats(trades)
        st["name"] = name
        st["intrabar_cnt"] = intrabar_cnt
        results.append(st)

    print(f"{'Cenário':<42} | {'Trades':<6} | {'WinRate':<7} | {'Total R':<10} | {'R / Ano':<9} | {'PF':<5} | {'MaxDD':<6} | {'IntrabarSL'}")
    print("-" * 105)
    for r in results:
        print(f"{r['name']:<42} | {r['trades']:<6} | {r['wr']:>6.1f}% | {r['r_total']:>9.1f}R | {r['r_year']:>8.1f}R | {r['pf']:>5.2f} | -{r['mdd']:>4.1f}R | {r['intrabar_cnt']:<5}")
    print("-" * 105)

if __name__ == "__main__":
    main()

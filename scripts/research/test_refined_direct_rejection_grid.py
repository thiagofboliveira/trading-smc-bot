"""Experimento Refinado Otimizado: SMC FVOB/OB + Indução + Entrada Direta no Open[i+1] após Rejeição.

Otimização: Pré-computa swings e indicadores uma única vez por ativo.
Execução super rápida (< 15 segundos para todo o grid).
"""
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

SYMBOLS = ["BRENT", "US30", "NAS100", "XAUUSD", "EURUSD", "GBPUSD"]
SPREADS = {
    "XAUUSD": 0.20,
    "EURUSD": 0.00008,
    "GBPUSD": 0.00010,
    "US30": 2.0,
    "NAS100": 1.5,
    "BRENT": 0.03,
}

@dataclass
class Trade:
    symbol: str
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    exit_price: float
    exit_reason: str
    r_multiple: float
    win: bool

@dataclass
class AssetData:
    symbol: str
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    ts: pd.DatetimeIndex
    ema8: np.ndarray
    ema80: np.ndarray
    sma200: np.ndarray
    highs_by_conf: dict[int, tuple[int, float]]
    lows_by_conf: dict[int, tuple[int, float]]
    spread: float
    n: int

def prepare_asset(sym: str) -> AssetData | None:
    p = Path(f"data/{sym}_M1_dukascopy.parquet")
    if not p.exists():
        return None
    df_m1 = pd.read_parquet(p)
    df_m5 = df_m1.resample("5min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()

    opens = df_m5["open"].to_numpy(dtype=float)
    highs = df_m5["high"].to_numpy(dtype=float)
    lows = df_m5["low"].to_numpy(dtype=float)
    closes = df_m5["close"].to_numpy(dtype=float)
    ts = df_m5.index
    n = len(df_m5)

    ema8 = df_m5["close"].ewm(span=8, adjust=False).mean().to_numpy(dtype=float)
    ema80 = df_m5["close"].ewm(span=80, adjust=False).mean().to_numpy(dtype=float)
    sma200 = df_m5["close"].rolling(window=200).mean().to_numpy(dtype=float)

    # Pré-computa swings (k=2) uma única vez
    k = 2
    swing_highs = []
    swing_lows = []
    for i in range(k, n - k):
        h = highs[i]
        if np.all(h >= highs[i - k : i]) and np.all(h >= highs[i + 1 : i + k + 1]):
            swing_highs.append((i, h))
        l = lows[i]
        if np.all(l <= lows[i - k : i]) and np.all(l <= lows[i + 1 : i + k + 1]):
            swing_lows.append((i, l))

    highs_by_conf = {idx + k: (idx, p) for idx, p in swing_highs}
    lows_by_conf = {idx + k: (idx, p) for idx, p in swing_lows}

    return AssetData(
        symbol=sym,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        ts=ts,
        ema8=ema8,
        ema80=ema80,
        sma200=sma200,
        highs_by_conf=highs_by_conf,
        lows_by_conf=lows_by_conf,
        spread=SPREADS[sym],
        n=n,
    )

def run_simulation(
    ad: AssetData,
    stop_ratio: float,
    target_mode: str,
    conduction_mode: str,
    wick_ratio_min: float,
    session_filter: bool,
) -> list[Trade]:
    n = ad.n
    if n < 250:
        return []

    opens, highs, lows, closes = ad.opens, ad.highs, ad.lows, ad.closes
    ts, ema8, ema80, sma200 = ad.ts, ad.ema8, ad.ema80, ad.sma200
    highs_by_conf, lows_by_conf = ad.highs_by_conf, ad.lows_by_conf
    spread = ad.spread
    symbol = ad.symbol

    trades: list[Trade] = []
    active_leg = None
    open_pos = None

    last_high = None
    last_low = None

    for i in range(200, n):
        if i in highs_by_conf:
            last_high = highs_by_conf[i]
        if i in lows_by_conf:
            last_low = lows_by_conf[i]

        # 1. Gerencia Posição Aberta
        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_tp = False
            hit_sl = False

            # Condução A: Trava de Lucro Causal (+1.0R ao atingir +1.618R)
            if conduction_mode == "lock_1618" and not pos["locked"]:
                if d == 1 and highs[i] >= pos["entry_price"] + 1.618 * pos["initial_risk"]:
                    pos["stop_price"] = pos["entry_price"] + 1.0 * pos["initial_risk"]
                    pos["locked"] = True
                elif d == -1 and (lows[i] + spread) <= pos["entry_price"] - 1.618 * pos["initial_risk"]:
                    pos["stop_price"] = pos["entry_price"] - 1.0 * pos["initial_risk"]
                    pos["locked"] = True

            # Condução B: Trailing Stop por MME8
            if conduction_mode == "trailing_ema8" and i > pos["entry_idx"]:
                if d == 1 and closes[i - 1] > pos["entry_price"]:
                    if lows[i] < ema8[i - 1]:
                        hit_sl = True
                elif d == -1 and closes[i - 1] < pos["entry_price"]:
                    if highs[i] + spread > ema8[i - 1]:
                        hit_sl = True

            if d == 1:
                if lows[i] <= pos["stop_price"]:
                    hit_sl = True
                if highs[i] >= pos["target_price"]:
                    hit_tp = True
            else:
                if highs[i] + spread >= pos["stop_price"]:
                    hit_sl = True
                if lows[i] + spread <= pos["target_price"]:
                    hit_tp = True

            if hit_sl and hit_tp:
                hit_sl = True
                hit_tp = False

            if hit_sl:
                exit_price = pos["stop_price"]
                r = (exit_price - pos["entry_price"]) / pos["initial_risk"] if d == 1 else (pos["entry_price"] - exit_price) / pos["initial_risk"]
                win = r > 0.0
                trades.append(Trade(
                    symbol=symbol,
                    direction=pos["direction"],
                    entry_time=pos["entry_time"],
                    exit_time=ts[i],
                    entry_price=pos["entry_price"],
                    stop_price=pos["stop_price"],
                    target_price=pos["target_price"],
                    exit_price=exit_price,
                    exit_reason="STOP_LOSS" if r <= 0 else "PROFIT_LOCK",
                    r_multiple=r,
                    win=win,
                ))
                open_pos = None
                active_leg = None
                continue
            elif hit_tp:
                exit_price = pos["target_price"]
                r = pos["r_target"]
                trades.append(Trade(
                    symbol=symbol,
                    direction=pos["direction"],
                    entry_time=pos["entry_time"],
                    exit_time=ts[i],
                    entry_price=pos["entry_price"],
                    stop_price=pos["stop_price"],
                    target_price=pos["target_price"],
                    exit_price=exit_price,
                    exit_reason="TAKE_PROFIT",
                    r_multiple=r,
                    win=True,
                ))
                open_pos = None
                active_leg = None
                continue

        # 2. Detecta BOS e Atualiza Perna
        bullish_trend = (ema80[i - 1] > sma200[i - 1]) and (closes[i - 1] > sma200[i - 1])
        bearish_trend = (ema80[i - 1] < sma200[i - 1]) and (closes[i - 1] < sma200[i - 1])

        if bullish_trend and last_high is not None and last_low is not None:
            if closes[i] > last_high[1] and closes[i - 1] <= last_high[1]:
                orig_idx, orig_p = last_low
                if i - orig_idx >= 3 and highs[i] > orig_p:
                    active_leg = {
                        "direction": "long",
                        "origin_idx": orig_idx,
                        "origin_price": orig_p,
                        "bos_idx": i,
                        "extreme_price": highs[i],
                        "extreme_idx": i,
                        "impulse_candles": i - orig_idx,
                        "idm_pivots": [],
                    }

        if bearish_trend and last_low is not None and last_high is not None:
            if closes[i] < last_low[1] and closes[i - 1] >= last_low[1]:
                orig_idx, orig_p = last_high
                if i - orig_idx >= 3 and lows[i] < orig_p:
                    active_leg = {
                        "direction": "short",
                        "origin_idx": orig_idx,
                        "origin_price": orig_p,
                        "bos_idx": i,
                        "extreme_price": lows[i],
                        "extreme_idx": i,
                        "impulse_candles": i - orig_idx,
                        "idm_pivots": [],
                    }

        # 3. Acompanha Perna Ativa
        if active_leg is not None and open_pos is None:
            leg = active_leg
            d = 1 if leg["direction"] == "long" else -1
            span = d * (leg["extreme_price"] - leg["origin_price"])
            if span <= 0:
                active_leg = None
                continue

            lvl_50 = leg["extreme_price"] - d * 0.50 * span
            if d == 1:
                if lows[i] > lvl_50 and highs[i] > leg["extreme_price"]:
                    leg["extreme_price"] = highs[i]
                    leg["extreme_idx"] = i
                    leg["impulse_candles"] = i - leg["origin_idx"]
            else:
                if highs[i] < lvl_50 and lows[i] < leg["extreme_price"]:
                    leg["extreme_price"] = lows[i]
                    leg["extreme_idx"] = i
                    leg["impulse_candles"] = i - leg["origin_idx"]

            span = d * (leg["extreme_price"] - leg["origin_price"])
            lvl_618 = leg["extreme_price"] - d * 0.618 * span
            lvl_790 = leg["extreme_price"] - d * 0.790 * span
            lvl_stop = leg["extreme_price"] - d * stop_ratio * span

            if i > leg["extreme_idx"]:
                if d == 1 and lows[i] > lvl_50:
                    leg["idm_pivots"].append(lows[i])
                elif d == -1 and highs[i] < lvl_50:
                    leg["idm_pivots"].append(highs[i])

            if d == 1 and lows[i] <= lvl_stop:
                active_leg = None
                continue
            elif d == -1 and highs[i] >= lvl_stop:
                active_leg = None
                continue

            touch_zone = (lows[i] <= lvl_618 and highs[i] >= lvl_790) if d == 1 else (highs[i] >= lvl_618 and lows[i] <= lvl_790)
            
            if touch_zone and i < n - 1:
                in_session = True
                if session_filter:
                    h_curr = ts[i].hour
                    in_session = (7 <= h_curr < 18)

                if in_session:
                    ret_candles = i - leg["extreme_idx"]
                    criterio_a = ret_candles >= leg["impulse_candles"]
                    criterio_b = len(leg["idm_pivots"]) >= 2

                    if criterio_a or criterio_b:
                        rng = highs[i] - lows[i]
                        if rng > 0:
                            rejection_ok = False
                            if d == 1:
                                lower_wick = min(opens[i], closes[i]) - lows[i]
                                if lower_wick / rng >= wick_ratio_min and closes[i] > lvl_790:
                                    rejection_ok = True
                            else:
                                upper_wick = highs[i] - max(opens[i], closes[i])
                                if upper_wick / rng >= wick_ratio_min and closes[i] < lvl_790:
                                    rejection_ok = True

                            if rejection_ok:
                                exec_price = opens[i + 1] + spread if d == 1 else opens[i + 1]
                                risk = abs(exec_price - lvl_stop)
                                if risk > 0:
                                    if target_mode == "0_percent":
                                        target_price = leg["extreme_price"]
                                    elif target_mode == "3R":
                                        target_price = exec_price + d * 3.0 * risk
                                    elif target_mode == "4R":
                                        target_price = exec_price + d * 4.0 * risk
                                    elif target_mode == "proj_1618":
                                        target_price = leg["extreme_price"] + d * 0.618 * span
                                    else:
                                        target_price = leg["extreme_price"]

                                    reward = abs(target_price - exec_price)
                                    r_target = reward / risk

                                    open_pos = {
                                        "direction": leg["direction"],
                                        "entry_idx": i + 1,
                                        "entry_time": ts[i + 1],
                                        "entry_price": exec_price,
                                        "stop_price": lvl_stop,
                                        "target_price": target_price,
                                        "initial_risk": risk,
                                        "r_target": r_target,
                                        "locked": False,
                                    }
                                    active_leg = None

    return trades

def main():
    print("Carregando e pré-computando dados dos 6 ativos...")
    assets = {sym: prepare_asset(sym) for sym in SYMBOLS}
    assets = {k: v for k, v in assets.items() if v is not None}

    stops = [0.800, 0.886, 1.000]
    targets = ["0_percent", "3R", "4R", "proj_1618"]
    conductions = ["none", "lock_1618", "trailing_ema8"]
    wicks = [0.30, 0.50]

    results = []
    print("Varrendo combinações com entrada direta em Open[i+1]...")

    for st in stops:
        for tg in targets:
            for cond in conductions:
                for wk in wicks:
                    tot_trades = 0
                    tot_r = 0.0
                    tot_wins = 0
                    tot_is_r = 0.0
                    tot_oos_r = 0.0
                    all_r_vals = []
                    sym_breakdown = {}

                    for sym, ad in assets.items():
                        tr = run_simulation(ad, st, tg, cond, wk, True)
                        n = len(tr)
                        if n > 0:
                            r_vals = [t.r_multiple for t in tr]
                            r_tot = sum(r_vals)
                            wins = sum(1 for t in tr if t.win)
                            split_dt = pd.Timestamp("2026-06-25", tz="UTC") if tr[0].entry_time.tzinfo is not None else pd.Timestamp("2026-06-25")
                            is_r = sum(t.r_multiple for t in tr if t.entry_time < split_dt)
                            oos_r = sum(t.r_multiple for t in tr if t.entry_time >= split_dt)

                            tot_trades += n
                            tot_r += r_tot
                            tot_wins += wins
                            tot_is_r += is_r
                            tot_oos_r += oos_r
                            all_r_vals.extend(r_vals)
                            sym_breakdown[sym] = (r_tot, n, (100.0 * wins / n))
                        else:
                            sym_breakdown[sym] = (0.0, 0, 0.0)

                    wr = 100.0 * tot_wins / tot_trades if tot_trades > 0 else 0.0
                    r_tr = tot_r / tot_trades if tot_trades > 0 else 0.0
                    ep = np.std(all_r_vals) / np.sqrt(tot_trades) if tot_trades > 1 else 0.0
                    gp = sum(r for r in all_r_vals if r > 0)
                    gl = -sum(r for r in all_r_vals if r < 0)
                    pf = gp / gl if gl > 0 else float("inf")

                    results.append({
                        "stop": st,
                        "target": tg,
                        "cond": cond,
                        "wick": wk,
                        "trades": tot_trades,
                        "r_total": tot_r,
                        "wr": wr,
                        "pf": pf,
                        "r_per_tr": r_tr,
                        "ep": ep,
                        "is_r": tot_is_r,
                        "oos_r": tot_oos_r,
                        "breakdown": sym_breakdown,
                    })

    results.sort(key=lambda x: x["r_total"], reverse=True)

    print("\n" + "=" * 105)
    print("  RANKING TOP 15: ENTRADA DIRETA NO OPEN[i+1] APÓS REJEIÇÃO (SESSÃO LONDRES/NY)")
    print("=" * 105)
    print(f"{'#':>2s} | {'Stop':5s} | {'Alvo':10s} | {'Condução':14s} | {'Pavio':5s} | {'Trades':>6s} | {'R Total':>8s} | {'WR %':>6s} | {'PF':>5s} | {'IS':>8s} | {'OOS':>8s}")
    print("-" * 105)

    for idx, r in enumerate(results[:15], 1):
        print(f"{idx:2d} | {r['stop']:5.3f} | {r['target']:10s} | {r['cond']:14s} | {r['wick']:4.2f}  | {r['trades']:6d} | {r['r_total']:7.1f}R | {r['wr']:5.1f}% | {r['pf']:5.2f} | {r['is_r']:7.1f}R | {r['oos_r']:7.1f}R")

    print("\n" + "=" * 105)
    print("  DETALHE POR ATIVO DAS TOP 3 VARIANTES")
    print("=" * 105)

    for rank in range(min(3, len(results))):
        best = results[rank]
        print(f"\n--- Rank #{rank+1}: Stop {best['stop']:.3f} | Alvo {best['target']} | Condução {best['cond']} | Pavio {best['wick']} ---")
        print(f"Total: {best['r_total']:.1f}R em {best['trades']} trades (WR {best['wr']:.1f}%, PF {best['pf']:.2f}, IS: {best['is_r']:.1f}R, OOS: {best['oos_r']:.1f}R)")
        print(f"{'Ativo':8s} | {'R Total':>8s} | {'Trades':>6s} | {'Acerto %':>8s}")
        print("-" * 36)
        for sym in SYMBOLS:
            sym_r, sym_n, sym_wr = best["breakdown"][sym]
            print(f"{sym:8s} | {sym_r:7.1f}R | {sym_n:6d} | {sym_wr:7.1f}%")

if __name__ == "__main__":
    main()

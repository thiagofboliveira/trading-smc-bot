"""Varredura Completa de Parâmetros: SMC FVOB / OB com Indução e Alinhamento MME80 + MMA200.

Testando:
- Stops: 0.800, 0.886, 1.000
- Alvos:
  1. 0_percent (topo do BOS - baseline)
  2. 3R (alvo fixo de 3.0x o risco)
  3. 4R_lock (alvo de 4.0x o risco com trava de +1.0R ao atingir 1.618R)
  4. proj_1618 (projeção de 1.618 da perna do BOS)
- Filtro de Sessão: Sem filtro vs Sessão Londres/NY (07:00-18:00 UTC)
- Divisão Temporal: 1ª metade (IS) vs 2ª metade (OOS)
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

def compute_indicators(df_m5: pd.DataFrame) -> pd.DataFrame:
    df = df_m5.copy()
    df["ema80"] = df["close"].ewm(span=80, adjust=False).mean()
    df["sma200"] = df["close"].rolling(window=200).mean()
    return df

def run_simulation(
    symbol: str,
    df_m5: pd.DataFrame,
    stop_ratio: float,
    target_mode: str,
    session_filter: bool,
    spread: float,
) -> list[Trade]:
    n = len(df_m5)
    if n < 250:
        return []

    opens = df_m5["open"].to_numpy(dtype=float)
    highs = df_m5["high"].to_numpy(dtype=float)
    lows = df_m5["low"].to_numpy(dtype=float)
    closes = df_m5["close"].to_numpy(dtype=float)
    ts = df_m5.index
    ema80 = df_m5["ema80"].to_numpy(dtype=float)
    sma200 = df_m5["sma200"].to_numpy(dtype=float)

    # 1. Pré-computa swings (k=2)
    k = 2
    swing_highs: list[tuple[int, float]] = []
    swing_lows: list[tuple[int, float]] = []

    for i in range(k, n - k):
        h = highs[i]
        if np.all(h >= highs[i - k : i]) and np.all(h >= highs[i + 1 : i + k + 1]):
            swing_highs.append((i, h))
        l = lows[i]
        if np.all(l <= lows[i - k : i]) and np.all(l <= lows[i + 1 : i + k + 1]):
            swing_lows.append((i, l))

    highs_by_conf: dict[int, tuple[int, float]] = {idx + k: (idx, p) for idx, p in swing_highs}
    lows_by_conf: dict[int, tuple[int, float]] = {idx + k: (idx, p) for idx, p in swing_lows}

    trades: list[Trade] = []
    active_leg = None
    pending_order = None
    open_pos = None

    last_high = None
    last_low = None

    for i in range(200, n):
        if i in highs_by_conf:
            last_high = highs_by_conf[i]
        if i in lows_by_conf:
            last_low = lows_by_conf[i]

        # -------------------------------------------------------------
        # 1. Gerencia Posição Aberta
        # -------------------------------------------------------------
        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_tp = False
            hit_sl = False

            # Trava de Lucro Causal (+1.0R ao atingir +1.618R)
            if target_mode == "4R_lock" and not pos["locked"]:
                if d == 1 and highs[i] >= pos["entry_price"] + 1.618 * pos["initial_risk"]:
                    pos["stop_price"] = pos["entry_price"] + 1.0 * pos["initial_risk"]
                    pos["locked"] = True
                elif d == -1 and (lows[i] + spread) <= pos["entry_price"] - 1.618 * pos["initial_risk"]:
                    pos["stop_price"] = pos["entry_price"] - 1.0 * pos["initial_risk"]
                    pos["locked"] = True

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
                # Pior caso causal
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
                pending_order = None
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
                pending_order = None
                continue

        # -------------------------------------------------------------
        # 2. Executa Ordem Armada (Gatilho de Rompimento da Rejeição)
        # -------------------------------------------------------------
        if pending_order is not None and open_pos is None:
            po = pending_order
            d = 1 if po["direction"] == "long" else -1
            triggered = False
            exec_price = 0.0

            if d == 1:
                if highs[i] >= po["trigger_price"]:
                    triggered = True
                    exec_price = max(opens[i], po["trigger_price"]) + spread
            else:
                if lows[i] <= po["trigger_price"]:
                    triggered = True
                    exec_price = min(opens[i], po["trigger_price"])

            if triggered:
                risk = abs(exec_price - po["stop_price"])
                if risk > 0:
                    # Define Target Price com base no target_mode
                    if target_mode == "0_percent":
                        target_price = po["extreme_price"]
                    elif target_mode == "3R":
                        target_price = exec_price + d * 3.0 * risk
                    elif target_mode == "4R_lock":
                        target_price = exec_price + d * 4.0 * risk
                    elif target_mode == "proj_1618":
                        target_price = po["extreme_price"] + d * 0.618 * po["leg_span"]
                    else:
                        target_price = po["extreme_price"]

                    reward = abs(target_price - exec_price)
                    r_target = reward / risk

                    open_pos = {
                        "direction": po["direction"],
                        "entry_time": ts[i],
                        "entry_price": exec_price,
                        "stop_price": po["stop_price"],
                        "target_price": target_price,
                        "initial_risk": risk,
                        "r_target": r_target,
                        "locked": False,
                    }
                    pending_order = None
                    active_leg = None
                    continue
                else:
                    pending_order = None
            else:
                pending_order = None

        # -------------------------------------------------------------
        # 3. Detecta BOS e Atualiza Perna Estrutural
        # -------------------------------------------------------------
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
                        "touched": False,
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
                        "touched": False,
                        "idm_pivots": [],
                    }

        # -------------------------------------------------------------
        # 4. Acompanha Perna Ativa, Indução e Blocos de Ordens
        # -------------------------------------------------------------
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

            # Invalidação da perna se violar o stop_ratio
            if d == 1 and lows[i] <= lvl_stop:
                active_leg = None
                continue
            elif d == -1 and highs[i] >= lvl_stop:
                active_leg = None
                continue

            touch_zone = (lows[i] <= lvl_618 and highs[i] >= lvl_790) if d == 1 else (highs[i] >= lvl_618 and lows[i] <= lvl_790)
            
            if touch_zone:
                # Checa filtro de sessão (07:00 às 18:00 UTC)
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
                            if d == 1:
                                lower_wick = min(opens[i], closes[i]) - lows[i]
                                if lower_wick / rng >= 0.30 and closes[i] > lvl_790:
                                    pending_order = {
                                        "direction": "long",
                                        "trigger_price": highs[i],
                                        "stop_price": lvl_stop,
                                        "extreme_price": leg["extreme_price"],
                                        "leg_span": span,
                                    }
                                    active_leg = None
                            else:
                                upper_wick = highs[i] - max(opens[i], closes[i])
                                if upper_wick / rng >= 0.30 and closes[i] < lvl_790:
                                    pending_order = {
                                        "direction": "short",
                                        "trigger_price": lows[i],
                                        "stop_price": lvl_stop,
                                        "extreme_price": leg["extreme_price"],
                                        "leg_span": span,
                                    }
                                    active_leg = None

    return trades

def load_all_m5() -> dict[str, pd.DataFrame]:
    res = {}
    for sym in SYMBOLS:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        if p.exists():
            df_m1 = pd.read_parquet(p)
            df_m5 = df_m1.resample("5min").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }).dropna()
            res[sym] = compute_indicators(df_m5)
    return res

def run_grid():
    dfs = load_all_m5()
    stops = [0.800, 0.886, 1.000]
    targets = ["0_percent", "3R", "4R_lock", "proj_1618"]
    sessions = [True, False]

    results = []

    print("Iniciando varredura de 24 variantes...")

    for sess in sessions:
        sess_str = "Sessao(07-18)" if sess else "24h"
        for st in stops:
            for tg in targets:
                tot_trades = 0
                tot_r = 0.0
                tot_wins = 0
                tot_is_r = 0.0
                tot_oos_r = 0.0
                all_r_vals = []
                sym_breakdown = {}

                for sym in SYMBOLS:
                    df = dfs[sym]
                    spread = SPREADS[sym]
                    tr = run_simulation(sym, df, st, tg, sess, spread)
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
                    "sess": sess_str,
                    "stop": st,
                    "target": tg,
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

    # Ordena pelo R Total
    results.sort(key=lambda x: x["r_total"], reverse=True)

    print("\n" + "=" * 96)
    print("  RANKING GERAL DAS 24 VARIANTES (TESTE DE EXTENSÃO DE ALVO E GESTÃO)")
    print("=" * 96)
    print(f"{'#':>2s} | {'Sessão':13s} | {'Stop':5s} | {'Alvo':10s} | {'Trades':>6s} | {'R Total':>8s} | {'WR %':>6s} | {'PF':>5s} | {'R/tr ± EP':>16s} | {'IS':>8s} | {'OOS':>8s}")
    print("-" * 96)

    for idx, r in enumerate(results, 1):
        print(f"{idx:2d} | {r['sess']:13s} | {r['stop']:5.3f} | {r['target']:10s} | {r['trades']:6d} | {r['r_total']:7.1f}R | {r['wr']:5.1f}% | {r['pf']:5.2f} | {r['r_per_tr']:6.3f} ± {r['ep']:5.3f} | {r['is_r']:7.1f}R | {r['oos_r']:7.1f}R")

    print("\n" + "=" * 96)
    print("  DETALHE POR ATIVO DAS 3 MELHORES VARIANTES")
    print("=" * 96)

    for rank in range(min(3, len(results))):
        best = results[rank]
        print(f"\n--- Rank #{rank+1}: {best['sess']} | Stop {best['stop']:.3f} | Alvo {best['target']} | Total: {best['r_total']:.1f}R (WR {best['wr']:.1f}%, PF {best['pf']:.2f}) ---")
        print(f"{'Ativo':8s} | {'R Total':>8s} | {'Trades':>6s} | {'Acerto %':>8s}")
        print("-" * 36)
        for sym in SYMBOLS:
            sym_r, sym_n, sym_wr = best["breakdown"][sym]
            print(f"{sym:8s} | {sym_r:7.1f}R | {sym_n:6d} | {sym_wr:7.1f}%")

if __name__ == "__main__":
    run_grid()

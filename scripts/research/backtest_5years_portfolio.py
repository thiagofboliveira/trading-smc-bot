"""Validação de 5 Anos (2021 a 2026) da Carteira Híbrida Especializada.

Período: 2021-11-01 a 2026-11-08 (5 anos completos de dados M1 Dukascopy)
Divisão Temporal:
- In-Sample (IS): 2021-11-01 a 2024-11-01 (3 primeiros anos)
- Out-of-Sample (OOS): 2024-11-01 a 2026-11-08 (2 últimos anos inéditos)

Carteira Especializada Avaliada:
1. US30 em M5: SMC Fibo Rejeição EMA80 Pavio + Indução (Alvo 4R, Trava 1.618R)
2. NAS100 em M10: SMC Fibo Rejeição EMA80 Pavio + Indução
3. BRENT em M10: SMC FVOB/OB com Alvo Projeção 1.618
4. EURUSD em M10: SMC Fibo Rejeição EMA80 Pavio + Indução
5. GBPUSD em M15: SMC FVOB/OB com Alvo Projeção 1.618
6. XAUUSD em M5: SMC Fibo Rejeição EMA80 Pavio + Indução
"""
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

SYMBOLS = ["US30", "NAS100", "BRENT", "EURUSD", "GBPUSD", "XAUUSD"]
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
class AssetTFData:
    symbol: str
    tf_name: str
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    ts: pd.DatetimeIndex
    ema80: np.ndarray
    sma200: np.ndarray
    highs_by_conf: dict[int, tuple[int, float]]
    lows_by_conf: dict[int, tuple[int, float]]
    spread: float
    n: int

def prepare_data(sym: str, tf: str) -> AssetTFData | None:
    p = Path(f"data/{sym}_M1_dukascopy.parquet")
    if not p.exists():
        return None
    df_m1 = pd.read_parquet(p)
    df_tf = df_m1.resample(tf).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna()

    opens = df_tf["open"].to_numpy(dtype=float)
    highs = df_tf["high"].to_numpy(dtype=float)
    lows = df_tf["low"].to_numpy(dtype=float)
    closes = df_tf["close"].to_numpy(dtype=float)
    ts = df_tf.index
    n = len(df_tf)

    ema80 = df_tf["close"].ewm(span=80, adjust=False).mean().to_numpy(dtype=float)
    sma200 = df_tf["close"].rolling(window=200).mean().to_numpy(dtype=float)

    k = 2
    swing_highs = []
    swing_lows = []
    for i in range(k, n - k):
        if np.all(highs[i] >= highs[i - k : i]) and np.all(highs[i] >= highs[i + 1 : i + k + 1]):
            swing_highs.append((i, highs[i]))
        if np.all(lows[i] <= lows[i - k : i]) and np.all(lows[i] <= lows[i + 1 : i + k + 1]):
            swing_lows.append((i, lows[i]))

    highs_by_conf = {idx + k: (idx, p) for idx, p in swing_highs}
    lows_by_conf = {idx + k: (idx, p) for idx, p in swing_lows}

    tf_label = "M5" if tf == "5min" else ("M10" if tf == "10min" else "M15")

    return AssetTFData(
        symbol=sym,
        tf_name=tf_label,
        opens=opens,
        highs=highs,
        lows=lows,
        closes=closes,
        ts=ts,
        ema80=ema80,
        sma200=sma200,
        highs_by_conf=highs_by_conf,
        lows_by_conf=lows_by_conf,
        spread=SPREADS[sym],
        n=n,
    )

def run_fibo_ema80(ad: AssetTFData) -> list[Trade]:
    n = ad.n
    if n < 100:
        return []

    opens, highs, lows, closes = ad.opens, ad.highs, ad.lows, ad.closes
    ts, ema80 = ad.ts, ad.ema80
    highs_by_conf, lows_by_conf = ad.highs_by_conf, ad.lows_by_conf
    spread = ad.spread
    symbol = ad.symbol

    trades = []
    active_leg = None
    open_pos = None
    last_high = None
    last_low = None

    for i in range(80, n):
        if i in highs_by_conf:
            last_high = highs_by_conf[i]
        if i in lows_by_conf:
            last_low = lows_by_conf[i]

        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_tp = False
            hit_sl = False

            if not pos["locked"]:
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
                hit_sl = True
                hit_tp = False

            if hit_sl:
                exit_price = pos["stop_price"]
                r = (exit_price - pos["entry_price"]) / pos["initial_risk"] if d == 1 else (pos["entry_price"] - exit_price) / pos["initial_risk"]
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
                    win=r > 0,
                ))
                open_pos = None
                active_leg = None
                continue
            elif hit_tp:
                trades.append(Trade(
                    symbol=symbol,
                    direction=pos["direction"],
                    entry_time=pos["entry_time"],
                    exit_time=ts[i],
                    entry_price=pos["entry_price"],
                    stop_price=pos["stop_price"],
                    target_price=pos["target_price"],
                    exit_price=pos["target_price"],
                    exit_reason="TAKE_PROFIT",
                    r_multiple=4.0,
                    win=True,
                ))
                open_pos = None
                active_leg = None
                continue

        if last_high is not None and last_low is not None:
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
                        "idm_pivots": [],
                    }

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
                        "idm_pivots": [],
                    }

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
            else:
                if highs[i] < lvl_50 and lows[i] < leg["extreme_price"]:
                    leg["extreme_price"] = lows[i]
                    leg["extreme_idx"] = i

            span = d * (leg["extreme_price"] - leg["origin_price"])
            lvl_50 = leg["extreme_price"] - d * 0.50 * span
            lvl_79 = leg["extreme_price"] - d * 0.79 * span
            lvl_stop = leg["extreme_price"] - d * 0.886 * span

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

            touch_zone = (lows[i] <= lvl_50 and highs[i] >= lvl_79) if d == 1 else (highs[i] >= lvl_50 and lows[i] <= lvl_79)
            touch_ema80 = (lows[i] <= ema80[i] <= highs[i])

            if touch_zone and touch_ema80 and i < n - 1:
                h_curr = ts[i].hour
                in_session = (7 <= h_curr < 18)

                if in_session and len(leg["idm_pivots"]) >= 1:
                    rng = highs[i] - lows[i]
                    if rng > 0:
                        rejection = False
                        if d == 1:
                            lower_wick = min(opens[i], closes[i]) - lows[i]
                            if lower_wick / rng >= 0.50 and closes[i] > ema80[i] and closes[i] > lvl_79:
                                rejection = True
                        else:
                            upper_wick = highs[i] - max(opens[i], closes[i])
                            if upper_wick / rng >= 0.50 and closes[i] < ema80[i] and closes[i] < lvl_79:
                                rejection = True

                        if rejection:
                            exec_price = opens[i + 1] + spread if d == 1 else opens[i + 1]
                            risk = abs(exec_price - lvl_stop)
                            if risk > 0:
                                target_price = exec_price + d * 4.0 * risk
                                open_pos = {
                                    "direction": leg["direction"],
                                    "entry_idx": i + 1,
                                    "entry_time": ts[i + 1],
                                    "entry_price": exec_price,
                                    "stop_price": lvl_stop,
                                    "target_price": target_price,
                                    "initial_risk": risk,
                                    "locked": False,
                                }
                                active_leg = None

    return trades

def run_fvob_proj(ad: AssetTFData) -> list[Trade]:
    n = ad.n
    if n < 200:
        return []

    opens, highs, lows, closes = ad.opens, ad.highs, ad.lows, ad.closes
    ts, ema80, sma200 = ad.ts, ad.ema80, ad.sma200
    highs_by_conf, lows_by_conf = ad.highs_by_conf, ad.lows_by_conf
    spread = ad.spread
    symbol = ad.symbol

    trades = []
    active_leg = None
    open_pos = None
    last_high = None
    last_low = None
    stop_ratio = 0.886

    for i in range(200, n):
        if i in highs_by_conf:
            last_high = highs_by_conf[i]
        if i in lows_by_conf:
            last_low = lows_by_conf[i]

        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_tp = False
            hit_sl = False

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
                r = -1.0
                trades.append(Trade(
                    symbol=symbol,
                    direction=pos["direction"],
                    entry_time=pos["entry_time"],
                    exit_time=ts[i],
                    entry_price=pos["entry_price"],
                    stop_price=pos["stop_price"],
                    target_price=pos["target_price"],
                    exit_price=exit_price,
                    exit_reason="STOP_LOSS",
                    r_multiple=r,
                    win=False,
                ))
                open_pos = None
                active_leg = None
                continue
            elif hit_tp:
                trades.append(Trade(
                    symbol=symbol,
                    direction=pos["direction"],
                    entry_time=pos["entry_time"],
                    exit_time=ts[i],
                    entry_price=pos["entry_price"],
                    stop_price=pos["stop_price"],
                    target_price=pos["target_price"],
                    exit_price=pos["target_price"],
                    exit_reason="TAKE_PROFIT",
                    r_multiple=pos["r_target"],
                    win=True,
                ))
                open_pos = None
                active_leg = None
                continue

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
                h_curr = ts[i].hour
                in_session = (7 <= h_curr < 18)

                if in_session:
                    ret_candles = i - leg["extreme_idx"]
                    criterio_a = ret_candles >= leg["impulse_candles"]
                    criterio_b = len(leg["idm_pivots"]) >= 1

                    if criterio_a or criterio_b:
                        rng = highs[i] - lows[i]
                        if rng > 0:
                            rejection_ok = False
                            if d == 1:
                                lower_wick = min(opens[i], closes[i]) - lows[i]
                                if lower_wick / rng >= 0.40 and closes[i] > lvl_790:
                                    rejection_ok = True
                            else:
                                upper_wick = highs[i] - max(opens[i], closes[i])
                                if upper_wick / rng >= 0.40 and closes[i] < lvl_790:
                                    rejection_ok = True

                            if rejection_ok:
                                exec_price = opens[i + 1] + spread if d == 1 else opens[i + 1]
                                risk = abs(exec_price - lvl_stop)
                                if risk > 0:
                                    target_price = leg["extreme_price"] + d * 0.618 * span
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

def max_drawdown_r(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    r_curve = np.cumsum([t.r_multiple for t in trades])
    peak = np.maximum.accumulate(r_curve)
    dd = peak - r_curve
    return float(np.max(dd)) if len(dd) > 0 else 0.0

def main():
    print("=" * 95)
    print("  RELATÓRIO AUDITADO DE 5 ANOS (2021-2026) — CARTEIRA HÍBRIDA ESPECIALIZADA")
    print("  Divisão Causal: In-Sample (2021-2024, 3 anos) vs Out-of-Sample (2024-2026, 2 anos)")
    print("=" * 95)

    portfolio_setup = [
        ("US30", "5min", "fibo_ema80", "US30 em M5 (Fibo EMA80 Pavio + Indução)"),
        ("NAS100", "10min", "fibo_ema80", "NAS100 em M10 (Fibo EMA80 Pavio + Indução)"),
        ("BRENT", "10min", "fvob_proj", "BRENT em M10 (FVOB Projeção 1.618)"),
        ("EURUSD", "10min", "fibo_ema80", "EURUSD em M10 (Fibo EMA80 Pavio + Indução)"),
        ("GBPUSD", "15min", "fvob_proj", "GBPUSD em M15 (FVOB Projeção 1.618)"),
        ("XAUUSD", "5min", "fibo_ema80", "XAUUSD em M5 (Fibo EMA80 Pavio + Indução)"),
    ]

    print(f"\n{'Ativo':8s} | {'Timeframe':9s} | {'Trades':>6s} | {'R Total':>8s} | {'R/ano':>7s} | {'Acerto %':>8s} | {'PF':>5s} | {'MaxDD':>6s} | {'IS (3a)':>8s} | {'OOS (2a)':>9s}")
    print("-" * 95)

    tot_trades = 0
    tot_r = 0.0
    tot_is_r = 0.0
    tot_oos_r = 0.0
    all_portfolio_trades = []

    for sym, tf, strat_mode, desc in portfolio_setup:
        ad = prepare_data(sym, tf)
        if ad is None:
            print(f"Sem dados para {sym}")
            continue

        if strat_mode == "fibo_ema80":
            trades = run_fibo_ema80(ad)
        else:
            trades = run_fvob_proj(ad)

        n = len(trades)
        if n == 0:
            continue

        r_vals = [t.r_multiple for t in trades]
        r_tot = sum(r_vals)
        r_ano = r_tot / 5.0
        wins = sum(1 for t in trades if t.win)
        wr = 100.0 * wins / n
        gp = sum(r for r in r_vals if r > 0)
        gl = -sum(r for r in r_vals if r < 0)
        pf = gp / gl if gl > 0 else float("inf")
        dd = max_drawdown_r(trades)

        split_dt = pd.Timestamp("2024-11-01", tz="UTC")
        is_r = sum(t.r_multiple for t in trades if t.entry_time < split_dt)
        oos_r = sum(t.r_multiple for t in trades if t.entry_time >= split_dt)

        tot_trades += n
        tot_r += r_tot
        tot_is_r += is_r
        tot_oos_r += oos_r
        all_portfolio_trades.extend(trades)

        print(f"{sym:8s} | {ad.tf_name:9s} | {n:6d} | {r_tot:7.1f}R | {r_ano:6.1f}R | {wr:7.1f}% | {pf:5.2f} | {dd:5.1f}R | {is_r:7.1f}R | {oos_r:8.1f}R")

    print("-" * 95)
    tot_r_ano = tot_r / 5.0
    all_portfolio_trades.sort(key=lambda t: t.entry_time)
    port_dd = max_drawdown_r(all_portfolio_trades)
    port_wr = 100.0 * sum(1 for t in all_portfolio_trades if t.win) / tot_trades if tot_trades > 0 else 0.0

    print(f"{'CARTEIRA':8s} | {'HÍBRIDA':9s} | {tot_trades:6d} | {tot_r:7.1f}R | {tot_r_ano:6.1f}R | {port_wr:7.1f}% |       | {port_dd:5.1f}R | {tot_is_r:7.1f}R | {tot_oos_r:8.1f}R")

    print("\n" + "=" * 95)
    print("  SIMULAÇÃO FINANCEIRA DE 5 ANOS DA CARTEIRA COMPLETA")
    print(f"  Risco por Trade: R$ 30,00 (1R = R$ 30,00) | Período: 5 anos")
    print("=" * 95)
    val_total = tot_r * 30.0
    val_ano = tot_r_ano * 30.0
    val_dd = port_dd * 30.0
    val_is = tot_is_r * 30.0
    val_oos = tot_oos_r * 30.0
    print(f"💰 Lucro Total em 5 anos (60 meses): R$ {val_total:,.2f}")
    print(f"📈 Lucro Médio Anual: R$ {val_ano:,.2f} / ano ({tot_r_ano:.1f}R/ano)")
    print(f"🛡️ Drawdown Máximo Histórico da Carteira: R$ {val_dd:,.2f} ({port_dd:.1f}R)")
    print(f"📊 Desempenho In-Sample (2021-2024, 3 anos): R$ {val_is:,.2f} ({tot_is_r:.1f}R)")
    print(f"🎯 Desempenho Out-of-Sample (2024-2026, 2 anos): R$ {val_oos:,.2f} ({tot_oos_r:.1f}R)")

if __name__ == "__main__":
    main()

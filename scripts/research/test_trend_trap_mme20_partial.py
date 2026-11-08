"""Estudo de Refinamento: Seguidor de Super Tendência nos Índices (NAS100 e US30).

Comparações Testadas:
1. Médias de Condução:
   - MME 8 (exponencial rápida)
   - MMA 9 (aritmética clássica)
   - MME 20 (tendência institucional)
   - Trava de Lucro em +2.0R (move stop para +1.0R) + Saída final por MME 20
2. Filtros de Sessão:
   - Londres/NY Ampla (07:00 - 18:00 UTC)
   - Nova York Foco (13:00 - 17:30 UTC - auge da volatilidade direcional de Wall St)
3. Timeframes: M10 e M15 nos 5 anos completos (2021 a 2026).
"""
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

SYMBOLS = ["NAS100", "US30"]
SPREADS = {
    "US30": 2.0,
    "NAS100": 1.5,
}

@dataclass
class Trade:
    symbol: str
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_price: float
    exit_price: float
    exit_reason: str
    r_multiple: float
    win: bool

@dataclass
class AssetData:
    symbol: str
    tf_name: str
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    ts: pd.DatetimeIndex
    mme8: np.ndarray
    mma9: np.ndarray
    mme20: np.ndarray
    mme80: np.ndarray
    mme200: np.ndarray
    adx14: np.ndarray
    slope80: np.ndarray
    spread: float
    n: int

def prepare_asset(sym: str, tf: str) -> AssetData | None:
    p = Path(f"data/{sym}_M1_dukascopy.parquet")
    if not p.exists():
        return None
    df_m1 = pd.read_parquet(p)
    df = df_m1.resample(tf).agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna()

    close = df["close"]
    high = df["high"]
    low = df["low"]

    mme8 = close.ewm(span=8, adjust=False).mean().to_numpy(dtype=float)
    mma9 = close.rolling(window=9).mean().to_numpy(dtype=float)
    mme20 = close.ewm(span=20, adjust=False).mean().to_numpy(dtype=float)
    mme80 = close.ewm(span=80, adjust=False).mean().to_numpy(dtype=float)
    mme200 = close.ewm(span=200, adjust=False).mean().to_numpy(dtype=float)

    # ATR(14)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=14).mean()

    # ADX(14)
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr_s = tr.rolling(window=14).sum()
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(window=14).sum() / tr_s)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(window=14).sum() / tr_s)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx14 = dx.rolling(window=14).mean().fillna(0).to_numpy(dtype=float)

    # Slope normalizado
    slope80 = ((df["close"].ewm(span=80, adjust=False).mean() - df["close"].ewm(span=80, adjust=False).mean().shift(10)) / (10 * atr.replace(0, np.nan))).fillna(0).to_numpy(dtype=float)

    tf_label = "M10" if tf == "10min" else "M15"

    return AssetData(
        symbol=sym,
        tf_name=tf_label,
        opens=df["open"].to_numpy(dtype=float),
        highs=df["high"].to_numpy(dtype=float),
        lows=df["low"].to_numpy(dtype=float),
        closes=df["close"].to_numpy(dtype=float),
        ts=df.index,
        mme8=mme8,
        mma9=mma9,
        mme20=mme20,
        mme80=mme80,
        mme200=mme200,
        adx14=adx14,
        slope80=slope80,
        spread=SPREADS[sym],
        n=len(df),
    )

def run_simulation(
    ad: AssetData,
    conduction_ma: str,       # 'mme8', 'mma9', 'mme20'
    use_profit_lock: bool,     # Trava em +2R -> Stop +1R
    ny_session_only: bool,     # True = 13:00-17:30 UTC / False = 07:00-18:00 UTC
) -> list[Trade]:
    n = ad.n
    if n < 250:
        return []

    opens, highs, lows, closes = ad.opens, ad.highs, ad.lows, ad.closes
    ts = ad.ts
    mme80, mme200, adx, slope80 = ad.mme80, ad.mme200, ad.adx14, ad.slope80
    spread = ad.spread
    symbol = ad.symbol

    # Escolhe a média de condução
    if conduction_ma == "mme8":
        ma_cond = ad.mme8
    elif conduction_ma == "mma9":
        ma_cond = ad.mma9
    else:
        ma_cond = ad.mme20

    mme8_entry = ad.mme8

    trades = []
    open_pos = None
    pending_order = None

    for i in range(210, n - 1):
        # 1. Posição Aberta
        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_sl = False
            exit_by_ma = False

            # Trava de Lucro Causal: Se bater +2.0R, move stop para +1.0R
            if use_profit_lock and not pos["locked"]:
                if d == 1 and highs[i] >= pos["entry_price"] + 2.0 * pos["initial_risk"]:
                    pos["stop_price"] = pos["entry_price"] + 1.0 * pos["initial_risk"]
                    pos["locked"] = True
                elif d == -1 and (lows[i] + spread) <= pos["entry_price"] - 2.0 * pos["initial_risk"]:
                    pos["stop_price"] = pos["entry_price"] - 1.0 * pos["initial_risk"]
                    pos["locked"] = True

            # Stop Loss
            if d == 1:
                if lows[i] <= pos["stop_price"]:
                    hit_sl = True
            else:
                if highs[i] + spread >= pos["stop_price"]:
                    hit_sl = True

            # Saída Causal por Média Móvel
            if i > pos["entry_idx"]:
                if d == 1 and closes[i] < ma_cond[i]:
                    exit_by_ma = True
                elif d == -1 and closes[i] > ma_cond[i]:
                    exit_by_ma = True

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
                    exit_price=exit_price,
                    exit_reason="STOP_LOSS" if r <= 0 else "PROFIT_LOCK",
                    r_multiple=r,
                    win=r > 0,
                ))
                open_pos = None
                pending_order = None
                continue

            elif exit_by_ma and i < n - 1:
                exit_price = opens[i + 1] if d == 1 else opens[i + 1] + spread
                r = (exit_price - pos["entry_price"]) / pos["initial_risk"] if d == 1 else (pos["entry_price"] - exit_price) / pos["initial_risk"]
                trades.append(Trade(
                    symbol=symbol,
                    direction=pos["direction"],
                    entry_time=pos["entry_time"],
                    exit_time=ts[i + 1],
                    entry_price=pos["entry_price"],
                    stop_price=pos["stop_price"],
                    exit_price=exit_price,
                    exit_reason="TRAILING_MA",
                    r_multiple=r,
                    win=r > 0,
                ))
                open_pos = None
                pending_order = None
                continue

        # 2. Ordem Armada
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
                    open_pos = {
                        "direction": po["direction"],
                        "entry_idx": i,
                        "entry_time": ts[i],
                        "entry_price": exec_price,
                        "stop_price": po["stop_price"],
                        "initial_risk": risk,
                        "locked": False,
                    }
                    pending_order = None
                    continue
                else:
                    pending_order = None
            else:
                pending_order = None

        # 3. Gatilho de Entrada
        if open_pos is None and pending_order is None:
            h = ts[i].hour
            m = ts[i].minute
            time_val = h * 60 + m

            if ny_session_only:
                # 13:00 às 17:30 UTC
                in_session = (13 * 60 <= time_val <= 17 * 60 + 30)
            else:
                # 07:00 às 18:00 UTC
                in_session = (7 * 60 <= time_val < 18 * 60)

            if not in_session:
                continue

            # Super Tendência
            strong_trend = adx[i - 1] >= 25.0
            bullish_macro = (closes[i - 1] > mme80[i - 1] > mme200[i - 1])
            bearish_macro = (closes[i - 1] < mme80[i - 1] < mme200[i - 1])

            slope_bullish = (0.10 <= slope80[i - 1] <= 1.00)
            slope_bearish = (-1.00 <= slope80[i - 1] <= -0.10)

            # Trap na MME8
            if strong_trend and bullish_macro and slope_bullish:
                touched_mme8 = (lows[i] <= mme8_entry[i] * 1.001)
                trap_fundo = (lows[i] < lows[i - 1]) and (closes[i] > lows[i - 1]) and (closes[i] > opens[i])
                if touched_mme8 and trap_fundo:
                    pending_order = {
                        "direction": "long",
                        "trigger_price": highs[i],
                        "stop_price": lows[i],
                    }

            elif strong_trend and bearish_macro and slope_bearish:
                touched_mme8 = (highs[i] >= mme8_entry[i] * 0.999)
                trap_topo = (highs[i] > highs[i - 1]) and (closes[i] < highs[i - 1]) and (closes[i] < opens[i])
                if touched_mme8 and trap_topo:
                    pending_order = {
                        "direction": "short",
                        "trigger_price": lows[i],
                        "stop_price": highs[i] + spread,
                    }

    return trades

def max_drawdown_r(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    r_curve = np.cumsum([t.r_multiple for t in trades])
    peak = np.maximum.accumulate(r_curve)
    dd = peak - r_curve
    return float(np.max(dd)) if len(dd) > 0 else 0.0

def main():
    print("=" * 105)
    print("  ESTUDO DE REFINAMENTO: CONDUÇÃO POR MME 20, TRAVA DE LUCRO E SESSÃO NY (5 ANOS: 2021-2026)")
    print("=" * 105)

    timeframes = ["10min", "15min"]
    ma_options = [
        ("mme8", False, "MME 8 Pura"),
        ("mma9", False, "MMA 9 Clássica"),
        ("mme20", False, "MME 20 Tendência"),
        ("mme20", True, "MME 20 + Trava 2R->+1R"),
    ]
    sessions = [
        (False, "Londres/NY (07-18h)"),
        (True, "Foco NY (13-17:30h)"),
    ]

    # Carrega dados
    data_store = {}
    for sym in SYMBOLS:
        data_store[sym] = {}
        for tf in timeframes:
            d = prepare_asset(sym, tf)
            if d:
                data_store[sym][tf] = d

    results = []

    for tf in timeframes:
        for sess_ny, sess_name in sessions:
            for ma_name, use_lock, ma_label in ma_options:
                tot_trades = 0
                tot_r = 0.0
                tot_is = 0.0
                tot_oos = 0.0
                all_trades = []
                sym_breakdown = {}

                for sym in SYMBOLS:
                    ad = data_store[sym].get(tf)
                    if not ad:
                        continue
                    tr = run_simulation(ad, ma_name, use_lock, sess_ny)
                    n = len(tr)
                    if n > 0:
                        r_vals = [t.r_multiple for t in tr]
                        r_tot = sum(r_vals)
                        wins = sum(1 for t in tr if t.win)
                        split_dt = pd.Timestamp("2024-11-01", tz="UTC")
                        is_r = sum(t.r_multiple for t in tr if t.entry_time < split_dt)
                        oos_r = sum(t.r_multiple for t in tr if t.entry_time >= split_dt)

                        tot_trades += n
                        tot_r += r_tot
                        tot_is += is_r
                        tot_oos += oos_r
                        all_trades.extend(tr)
                        sym_breakdown[sym] = (r_tot, n, 100.0 * wins / n)
                    else:
                        sym_breakdown[sym] = (0.0, 0, 0.0)

                wr = 100.0 * sum(1 for t in all_trades if t.win) / tot_trades if tot_trades > 0 else 0.0
                gp = sum(t.r_multiple for t in all_trades if t.r_multiple > 0)
                gl = -sum(t.r_multiple for t in all_trades if t.r_multiple < 0)
                pf = gp / gl if gl > 0 else float("inf")
                dd = max_drawdown_r(all_trades)

                tf_str = "M10" if tf == "10min" else "M15"
                results.append({
                    "tf": tf_str,
                    "sess": sess_name,
                    "ma": ma_label,
                    "trades": tot_trades,
                    "r_total": tot_r,
                    "r_ano": tot_r / 5.0,
                    "wr": wr,
                    "pf": pf,
                    "dd": dd,
                    "is_r": tot_is,
                    "oos_r": tot_oos,
                    "breakdown": sym_breakdown,
                })

    results.sort(key=lambda x: x["r_total"], reverse=True)

    print(f"{'#':>2s} | {'TF':4s} | {'Sessão':18s} | {'Condução':22s} | {'Trades':>6s} | {'R Total':>8s} | {'R/ano':>7s} | {'WR %':>6s} | {'PF':>5s} | {'MaxDD':>6s} | {'IS (3a)':>8s} | {'OOS (2a)':>9s}")
    print("-" * 125)

    for idx, r in enumerate(results, 1):
        print(f"{idx:2d} | {r['tf']:4s} | {r['sess']:18s} | {r['ma']:22s} | {r['trades']:6d} | {r['r_total']:7.1f}R | {r['r_ano']:6.1f}R | {r['wr']:5.1f}% | {r['pf']:5.2f} | {r['dd']:5.1f}R | {r['is_r']:7.1f}R | {r['oos_r']:8.1f}R")

    print("\n" + "=" * 105)
    print("  DETALHE POR ATIVO DAS 3 MELHORES CONFIGURAÇÕES (5 ANOS)")
    print("=" * 105)

    for rank in range(min(3, len(results))):
        best = results[rank]
        print(f"\n--- Rank #{rank+1}: {best['tf']} | {best['sess']} | {best['ma']} ---")
        print(f"Total Carteira: {best['r_total']:.1f}R em 5 anos ({best['r_ano']:.1f}R/ano, PF {best['pf']:.2f}, MaxDD {best['dd']:.1f}R, IS {best['is_r']:.1f}R, OOS {best['oos_r']:.1f}R)")
        print(f"{'Ativo':8s} | {'R Total':>8s} | {'Trades':>6s} | {'Acerto %':>8s}")
        print("-" * 36)
        for sym in SYMBOLS:
            sym_r, sym_n, sym_wr = best["breakdown"][sym]
            print(f"{sym:8s} | {sym_r:7.1f}R | {sym_n:6d} | {sym_wr:7.1f}%")

if __name__ == "__main__":
    main()

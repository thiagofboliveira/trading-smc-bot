"""Estudo Comparativo de Setups Seguidor de Tendência nos Índices (5 Anos: 2021-2026).

Setups Avaliados:
1. TRAP na MME 8 (falso rompimento da barra anterior na média)
2. INSIDE BAR na Média (contração de volatilidade na MME 8 ou MME 20)
3. PINBAR / REJEIÇÃO na Média (martelo / estrela cadente com pavio >= 50% na média)
4. ENGOLFO na Média (barra engolfando a barra anterior após toque na média)
5. BARRA DE FORÇA / PONTO CONTÍNUO (barra direcional fechando no terço extremo a partir da média)

Filtro Macro Causal:
- ADX(14) >= 25 em i-1
- MME 80 e MME 200 alinhadas em i-1
- Slope da MME 80 normalizado por ATR em [0.10, 1.00] em i-1

Execução Causal:
- Ordem BuyStop/SellStop armada na barra i
- Execução na violação do gatilho na barra i+1 ou posterior
- Saída por condução de média (MME 20 institucional e MME 8 rápida)
- Spreads reais: NAS100 = 1.5 pts, US30 = 2.0 pts
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
    setup_name: str
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
    time_vals: np.ndarray   # hour * 60 + minute (otimização ultra-rápida)
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
    time_vals = (df.index.hour * 60 + df.index.minute).to_numpy(dtype=np.int32)

    return AssetData(
        symbol=sym,
        tf_name=tf_label,
        opens=df["open"].to_numpy(dtype=float),
        highs=df["high"].to_numpy(dtype=float),
        lows=df["low"].to_numpy(dtype=float),
        closes=df["close"].to_numpy(dtype=float),
        time_vals=time_vals,
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

def run_setup_simulation(
    ad: AssetData,
    setup_name: str,          # 'trap', 'inside_bar', 'pinbar', 'engolfo', 'barra_forca'
    conduction_ma: str,       # 'mme20', 'mme8'
    ny_session_only: bool,     # True = 13:00-17:30 UTC / False = 07:00-18:00 UTC
) -> list[Trade]:
    n = ad.n
    if n < 250:
        return []

    opens, highs, lows, closes = ad.opens, ad.highs, ad.lows, ad.closes
    ts = ad.ts
    time_vals = ad.time_vals
    mme8, mme20 = ad.mme8, ad.mme20
    mme80, mme200, adx, slope80 = ad.mme80, ad.mme200, ad.adx14, ad.slope80
    spread = ad.spread
    symbol = ad.symbol

    ma_cond = ad.mme20 if conduction_ma == "mme20" else ad.mme8

    trades = []
    open_pos = None
    pending_order = None

    t_start = 13 * 60 if ny_session_only else 7 * 60
    t_end = 17 * 60 + 30 if ny_session_only else 18 * 60

    for i in range(210, n - 1):
        # 1. Gerenciar Posição Aberta
        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_sl = False
            exit_by_ma = False

            # Stop Loss
            if d == 1:
                if lows[i] <= pos["stop_price"]:
                    hit_sl = True
            else:
                if highs[i] + spread >= pos["stop_price"]:
                    hit_sl = True

            # Saída Causal por Fechamento além da Média
            if i > pos["entry_idx"]:
                if d == 1 and closes[i] < ma_cond[i]:
                    exit_by_ma = True
                elif d == -1 and closes[i] > ma_cond[i]:
                    exit_by_ma = True

            if hit_sl:
                if d == 1:
                    raw_exit = min(pos["stop_price"], opens[i])
                    exit_price = raw_exit - 1.0
                    r = (exit_price - pos["entry_price"]) / pos["initial_risk"]
                else:
                    raw_exit = max(pos["stop_price"], opens[i] + spread)
                    exit_price = raw_exit + 1.0
                    r = (pos["entry_price"] - exit_price) / pos["initial_risk"]
                trades.append(Trade(
                    symbol=symbol,
                    setup_name=setup_name,
                    direction=pos["direction"],
                    entry_time=pos["entry_time"],
                    exit_time=ts[i],
                    entry_price=pos["entry_price"],
                    stop_price=pos["stop_price"],
                    exit_price=exit_price,
                    exit_reason="STOP_LOSS",
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
                    setup_name=setup_name,
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

        # 2. Ordem Armada (Stop Limit na violação do candle que gerou o sinal)
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
                    entry_stopped = False
                    if d == 1:
                        if lows[i] <= po["stop_price"]:
                            entry_stopped = True
                            raw_exit = min(po["stop_price"], opens[i])
                            exit_price = raw_exit - 1.0
                            r = (exit_price - exec_price) / risk
                    else:
                        if highs[i] + spread >= po["stop_price"]:
                            entry_stopped = True
                            raw_exit = max(po["stop_price"], opens[i] + spread)
                            exit_price = raw_exit + 1.0
                            r = (exec_price - exit_price) / risk

                    if entry_stopped:
                        trades.append(Trade(
                            symbol=symbol,
                            setup_name=setup_name,
                            direction=po["direction"],
                            entry_time=ts[i],
                            exit_time=ts[i],
                            entry_price=exec_price,
                            stop_price=po["stop_price"],
                            exit_price=exit_price,
                            exit_reason="STOP_LOSS_ENTRY",
                            r_multiple=r,
                            win=r > 0,
                        ))
                        open_pos = None
                        pending_order = None
                        continue
                    else:
                        open_pos = {
                            "direction": po["direction"],
                            "entry_idx": i,
                            "entry_time": ts[i],
                            "entry_price": exec_price,
                            "stop_price": po["stop_price"],
                            "initial_risk": risk,
                        }
                    pending_order = None
                    continue
                else:
                    pending_order = None
            else:
                # Se não acionou na barra seguinte, a ordem é cancelada para evitar ordens zumbis
                pending_order = None

        # 3. Identificar Sinal do Setup na barra i
        if open_pos is None and pending_order is None:
            t_val = time_vals[i]
            if not (t_start <= t_val <= t_end):
                continue

            # Super Tendência Causal (medida em i-1)
            strong_trend = adx[i - 1] >= 25.0
            bullish_macro = (closes[i - 1] > mme80[i - 1] > mme200[i - 1])
            bearish_macro = (closes[i - 1] < mme80[i - 1] < mme200[i - 1])
            slope_bullish = (0.10 <= slope80[i - 1] <= 1.00)
            slope_bearish = (-1.00 <= slope80[i - 1] <= -0.10)

            c_range = highs[i] - lows[i]
            if c_range <= 0:
                continue

            # -------------------------------------------------------------
            # SETUP 1: TRAP na MME 8
            # -------------------------------------------------------------
            if setup_name == "trap":
                if strong_trend and bullish_macro and slope_bullish:
                    touched_mme8 = (lows[i] <= mme8[i] * 1.001)
                    trap_fundo = (lows[i] < lows[i - 1]) and (closes[i] > lows[i - 1]) and (closes[i] > opens[i])
                    if touched_mme8 and trap_fundo:
                        pending_order = {"direction": "long", "trigger_price": highs[i], "stop_price": lows[i]}
                elif strong_trend and bearish_macro and slope_bearish:
                    touched_mme8 = (highs[i] >= mme8[i] * 0.999)
                    trap_topo = (highs[i] > highs[i - 1]) and (closes[i] < highs[i - 1]) and (closes[i] < opens[i])
                    if touched_mme8 and trap_topo:
                        pending_order = {"direction": "short", "trigger_price": lows[i], "stop_price": highs[i] + spread}

            # -------------------------------------------------------------
            # SETUP 2: INSIDE BAR na Média (MME 8 ou MME 20)
            # -------------------------------------------------------------
            elif setup_name == "inside_bar":
                is_inside = (highs[i] <= highs[i - 1]) and (lows[i] >= lows[i - 1])
                if is_inside and strong_trend:
                    if bullish_macro and slope_bullish:
                        # Tocou MME 8 ou MME 20
                        touched_ma = (lows[i] <= max(mme8[i], mme20[i]) * 1.001)
                        if touched_ma:
                            pending_order = {"direction": "long", "trigger_price": highs[i], "stop_price": lows[i]}
                    elif bearish_macro and slope_bearish:
                        touched_ma = (highs[i] >= min(mme8[i], mme20[i]) * 0.999)
                        if touched_ma:
                            pending_order = {"direction": "short", "trigger_price": lows[i], "stop_price": highs[i] + spread}

            # -------------------------------------------------------------
            # SETUP 3: PINBAR / REJEIÇÃO na Média (Pavio >= 50%)
            # -------------------------------------------------------------
            elif setup_name == "pinbar":
                if strong_trend:
                    if bullish_macro and slope_bullish:
                        touched_ma = (lows[i] <= max(mme8[i], mme20[i]) * 1.001)
                        lower_wick = min(opens[i], closes[i]) - lows[i]
                        is_bull_pin = (lower_wick / c_range >= 0.50) and (closes[i] >= lows[i] + 0.55 * c_range)
                        if touched_ma and is_bull_pin:
                            pending_order = {"direction": "long", "trigger_price": highs[i], "stop_price": lows[i]}
                    elif bearish_macro and slope_bearish:
                        touched_ma = (highs[i] >= min(mme8[i], mme20[i]) * 0.999)
                        upper_wick = highs[i] - max(opens[i], closes[i])
                        is_bear_pin = (upper_wick / c_range >= 0.50) and (closes[i] <= lows[i] + 0.45 * c_range)
                        if touched_ma and is_bear_pin:
                            pending_order = {"direction": "short", "trigger_price": lows[i], "stop_price": highs[i] + spread}

            # -------------------------------------------------------------
            # SETUP 4: ENGOLFO na Média
            # -------------------------------------------------------------
            elif setup_name == "engolfo":
                if strong_trend:
                    if bullish_macro and slope_bullish:
                        touched_ma = (lows[i] <= max(mme8[i], mme20[i]) * 1.001)
                        prev_bear = closes[i - 1] < opens[i - 1]
                        bull_engulf = (closes[i] > opens[i]) and (closes[i] >= opens[i - 1]) and (opens[i] <= closes[i - 1])
                        if touched_ma and prev_bear and bull_engulf:
                            pending_order = {"direction": "long", "trigger_price": highs[i], "stop_price": lows[i]}
                    elif bearish_macro and slope_bearish:
                        touched_ma = (highs[i] >= min(mme8[i], mme20[i]) * 0.999)
                        prev_bull = closes[i - 1] > opens[i - 1]
                        bear_engulf = (closes[i] < opens[i]) and (closes[i] <= opens[i - 1]) and (opens[i] >= closes[i - 1])
                        if touched_ma and prev_bull and bear_engulf:
                            pending_order = {"direction": "short", "trigger_price": lows[i], "stop_price": highs[i] + spread}

            # -------------------------------------------------------------
            # SETUP 5: BARRA DE FORÇA / PONTO CONTÍNUO (Oliver Velez / LW 9.3)
            # -------------------------------------------------------------
            elif setup_name == "barra_forca":
                if strong_trend:
                    if bullish_macro and slope_bullish:
                        touched_ma = (lows[i] <= max(mme8[i], mme20[i]) * 1.001)
                        # Barra fecha com forte ímpeto no terço superior (>= 70% do range) e fecha acima da MME 8
                        strong_bull = (closes[i] > opens[i]) and ((closes[i] - lows[i]) / c_range >= 0.70) and (closes[i] > mme8[i])
                        if touched_ma and strong_bull:
                            pending_order = {"direction": "long", "trigger_price": highs[i], "stop_price": lows[i]}
                    elif bearish_macro and slope_bearish:
                        touched_ma = (highs[i] >= min(mme8[i], mme20[i]) * 0.999)
                        strong_bear = (closes[i] < opens[i]) and ((highs[i] - closes[i]) / c_range >= 0.70) and (closes[i] < mme8[i])
                        if touched_ma and strong_bear:
                            pending_order = {"direction": "short", "trigger_price": lows[i], "stop_price": highs[i] + spread}

    return trades

def max_drawdown_r(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    r_curve = np.cumsum([t.r_multiple for t in trades])
    peak = np.maximum.accumulate(r_curve)
    dd = peak - r_curve
    return float(np.max(dd)) if len(dd) > 0 else 0.0

def main():
    print("=" * 115)
    print("  COMPARAÇÃO DE SETUPS DE TENDÊNCIA: TRAP vs INSIDE BAR vs PINBAR vs ENGOLFO vs BARRA DE FORÇA")
    print("  DADOS REAIS DE 5 ANOS (2021-2026) | ÍNDICES (NAS100 e US30) | SPREADS REAIS")
    print("=" * 115)

    timeframes = ["10min", "15min"]
    setups = [
        ("trap", "Trap na MME 8"),
        ("inside_bar", "Inside Bar na Média"),
        ("pinbar", "Pinbar / Rejeição (Pavio 50%)"),
        ("engolfo", "Engolfo na Média"),
        ("barra_forca", "Barra de Força (Ponto Contínuo)"),
    ]
    conductions = [
        ("mme20", "MME 20 Institucional"),
        ("mme8", "MME 8 Rápida"),
    ]
    sessions = [
        (True, "Foco NY (13-17:30h)"),
        (False, "Londres/NY (07-18h)"),
    ]

    print("\nCarregando dados históricos e pré-computando indicadores...")
    data_store = {}
    for sym in SYMBOLS:
        data_store[sym] = {}
        for tf in timeframes:
            d = prepare_asset(sym, tf)
            if d:
                data_store[sym][tf] = d
    print("Dados carregados com sucesso!\n")

    results = []
    split_dt = pd.Timestamp("2024-11-01", tz="UTC")

    for tf in timeframes:
        tf_label = "M10" if tf == "10min" else "M15"
        for sess_ny, sess_name in sessions:
            for cond_ma, cond_name in conductions:
                for setup_id, setup_name in setups:
                    all_trades = []
                    sym_breakdown = {}

                    for sym in SYMBOLS:
                        ad = data_store[sym].get(tf)
                        if not ad:
                            continue
                        tr = run_setup_simulation(ad, setup_id, cond_ma, sess_ny)
                        all_trades.extend(tr)

                        n_s = len(tr)
                        if n_s > 0:
                            r_s = sum(t.r_multiple for t in tr)
                            w_s = sum(1 for t in tr if t.win)
                            sym_breakdown[sym] = (r_s, n_s, 100.0 * w_s / n_s)
                        else:
                            sym_breakdown[sym] = (0.0, 0, 0.0)

                    tot_trades = len(all_trades)
                    if tot_trades == 0:
                        continue

                    r_vals = [t.r_multiple for t in all_trades]
                    tot_r = sum(r_vals)
                    wins = sum(1 for t in all_trades if t.win)
                    wr = 100.0 * wins / tot_trades
                    gp = sum(t.r_multiple for t in all_trades if t.r_multiple > 0)
                    gl = -sum(t.r_multiple for t in all_trades if t.r_multiple < 0)
                    pf = gp / gl if gl > 0 else float("inf")
                    dd = max_drawdown_r(all_trades)

                    is_r = sum(t.r_multiple for t in all_trades if t.entry_time < split_dt)
                    oos_r = sum(t.r_multiple for t in all_trades if t.entry_time >= split_dt)

                    results.append({
                        "tf": tf_label,
                        "sess": sess_name,
                        "cond": cond_name,
                        "setup": setup_name,
                        "trades": tot_trades,
                        "r_total": tot_r,
                        "r_ano": tot_r / 5.0,
                        "wr": wr,
                        "pf": pf,
                        "dd": dd,
                        "is_r": is_r,
                        "oos_r": oos_r,
                        "breakdown": sym_breakdown,
                    })

    # Ordena pelo R total
    results.sort(key=lambda x: x["r_total"], reverse=True)

    print(f"{'#':>2s} | {'Setup':30s} | {'TF':4s} | {'Sessão':18s} | {'Condução':20s} | {'Trades':>6s} | {'R Total':>8s} | {'R/ano':>7s} | {'WR %':>6s} | {'PF':>5s} | {'MaxDD':>6s} | {'IS':>7s} | {'OOS':>8s}")
    print("-" * 145)

    for idx, r in enumerate(results[:20], 1):
        print(f"{idx:2d} | {r['setup']:30s} | {r['tf']:4s} | {r['sess']:18s} | {r['cond']:20s} | {r['trades']:6d} | {r['r_total']:7.1f}R | {r['r_ano']:6.1f}R | {r['wr']:5.1f}% | {r['pf']:5.2f} | {r['dd']:5.1f}R | {r['is_r']:6.1f}R | {r['oos_r']:7.1f}R")

    print("\n" + "=" * 115)
    print("  DETALHE DOS 5 MELHORES MODELOS (NAS100 vs US30)")
    print("=" * 115)

    for rank in range(min(5, len(results))):
        best = results[rank]
        print(f"\n--- Rank #{rank+1}: {best['setup']} | {best['tf']} | {best['sess']} | {best['cond']} ---")
        print(f"Total: {best['r_total']:.1f}R ({best['r_ano']:.1f}R/ano, PF {best['pf']:.2f}, MaxDD {best['dd']:.1f}R, IS {best['is_r']:.1f}R, OOS {best['oos_r']:.1f}R)")
        print(f"{'Ativo':8s} | {'R Total':>8s} | {'Trades':>6s} | {'Acerto %':>8s}")
        print("-" * 36)
        for sym in SYMBOLS:
            sym_r, sym_n, sym_wr = best["breakdown"][sym]
            print(f"{sym:8s} | {sym_r:7.1f}R | {sym_n:6d} | {sym_wr:7.1f}%")

if __name__ == "__main__":
    main()

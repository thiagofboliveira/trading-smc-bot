"""Estudo de Estratégias para Mercado Lateral / Range-Bound (5 Anos: 2021-2026).

Objetivo:
Operar nos momentos em que NÃO há super tendência (ADX < 20, médias flat),
evitando operações de tendência e buscando reversão à média nos extremos do range.

Regime Lateral Causal (medido estritamente em i-1):
- ADX(14) < 20.0 (ausência de força direcional)
- Inclinação da MME 80 flat: abs(slope80) < 0.10

Setups Avaliados:
1. FALSE BREAKOUT / SWEEP DO RANGE (Falso rompimento do suporte/resistência de 20 barras)
2. BANDAS DE BOLLINGER REVERSÃO (Toque fora da banda de 2 desvios com retorno)
3. IFR(14) REVERSÃO EM RANGE (IFR < 30 na compra ou IFR > 70 na venda)

Alvos Testados:
- Alvo no centro do range (MME 20)
- Alvo fixo de 1.5R
- Alvo fixo de 2.0R

Timeframes: M15 e M10 nos 5 anos completos.
"""

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

SYMBOLS = ["NAS100", "US30", "BRENT", "EURUSD", "GBPUSD", "XAUUSD"]
SPREADS = {
    "US30": 2.0,
    "NAS100": 1.5,
    "BRENT": 0.03,
    "EURUSD": 0.00010,
    "GBPUSD": 0.00015,
    "XAUUSD": 0.25,
}

@dataclass
class Trade:
    symbol: str
    setup_name: str
    target_mode: str
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
class RangeAssetData:
    symbol: str
    tf_name: str
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    time_vals: np.ndarray
    ts: pd.DatetimeIndex
    mme20: np.ndarray
    mme80: np.ndarray
    mme200: np.ndarray
    adx14: np.ndarray
    slope80: np.ndarray
    bb_upper: np.ndarray
    bb_lower: np.ndarray
    bb_mid: np.ndarray
    rsi14: np.ndarray
    range_high_20: np.ndarray
    range_low_20: np.ndarray
    spread: float
    n: int

def prepare_range_asset(sym: str, tf: str) -> RangeAssetData | None:
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
    slope80 = ((close.ewm(span=80, adjust=False).mean() - close.ewm(span=80, adjust=False).mean().shift(10)) / (10 * atr.replace(0, np.nan))).fillna(0).to_numpy(dtype=float)

    # Bollinger Bands (20, 2)
    bb_mid = close.rolling(window=20).mean()
    bb_std = close.rolling(window=20).std()
    bb_upper = (bb_mid + 2.0 * bb_std).fillna(0).to_numpy(dtype=float)
    bb_lower = (bb_mid - 2.0 * bb_std).fillna(0).to_numpy(dtype=float)
    bb_mid_arr = bb_mid.fillna(0).to_numpy(dtype=float)

    # RSI(14)
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(window=14).mean()
    loss = (-delta.clip(upper=0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi14 = (100 - (100 / (1 + rs))).fillna(50).to_numpy(dtype=float)

    # Range High/Low de 20 barras (shiftado por 1 para ser estritamente causal em i-1)
    range_high_20 = high.shift(1).rolling(window=20).max().fillna(0).to_numpy(dtype=float)
    range_low_20 = low.shift(1).rolling(window=20).min().fillna(0).to_numpy(dtype=float)

    tf_label = "M10" if tf == "10min" else "M15"
    time_vals = (df.index.hour * 60 + df.index.minute).to_numpy(dtype=np.int32)

    return RangeAssetData(
        symbol=sym,
        tf_name=tf_label,
        opens=df["open"].to_numpy(dtype=float),
        highs=df["high"].to_numpy(dtype=float),
        lows=df["low"].to_numpy(dtype=float),
        closes=df["close"].to_numpy(dtype=float),
        time_vals=time_vals,
        ts=df.index,
        mme20=mme20,
        mme80=mme80,
        mme200=mme200,
        adx14=adx14,
        slope80=slope80,
        bb_upper=bb_upper,
        bb_lower=bb_lower,
        bb_mid=bb_mid_arr,
        rsi14=rsi14,
        range_high_20=range_high_20,
        range_low_20=range_low_20,
        spread=SPREADS[sym],
        n=len(df),
    )

def run_range_simulation(
    ad: RangeAssetData,
    setup_name: str,          # 'sweep_range', 'bollinger', 'rsi_extremo'
    target_mode: str,         # 'center_ma', '1.5R', '2.0R'
) -> list[Trade]:
    n = ad.n
    if n < 220:
        return []

    opens, highs, lows, closes = ad.opens, ad.highs, ad.lows, ad.closes
    ts = ad.ts
    time_vals = ad.time_vals
    adx = ad.adx14
    slope80 = ad.slope80
    bb_u = ad.bb_upper
    bb_l = ad.bb_lower
    bb_m = ad.bb_mid
    rsi = ad.rsi14
    r_h = ad.range_high_20
    r_l = ad.range_low_20
    mme20 = ad.mme20
    spread = ad.spread
    symbol = ad.symbol

    trades: list[Trade] = []
    open_pos = None
    pending_order = None

    for i in range(210, n - 1):
        # 1. Posição Aberta
        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_sl = False
            hit_tp = False
            exit_by_center = False

            # Stop Loss
            if d == 1:
                if lows[i] <= pos["stop_price"]:
                    hit_sl = True
            else:
                if highs[i] + spread >= pos["stop_price"]:
                    hit_sl = True

            # Target fixo
            if pos["target_price"] is not None:
                if d == 1:
                    if highs[i] >= pos["target_price"]:
                        hit_tp = True
                else:
                    if lows[i] <= pos["target_price"]:
                        hit_tp = True

            # Target no centro do range (MME 20)
            if target_mode == "center_ma" and i > pos["entry_idx"]:
                if d == 1 and closes[i] >= mme20[i]:
                    exit_by_center = True
                elif d == -1 and closes[i] <= mme20[i]:
                    exit_by_center = True

            if hit_sl:
                exit_price = pos["stop_price"]
                r = (exit_price - pos["entry_price"]) / pos["initial_risk"] if d == 1 else (pos["entry_price"] - exit_price) / pos["initial_risk"]
                trades.append(Trade(symbol, setup_name, target_mode, pos["direction"], pos["entry_time"], ts[i], pos["entry_price"], pos["stop_price"], exit_price, "STOP_LOSS", float(r), False))
                open_pos = None
                pending_order = None
                continue

            elif hit_tp:
                exit_price = pos["target_price"]
                r = (exit_price - pos["entry_price"]) / pos["initial_risk"] if d == 1 else (pos["entry_price"] - exit_price) / pos["initial_risk"]
                trades.append(Trade(symbol, setup_name, target_mode, pos["direction"], pos["entry_time"], ts[i], pos["entry_price"], pos["stop_price"], exit_price, "TAKE_PROFIT", float(r), True))
                open_pos = None
                pending_order = None
                continue

            elif exit_by_center and i < n - 1:
                exit_price = opens[i + 1] if d == 1 else opens[i + 1] + spread
                r = (exit_price - pos["entry_price"]) / pos["initial_risk"] if d == 1 else (pos["entry_price"] - exit_price) / pos["initial_risk"]
                trades.append(Trade(symbol, setup_name, target_mode, pos["direction"], pos["entry_time"], ts[i + 1], pos["entry_price"], pos["stop_price"], exit_price, "CENTER_MA", float(r), r > 0))
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
                    tp_price = None
                    if target_mode == "1.5R":
                        tp_price = exec_price + 1.5 * risk if d == 1 else exec_price - 1.5 * risk
                    elif target_mode == "2.0R":
                        tp_price = exec_price + 2.0 * risk if d == 1 else exec_price - 2.0 * risk

                    open_pos = {
                        "direction": po["direction"],
                        "entry_idx": i,
                        "entry_time": ts[i],
                        "entry_price": exec_price,
                        "stop_price": po["stop_price"],
                        "target_price": tp_price,
                        "initial_risk": risk,
                    }
                pending_order = None
                continue
            else:
                pending_order = None

        # 3. Identificar Sinal de Range
        if open_pos is None and pending_order is None:
            # Horário de sessão (evita madrugadas com spread alto)
            t_val = time_vals[i]
            if not (8 * 60 <= t_val <= 18 * 60):
                continue

            # REGIME LATERAL CAUSAL (medido em i-1)
            # 1. ADX baixo (ausência de super tendência)
            is_choppy = adx[i - 1] < 20.0
            # 2. Médias flats (inclinação próxima de zero)
            is_flat = abs(slope80[i - 1]) < 0.10

            if not (is_choppy and is_flat):
                continue

            c_range = highs[i] - lows[i]
            if c_range <= 0:
                continue

            # -------------------------------------------------------------
            # SETUP 1: SWEEP / FALSO ROMPIMENTO DO RANGE (Liquidity Grab)
            # -------------------------------------------------------------
            if setup_name == "sweep_range":
                # Falso rompimento do suporte (Spring no fundo do range)
                sweep_low = (lows[i] < r_l[i]) and (closes[i] > r_l[i]) and (closes[i] > opens[i])
                if sweep_low:
                    pending_order = {"direction": "long", "trigger_price": highs[i], "stop_price": lows[i]}

                # Falso rompimento da resistência (Upthrust no topo do range)
                sweep_high = (highs[i] > r_h[i]) and (closes[i] < r_h[i]) and (closes[i] < opens[i])
                if sweep_high:
                    pending_order = {"direction": "short", "trigger_price": lows[i], "stop_price": highs[i] + spread}

            # -------------------------------------------------------------
            # SETUP 2: BANDAS DE BOLLINGER REVERSÃO
            # -------------------------------------------------------------
            elif setup_name == "bollinger":
                # Toque fora da banda inferior com fechamento de volta
                touch_lower = (lows[i] < bb_l[i]) and (closes[i] > bb_l[i]) and (closes[i] > opens[i])
                if touch_lower:
                    pending_order = {"direction": "long", "trigger_price": highs[i], "stop_price": lows[i]}

                # Toque fora da banda superior com fechamento de volta
                touch_upper = (highs[i] > bb_u[i]) and (closes[i] < bb_u[i]) and (closes[i] < opens[i])
                if touch_upper:
                    pending_order = {"direction": "short", "trigger_price": lows[i], "stop_price": highs[i] + spread}

            # -------------------------------------------------------------
            # SETUP 3: IFR REVERSÃO EM RANGE
            # -------------------------------------------------------------
            elif setup_name == "rsi_extremo":
                if rsi[i - 1] < 30.0 and closes[i] > opens[i]:
                    pending_order = {"direction": "long", "trigger_price": highs[i], "stop_price": lows[i]}
                elif rsi[i - 1] > 70.0 and closes[i] < opens[i]:
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
    print("  ESTUDO DE REGIME: ESTRATÉGIAS PARA MERCADO LATERAL / RANGE (5 ANOS: 2021-2026)")
    print("  FILTRO: ADX < 20.0 + SLOPE MME80 FLAT (< 0.10) EM i-1 | DADOS REAIS DUKASCOPY")
    print("=" * 115)

    timeframes = ["15min", "10min"]
    setups = [
        ("sweep_range", "Falso Rompimento de Range (Sweep)"),
        ("bollinger", "Bandas de Bollinger Reversão"),
        ("rsi_extremo", "IFR(14) Extremo em Consolidação"),
    ]
    targets = [
        ("center_ma", "Saída na Média Central (MME20)"),
        ("1.5R", "Alvo Fixo 1.5R"),
        ("2.0R", "Alvo Fixo 2.0R"),
    ]

    print("\nCarregando dados históricos de 5 anos...")
    data_store = {}
    for sym in SYMBOLS:
        data_store[sym] = {}
        for tf in timeframes:
            d = prepare_range_asset(sym, tf)
            if d:
                data_store[sym][tf] = d
    print("Dados carregados com sucesso!\n")

    results = []
    split_dt = pd.Timestamp("2024-11-01", tz="UTC")

    for tf in timeframes:
        tf_label = "M15" if tf == "15min" else "M10"
        for setup_id, setup_name in setups:
            for tgt_id, tgt_name in targets:
                all_trades = []
                sym_breakdown = {}

                for sym in SYMBOLS:
                    ad = data_store[sym].get(tf)
                    if not ad:
                        continue
                    tr = run_range_simulation(ad, setup_id, tgt_id)
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
                    "setup": setup_name,
                    "target": tgt_name,
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

    results.sort(key=lambda x: x["r_total"], reverse=True)

    print(f"{'#':>2s} | {'Setup':35s} | {'TF':4s} | {'Alvo':28s} | {'Trades':>6s} | {'R Total':>8s} | {'WR %':>6s} | {'PF':>5s} | {'MaxDD':>6s} | {'IS':>7s} | {'OOS':>8s}")
    print("-" * 135)

    for idx, r in enumerate(results[:15], 1):
        print(f"{idx:2d} | {r['setup']:35s} | {r['tf']:4s} | {r['target']:28s} | {r['trades']:6d} | {r['r_total']:7.1f}R | {r['wr']:5.1f}% | {r['pf']:5.2f} | {r['dd']:5.1f}R | {r['is_r']:6.1f}R | {r['oos_r']:7.1f}R")

    print("\n" + "=" * 115)
    print("  DETALHE POR ATIVO DAS 3 MELHORES CONFIGURAÇÕES DE RANGE")
    print("=" * 115)

    for rank in range(min(3, len(results))):
        best = results[rank]
        print(f"\n--- Rank #{rank+1}: {best['setup']} | {best['tf']} | {best['target']} ---")
        print(f"Total: {best['r_total']:.1f}R em 5 anos ({best['r_ano']:.1f}R/ano, PF {best['pf']:.2f}, MaxDD {best['dd']:.1f}R, IS {best['is_r']:.1f}R, OOS {best['oos_r']:.1f}R)")
        print(f"{'Ativo':8s} | {'R Total':>8s} | {'Trades':>6s} | {'Acerto %':>8s}")
        print("-" * 36)
        for sym in SYMBOLS:
            sym_r, sym_n, sym_wr = best["breakdown"][sym]
            print(f"{sym:8s} | {sym_r:7.1f}R | {sym_n:6d} | {sym_wr:7.1f}%")

if __name__ == "__main__":
    main()

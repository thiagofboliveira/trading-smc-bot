"""Estudo Sistemático de Wyckoff em Mercados Laterais (5 Anos: 2021-2026).

Metodologia de Wyckoff para Consolidações:
1. Identificação do Trading Range (TR):
   - Lookback de N barras (20, 40, 60 barras M15)
   - Largura mínima do range: TR_High - TR_Low >= 2.0 * ATR(14) para garantir espaço para andar
2. Fase C (O Teste / Manipulação de Liquidez):
   - SPRING (Compra): Fura o suporte do range (TR_Low), absorve liquidez e fecha de volta
     para dentro do range com pavio inferior >= 40% da barra.
   - UTAD / UPTHRUST (Venda): Fura a resistência do range (TR_High), absorve liquidez e fecha
     de volta para dentro do range com pavio superior >= 40% da barra.
3. Confirmação / Execução Causal:
   - Ordem Stop armada na barra i
   - Execução na violação do extremo na barra i+1 em diante
   - Stop loss no extremo do Spring/UTAD
4. Alvos Avaliados:
   - Alvo Fixo 2.5R
   - Alvo Fixo 3.0R
   - Alvo no Extremo Oposto do Range (Travessia completa do TR)
   - Alvo no Extremo Oposto com Trava de Lucro em +1.5R (move stop para BE)

Spreads reais aplicados:
NAS100: 1.5 pts | US30: 2.0 pts | BRENT: 0.03 | EURUSD: 1.0 pip | GBPUSD: 1.5 pips | XAUUSD: 0.25
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
    lookback: int
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
class WyckoffAssetData:
    symbol: str
    opens: np.ndarray
    highs: np.ndarray
    lows: np.ndarray
    closes: np.ndarray
    volumes: np.ndarray
    time_vals: np.ndarray
    ts: pd.DatetimeIndex
    atr14: np.ndarray
    vol_sma20: np.ndarray
    spread: float
    n: int

def prepare_wyckoff_asset(sym: str) -> WyckoffAssetData | None:
    p = Path(f"data/{sym}_M1_dukascopy.parquet")
    if not p.exists():
        return None
    df_m1 = pd.read_parquet(p)
    df = df_m1.resample("15min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna()

    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=14).mean().fillna(0).to_numpy(dtype=float)

    vol_sma = volume.rolling(window=20).mean().fillna(0).to_numpy(dtype=float)
    time_vals = (df.index.hour * 60 + df.index.minute).to_numpy(dtype=np.int32)

    return WyckoffAssetData(
        symbol=sym,
        opens=df["open"].to_numpy(dtype=float),
        highs=df["high"].to_numpy(dtype=float),
        lows=df["low"].to_numpy(dtype=float),
        closes=df["close"].to_numpy(dtype=float),
        volumes=volume.to_numpy(dtype=float),
        time_vals=time_vals,
        ts=df.index,
        atr14=atr,
        vol_sma20=vol_sma,
        spread=SPREADS[sym],
        n=len(df),
    )

def run_wyckoff_simulation(
    ad: WyckoffAssetData,
    lookback: int,            # 20, 40, 60 barras
    target_mode: str,         # '2.5R', '3.0R', 'opposite_extreme', 'opposite_lock'
    require_volume: bool,     # volume > média
) -> list[Trade]:
    n = ad.n
    if n < lookback + 50:
        return []

    opens, highs, lows, closes = ad.opens, ad.highs, ad.lows, ad.closes
    volumes = ad.volumes
    vol_sma = ad.vol_sma20
    atr = ad.atr14
    time_vals = ad.time_vals
    ts = ad.ts
    spread = ad.spread
    symbol = ad.symbol

    trades: list[Trade] = []
    open_pos = None
    pending_order = None

    for i in range(lookback + 20, n - 1):
        # 1. Posição Aberta
        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_sl = False
            hit_tp = False

            # Trava de lucro em +1.5R para breakeven
            if pos["use_lock"] and not pos["locked"]:
                if d == 1 and highs[i] >= pos["entry_price"] + 1.5 * pos["initial_risk"]:
                    pos["stop_price"] = pos["entry_price"]
                    pos["locked"] = True
                elif d == -1 and (lows[i] + spread) <= pos["entry_price"] - 1.5 * pos["initial_risk"]:
                    pos["stop_price"] = pos["entry_price"]
                    pos["locked"] = True

            # Stop Loss
            if d == 1:
                if lows[i] <= pos["stop_price"]:
                    hit_sl = True
            else:
                if highs[i] + spread >= pos["stop_price"]:
                    hit_sl = True

            # Take Profit
            if d == 1:
                if highs[i] >= pos["target_price"]:
                    hit_tp = True
            else:
                if lows[i] <= pos["target_price"]:
                    hit_tp = True

            if hit_sl:
                exit_price = pos["stop_price"]
                r = (exit_price - pos["entry_price"]) / pos["initial_risk"] if d == 1 else (pos["entry_price"] - exit_price) / pos["initial_risk"]
                trades.append(Trade(symbol, lookback, target_mode, pos["direction"], pos["entry_time"], ts[i], pos["entry_price"], pos["stop_price"], exit_price, "STOP_LOSS", float(r), r > 0))
                open_pos = None
                pending_order = None
                continue

            elif hit_tp:
                exit_price = pos["target_price"]
                r = (exit_price - pos["entry_price"]) / pos["initial_risk"] if d == 1 else (pos["entry_price"] - exit_price) / pos["initial_risk"]
                trades.append(Trade(symbol, lookback, target_mode, pos["direction"], pos["entry_time"], ts[i], pos["entry_price"], pos["stop_price"], exit_price, "TAKE_PROFIT", float(r), True))
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
                    tp_price = 0.0
                    use_lock = (target_mode == "opposite_lock")

                    if target_mode == "2.5R":
                        tp_price = exec_price + 2.5 * risk if d == 1 else exec_price - 2.5 * risk
                    elif target_mode == "3.0R":
                        tp_price = exec_price + 3.0 * risk if d == 1 else exec_price - 3.0 * risk
                    else:  # 'opposite_extreme' ou 'opposite_lock'
                        tp_price = po["tr_extreme"]

                    open_pos = {
                        "direction": po["direction"],
                        "entry_idx": i,
                        "entry_time": ts[i],
                        "entry_price": exec_price,
                        "stop_price": po["stop_price"],
                        "target_price": tp_price,
                        "initial_risk": risk,
                        "use_lock": use_lock,
                        "locked": False,
                    }
                pending_order = None
                continue
            else:
                pending_order = None

        # 3. Identificar Setup Wyckoff na barra i
        if open_pos is None and pending_order is None:
            t_val = time_vals[i]
            # Sessão Londres/NY (08:00 às 18:00 UTC)
            if not (8 * 60 <= t_val <= 18 * 60):
                continue

            # Trading Range estritamente causal medido de i - lookback até i - 1
            tr_high = np.max(highs[i - lookback : i])
            tr_low = np.min(lows[i - lookback : i])
            tr_width = tr_high - tr_low

            # Largura mínima de 2.0x ATR para evitar ranges minúsculos
            if tr_width < 2.0 * atr[i - 1]:
                continue

            c_range = highs[i] - lows[i]
            if c_range <= 0:
                continue

            vol_ok = True
            if require_volume and vol_sma[i] > 0:
                vol_ok = (volumes[i] >= 1.0 * vol_sma[i])

            if not vol_ok:
                continue

            # --- WYCKOFF SPRING (Compra) ---
            # Preço fura tr_low, mas fecha acima dele, com pavio inferior >= 40%
            pierced_support = lows[i] < tr_low
            closed_inside_bull = closes[i] > tr_low
            lower_wick = min(opens[i], closes[i]) - lows[i]
            wick_ratio_bull = lower_wick / c_range
            close_top_half = closes[i] >= lows[i] + 0.45 * c_range

            if pierced_support and closed_inside_bull and wick_ratio_bull >= 0.40 and close_top_half:
                pending_order = {
                    "direction": "long",
                    "trigger_price": highs[i],
                    "stop_price": lows[i],
                    "tr_extreme": tr_high,
                }

            # --- WYCKOFF UPTHRUST / UTAD (Venda) ---
            # Preço fura tr_high, mas fecha abaixo dele, com pavio superior >= 40%
            pierced_resistance = highs[i] > tr_high
            closed_inside_bear = closes[i] < tr_high
            upper_wick = highs[i] - max(opens[i], closes[i])
            wick_ratio_bear = upper_wick / c_range
            close_bottom_half = closes[i] <= lows[i] + 0.55 * c_range

            if pierced_resistance and closed_inside_bear and wick_ratio_bear >= 0.40 and close_bottom_half:
                pending_order = {
                    "direction": "short",
                    "trigger_price": lows[i],
                    "stop_price": highs[i] + spread,
                    "tr_extreme": tr_low,
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
    print("=" * 115)
    print("  ESTUDO DE WYCKOFF EM CONSOLIDAÇÕES: SPRING & UTAD (5 ANOS: 2021-2026)")
    print("  DADOS REAIS DUKASCOPY (M15) | SPREADS REAIS | 6 ATIVOS")
    print("=" * 115)

    lookbacks = [20, 40, 60]
    targets = [
        ("2.5R", "Alvo Fixo 2.5R"),
        ("3.0R", "Alvo Fixo 3.0R"),
        ("opposite_extreme", "Extremo Oposto do TR"),
        ("opposite_lock", "Extremo Oposto + Trava 1.5R"),
    ]

    print("\nCarregando dados históricos M15 de 5 anos...")
    data_store = {}
    for sym in SYMBOLS:
        d = prepare_wyckoff_asset(sym)
        if d:
            data_store[sym] = d
    print("Dados carregados com sucesso!\n")

    results = []
    split_dt = pd.Timestamp("2024-11-01", tz="UTC")

    for lb in lookbacks:
        for tgt_id, tgt_name in targets:
            for req_vol in [False, True]:
                vol_str = "Com Volume" if req_vol else "Sem Filtro Vol"
                all_trades = []
                sym_breakdown = {}

                for sym in SYMBOLS:
                    ad = data_store.get(sym)
                    if not ad:
                        continue
                    tr = run_wyckoff_simulation(ad, lb, tgt_id, req_vol)
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
                    "lookback": lb,
                    "target": tgt_name,
                    "vol": vol_str,
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

    print(f"{'#':>2s} | {'Lookback':9s} | {'Alvo':28s} | {'Volume':14s} | {'Trades':>6s} | {'R Total':>8s} | {'WR %':>6s} | {'PF':>5s} | {'MaxDD':>6s} | {'IS':>7s} | {'OOS':>8s}")
    print("-" * 125)

    for idx, r in enumerate(results[:15], 1):
        print(f"{idx:2d} | {r['lookback']:4d} bar | {r['target']:28s} | {r['vol']:14s} | {r['trades']:6d} | {r['r_total']:7.1f}R | {r['wr']:5.1f}% | {r['pf']:5.2f} | {r['dd']:5.1f}R | {r['is_r']:6.1f}R | {r['oos_r']:7.1f}R")

    print("\n" + "=" * 115)
    print("  DETALHE POR ATIVO DAS 3 MELHORES CONFIGURAÇÕES WYCKOFF (5 ANOS)")
    print("=" * 115)

    for rank in range(min(3, len(results))):
        best = results[rank]
        print(f"\n--- Rank #{rank+1}: {best['lookback']} barras | {best['target']} | {best['vol']} ---")
        print(f"Total Carteira: {best['r_total']:.1f}R em 5 anos ({best['r_ano']:.1f}R/ano, PF {best['pf']:.2f}, MaxDD {best['dd']:.1f}R, IS {best['is_r']:.1f}R, OOS {best['oos_r']:.1f}R)")
        print(f"{'Ativo':8s} | {'R Total':>8s} | {'Trades':>6s} | {'Acerto %':>8s}")
        print("-" * 36)
        for sym in SYMBOLS:
            sym_r, sym_n, sym_wr = best["breakdown"][sym]
            print(f"{sym:8s} | {sym_r:7.1f}R | {sym_n:6d} | {sym_wr:7.1f}%")

if __name__ == "__main__":
    main()

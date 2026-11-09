"""CAMINHO 2: Trend Following Sistemático Multi-Ativos em D1 e H4.

Objetivo:
Avaliar se uma carteira diversificada de Trend Following em D1 ou H4 é lucrativa globalmente,
operando 6 a 8 mercados distintos:
- Índices: NAS100, US30, GER40, SPX500
- Commodities: XAUUSD (Ouro), BRENT (Petróleo)
- FX: EURUSD, GBPUSD

Modelos Testados:
1. Donchian 20/10 (Rompimento do canal de 20 barras, saída no canal de 10 barras oposto).
2. Donchian 50/20 (Rompimento do canal de 50 barras, saída no canal de 20 barras oposto).
3. EMA Cross 20/50 com Trailing Stop 2.5x ATR.

Protocolo Anti-Viés (AGENTS.md):
- Indicadores em i-1 (shift(1)).
- Entradas no canal executadas no trigger ou Open com gap + spread + slippage.
- Checagem imediata de stop na barra de entrada.
- Stops em gap no Open.
- Spreads e slippage reais por ativo.
"""

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

SPREADS = {
    "XAUUSD": 0.20,
    "EURUSD": 0.00008,
    "GBPUSD": 0.00010,
    "US30": 2.0,
    "NAS100": 1.5,
    "BRENT": 0.03,
    "GER40": 1.5,
    "SPX500": 0.5,
}

SLIPPAGES = {
    "XAUUSD": 0.10,
    "EURUSD": 0.00005,
    "GBPUSD": 0.00005,
    "US30": 1.0,
    "NAS100": 1.0,
    "BRENT": 0.02,
    "GER40": 1.0,
    "SPX500": 0.5,
}


@dataclass
class Trade:
    symbol: str
    strategy: str
    tf: str
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_price: float
    exit_price: float
    exit_reason: str
    r_multiple: float
    win: bool


def calc_stats(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0, "wr": 0.0, "pf": 0.0, "total_r": 0.0, "mean_r": 0.0, "se_r": 0.0, "t_stat": 0.0, "max_dd": 0.0, "longs": 0, "shorts": 0}
    rs = np.array([t.r_multiple for t in trades])
    w = rs[rs > 0]
    l = rs[rs < 0]
    pf = (w.sum() / abs(l.sum())) if len(l) > 0 else 99.0
    wr = len(w) / len(rs) * 100.0
    se = rs.std(ddof=1) / np.sqrt(len(rs)) if len(rs) > 1 else 0.0
    t = rs.mean() / se if se > 0 else 0.0
    cum = np.cumsum(rs)
    dd = np.maximum.accumulate(cum) - cum
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0
    longs = sum(1 for tr in trades if tr.direction == "long")
    shorts = sum(1 for tr in trades if tr.direction == "short")
    return {
        "n": len(rs), "wr": wr, "pf": pf, "total_r": float(rs.sum()),
        "mean_r": float(rs.mean()), "se_r": float(se), "t_stat": float(t),
        "max_dd": max_dd, "longs": longs, "shorts": shorts,
    }


def compute_atr(df: pd.DataFrame, period: int = 20) -> np.ndarray:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().bfill()
    return atr.to_numpy(dtype=float)


def simulate_donchian(
    df: pd.DataFrame,
    symbol: str,
    tf_name: str,
    spread: float,
    slippage: float,
    entry_window: int = 20,
    exit_window: int = 10,
    atr_stop_mult: float = 2.0,
) -> list[Trade]:
    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    ts = df.index

    # Canais causais calculados em i-1
    dh_entry = df["high"].shift(1).rolling(entry_window).max().to_numpy(dtype=float)
    dl_entry = df["low"].shift(1).rolling(entry_window).min().to_numpy(dtype=float)
    dh_exit = df["high"].shift(1).rolling(exit_window).max().to_numpy(dtype=float)
    dl_exit = df["low"].shift(1).rolling(exit_window).min().to_numpy(dtype=float)
    atr = compute_atr(df.shift(1), period=20)

    trades: list[Trade] = []
    open_pos = None

    for i in range(entry_window + 5, len(df)):
        curr_time = ts[i]

        # 1. Gestão de posição aberta
        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_sl = False
            exit_by_rule = False
            exit_price = 0.0

            # Checa Stop Loss
            if d == 1:
                if lows[i] <= pos["stop_price"]:
                    hit_sl = True
                    raw_exit = min(pos["stop_price"], opens[i])
                    exit_price = raw_exit - slippage
            else:
                if highs[i] + spread >= pos["stop_price"]:
                    hit_sl = True
                    raw_exit = max(pos["stop_price"], opens[i] + spread)
                    exit_price = raw_exit + slippage

            # Checa Saída por canal oposto (após a barra de entrada)
            if not hit_sl and i > pos["entry_idx"]:
                if d == 1 and lows[i] <= dl_exit[i]:
                    exit_by_rule = True
                    raw_exit = min(dl_exit[i], opens[i])
                    exit_price = raw_exit - slippage
                elif d == -1 and highs[i] + spread >= dh_exit[i]:
                    exit_by_rule = True
                    raw_exit = max(dh_exit[i], opens[i] + spread)
                    exit_price = raw_exit + slippage

            if hit_sl or exit_by_rule:
                reason = "STOP_LOSS" if hit_sl else "DONCHIAN_EXIT"
                if d == 1:
                    r = (exit_price - pos["entry_price"]) / pos["initial_risk"]
                else:
                    r = (pos["entry_price"] - exit_price) / pos["initial_risk"]

                trades.append(
                    Trade(symbol, f"TURTLE_{entry_window}_{exit_window}", tf_name, pos["direction"], pos["entry_time"], curr_time, pos["entry_price"], pos["stop_price"], exit_price, reason, float(r), bool(r > 0))
                )
                open_pos = None
                continue

        # 2. Novas entradas (somente se desposicionado)
        if open_pos is None:
            long_trigger = dh_entry[i]
            short_trigger = dl_entry[i]

            triggered_long = highs[i] >= long_trigger
            triggered_short = lows[i] <= short_trigger

            # Se ambos romperam na mesma barra, conflito -> skip
            if triggered_long and triggered_short:
                continue

            if triggered_long:
                raw_fill = max(long_trigger, opens[i])
                fill_price = raw_fill + spread + slippage
                risk_pts = atr_stop_mult * atr[i]
                stop_price = fill_price - risk_pts

                # Checagem imediata de stop na barra de entrada
                if lows[i] <= stop_price:
                    raw_exit = min(stop_price, opens[i])
                    exit_price = raw_exit - slippage
                    r = (exit_price - fill_price) / risk_pts
                    trades.append(Trade(symbol, f"TURTLE_{entry_window}_{exit_window}", tf_name, "long", curr_time, curr_time, fill_price, stop_price, exit_price, "STOP_ENTRY_BAR", float(r), bool(r > 0)))
                else:
                    open_pos = {"entry_idx": i, "entry_time": curr_time, "direction": "long", "entry_price": fill_price, "stop_price": stop_price, "initial_risk": risk_pts}

            elif triggered_short:
                raw_fill = min(short_trigger, opens[i])
                fill_price = raw_fill - slippage
                risk_pts = atr_stop_mult * atr[i]
                stop_price = fill_price + risk_pts

                # Checagem imediata de stop na barra de entrada
                if highs[i] + spread >= stop_price:
                    raw_exit = max(stop_price, opens[i] + spread)
                    exit_price = raw_exit + slippage
                    r = (fill_price - exit_price) / risk_pts
                    trades.append(Trade(symbol, f"TURTLE_{entry_window}_{exit_window}", tf_name, "short", curr_time, curr_time, fill_price, stop_price, exit_price, "STOP_ENTRY_BAR", float(r), bool(r > 0)))
                else:
                    open_pos = {"entry_idx": i, "entry_time": curr_time, "direction": "short", "entry_price": fill_price, "stop_price": stop_price, "initial_risk": risk_pts}

    return trades


def run_caminho2():
    print("=" * 115)
    print("CAMINHO 2: TREND FOLLOWING SISTEMÁTICO MULTI-ATIVOS (D1 E H4)")
    print("=" * 115)

    asset_configs = [
        ("NAS100", "data/NAS100_M1_dukascopy.parquet"),
        ("US30", "data/US30_M1_dukascopy.parquet"),
        ("XAUUSD", "data/XAUUSD_M1_dukascopy.parquet"),
        ("BRENT", "data/BRENT_M1_dukascopy.parquet"),
        ("EURUSD", "data/EURUSD_M1_dukascopy.parquet"),
        ("GBPUSD", "data/GBPUSD_M1_dukascopy.parquet"),
        ("SPX500", "data/holdout/SPX500_M1.parquet"),
        ("GER40", "data/holdout/GER40_M1.parquet"),
    ]

    for tf_resample, tf_name in [("1D", "D1"), ("4h", "H4")]:
        print(f"\n========================== TIMEFRAME: {tf_name} ==========================")
        for strat_name, e_win, x_win in [("TURTLE_20_10", 20, 10), ("TURTLE_50_20", 50, 20)]:
            print(f"\n>>> MODELO: {strat_name} no {tf_name}")
            print(f"{'Ativo':<8} | {'Trades':<6} | {'Total R':<8} | {'R/trade':<18} | {'PF':<5} | {'WR':<6} | {'Longs/Shorts':<14} | {'MaxDD':<6}")
            print("-" * 90)

            all_trades: list[Trade] = []
            for sym, path in asset_configs:
                p = Path(path)
                if not p.exists():
                    continue
                df_m1 = pd.read_parquet(p)
                df_tf = df_m1.resample(tf_resample).agg({
                    "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
                }).dropna()
                # Saneamento de barras com volume < 20% da mediana
                df_tf = df_tf[df_tf["volume"] > 0.20 * df_tf["volume"].median()].copy()

                trades = simulate_donchian(df_tf, sym, tf_name, SPREADS[sym], SLIPPAGES[sym], entry_window=e_win, exit_window=x_win)
                st = calc_stats(trades)
                all_trades.extend(trades)
                print(f"{sym:<8} | {st['n']:<6d} | {st['total_r']:+7.1f}R | {st['mean_r']:+0.3f}±{st['se_r']:0.3f} (t={st['t_stat']:4.2f}) | {st['pf']:<5.2f} | {st['wr']:<5.1f}% | {st['longs']:2d}L / {st['shorts']:2d}S | {st['max_dd']:<5.1f}R")

            st_port = calc_stats(all_trades)
            print("-" * 90)
            print(f"CARTEIRA GLOBAL {tf_name} ({strat_name}): Trades={st_port['n']} | TotalR={st_port['total_r']:+.1f}R | R/trade={st_port['mean_r']:+.3f}±{st_port['se_r']:.3f} | t-stat={st_port['t_stat']:.2f} | PF={st_port['pf']:.2f} | WR={st_port['wr']:.1f}% | MaxDD={st_port['max_dd']:.1f}R")


if __name__ == "__main__":
    run_caminho2()

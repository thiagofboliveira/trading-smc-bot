"""CAMINHO 3: Arbitragem Estatística / Pairs Trading Intradiário (M5 e M15).

Pares Avaliados:
1. NAS100 vs SPX500 (Índices dos EUA - Cointegração de Ações)
2. EURUSD vs GBPUSD (Moedas Europeias - Cointegração FX)

Metodologia Quantitativa Estrita:
- Alinhamento de timestamps exatos entre os dois ativos.
- Rolling OLS para hedge ratio beta em i-1 (ou log price ratio).
- Rolling Z-Score do spread em i-1: Z = (Spread[i-1] - Mean[i-1]) / Std[i-1].
- Entrada: |Z| > 2.0 (executada no Open[i] de ambos os ativos com spread e slippage reais em cada ponta).
- Saída: Z cruza a média (0.0), ou stop de divergência (|Z| > 3.5), ou time stop no fim do dia.
- Fricção: Spread e slippage aplicados em AMBOS os ativos na entrada e na saída.
"""

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

SPREADS = {
    "NAS100": 1.5,
    "SPX500": 0.5,
    "EURUSD": 0.00008,
    "GBPUSD": 0.00010,
}

SLIPPAGES = {
    "NAS100": 1.0,
    "SPX500": 0.5,
    "EURUSD": 0.00005,
    "GBPUSD": 0.00005,
}


@dataclass
class PairTrade:
    pair_name: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    direction: str  # 'LONG_A_SHORT_B' ou 'SHORT_A_LONG_B'
    r_multiple: float
    win: bool
    exit_reason: str


def calc_stats(trades: list[PairTrade]) -> dict:
    if not trades:
        return {"n": 0, "wr": 0.0, "pf": 0.0, "total_r": 0.0, "mean_r": 0.0, "se_r": 0.0, "t_stat": 0.0, "max_dd": 0.0}
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
    return {"n": len(rs), "wr": wr, "pf": pf, "total_r": float(rs.sum()), "mean_r": float(rs.mean()), "se_r": float(se), "t_stat": float(t), "max_dd": max_dd}


def simulate_pairs_trading(
    df_a: pd.DataFrame,
    df_b: pd.DataFrame,
    sym_a: str,
    sym_b: str,
    lookback: int = 60,
    z_entry: float = 2.0,
    z_exit: float = 0.0,
    z_stop: float = 3.5,
    max_hold_bars: int = 48,
) -> list[PairTrade]:
    # Alinhamento inner por timestamp
    df = pd.DataFrame({
        "open_a": df_a["open"],
        "close_a": df_a["close"],
        "high_a": df_a["high"],
        "low_a": df_a["low"],
        "open_b": df_b["open"],
        "close_b": df_b["close"],
        "high_b": df_b["high"],
        "low_b": df_b["low"],
    }).dropna()

    if len(df) < lookback + 10:
        return []

    log_a = np.log(df["close_a"])
    log_b = np.log(df["close_b"])

    # Normalização de spread por log ratio
    # Spread[t] = log(A) - log(B)
    # Causal: rolling mean e std calculados em i-1 (shift(1))
    spread = log_a - log_b
    mean_spread = spread.shift(1).rolling(lookback).mean()
    std_spread = spread.shift(1).rolling(lookback).std().replace(0, 1e-6)
    z_score = ((spread.shift(1) - mean_spread) / std_spread).to_numpy(dtype=float)

    opens_a = df["open_a"].to_numpy(dtype=float)
    closes_a = df["close_a"].to_numpy(dtype=float)
    opens_b = df["open_b"].to_numpy(dtype=float)
    closes_b = df["close_b"].to_numpy(dtype=float)
    ts = df.index

    spread_a = SPREADS[sym_a]
    slip_a = SLIPPAGES[sym_a]
    spread_b = SPREADS[sym_b]
    slip_b = SLIPPAGES[sym_b]

    trades: list[PairTrade] = []
    open_pos = None

    for i in range(lookback + 5, len(df)):
        curr_time = ts[i]

        # 1. Gestão de posição aberta
        if open_pos is not None:
            pos = open_pos
            hold_bars = i - pos["entry_idx"]
            z_curr = z_score[i]
            hit_mean = False
            hit_stop = False

            if pos["direction"] == "SHORT_A_LONG_B":
                # Esperamos que Z caia de volta para 0
                if z_curr <= z_exit:
                    hit_mean = True
                elif z_curr >= z_stop:
                    hit_stop = True
            elif pos["direction"] == "LONG_A_SHORT_B":
                # Esperamos que Z suba de volta para 0
                if z_curr >= -z_exit:
                    hit_mean = True
                elif z_curr <= -z_stop:
                    hit_stop = True

            hit_time = hold_bars >= max_hold_bars

            if hit_mean or hit_stop or hit_time:
                # Saída a mercado no Open[i]
                if pos["direction"] == "SHORT_A_LONG_B":
                    # Fecha Short A (paga ask = open + spread + slippage)
                    exit_a = opens_a[i] + spread_a + slip_a
                    # Fecha Long B (vende bid = open - slippage)
                    exit_b = opens_b[i] - slip_b

                    pnl_a_pct = (pos["entry_a"] - exit_a) / pos["entry_a"]
                    pnl_b_pct = (exit_b - pos["entry_b"]) / pos["entry_b"]
                else:
                    # Fecha Long A (vende bid = open - slippage)
                    exit_a = opens_a[i] - slip_a
                    # Fecha Short B (paga ask = open + spread + slippage)
                    exit_b = opens_b[i] + spread_b + slip_b

                    pnl_a_pct = (exit_a - pos["entry_a"]) / pos["entry_a"]
                    pnl_b_pct = (pos["entry_b"] - exit_b) / pos["entry_b"]

                # Retorno combinado em % (50% alocado em cada ponta)
                total_pnl_pct = 0.5 * pnl_a_pct + 0.5 * pnl_b_pct
                # R-múltiplo: risco normalizado por trade (target risk ~ 0.5% por trade de spread)
                r_mult = total_pnl_pct / pos["risk_unit"]

                reason = "MEAN_REVERSION" if hit_mean else ("STOP_LOSS" if hit_stop else "TIME_STOP")
                trades.append(PairTrade(f"{sym_a}_{sym_b}", pos["entry_time"], curr_time, pos["direction"], float(r_mult), bool(r_mult > 0), reason))
                open_pos = None
                continue

        # 2. Novas Entradas
        if open_pos is None:
            z_curr = z_score[i]
            # Medida de risco aproximada: volatilidade do spread no lookback
            risk_unit = max(float(std_spread.iloc[i - 1]), 0.002)

            if z_curr > z_entry:
                # Short A, Long B
                entry_a = opens_a[i] - slip_a  # vende a mercado no bid
                entry_b = opens_b[i] + spread_b + slip_b  # compra a mercado no ask
                open_pos = {
                    "entry_idx": i,
                    "entry_time": curr_time,
                    "direction": "SHORT_A_LONG_B",
                    "entry_a": entry_a,
                    "entry_b": entry_b,
                    "risk_unit": risk_unit,
                }
            elif z_curr < -z_entry:
                # Long A, Short B
                entry_a = opens_a[i] + spread_a + slip_a  # compra no ask
                entry_b = opens_b[i] - slip_b  # vende no bid
                open_pos = {
                    "entry_idx": i,
                    "entry_time": curr_time,
                    "direction": "LONG_A_SHORT_B",
                    "entry_a": entry_a,
                    "entry_b": entry_b,
                    "risk_unit": risk_unit,
                }

    return trades


def run_caminho3():
    print("=" * 115)
    print("CAMINHO 3: ARBITRAGEM ESTATÍSTICA / PAIRS TRADING INTRADIÁRIO (M5 E M15)")
    print("=" * 115)

    pairs = [
        ("NAS100", "data/NAS100_M1_dukascopy.parquet", "SPX500", "data/holdout/SPX500_M1.parquet"),
        ("EURUSD", "data/EURUSD_M1_dukascopy.parquet", "GBPUSD", "data/GBPUSD_M1_dukascopy.parquet"),
    ]

    for tf_name in ["M15", "M5"]:
        print(f"\n========================== TIMEFRAME: {tf_name} ==========================")
        for sym_a, path_a, sym_b, path_b in pairs:
            p_a = Path(path_a)
            p_b = Path(path_b)
            if not p_a.exists() or not p_b.exists():
                continue

            df_a_m1 = pd.read_parquet(p_a)
            df_b_m1 = pd.read_parquet(p_b)

            resample_rule = "15min" if tf_name == "M15" else "5min"
            df_a = df_a_m1.resample(resample_rule).agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
            df_b = df_b_m1.resample(resample_rule).agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()

            for z_in, lb in [(2.0, 60), (2.5, 96), (1.8, 40)]:
                trades = simulate_pairs_trading(df_a, df_b, sym_a, sym_b, lookback=lb, z_entry=z_in)
                st = calc_stats(trades)
                print(f"PAR {sym_a}/{sym_b} ({tf_name} | Z>{z_in} | LB={lb}): Trades={st['n']:4d} | TotalR={st['total_r']:+7.1f}R | R/trade={st['mean_r']:+0.3f}±{st['se_r']:0.3f} (t={st['t_stat']:4.2f}) | PF={st['pf']:4.2f} | WR={st['wr']:4.1f}% | MaxDD={st['max_dd']:5.1f}R")


if __name__ == "__main__":
    run_caminho3()

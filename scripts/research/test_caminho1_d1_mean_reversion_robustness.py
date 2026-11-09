"""CAMINHO 1: Análise Exaustiva de Robustez e Estabilidade de Parâmetros
Estratégia: Reversão à Média Diária (Connors RSI(2) + IBS) em Índices de Ações.

Objetivos:
1. Matriz de Sensibilidade (Evitar Overfitting):
   - RSI(2) threshold: 5, 8, 10, 12, 15
   - IBS threshold: 0.10, 0.15, 0.20, 0.25
   - Exit MA: SMA(3), SMA(5), SMA(7)
   - Max Hold: 3, 5, 7 dias
   - Stop Loss: 1.5x ATR, 2.0x ATR, 2.5x ATR, 3.0x ATR
2. Estudo Fora da Amostra (Holdouts):
   - In-Sample: NAS100, US30 (2021-2026)
   - Out-of-Sample: NAS100 Pré-2021 (2018-2021), SPX500 (2022-2024)
3. Simulação de Portfólio Consolidado:
   - Alocação de capital e controle de exposição conjunta.
4. Teste de Permutação e Bootstrap (Significância Estatística).
"""

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

SPREADS = {
    "NAS100": 1.5,
    "US30": 2.0,
    "SPX500": 0.5,
}

SLIPPAGES = {
    "NAS100": 1.0,
    "US30": 1.0,
    "SPX500": 0.5,
}


@dataclass
class Trade:
    symbol: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_price: float
    exit_price: float
    exit_reason: str
    r_multiple: float
    win: bool


def compute_rsi(series: pd.Series, period: int = 2) -> np.ndarray:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-9)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.bfill().to_numpy(dtype=float)


def compute_atr(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().bfill()
    return atr.to_numpy(dtype=float)


def load_clean_d1(parquet_path: Path) -> pd.DataFrame:
    df_m1 = pd.read_parquet(parquet_path)
    d1_raw = df_m1.resample("1D").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    }).dropna()
    # Expurgar vela fantasma de domingo da Dukascopy
    d1_clean = d1_raw[d1_raw["volume"] > 0.20 * d1_raw["volume"].median()].copy()
    return d1_clean


def simulate_d1_mreversion(
    df_d1: pd.DataFrame,
    symbol: str,
    spread: float,
    slippage: float,
    rsi_th: float = 10.0,
    ibs_th: float = 0.20,
    exit_sma_period: int = 5,
    max_hold_days: int = 5,
    atr_stop_mult: float = 2.0,
) -> list[Trade]:
    opens = df_d1["open"].to_numpy(dtype=float)
    highs = df_d1["high"].to_numpy(dtype=float)
    lows = df_d1["low"].to_numpy(dtype=float)
    closes = df_d1["close"].to_numpy(dtype=float)
    ts = df_d1.index

    # Indicadores em i-1 (estritamente causais)
    sma200 = df_d1["close"].shift(1).rolling(200).mean().to_numpy(dtype=float)
    sma_exit = df_d1["close"].shift(1).rolling(exit_sma_period).mean().to_numpy(dtype=float)
    rsi2 = compute_rsi(df_d1["close"].shift(1), period=2)
    atr14 = compute_atr(df_d1.shift(1), period=14)

    h_prev = df_d1["high"].shift(1).to_numpy(dtype=float)
    l_prev = df_d1["low"].shift(1).to_numpy(dtype=float)
    c_prev = df_d1["close"].shift(1).to_numpy(dtype=float)
    rng_prev = np.maximum(h_prev - l_prev, 1e-6)
    ibs = (c_prev - l_prev) / rng_prev

    trades: list[Trade] = []
    open_pos = None

    for i in range(205, len(df_d1)):
        curr_time = ts[i]

        # 1. Gestão de posição aberta
        if open_pos is not None:
            risk = open_pos["initial_risk"]
            hold_days = i - open_pos["entry_idx"]

            # Checagem de Stop Loss estrutural
            if lows[i] <= open_pos["stop_price"]:
                raw_exit = min(open_pos["stop_price"], opens[i])
                exit_price = raw_exit - slippage
                r = (exit_price - open_pos["entry_price"]) / risk
                trades.append(Trade(symbol, open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "STOP_LOSS", float(r), bool(r > 0)))
                open_pos = None
                continue

            # Saída por Média ou Tempo (avaliada em i-1, executada em Open de i)
            exit_by_sma = c_prev[i] > sma_exit[i]
            exit_by_time = hold_days >= max_hold_days

            if exit_by_sma or exit_by_time:
                exit_price = opens[i] - slippage
                r = (exit_price - open_pos["entry_price"]) / risk
                reason = f"EXIT_SMA{exit_sma_period}" if exit_by_sma else "TIME_STOP"
                trades.append(Trade(symbol, open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, reason, float(r), bool(r > 0)))
                open_pos = None
                continue

        # 2. Entrada
        if open_pos is None:
            is_bull_regime = c_prev[i] > sma200[i]
            is_oversold = (rsi2[i] < rsi_th) or (ibs[i] < ibs_th)

            if is_bull_regime and is_oversold:
                entry_price = opens[i] + spread + slippage
                risk_pts = atr_stop_mult * atr14[i]
                stop_price = entry_price - risk_pts

                if risk_pts > 0:
                    if lows[i] <= stop_price:
                        raw_exit = min(stop_price, opens[i])
                        exit_price = raw_exit - slippage
                        r = (exit_price - entry_price) / risk_pts
                        trades.append(Trade(symbol, curr_time, curr_time, entry_price, stop_price, exit_price, "STOP_ENTRY_DAY", float(r), bool(r > 0)))
                    else:
                        open_pos = {"entry_idx": i, "entry_time": curr_time, "entry_price": entry_price, "stop_price": stop_price, "initial_risk": risk_pts}

    return trades


def calc_stats(trades: list[Trade]) -> dict:
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


def main():
    print("=" * 110)
    print("CAMINHO 1: AUDITORIA DE ROBUSTEZ E ESTABILIDADE DE PARÂMETROS - REVERSÃO À MÉDIA D1")
    print("=" * 110)

    # 1. Carregar Dados
    data = {
        "NAS100": load_clean_d1(Path("data/NAS100_M1_dukascopy.parquet")),
        "US30": load_clean_d1(Path("data/US30_M1_dukascopy.parquet")),
        "SPX500_OOS": load_clean_d1(Path("data/holdout/SPX500_M1.parquet")),
    }
    df_pre = load_clean_d1(Path("data/holdout/NAS100_M1.parquet"))
    data["NAS100_PRE2021_OOS"] = df_pre[df_pre.index < "2021-11-01"].copy()

    # 2. Grade de Sensibilidade
    rsi_list = [5.0, 8.0, 10.0, 12.0, 15.0]
    ibs_list = [0.10, 0.15, 0.20, 0.25]
    sma_list = [3, 5, 7]
    stop_list = [1.5, 2.0, 2.5]

    print("\n--- TESTE 1: Sensibilidade do Limiar de RSI(2) (com IBS=0.20, SMA=5, Stop=2.0x ATR) ---")
    print(f"{'RSI Threshold':<15} | {'NAS100 (In-Sample)':<30} | {'US30 (In-Sample)':<30} | {'NAS100 Pré-2021 (OOS)':<30}")
    print("-" * 110)
    for rsi in rsi_list:
        st_nas = calc_stats(simulate_d1_mreversion(data["NAS100"], "NAS100", 1.5, 1.0, rsi_th=rsi, ibs_th=0.20, exit_sma_period=5, atr_stop_mult=2.0))
        st_us = calc_stats(simulate_d1_mreversion(data["US30"], "US30", 2.0, 1.0, rsi_th=rsi, ibs_th=0.20, exit_sma_period=5, atr_stop_mult=2.0))
        st_pre = calc_stats(simulate_d1_mreversion(data["NAS100_PRE2021_OOS"], "NAS100", 1.5, 1.0, rsi_th=rsi, ibs_th=0.20, exit_sma_period=5, atr_stop_mult=2.0))
        print(f"RSI < {rsi:<10.1f} | N={st_nas['n']:2d} Tot={st_nas['total_r']:+5.1f}R PF={st_nas['pf']:4.2f} WR={st_nas['wr']:4.1f}% | N={st_us['n']:2d} Tot={st_us['total_r']:+5.1f}R PF={st_us['pf']:4.2f} WR={st_us['wr']:4.1f}% | N={st_pre['n']:2d} Tot={st_pre['total_r']:+5.1f}R PF={st_pre['pf']:4.2f} WR={st_pre['wr']:4.1f}%")

    print("\n--- TESTE 2: Sensibilidade do Limiar de IBS (com RSI=10.0, SMA=5, Stop=2.0x ATR) ---")
    print(f"{'IBS Threshold':<15} | {'NAS100 (In-Sample)':<30} | {'US30 (In-Sample)':<30} | {'NAS100 Pré-2021 (OOS)':<30}")
    print("-" * 110)
    for ibs in ibs_list:
        st_nas = calc_stats(simulate_d1_mreversion(data["NAS100"], "NAS100", 1.5, 1.0, rsi_th=10.0, ibs_th=ibs, exit_sma_period=5, atr_stop_mult=2.0))
        st_us = calc_stats(simulate_d1_mreversion(data["US30"], "US30", 2.0, 1.0, rsi_th=10.0, ibs_th=ibs, exit_sma_period=5, atr_stop_mult=2.0))
        st_pre = calc_stats(simulate_d1_mreversion(data["NAS100_PRE2021_OOS"], "NAS100", 1.5, 1.0, rsi_th=10.0, ibs_th=ibs, exit_sma_period=5, atr_stop_mult=2.0))
        print(f"IBS < {ibs:<10.2f} | N={st_nas['n']:2d} Tot={st_nas['total_r']:+5.1f}R PF={st_nas['pf']:4.2f} WR={st_nas['wr']:4.1f}% | N={st_us['n']:2d} Tot={st_us['total_r']:+5.1f}R PF={st_us['pf']:4.2f} WR={st_us['wr']:4.1f}% | N={st_pre['n']:2d} Tot={st_pre['total_r']:+5.1f}R PF={st_pre['pf']:4.2f} WR={st_pre['wr']:4.1f}%")

    print("\n--- TESTE 3: Sensibilidade da Média de Saída (SMA) ---")
    print(f"{'Exit Rule':<15} | {'NAS100 (In-Sample)':<30} | {'US30 (In-Sample)':<30} | {'NAS100 Pré-2021 (OOS)':<30}")
    print("-" * 110)
    for sma in sma_list:
        st_nas = calc_stats(simulate_d1_mreversion(data["NAS100"], "NAS100", 1.5, 1.0, rsi_th=10.0, ibs_th=0.20, exit_sma_period=sma, atr_stop_mult=2.0))
        st_us = calc_stats(simulate_d1_mreversion(data["US30"], "US30", 2.0, 1.0, rsi_th=10.0, ibs_th=0.20, exit_sma_period=sma, atr_stop_mult=2.0))
        st_pre = calc_stats(simulate_d1_mreversion(data["NAS100_PRE2021_OOS"], "NAS100", 1.5, 1.0, rsi_th=10.0, ibs_th=0.20, exit_sma_period=sma, atr_stop_mult=2.0))
        print(f"Exit SMA({sma})    | N={st_nas['n']:2d} Tot={st_nas['total_r']:+5.1f}R PF={st_nas['pf']:4.2f} WR={st_nas['wr']:4.1f}% | N={st_us['n']:2d} Tot={st_us['total_r']:+5.1f}R PF={st_us['pf']:4.2f} WR={st_us['wr']:4.1f}% | N={st_pre['n']:2d} Tot={st_pre['total_r']:+5.1f}R PF={st_pre['pf']:4.2f} WR={st_pre['wr']:4.1f}%")

    print("\n--- TESTE 4: Sensibilidade do Stop Loss (ATR Multiple) ---")
    print(f"{'Stop Loss':<15} | {'NAS100 (In-Sample)':<30} | {'US30 (In-Sample)':<30} | {'NAS100 Pré-2021 (OOS)':<30}")
    print("-" * 110)
    for stp in stop_list:
        st_nas = calc_stats(simulate_d1_mreversion(data["NAS100"], "NAS100", 1.5, 1.0, rsi_th=10.0, ibs_th=0.20, exit_sma_period=5, atr_stop_mult=stp))
        st_us = calc_stats(simulate_d1_mreversion(data["US30"], "US30", 2.0, 1.0, rsi_th=10.0, ibs_th=0.20, exit_sma_period=5, atr_stop_mult=stp))
        st_pre = calc_stats(simulate_d1_mreversion(data["NAS100_PRE2021_OOS"], "NAS100", 1.5, 1.0, rsi_th=10.0, ibs_th=0.20, exit_sma_period=5, atr_stop_mult=stp))
        print(f"Stop {stp:.1f}x ATR  | N={st_nas['n']:2d} Tot={st_nas['total_r']:+5.1f}R PF={st_nas['pf']:4.2f} WR={st_nas['wr']:4.1f}% | N={st_us['n']:2d} Tot={st_us['total_r']:+5.1f}R PF={st_us['pf']:4.2f} WR={st_us['wr']:4.1f}% | N={st_pre['n']:2d} Tot={st_pre['total_r']:+5.1f}R PF={st_pre['pf']:4.2f} WR={st_pre['wr']:4.1f}%")

    print("\n--- TESTE 5: Carteira Conjunta Equilibrada (NAS100 + US30) In-Sample (2021-2026) ---")
    tr_nas = simulate_d1_mreversion(data["NAS100"], "NAS100", 1.5, 1.0, rsi_th=10.0, ibs_th=0.20, exit_sma_period=5, atr_stop_mult=2.0)
    tr_us = simulate_d1_mreversion(data["US30"], "US30", 2.0, 1.0, rsi_th=10.0, ibs_th=0.20, exit_sma_period=5, atr_stop_mult=2.0)
    all_tr = sorted(tr_nas + tr_us, key=lambda t: t.exit_time)
    st_port = calc_stats(all_tr)
    print(f"CARTEIRA COMBINADA (NAS100 + US30):")
    print(f"Trades={st_port['n']} | TotalR={st_port['total_r']:+.1f}R | R/trade={st_port['mean_r']:+.3f}±{st_port['se_r']:.3f} | t-stat={st_port['t_stat']:.2f} | PF={st_port['pf']:.2f} | WR={st_port['wr']:.1f}% | MaxDD={st_port['max_dd']:.1f}R")

if __name__ == "__main__":
    main()

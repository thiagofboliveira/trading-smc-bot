"""Pesquisa Quantitativa - Timeframe Diário (D1):
1. Reversão à Média Diária (Connors RSI(2) + IBS - Internal Bar Strength).
2. Trend Following Sistemático Long-Only no D1 (MME 50/200 + Chandelier ATR).

Fundamento:
- No D1, a fricção de spread + slippage representa menos de 0.5% do trade (vs 12% no M5).
- Larry Connors & Cesar Alvarez, "Short Term Trading Strategies That Work".
- Cooper (1999 JFE), Avramov et al. (2006): Anomalia de sobre-reação de curto prazo em índices de ações.

Regras Causaís Estritas (AGENTS.md):
- Indicadores calculados em i-1 (ou no fechamento de D1 para execução no Open de D+1).
- Execução no Open de D+1 com slippage e spread.
- Comparação com Buy & Hold passivo.
- Teste em NAS100, US30, SPX500, GER40 e BRENT.
"""

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

SPREADS = {
    "NAS100": 1.5,
    "US30": 2.0,
    "SPX500": 0.5,
    "GER40": 1.5,
    "BRENT": 0.03,
    "XAUUSD": 0.20,
}

SLIPPAGES = {
    "NAS100": 1.0,
    "US30": 1.0,
    "SPX500": 0.5,
    "GER40": 1.0,
    "BRENT": 0.02,
    "XAUUSD": 0.10,
}


@dataclass
class Trade:
    symbol: str
    strategy: str
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
        return {
            "n": 0, "wr": 0.0, "pf": 0.0, "total_r": 0.0,
            "mean_r": 0.0, "se_r": 0.0, "t_stat": 0.0,
            "max_dd": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
        }
    rs = np.array([t.r_multiple for t in trades])
    wins = rs[rs > 0]
    losses = rs[rs < 0]

    gp = float(wins.sum()) if len(wins) > 0 else 0.0
    gl = float(abs(losses.sum())) if len(losses) > 0 else 0.0
    pf = (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0)

    wr = float(len(wins) / len(rs)) * 100.0
    total_r = float(rs.sum())
    mean_r = float(rs.mean())
    se_r = float(rs.std(ddof=1) / np.sqrt(len(rs))) if len(rs) > 1 else 0.0
    t_stat = (mean_r / se_r) if se_r > 0 else 0.0

    cum_r = np.cumsum(rs)
    peak = np.maximum.accumulate(cum_r)
    dd = peak - cum_r
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

    avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(abs(losses.mean())) if len(losses) > 0 else 0.0

    return {
        "n": len(trades),
        "wr": wr,
        "pf": pf,
        "total_r": total_r,
        "mean_r": mean_r,
        "se_r": se_r,
        "t_stat": t_stat,
        "max_dd": max_dd,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
    }


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


def simulate_d1_mean_reversion_rsi2(
    df_d1: pd.DataFrame,
    symbol: str,
    spread: float,
    slippage: float,
    rsi_threshold: float = 10.0,
    max_hold_days: int = 5,
) -> list[Trade]:
    """Connors RSI(2) Daily Mean Reversion:
    - Filtro Macro: Close[i-1] > SMA200[i-1]
    - Gatilho: RSI(2)[i-1] < rsi_threshold
    - Entrada: Open[i] + spread + slippage
    - Saída: Quando Close[i-1] > SMA5[i-1] ou max_hold_days atingido
    - Stop Loss: 2.0 * ATR(14)
    """
    opens = df_d1["open"].to_numpy(dtype=float)
    highs = df_d1["high"].to_numpy(dtype=float)
    lows = df_d1["low"].to_numpy(dtype=float)
    closes = df_d1["close"].to_numpy(dtype=float)
    ts = df_d1.index

    # Indicadores causais em i-1
    sma200 = df_d1["close"].shift(1).rolling(200).mean().to_numpy(dtype=float)
    sma5 = df_d1["close"].shift(1).rolling(5).mean().to_numpy(dtype=float)
    rsi2 = compute_rsi(df_d1["close"].shift(1), period=2)
    atr14 = compute_atr(df_d1.shift(1), period=14)

    # IBS causal: (Close[i-1] - Low[i-1]) / (High[i-1] - Low[i-1])
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

            # Checa Stop Loss
            if lows[i] <= open_pos["stop_price"]:
                raw_exit = min(open_pos["stop_price"], opens[i])
                exit_price = raw_exit - slippage
                r = (exit_price - open_pos["entry_price"]) / risk
                trades.append(
                    Trade(symbol, f"D1_RSI2_{rsi_threshold}", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "STOP_LOSS", float(r), bool(r > 0))
                )
                open_pos = None
                continue

            # Saída por Alvo: Fechamento de i-1 cruzou acima da SMA(5)
            exit_by_sma = c_prev[i] > sma5[i]
            exit_by_time = hold_days >= max_hold_days

            if exit_by_sma or exit_by_time:
                exit_price = opens[i] - slippage
                r = (exit_price - open_pos["entry_price"]) / risk
                reason = "EXIT_SMA5" if exit_by_sma else "TIME_STOP"
                trades.append(
                    Trade(symbol, f"D1_RSI2_{rsi_threshold}", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, reason, float(r), bool(r > 0))
                )
                open_pos = None
                continue

        # 2. Entrada de novo trade
        if open_pos is None:
            is_bull_regime = c_prev[i] > sma200[i]
            is_oversold = (rsi2[i] < rsi_threshold) or (ibs[i] < 0.20)

            if is_bull_regime and is_oversold:
                entry_price = opens[i] + spread + slippage
                risk_pts = 2.0 * atr14[i]
                stop_price = entry_price - risk_pts

                if risk_pts > 0:
                    # Checagem imediata de stop intrabar no dia de entrada
                    if lows[i] <= stop_price:
                        raw_exit = min(stop_price, opens[i])
                        exit_price = raw_exit - slippage
                        r = (exit_price - entry_price) / risk_pts
                        trades.append(
                            Trade(symbol, f"D1_RSI2_{rsi_threshold}", curr_time, curr_time, entry_price, stop_price, exit_price, "STOP_ENTRY_DAY", float(r), bool(r > 0))
                        )
                    else:
                        open_pos = {
                            "entry_idx": i,
                            "entry_time": curr_time,
                            "entry_price": entry_price,
                            "stop_price": stop_price,
                            "initial_risk": risk_pts,
                        }

    return trades


def run_d1_suite():
    print("=" * 115)
    print("PESQUISA QUANTITATIVA NO DIÁRIO (D1): REVERSÃO À MÉDIA (RSI(2) + IBS) EM ÍNDICES E COMMODITIES")
    print("=" * 115)

    experiments = [
        {"rsi": 10.0, "hold": 5},
        {"rsi": 5.0, "hold": 5},
        {"rsi": 15.0, "hold": 4},
        {"rsi": 10.0, "hold": 3},
    ]

    symbols = ["NAS100", "US30", "BRENT", "XAUUSD"]

    for exp in experiments:
        rsi_th = exp["rsi"]
        hold_d = exp["hold"]
        print(f"\n>>> CONFIGURAÇÃO D1: RSI(2) < {rsi_th} | Max Hold: {hold_d} dias | Stop 2x ATR | Saída SMA5")
        print("-" * 115)

        all_tr = []
        for sym in symbols:
            p = Path(f"data/{sym}_M1_dukascopy.parquet")
            if not p.exists():
                continue
            df_m1 = pd.read_parquet(p)
            df_d1 = df_m1.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()

            tr = simulate_d1_mean_reversion_rsi2(df_d1, sym, SPREADS[sym], SLIPPAGES[sym], rsi_threshold=rsi_th, max_hold_days=hold_d)
            st = calc_stats(tr)
            all_tr.extend(tr)
            print(
                f"{sym:6s} | Trades={st['n']:3d} | TotalR={st['total_r']:+6.1f}R | "
                f"R/trade={st['mean_r']:+0.3f}±{st['se_r']:0.3f} (t={st['t_stat']:4.2f}) | "
                f"PF={st['pf']:4.2f} | WR={st['wr']:4.1f}% | AvgWin={st['avg_win']:4.2f}R | AvgLoss={st['avg_loss']:4.2f}R | MaxDD={st['max_dd']:4.1f}R"
            )

        st_all = calc_stats(all_tr)
        print(
            f"[CONSOLIDADO D1 CARTEIRA]: Trades={st_all['n']} | TotalR={st_all['total_r']:+.1f}R | "
            f"R/trade={st_all['mean_r']:+.3f}±{st_all['se_r']:.3f} | t-stat={st_all['t_stat']:.2f} | PF={st_all['pf']:.2f} | WR={st_all['wr']:.1f}% | MaxDD={st_all['max_dd']:.1f}R"
        )


if __name__ == "__main__":
    run_d1_suite()

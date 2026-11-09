"""Pesquisa Quantitativa - Hipótese 3: Reversão à Média no VWAP (Bandas de 2.0σ a 3.0σ).

Fundamentação:
- Teoria de Leilão e Preço de Equilíbrio: o VWAP diário é o benchmark de execução institucional.
- Em 70%+ do tempo, o mercado intradiário oscila em torno da média de volume. Extensões extremas (2.0 a 3.0 desvios) tendem a reverter.

Regras do Sistema:
- Cálculo causal de VWAP e Bandas de Desvio-Padrão diárias (2.0σ e 2.5σ).
- Sinal de Exaustão (M5):
  - Venda (Sobrecompra): Preço fura a banda superior (+2.0σ/+2.5σ), mas fecha de volta para DENTRO da banda.
  - Compra (Sobrevenda): Preço fura a banda inferior (-2.0σ/-2.5σ), mas fecha de volta para DENTRO da banda.
- Entrada: Abertura da barra i.
- Stop Loss: Extremo da barra de rejeição i-1 + slippage.
- Saídas Testadas:
  - Saída 1: Retorno ao VWAP Central.
  - Saída 2: Retorno à banda de 1.0σ (saída mais conservadora).
  - Saída 3: Alvo Fixo 1.5R.
- Regras Anti-Viés (AGENTS.md):
  - Indicadores reiniciados no início de cada sessão diária.
  - Stop loss na barra de entrada testado no fill.
  - Custos reais de spread e slippage aplicados.
  - 5 anos de dados (2021-2026).
"""

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

SYMBOLS = ["NAS100", "US30", "BRENT", "EURUSD", "GBPUSD", "XAUUSD"]

SPREADS = {
    "XAUUSD": 0.20,
    "EURUSD": 0.00008,
    "GBPUSD": 0.00010,
    "US30": 2.0,
    "NAS100": 1.5,
    "BRENT": 0.03,
}

SLIPPAGES = {
    "XAUUSD": 0.10,
    "EURUSD": 0.00005,
    "GBPUSD": 0.00005,
    "US30": 1.0,
    "NAS100": 1.0,
    "BRENT": 0.02,
}

OOS_SPLIT_DATE = pd.Timestamp("2024-11-01", tz="UTC")


@dataclass
class Trade:
    symbol: str
    strategy: str
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_price: float
    exit_price: float
    exit_reason: str
    r_multiple: float
    win: bool
    is_oos: bool


def calc_stats(trades: list[Trade]) -> dict:
    if not trades:
        return {
            "n": 0, "wr": 0.0, "pf": 0.0, "total_r": 0.0,
            "mean_r": 0.0, "se_r": 0.0, "t_stat": 0.0,
            "max_dd": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "longs": 0, "shorts": 0,
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

    longs = sum(1 for t in trades if t.direction == "long")
    shorts = sum(1 for t in trades if t.direction == "short")

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
        "longs": longs,
        "shorts": shorts,
    }


def compute_vwap_bands(df: pd.DataFrame, num_std: float = 2.0) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Calcula VWAP diário cumulativo e bandas de desvio-padrão causais."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    volume = df["volume"].replace(0, 1.0)
    vp = typical_price * volume

    df_temp = pd.DataFrame({"typical": typical_price, "vp": vp, "vol": volume}, index=df.index)
    df_temp["date"] = df_temp.index.date

    cum_vp = df_temp.groupby("date")["vp"].cumsum()
    cum_vol = df_temp.groupby("date")["vol"].cumsum()
    vwap = cum_vp / cum_vol

    # Variância ponderada
    df_temp["sq_diff"] = (df_temp["typical"] - vwap) ** 2 * df_temp["vol"]
    cum_sq = df_temp.groupby("date")["sq_diff"].cumsum()
    variance = cum_sq / cum_vol
    std = np.sqrt(np.maximum(variance, 0.0))

    upper_band = vwap + num_std * std
    lower_band = vwap - num_std * std
    upper_1std = vwap + 1.0 * std
    lower_1std = vwap - 1.0 * std

    return (
        vwap.to_numpy(dtype=float),
        upper_band.to_numpy(dtype=float),
        lower_band.to_numpy(dtype=float),
        upper_1std.to_numpy(dtype=float),
        lower_1std.to_numpy(dtype=float),
    )


def simulate_vwap_mean_reversion(
    df_m5: pd.DataFrame,
    symbol: str,
    spread: float,
    slippage: float,
    num_std: float = 2.0,  # 2.0 ou 2.5
    exit_mode: str = "VWAP",  # 'VWAP', 'BAND_1STD', 'FIXED_1_5R'
) -> list[Trade]:
    vwap, upper, lower, up_1std, low_1std = compute_vwap_bands(df_m5, num_std=num_std)

    opens = df_m5["open"].to_numpy(dtype=float)
    highs = df_m5["high"].to_numpy(dtype=float)
    lows = df_m5["low"].to_numpy(dtype=float)
    closes = df_m5["close"].to_numpy(dtype=float)
    ts = df_m5.index

    trades: list[Trade] = []
    day_groups = df_m5.groupby(df_m5.index.date).indices

    for day, day_indices in day_groups.items():
        if len(day_indices) < 20:
            continue

        # Horário de operação: 08:00 às 20:00 UTC (evita os primeiros 30 min da Ásia onde VWAP não convergiu)
        session_start = pd.Timestamp(f"{day} 08:00:00", tz="UTC")
        session_end = pd.Timestamp(f"{day} 20:00:00", tz="UTC")

        trade_bars = [idx for idx in day_indices if session_start <= ts[idx] <= session_end]
        if not trade_bars:
            continue

        open_pos = None

        for idx in trade_bars:
            curr_time = ts[idx]

            # 1. Gestão de posição aberta
            if open_pos is not None:
                risk = open_pos["initial_risk"]
                direction = open_pos["direction"]

                if direction == "long":
                    # Stop loss
                    if lows[idx] <= open_pos["stop_price"]:
                        raw_exit = min(open_pos["stop_price"], opens[idx])
                        exit_price = raw_exit - slippage
                        r = (exit_price - open_pos["entry_price"]) / risk
                        trades.append(
                            Trade(symbol, f"VWAP_REV_{num_std}std_{exit_mode}", "long", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "STOP_LOSS", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                        )
                        open_pos = None
                        continue

                    # Modos de Saída
                    if exit_mode == "VWAP":
                        if highs[idx] >= vwap[idx]:
                            raw_exit = max(vwap[idx], opens[idx])
                            exit_price = raw_exit - slippage
                            r = (exit_price - open_pos["entry_price"]) / risk
                            trades.append(
                                Trade(symbol, f"VWAP_REV_{num_std}std_{exit_mode}", "long", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "EXIT_VWAP", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                            )
                            open_pos = None
                            continue

                    elif exit_mode == "BAND_1STD":
                        if highs[idx] >= low_1std[idx]:
                            raw_exit = max(low_1std[idx], opens[idx])
                            exit_price = raw_exit - slippage
                            r = (exit_price - open_pos["entry_price"]) / risk
                            trades.append(
                                Trade(symbol, f"VWAP_REV_{num_std}std_{exit_mode}", "long", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "EXIT_1STD", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                            )
                            open_pos = None
                            continue

                    elif exit_mode == "FIXED_1_5R":
                        tp = open_pos["entry_price"] + 1.5 * risk
                        if highs[idx] >= tp:
                            raw_exit = max(tp, opens[idx])
                            exit_price = raw_exit - slippage
                            r = (exit_price - open_pos["entry_price"]) / risk
                            trades.append(
                                Trade(symbol, f"VWAP_REV_{num_std}std_{exit_mode}", "long", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "TAKE_PROFIT_1_5R", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                            )
                            open_pos = None
                            continue

                    # Zeragem no fim da sessão
                    if curr_time >= session_end - pd.Timedelta(minutes=5):
                        exit_price = closes[idx] - slippage
                        r = (exit_price - open_pos["entry_price"]) / risk
                        trades.append(
                            Trade(symbol, f"VWAP_REV_{num_std}std_{exit_mode}", "long", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "SESSION_CLOSE", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                        )
                        open_pos = None
                        continue

                else:  # short
                    if highs[idx] + spread >= open_pos["stop_price"]:
                        raw_exit = max(open_pos["stop_price"], opens[idx] + spread)
                        exit_price = raw_exit + slippage
                        r = (open_pos["entry_price"] - exit_price) / risk
                        trades.append(
                            Trade(symbol, f"VWAP_REV_{num_std}std_{exit_mode}", "short", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "STOP_LOSS", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                        )
                        open_pos = None
                        continue

                    if exit_mode == "VWAP":
                        if lows[idx] <= vwap[idx]:
                            raw_exit = min(vwap[idx], opens[idx])
                            exit_price = raw_exit + slippage
                            r = (open_pos["entry_price"] - exit_price) / risk
                            trades.append(
                                Trade(symbol, f"VWAP_REV_{num_std}std_{exit_mode}", "short", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "EXIT_VWAP", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                            )
                            open_pos = None
                            continue

                    elif exit_mode == "BAND_1STD":
                        if lows[idx] <= up_1std[idx]:
                            raw_exit = min(up_1std[idx], opens[idx])
                            exit_price = raw_exit + slippage
                            r = (open_pos["entry_price"] - exit_price) / risk
                            trades.append(
                                Trade(symbol, f"VWAP_REV_{num_std}std_{exit_mode}", "short", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "EXIT_1STD", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                            )
                            open_pos = None
                            continue

                    elif exit_mode == "FIXED_1_5R":
                        tp = open_pos["entry_price"] - 1.5 * risk
                        if lows[idx] <= tp:
                            raw_exit = min(tp, opens[idx])
                            exit_price = raw_exit + slippage
                            r = (open_pos["entry_price"] - exit_price) / risk
                            trades.append(
                                Trade(symbol, f"VWAP_REV_{num_std}std_{exit_mode}", "short", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "TAKE_PROFIT_1_5R", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                            )
                            open_pos = None
                            continue

                    if curr_time >= session_end - pd.Timedelta(minutes=5):
                        exit_price = closes[idx] + spread + slippage
                        r = (open_pos["entry_price"] - exit_price) / risk
                        trades.append(
                            Trade(symbol, f"VWAP_REV_{num_std}std_{exit_mode}", "short", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "SESSION_CLOSE", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                        )
                        open_pos = None
                        continue

            # 2. Entrada na Reversão à Média
            if open_pos is None:
                # Compra: Mínima de i-1 furou lower band, mas fechou de volta ACIMA
                long_signal = (lows[idx - 1] <= lower[idx - 1]) and (closes[idx - 1] > lower[idx - 1])
                # Venda: Máxima de i-1 furou upper band, mas fechou de volta ABAIXO
                short_signal = (highs[idx - 1] >= upper[idx - 1]) and (closes[idx - 1] < upper[idx - 1])

                if long_signal and not short_signal:
                    entry_price = opens[idx] + spread + slippage
                    sl_price = lows[idx - 1] - slippage
                    risk = entry_price - sl_price
                    if risk > 0:
                        if lows[idx] <= sl_price:
                            raw_exit = min(sl_price, opens[idx])
                            exit_price = raw_exit - slippage
                            r = (exit_price - entry_price) / risk
                            trades.append(
                                Trade(symbol, f"VWAP_REV_{num_std}std_{exit_mode}", "long", curr_time, curr_time, entry_price, sl_price, exit_price, "STOP_ENTRY_BAR", float(r), bool(r > 0), bool(curr_time >= OOS_SPLIT_DATE))
                            )
                        else:
                            open_pos = {
                                "direction": "long",
                                "entry_time": curr_time,
                                "entry_price": entry_price,
                                "stop_price": sl_price,
                                "initial_risk": risk,
                            }

                elif short_signal and not long_signal:
                    entry_price = opens[idx] - slippage
                    sl_price = highs[idx - 1] + spread + slippage
                    risk = sl_price - entry_price
                    if risk > 0:
                        if highs[idx] + spread >= sl_price:
                            raw_exit = max(sl_price, opens[idx] + spread)
                            exit_price = raw_exit + slippage
                            r = (entry_price - exit_price) / risk
                            trades.append(
                                Trade(symbol, f"VWAP_REV_{num_std}std_{exit_mode}", "short", curr_time, curr_time, entry_price, sl_price, exit_price, "STOP_ENTRY_BAR", float(r), bool(r > 0), bool(curr_time >= OOS_SPLIT_DATE))
                            )
                        else:
                            open_pos = {
                                "direction": "short",
                                "entry_time": curr_time,
                                "entry_price": entry_price,
                                "stop_price": sl_price,
                                "initial_risk": risk,
                            }

    return trades


def run_vwap_experiments():
    print("=" * 115)
    print("PESQUISA HIPÓTESE 3: REVERSÃO À MÉDIA NO VWAP (BANDAS DE DESVIO-PADRÃO)")
    print("=" * 115)

    experiments = [
        {"std": 2.0, "exit": "VWAP"},
        {"std": 2.5, "exit": "VWAP"},
        {"std": 2.0, "exit": "BAND_1STD"},
        {"std": 2.0, "exit": "FIXED_1_5R"},
    ]

    for exp in experiments:
        num_s = exp["std"]
        exit_m = exp["exit"]
        print(f"\n>>> CONFIGURAÇÃO: Bandas {num_s}σ | Saída: {exit_m}")
        print("-" * 115)

        all_trades = []
        for sym in SYMBOLS:
            p = Path(f"data/{sym}_M1_dukascopy.parquet")
            if not p.exists():
                continue
            df_m1 = pd.read_parquet(p)
            df_m5 = df_m1.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()

            tr = simulate_vwap_mean_reversion(df_m5, sym, SPREADS[sym], SLIPPAGES[sym], num_std=num_s, exit_mode=exit_m)
            st = calc_stats(tr)
            all_trades.extend(tr)
            print(
                f"{sym:6s} | Trades={st['n']:3d} (C:{st['longs']:2d} V:{st['shorts']:2d}) | "
                f"TotalR={st['total_r']:+6.1f}R | R/trade={st['mean_r']:+0.2f}±{st['se_r']:0.2f} (t={st['t_stat']:4.2f}) | "
                f"PF={st['pf']:4.2f} | WR={st['wr']:4.1f}% | AvgWin={st['avg_win']:4.1f}R | AvgLoss={st['avg_loss']:4.1f}R | MaxDD={st['max_dd']:4.1f}R"
            )

        st_all = calc_stats(all_trades)
        print(f"\n[CONSOLIDADO CARTEIRA - VWAP REV {num_s}std {exit_m}]")
        print(
            f"Trades: {st_all['n']} (C:{st_all['longs']} V:{st_all['shorts']}) | Total R: {st_all['total_r']:+.1f}R | "
            f"R/trade: {st_all['mean_r']:+.3f} ± {st_all['se_r']:.3f} | t-stat: {st_all['t_stat']:.2f} | PF: {st_all['pf']:.2f} | WR: {st_all['wr']:.1f}% | MaxDD: {st_all['max_dd']:.1f}R"
        )


if __name__ == "__main__":
    run_vwap_experiments()

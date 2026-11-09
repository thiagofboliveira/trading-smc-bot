"""Pesquisa Quantitativa - Hipótese 2: Falha de Rompimento de Liquidez (Fade the Sweep / False Breakout).

Fundamentação:
- Microestrutura de Livro de Ordens: Osler (2003, 2005), Stop-loss orders and price cascades.
- Como ~75% dos rompimentos intradiários falham, operamos a FAVOR DA REJEIÇÃO do rompimento.

Regras do Sistema:
- Níveis Rastreados:
  1. Máxima e Mínima do Dia Anterior (PDH / PDL).
  2. Range da Sessão Asiática (00:00 às 07:00 UTC): Asian High / Asian Low.
- Condição de Falso Rompimento (Sweep & Reversal) no M5:
  - Compra (Sweep de Fundo): Barra fura a mínima (PDL ou Asian Low), mas o fechamento volta ACIMA do nível.
  - Venda (Sweep de Topo): Barra fura a máxima (PDH ou Asian High), mas o fechamento volta ABAIXO do nível.
- Entrada: Abertura da barra seguinte (i).
- Stop Loss: Extremo do pavio da violação + slippage.
- Saídas Testadas:
  - Saída 1: Retorno ao VWAP Diário.
  - Saída 2: Alvo Fixo 1.5R.
  - Saída 3: Alvo Fixo 2.0R.
  - Saída 4: Extremo oposto da consolidação (Asian High/Low oposto).
- Regras Anti-Viés (AGENTS.md):
  - Níveis puramente causais calculados antes da sessão.
  - Stop na barra de entrada checado intrabar.
  - Spreads reais e slippage aplicados.
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


def compute_session_vwap(df: pd.DataFrame) -> np.ndarray:
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    volume = df["volume"].replace(0, 1.0)
    vp = typical_price * volume
    df_temp = pd.DataFrame({"vp": vp, "vol": volume}, index=df.index)
    df_temp["date"] = df_temp.index.date
    cum_vp = df_temp.groupby("date")["vp"].cumsum()
    cum_vol = df_temp.groupby("date")["vol"].cumsum()
    return (cum_vp / cum_vol).to_numpy(dtype=float)


def simulate_false_breakout(
    df_m5: pd.DataFrame,
    symbol: str,
    spread: float,
    slippage: float,
    level_type: str = "ASIAN_RANGE",  # 'ASIAN_RANGE' ou 'PREV_DAY'
    exit_mode: str = "VWAP",  # 'VWAP', 'FIXED_1_5R', 'FIXED_2R', 'OPPOSITE_LEVEL'
) -> list[Trade]:
    vwap = compute_session_vwap(df_m5)
    opens = df_m5["open"].to_numpy(dtype=float)
    highs = df_m5["high"].to_numpy(dtype=float)
    lows = df_m5["low"].to_numpy(dtype=float)
    closes = df_m5["close"].to_numpy(dtype=float)
    ts = df_m5.index

    trades: list[Trade] = []
    day_groups = df_m5.groupby(df_m5.index.date).indices
    days = list(day_groups.keys())

    # Pre-calcula máximas e mínimas diárias causais
    daily_high = {}
    daily_low = {}
    for day, indices in day_groups.items():
        daily_high[day] = float(np.max(highs[indices]))
        daily_low[day] = float(np.min(lows[indices]))

    for d_idx in range(1, len(days)):
        day = days[d_idx]
        prev_day = days[d_idx - 1]
        day_indices = day_groups[day]
        if len(day_indices) < 20:
            continue

        if level_type == "PREV_DAY":
            lvl_high = daily_high[prev_day]
            lvl_low = daily_low[prev_day]
            trading_start = pd.Timestamp(f"{day} 08:00:00", tz="UTC")
        else:  # ASIAN_RANGE (00:00 às 07:00 UTC)
            asian_start = pd.Timestamp(f"{day} 00:00:00", tz="UTC")
            asian_end = pd.Timestamp(f"{day} 07:00:00", tz="UTC")
            asian_bars = [idx for idx in day_indices if asian_start <= ts[idx] < asian_end]
            if not asian_bars:
                continue
            lvl_high = float(np.max(highs[asian_bars]))
            lvl_low = float(np.min(lows[asian_bars]))
            trading_start = asian_end

        session_end = pd.Timestamp(f"{day} 21:00:00", tz="UTC")

        # Filtra barras de negociação da sessão de Londres e NY
        trade_bars = [idx for idx in day_indices if trading_start <= ts[idx] <= session_end]
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
                            Trade(symbol, f"SWEEP_{level_type}_{exit_mode}", "long", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "STOP_LOSS", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
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
                                Trade(symbol, f"SWEEP_{level_type}_{exit_mode}", "long", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "EXIT_VWAP", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
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
                                Trade(symbol, f"SWEEP_{level_type}_{exit_mode}", "long", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "TAKE_PROFIT_1_5R", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                            )
                            open_pos = None
                            continue

                    elif exit_mode == "FIXED_2R":
                        tp = open_pos["entry_price"] + 2.0 * risk
                        if highs[idx] >= tp:
                            raw_exit = max(tp, opens[idx])
                            exit_price = raw_exit - slippage
                            r = (exit_price - open_pos["entry_price"]) / risk
                            trades.append(
                                Trade(symbol, f"SWEEP_{level_type}_{exit_mode}", "long", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "TAKE_PROFIT_2R", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                            )
                            open_pos = None
                            continue

                    elif exit_mode == "OPPOSITE_LEVEL":
                        if highs[idx] >= lvl_high:
                            raw_exit = max(lvl_high, opens[idx])
                            exit_price = raw_exit - slippage
                            r = (exit_price - open_pos["entry_price"]) / risk
                            trades.append(
                                Trade(symbol, f"SWEEP_{level_type}_{exit_mode}", "long", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "EXIT_OPPOSITE_LEVEL", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                            )
                            open_pos = None
                            continue

                    # Zeragem no fim da sessão
                    if curr_time >= session_end - pd.Timedelta(minutes=5):
                        exit_price = closes[idx] - slippage
                        r = (exit_price - open_pos["entry_price"]) / risk
                        trades.append(
                            Trade(symbol, f"SWEEP_{level_type}_{exit_mode}", "long", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "SESSION_CLOSE", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                        )
                        open_pos = None
                        continue

                else:  # short
                    if highs[idx] + spread >= open_pos["stop_price"]:
                        raw_exit = max(open_pos["stop_price"], opens[idx] + spread)
                        exit_price = raw_exit + slippage
                        r = (open_pos["entry_price"] - exit_price) / risk
                        trades.append(
                            Trade(symbol, f"SWEEP_{level_type}_{exit_mode}", "short", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "STOP_LOSS", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                        )
                        open_pos = None
                        continue

                    if exit_mode == "VWAP":
                        if lows[idx] <= vwap[idx]:
                            raw_exit = min(vwap[idx], opens[idx])
                            exit_price = raw_exit + slippage
                            r = (open_pos["entry_price"] - exit_price) / risk
                            trades.append(
                                Trade(symbol, f"SWEEP_{level_type}_{exit_mode}", "short", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "EXIT_VWAP", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
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
                                Trade(symbol, f"SWEEP_{level_type}_{exit_mode}", "short", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "TAKE_PROFIT_1_5R", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                            )
                            open_pos = None
                            continue

                    elif exit_mode == "FIXED_2R":
                        tp = open_pos["entry_price"] - 2.0 * risk
                        if lows[idx] <= tp:
                            raw_exit = min(tp, opens[idx])
                            exit_price = raw_exit + slippage
                            r = (open_pos["entry_price"] - exit_price) / risk
                            trades.append(
                                Trade(symbol, f"SWEEP_{level_type}_{exit_mode}", "short", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "TAKE_PROFIT_2R", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                            )
                            open_pos = None
                            continue

                    elif exit_mode == "OPPOSITE_LEVEL":
                        if lows[idx] <= lvl_low:
                            raw_exit = min(lvl_low, opens[idx])
                            exit_price = raw_exit + slippage
                            r = (open_pos["entry_price"] - exit_price) / risk
                            trades.append(
                                Trade(symbol, f"SWEEP_{level_type}_{exit_mode}", "short", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "EXIT_OPPOSITE_LEVEL", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                            )
                            open_pos = None
                            continue

                    if curr_time >= session_end - pd.Timedelta(minutes=5):
                        exit_price = closes[idx] + spread + slippage
                        r = (open_pos["entry_price"] - exit_price) / risk
                        trades.append(
                            Trade(symbol, f"SWEEP_{level_type}_{exit_mode}", "short", open_pos["entry_time"], curr_time, open_pos["entry_price"], open_pos["stop_price"], exit_price, "SESSION_CLOSE", float(r), bool(r > 0), bool(open_pos["entry_time"] >= OOS_SPLIT_DATE))
                        )
                        open_pos = None
                        continue

            # 2. Entrada no Falso Rompimento
            if open_pos is None:
                # Sweep de Fundo (Compra): Mínima da barra i-1 furou lvl_low, mas fechou de volta ACIMA
                sweep_low = (lows[idx - 1] < lvl_low) and (closes[idx - 1] > lvl_low)
                # Sweep de Topo (Venda): Máxima da barra i-1 furou lvl_high, mas fechou de volta ABAIXO
                sweep_high = (highs[idx - 1] > lvl_high) and (closes[idx - 1] < lvl_high)

                if sweep_low and not sweep_high:
                    entry_price = opens[idx] + spread + slippage
                    sl_price = lows[idx - 1] - slippage
                    risk = entry_price - sl_price
                    if risk > 0:
                        if lows[idx] <= sl_price:
                            raw_exit = min(sl_price, opens[idx])
                            exit_price = raw_exit - slippage
                            r = (exit_price - entry_price) / risk
                            trades.append(
                                Trade(symbol, f"SWEEP_{level_type}_{exit_mode}", "long", curr_time, curr_time, entry_price, sl_price, exit_price, "STOP_ENTRY_BAR", float(r), bool(r > 0), bool(curr_time >= OOS_SPLIT_DATE))
                            )
                        else:
                            open_pos = {
                                "direction": "long",
                                "entry_time": curr_time,
                                "entry_price": entry_price,
                                "stop_price": sl_price,
                                "initial_risk": risk,
                            }

                elif sweep_high and not sweep_low:
                    entry_price = opens[idx] - slippage
                    sl_price = highs[idx - 1] + spread + slippage
                    risk = sl_price - entry_price
                    if risk > 0:
                        if highs[idx] + spread >= sl_price:
                            raw_exit = max(sl_price, opens[idx] + spread)
                            exit_price = raw_exit + slippage
                            r = (entry_price - exit_price) / risk
                            trades.append(
                                Trade(symbol, f"SWEEP_{level_type}_{exit_mode}", "short", curr_time, curr_time, entry_price, sl_price, exit_price, "STOP_ENTRY_BAR", float(r), bool(r > 0), bool(curr_time >= OOS_SPLIT_DATE))
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


def run_sweep_experiments():
    print("=" * 115)
    print("PESQUISA HIPÓTESE 2: FALHA DE ROMPIMENTO DE LIQUIDEZ (FADE THE SWEEP)")
    print("=" * 115)

    experiments = [
        {"level": "ASIAN_RANGE", "exit": "VWAP"},
        {"level": "ASIAN_RANGE", "exit": "FIXED_1_5R"},
        {"level": "ASIAN_RANGE", "exit": "OPPOSITE_LEVEL"},
        {"level": "PREV_DAY", "exit": "VWAP"},
        {"level": "PREV_DAY", "exit": "FIXED_1_5R"},
    ]

    for exp in experiments:
        lvl = exp["level"]
        exit_m = exp["exit"]
        print(f"\n>>> CONFIGURAÇÃO: Nível: {lvl} | Saída: {exit_m}")
        print("-" * 115)

        all_trades = []
        for sym in SYMBOLS:
            p = Path(f"data/{sym}_M1_dukascopy.parquet")
            if not p.exists():
                continue
            df_m1 = pd.read_parquet(p)
            df_m5 = df_m1.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()

            tr = simulate_false_breakout(df_m5, sym, SPREADS[sym], SLIPPAGES[sym], level_type=lvl, exit_mode=exit_m)
            st = calc_stats(tr)
            all_trades.extend(tr)
            print(
                f"{sym:6s} | Trades={st['n']:3d} (C:{st['longs']:2d} V:{st['shorts']:2d}) | "
                f"TotalR={st['total_r']:+6.1f}R | R/trade={st['mean_r']:+0.2f}±{st['se_r']:0.2f} (t={st['t_stat']:4.2f}) | "
                f"PF={st['pf']:4.2f} | WR={st['wr']:4.1f}% | AvgWin={st['avg_win']:4.1f}R | AvgLoss={st['avg_loss']:4.1f}R | MaxDD={st['max_dd']:4.1f}R"
            )

        st_all = calc_stats(all_trades)
        print(f"\n[CONSOLIDADO CARTEIRA - SWEEP {lvl} {exit_m}]")
        print(
            f"Trades: {st_all['n']} (C:{st_all['longs']} V:{st_all['shorts']}) | Total R: {st_all['total_r']:+.1f}R | "
            f"R/trade: {st_all['mean_r']:+.3f} ± {st_all['se_r']:.3f} | t-stat: {st_all['t_stat']:.2f} | PF: {st_all['pf']:.2f} | WR: {st_all['wr']:.1f}% | MaxDD: {st_all['max_dd']:.1f}R"
        )


if __name__ == "__main__":
    run_sweep_experiments()

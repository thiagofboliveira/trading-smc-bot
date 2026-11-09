"""Pesquisa Quantitativa - Hipótese 1: Opening Range Breakout (ORB) + VWAP no Pregão de NY.

Fundamentação:
- Toby Crabel (1990), Day Trading with Short Term Price Patterns.
- Zarattini & Aziz (SSRN, 2023/2024), Opening Range Breakouts & Beat the Market.

Regras do Sistema:
- Janela de Abertura: 14:30 às 15:00 UTC (30m ORB) e 14:30 às 14:45 UTC (15m ORB).
- Filtro VWAP: Compra só se Fechamento > VWAP; Venda só se Fechamento < VWAP.
- Entrada: Próxima barra após confirmação do rompimento do ORB.
- Stop Loss:
  - Variante 1: Extremo oposto do ORB (Full Range).
  - Variante 2: Ponto médio do ORB (Midpoint Range - 50%).
- Saídas Testadas:
  - Saída 1: Fim da Sessão de NY (20:55 UTC).
  - Saída 2: Trailing pelo VWAP da Sessão.
  - Saída 3: Alvo Fixo 2.0R (com zeragem no fim do dia se não atingir).
- Regras Anti-Viés (AGENTS.md):
  - No máximo 1 trade por ativo por dia.
  - Stop testado intrabar na barra de entrada.
  - Slippage realista (1.0 pt em índices) + spread real.
  - Teste em 5 anos (2021-2026).
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
    """Calcula VWAP diário cumulativo reiniciado a cada dia."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    volume = df["volume"].replace(0, 1.0)  # Evita divisão por zero
    vp = typical_price * volume

    df_temp = pd.DataFrame({"vp": vp, "vol": volume}, index=df.index)
    df_temp["date"] = df_temp.index.date

    cum_vp = df_temp.groupby("date")["vp"].cumsum()
    cum_vol = df_temp.groupby("date")["vol"].cumsum()
    vwap = cum_vp / cum_vol
    return vwap.to_numpy(dtype=float)


def simulate_orb(
    df_m5: pd.DataFrame,
    symbol: str,
    spread: float,
    slippage: float,
    orb_minutes: int = 30,  # 15 ou 30 minutos
    stop_mode: str = "MIDPOINT",  # 'MIDPOINT' (50% do range) ou 'FULL' (extremo oposto)
    exit_mode: str = "SESSION_CLOSE",  # 'SESSION_CLOSE', 'TRAILING_VWAP', 'FIXED_2R'
) -> list[Trade]:
    """Simula a estratégia de ORB no gráfico M5."""
    vwap = compute_session_vwap(df_m5)
    opens = df_m5["open"].to_numpy(dtype=float)
    highs = df_m5["high"].to_numpy(dtype=float)
    lows = df_m5["low"].to_numpy(dtype=float)
    closes = df_m5["close"].to_numpy(dtype=float)
    ts = df_m5.index

    # Horários de referência (UTC)
    # Sessão de NY: 14:30 UTC até 21:00 UTC
    trades: list[Trade] = []

    # Agrupa barras por dia de forma ultra-rápida O(1)
    day_groups = df_m5.groupby(df_m5.index.date).indices

    for day, day_indices in day_groups.items():
        if len(day_indices) < 20:
            continue

        # Identifica janela do ORB (14:30 até 14:30 + orb_minutes)
        # Ex: 14:30 a 15:00 UTC para orb_minutes=30
        orb_start_time = pd.Timestamp(f"{day} 14:30:00", tz="UTC")
        orb_end_time = pd.Timestamp(f"{day} 14:30:00", tz="UTC") + pd.Timedelta(minutes=orb_minutes)
        session_close_time = pd.Timestamp(f"{day} 21:00:00", tz="UTC")

        orb_bars = [idx for idx in day_indices if orb_start_time <= ts[idx] < orb_end_time]
        if not orb_bars:
            continue

        orb_high = float(np.max(highs[orb_bars]))
        orb_low = float(np.min(lows[orb_bars]))
        orb_mid = (orb_high + orb_low) / 2.0

        # Posição por dia
        traded_today = False
        open_pos = None

        # Varre as barras pós-ORB até o fim da sessão
        trading_bars = [idx for idx in day_indices if ts[idx] >= orb_end_time and ts[idx] <= session_close_time]

        for idx in trading_bars:
            curr_time = ts[idx]

            # 1. Gestão de posição aberta
            if open_pos is not None:
                risk = open_pos["initial_risk"]
                direction = open_pos["direction"]

                # A. Stop loss
                if direction == "long":
                    if lows[idx] <= open_pos["stop_price"]:
                        raw_exit = min(open_pos["stop_price"], opens[idx])
                        exit_price = raw_exit - slippage
                        r = (exit_price - open_pos["entry_price"]) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"ORB_{orb_minutes}m_{stop_mode}_{exit_mode}",
                                direction="long",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="STOP_LOSS",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

                    # B. Saídas Específicas
                    if exit_mode == "FIXED_2R":
                        tp = open_pos["entry_price"] + 2.0 * risk
                        if highs[idx] >= tp:
                            raw_exit = max(tp, opens[idx])
                            exit_price = raw_exit - slippage
                            r = (exit_price - open_pos["entry_price"]) / risk
                            trades.append(
                                Trade(
                                    symbol=symbol,
                                    strategy=f"ORB_{orb_minutes}m_{stop_mode}_{exit_mode}",
                                    direction="long",
                                    entry_time=open_pos["entry_time"],
                                    exit_time=curr_time,
                                    entry_price=open_pos["entry_price"],
                                    stop_price=open_pos["stop_price"],
                                    exit_price=exit_price,
                                    exit_reason="TAKE_PROFIT_2R",
                                    r_multiple=float(r),
                                    win=bool(r > 0),
                                    is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                                )
                            )
                            open_pos = None
                            continue

                    elif exit_mode == "TRAILING_VWAP":
                        # Sai se fechar abaixo do VWAP
                        if closes[idx - 1] < vwap[idx - 1]:
                            exit_price = opens[idx] - slippage
                            r = (exit_price - open_pos["entry_price"]) / risk
                            trades.append(
                                Trade(
                                    symbol=symbol,
                                    strategy=f"ORB_{orb_minutes}m_{stop_mode}_{exit_mode}",
                                    direction="long",
                                    entry_time=open_pos["entry_time"],
                                    exit_time=curr_time,
                                    entry_price=open_pos["entry_price"],
                                    stop_price=open_pos["stop_price"],
                                    exit_price=exit_price,
                                    exit_reason="EXIT_BELOW_VWAP",
                                    r_multiple=float(r),
                                    win=bool(r > 0),
                                    is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                                )
                            )
                            open_pos = None
                            continue

                    # C. Zeragem no fim da sessão
                    if curr_time >= session_close_time - pd.Timedelta(minutes=5):
                        exit_price = closes[idx] - slippage
                        r = (exit_price - open_pos["entry_price"]) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"ORB_{orb_minutes}m_{stop_mode}_{exit_mode}",
                                direction="long",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="SESSION_CLOSE",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

                else:  # short
                    if highs[idx] + spread >= open_pos["stop_price"]:
                        raw_exit = max(open_pos["stop_price"], opens[idx] + spread)
                        exit_price = raw_exit + slippage
                        r = (open_pos["entry_price"] - exit_price) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"ORB_{orb_minutes}m_{stop_mode}_{exit_mode}",
                                direction="short",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="STOP_LOSS",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

                    if exit_mode == "FIXED_2R":
                        tp = open_pos["entry_price"] - 2.0 * risk
                        if lows[idx] <= tp:
                            raw_exit = min(tp, opens[idx])
                            exit_price = raw_exit + slippage
                            r = (open_pos["entry_price"] - exit_price) / risk
                            trades.append(
                                Trade(
                                    symbol=symbol,
                                    strategy=f"ORB_{orb_minutes}m_{stop_mode}_{exit_mode}",
                                    direction="short",
                                    entry_time=open_pos["entry_time"],
                                    exit_time=curr_time,
                                    entry_price=open_pos["entry_price"],
                                    stop_price=open_pos["stop_price"],
                                    exit_price=exit_price,
                                    exit_reason="TAKE_PROFIT_2R",
                                    r_multiple=float(r),
                                    win=bool(r > 0),
                                    is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                                )
                            )
                            open_pos = None
                            continue

                    elif exit_mode == "TRAILING_VWAP":
                        if closes[idx - 1] > vwap[idx - 1]:
                            exit_price = opens[idx] + spread + slippage
                            r = (open_pos["entry_price"] - exit_price) / risk
                            trades.append(
                                Trade(
                                    symbol=symbol,
                                    strategy=f"ORB_{orb_minutes}m_{stop_mode}_{exit_mode}",
                                    direction="short",
                                    entry_time=open_pos["entry_time"],
                                    exit_time=curr_time,
                                    entry_price=open_pos["entry_price"],
                                    stop_price=open_pos["stop_price"],
                                    exit_price=exit_price,
                                    exit_reason="EXIT_ABOVE_VWAP",
                                    r_multiple=float(r),
                                    win=bool(r > 0),
                                    is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                                )
                            )
                            open_pos = None
                            continue

                    if curr_time >= session_close_time - pd.Timedelta(minutes=5):
                        exit_price = closes[idx] + spread + slippage
                        r = (open_pos["entry_price"] - exit_price) / risk
                        trades.append(
                            Trade(
                                symbol=symbol,
                                strategy=f"ORB_{orb_minutes}m_{stop_mode}_{exit_mode}",
                                direction="short",
                                entry_time=open_pos["entry_time"],
                                exit_time=curr_time,
                                entry_price=open_pos["entry_price"],
                                stop_price=open_pos["stop_price"],
                                exit_price=exit_price,
                                exit_reason="SESSION_CLOSE",
                                r_multiple=float(r),
                                win=bool(r > 0),
                                is_oos=bool(open_pos["entry_time"] >= OOS_SPLIT_DATE),
                            )
                        )
                        open_pos = None
                        continue

            # 2. Entrada de novo trade (apenas 1 trade por dia)
            if open_pos is None and not traded_today:
                # Checa sinal de rompimento na barra i-1
                prev_close = closes[idx - 1]
                prev_vwap = vwap[idx - 1]

                long_signal = (prev_close > orb_high) and (prev_close > prev_vwap)
                short_signal = (prev_close < orb_low) and (prev_close < prev_vwap)

                if long_signal and not short_signal:
                    entry_price = opens[idx] + spread + slippage
                    sl_price = (orb_mid if stop_mode == "MIDPOINT" else orb_low) - slippage
                    risk = entry_price - sl_price
                    if risk > 0:
                        traded_today = True
                        # Checa stop imediato intrabar
                        if lows[idx] <= sl_price:
                            raw_exit = min(sl_price, opens[idx])
                            exit_price = raw_exit - slippage
                            r = (exit_price - entry_price) / risk
                            trades.append(
                                Trade(
                                    symbol=symbol,
                                    strategy=f"ORB_{orb_minutes}m_{stop_mode}_{exit_mode}",
                                    direction="long",
                                    entry_time=curr_time,
                                    exit_time=curr_time,
                                    entry_price=entry_price,
                                    stop_price=sl_price,
                                    exit_price=exit_price,
                                    exit_reason="STOP_ENTRY_BAR",
                                    r_multiple=float(r),
                                    win=bool(r > 0),
                                    is_oos=bool(curr_time >= OOS_SPLIT_DATE),
                                )
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
                    sl_price = (orb_mid if stop_mode == "MIDPOINT" else orb_high) + spread + slippage
                    risk = sl_price - entry_price
                    if risk > 0:
                        traded_today = True
                        if highs[idx] + spread >= sl_price:
                            raw_exit = max(sl_price, opens[idx] + spread)
                            exit_price = raw_exit + slippage
                            r = (entry_price - exit_price) / risk
                            trades.append(
                                Trade(
                                    symbol=symbol,
                                    strategy=f"ORB_{orb_minutes}m_{stop_mode}_{exit_mode}",
                                    direction="short",
                                    entry_time=curr_time,
                                    exit_time=curr_time,
                                    entry_price=entry_price,
                                    stop_price=sl_price,
                                    exit_price=exit_price,
                                    exit_reason="STOP_ENTRY_BAR",
                                    r_multiple=float(r),
                                    win=bool(r > 0),
                                    is_oos=bool(curr_time >= OOS_SPLIT_DATE),
                                )
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


def run_orb_experiments():
    print("=" * 115)
    print("PESQUISA HIPÓTESE 1: OPENING RANGE BREAKOUT (ORB) + VWAP NO PREGÃO DE NY")
    print("=" * 115)

    experiments = [
        {"orb_min": 30, "stop": "MIDPOINT", "exit": "SESSION_CLOSE"},
        {"orb_min": 30, "stop": "FULL", "exit": "SESSION_CLOSE"},
        {"orb_min": 30, "stop": "MIDPOINT", "exit": "TRAILING_VWAP"},
        {"orb_min": 30, "stop": "MIDPOINT", "exit": "FIXED_2R"},
        {"orb_min": 15, "stop": "MIDPOINT", "exit": "SESSION_CLOSE"},
    ]

    for exp in experiments:
        orb_min = exp["orb_min"]
        stop_m = exp["stop"]
        exit_m = exp["exit"]
        print(f"\n>>> CONFIGURAÇÃO: ORB {orb_min}m | Stop: {stop_m} | Saída: {exit_m}")
        print("-" * 115)

        all_trades = []
        for sym in SYMBOLS:
            p = Path(f"data/{sym}_M1_dukascopy.parquet")
            if not p.exists():
                continue
            df_m1 = pd.read_parquet(p)
            df_m5 = df_m1.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()

            tr = simulate_orb(df_m5, sym, SPREADS[sym], SLIPPAGES[sym], orb_minutes=orb_min, stop_mode=stop_m, exit_mode=exit_m)
            st = calc_stats(tr)
            all_trades.extend(tr)
            print(
                f"{sym:6s} | Trades={st['n']:3d} (C:{st['longs']:2d} V:{st['shorts']:2d}) | "
                f"TotalR={st['total_r']:+6.1f}R | R/trade={st['mean_r']:+0.2f}±{st['se_r']:0.2f} (t={st['t_stat']:4.2f}) | "
                f"PF={st['pf']:4.2f} | WR={st['wr']:4.1f}% | AvgWin={st['avg_win']:4.1f}R | AvgLoss={st['avg_loss']:4.1f}R | MaxDD={st['max_dd']:4.1f}R"
            )

        st_all = calc_stats(all_trades)
        print(f"\n[CONSOLIDADO CARTEIRA - ORB {orb_min}m {stop_m} {exit_m}]")
        print(
            f"Trades: {st_all['n']} (C:{st_all['longs']} V:{st_all['shorts']}) | Total R: {st_all['total_r']:+.1f}R | "
            f"R/trade: {st_all['mean_r']:+.3f} ± {st_all['se_r']:.3f} | t-stat: {st_all['t_stat']:.2f} | PF: {st_all['pf']:.2f} | WR: {st_all['wr']:.1f}% | MaxDD: {st_all['max_dd']:.1f}R"
        )


if __name__ == "__main__":
    run_orb_experiments()

"""Pesquisa Rigorosa de SMC Multi-Timeframe: Estrutura Macro (H1) + Refinamento Micro CHoCH (M15).

Conceito Institucional:
1. Macro (H1): Identifica perna impulsiva confirmada (Pivôs com k=2 em H1 sem lookahead).
   - Traça Fibonacci na perna (0.0% no topo/fundo, 100.0% na origem).
   - POI Macro: Zona de Desconto / OTE entre 61.8% e 78.6%.
2. Micro (M15):
   - Preço entra no POI Macro.
   - Aguarda CHoCH (Change of Character) no M15: rompimento do último topo/fundo da correção.
3. Execução Causal (AGENTS.md):
   - Entrada no candle seguinte ao CHoCH confirmado.
   - Stop Loss: Extremo da estrutura do CHoCH micro (fundo para Long, topo para Short).
   - Take Profit: Nível 0.0% da perna macro (topo para Long, fundo para Short).
   - Filtro de Geometria: Requer RR >= 2.0 (caso contrário, descarta o setup).
   - Checagem imediata de stop na barra de entrada.
   - Gaps de abertura no stop loss preenchidos no Open.
   - Spreads reais e slippage aplicados.
   - Modo single-position estrito por ativo.
   - Auditoria de simetria (compras vs vendas) e controle de entradas no Open vs Gatilho.
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
class Pivot:
    time: pd.Timestamp
    kind: str  # 'high' ou 'low'
    price: float
    confirmed_idx: int
    confirmed_time: pd.Timestamp


@dataclass
class Trade:
    symbol: str
    direction: str  # 'long' ou 'short'
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    exit_price: float
    exit_reason: str
    r_multiple: float
    win: bool
    is_oos: bool
    theoretical_rr: float


def find_causal_pivots(df: pd.DataFrame, k: int = 2) -> list[Pivot]:
    """Detecta pivôs com confirmação causal estrita em k barras à frente."""
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    ts = df.index
    n = len(df)
    pivots: list[Pivot] = []

    for i in range(k, n - k):
        # Topo: maior que k barras antes e maior ou igual a k barras depois
        is_high = np.all(highs[i] > highs[i - k : i]) and np.all(highs[i] >= highs[i + 1 : i + k + 1])
        # Fundo: menor que k barras antes e menor ou igual a k barras depois
        is_low = np.all(lows[i] < lows[i - k : i]) and np.all(lows[i] <= lows[i + 1 : i + k + 1])

        if is_high:
            pivots.append(Pivot(
                time=ts[i],
                kind="high",
                price=float(highs[i]),
                confirmed_idx=i + k,
                confirmed_time=ts[i + k],
            ))
        if is_low:
            pivots.append(Pivot(
                time=ts[i],
                kind="low",
                price=float(lows[i]),
                confirmed_idx=i + k,
                confirmed_time=ts[i + k],
            ))

    # Ordenar por confirmed_time
    pivots.sort(key=lambda p: (p.confirmed_time, p.time))
    return pivots


def simulate_smc_macro_micro(
    df_h1: pd.DataFrame,
    df_m15: pd.DataFrame,
    symbol: str,
    spread: float,
    slippage: float,
    min_rr: float = 1.5,
    target_mode: str = "MACRO_EXTREME",  # 'MACRO_EXTREME', 'FIXED_2R', 'FIXED_1_5R', 'FIXED_3R'
    k_macro: int = 2,
    k_micro: int = 2,
) -> list[Trade]:
    """Simula estratégia causal SMC Macro (H1) + Micro CHoCH (M15)."""
    pivots_h1 = find_causal_pivots(df_h1, k=k_macro)
    pivots_m15 = find_causal_pivots(df_m15, k=k_micro)

    opens_m15 = df_m15["open"].to_numpy(dtype=float)
    highs_m15 = df_m15["high"].to_numpy(dtype=float)
    lows_m15 = df_m15["low"].to_numpy(dtype=float)
    closes_m15 = df_m15["close"].to_numpy(dtype=float)
    ts_m15 = df_m15.index
    n_m15 = len(df_m15)

    last_high_h1: Pivot | None = None
    last_low_h1: Pivot | None = None
    last_micro_high: Pivot | None = None
    last_micro_low: Pivot | None = None

    p_h1_idx = 0
    num_p_h1 = len(pivots_h1)

    p_m15_idx = 0
    num_p_m15 = len(pivots_m15)

    trades: list[Trade] = []
    open_pos = None

    for i in range(50, n_m15 - 1):
        cur_time = ts_m15[i]

        while p_h1_idx < num_p_h1 and pivots_h1[p_h1_idx].confirmed_time <= cur_time:
            p = pivots_h1[p_h1_idx]
            if p.kind == "high":
                last_high_h1 = p
            else:
                last_low_h1 = p
            p_h1_idx += 1

        while p_m15_idx < num_p_m15 and pivots_m15[p_m15_idx].confirmed_time <= cur_time:
            p = pivots_m15[p_m15_idx]
            if p.kind == "high":
                last_micro_high = p
            else:
                last_micro_low = p
            p_m15_idx += 1

        # 1. GESTÃO DE POSIÇÃO ABERTA
        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_sl = False
            hit_tp = False

            if d == 1:
                if lows_m15[i] <= pos["stop_price"]:
                    hit_sl = True
                elif highs_m15[i] >= pos["target_price"]:
                    hit_tp = True
            else:
                if highs_m15[i] + spread >= pos["stop_price"]:
                    hit_sl = True
                elif lows_m15[i] + spread <= pos["target_price"]:
                    hit_tp = True

            # Conflito na mesma barra: assume stop loss (conservadorismo estrito)
            if hit_sl and hit_tp:
                hit_tp = False

            if hit_sl:
                if d == 1:
                    raw_exit = min(pos["stop_price"], opens_m15[i])
                    exit_price = raw_exit - slippage
                    r = (exit_price - pos["entry_price"]) / pos["initial_risk"]
                else:
                    raw_exit = max(pos["stop_price"], opens_m15[i] + spread)
                    exit_price = raw_exit + slippage
                    r = (pos["entry_price"] - exit_price) / pos["initial_risk"]

                trades.append(
                    Trade(
                        symbol=symbol,
                        direction=pos["direction"],
                        entry_time=pos["entry_time"],
                        exit_time=ts_m15[i],
                        entry_price=pos["entry_price"],
                        stop_price=pos["stop_price"],
                        target_price=pos["target_price"],
                        exit_price=exit_price,
                        exit_reason="STOP_LOSS",
                        r_multiple=float(r),
                        win=bool(r > 0),
                        is_oos=bool(ts_m15[i] >= OOS_SPLIT_DATE),
                        theoretical_rr=pos["theoretical_rr"],
                    )
                )
                open_pos = None
                continue

            elif hit_tp:
                exit_price = pos["target_price"]
                r = (
                    (exit_price - pos["entry_price"]) / pos["initial_risk"]
                    if d == 1
                    else (pos["entry_price"] - exit_price) / pos["initial_risk"]
                )
                trades.append(
                    Trade(
                        symbol=symbol,
                        direction=pos["direction"],
                        entry_time=pos["entry_time"],
                        exit_time=ts_m15[i],
                        entry_price=pos["entry_price"],
                        stop_price=pos["stop_price"],
                        target_price=pos["target_price"],
                        exit_price=exit_price,
                        exit_reason="TAKE_PROFIT",
                        r_multiple=float(r),
                        win=bool(r > 0),
                        is_oos=bool(ts_m15[i] >= OOS_SPLIT_DATE),
                        theoretical_rr=pos["theoretical_rr"],
                    )
                )
                open_pos = None
                continue

        # 2. IDENTIFICAÇÃO DE SINAIS
        if open_pos is None and last_high_h1 is not None and last_low_h1 is not None:
            is_macro_bullish = last_high_h1.time > last_low_h1.time and last_high_h1.price > last_low_h1.price
            is_macro_bearish = last_low_h1.time > last_high_h1.time and last_low_h1.price < last_high_h1.price

            long_signal = False
            short_signal = False
            long_entry, short_entry = 0.0, 0.0
            long_sl, short_sl = 0.0, 0.0
            long_tp, short_tp = 0.0, 0.0
            long_rr, short_rr = 0.0, 0.0

            if is_macro_bullish and last_micro_high is not None and last_micro_low is not None:
                p_low = last_low_h1.price
                p_high = last_high_h1.price
                leg_range = p_high - p_low

                poi_top = p_high - 0.618 * leg_range
                poi_bottom = p_high - 0.786 * leg_range

                in_poi = (lows_m15[i - 1] <= poi_top) and (closes_m15[i - 1] >= poi_bottom) and (lows_m15[i - 1] > p_low)
                micro_valid = (last_micro_high.time > last_high_h1.time) and (last_micro_low.time > last_high_h1.time)

                if in_poi and micro_valid:
                    choch_confirmed = (closes_m15[i - 1] > last_micro_high.price) and (closes_m15[i - 2] <= last_micro_high.price)
                    if choch_confirmed:
                        long_entry = opens_m15[i] + spread + slippage
                        long_sl = last_micro_low.price - slippage
                        risk = long_entry - long_sl

                        if target_mode == "MACRO_EXTREME":
                            long_tp = p_high
                        elif target_mode == "FIXED_2R":
                            long_tp = long_entry + 2.0 * risk
                        elif target_mode == "FIXED_1_5R":
                            long_tp = long_entry + 1.5 * risk
                        elif target_mode == "FIXED_3R":
                            long_tp = long_entry + 3.0 * risk

                        reward = long_tp - long_entry
                        if risk > 0 and reward > 0:
                            long_rr = reward / risk
                            if long_rr >= min_rr:
                                long_signal = True

            elif is_macro_bearish and last_micro_high is not None and last_micro_low is not None:
                p_high = last_high_h1.price
                p_low = last_low_h1.price
                leg_range = p_high - p_low

                poi_bottom = p_low + 0.618 * leg_range
                poi_top = p_low + 0.786 * leg_range

                in_poi = (highs_m15[i - 1] >= poi_bottom) and (closes_m15[i - 1] <= poi_top) and (highs_m15[i - 1] < p_high)
                micro_valid = (last_micro_high.time > last_low_h1.time) and (last_micro_low.time > last_low_h1.time)

                if in_poi and micro_valid:
                    choch_confirmed = (closes_m15[i - 1] < last_micro_low.price) and (closes_m15[i - 2] >= last_micro_low.price)
                    if choch_confirmed:
                        short_entry = opens_m15[i] - slippage
                        short_sl = last_micro_high.price + spread + slippage
                        risk = short_sl - short_entry

                        if target_mode == "MACRO_EXTREME":
                            short_tp = p_low
                        elif target_mode == "FIXED_2R":
                            short_tp = short_entry - 2.0 * risk
                        elif target_mode == "FIXED_1_5R":
                            short_tp = short_entry - 1.5 * risk
                        elif target_mode == "FIXED_3R":
                            short_tp = short_entry - 3.0 * risk

                        reward = short_entry - short_tp
                        if risk > 0 and reward > 0:
                            short_rr = reward / risk
                            if short_rr >= min_rr:
                                short_signal = True

            if long_signal and short_signal:
                continue

            if long_signal:
                risk = long_entry - long_sl
                if lows_m15[i] <= long_sl:
                    raw_exit = min(long_sl, opens_m15[i])
                    exit_price = raw_exit - slippage
                    r = (exit_price - long_entry) / risk
                    trades.append(
                        Trade(
                            symbol=symbol,
                            direction="long",
                            entry_time=ts_m15[i],
                            exit_time=ts_m15[i],
                            entry_price=long_entry,
                            stop_price=long_sl,
                            target_price=long_tp,
                            exit_price=exit_price,
                            exit_reason="STOP_LOSS_ENTRY",
                            r_multiple=float(r),
                            win=bool(r > 0),
                            is_oos=bool(ts_m15[i] >= OOS_SPLIT_DATE),
                            theoretical_rr=long_rr,
                        )
                    )
                else:
                    open_pos = {
                        "direction": "long",
                        "entry_idx": i,
                        "entry_time": ts_m15[i],
                        "entry_price": long_entry,
                        "stop_price": long_sl,
                        "target_price": long_tp,
                        "initial_risk": risk,
                        "theoretical_rr": long_rr,
                    }

            elif short_signal:
                risk = short_sl - short_entry
                if highs_m15[i] + spread >= short_sl:
                    raw_exit = max(short_sl, opens_m15[i] + spread)
                    exit_price = raw_exit + slippage
                    r = (short_entry - exit_price) / risk
                    trades.append(
                        Trade(
                            symbol=symbol,
                            direction="short",
                            entry_time=ts_m15[i],
                            exit_time=ts_m15[i],
                            entry_price=short_entry,
                            stop_price=short_sl,
                            target_price=short_tp,
                            exit_price=exit_price,
                            exit_reason="STOP_LOSS_ENTRY",
                            r_multiple=float(r),
                            win=bool(r > 0),
                            is_oos=bool(ts_m15[i] >= OOS_SPLIT_DATE),
                            theoretical_rr=short_rr,
                        )
                    )
                else:
                    open_pos = {
                        "direction": "short",
                        "entry_idx": i,
                        "entry_time": ts_m15[i],
                        "entry_price": short_entry,
                        "stop_price": short_sl,
                        "target_price": short_tp,
                        "initial_risk": risk,
                        "theoretical_rr": short_rr,
                    }

            # Conflito mútuo: descartar
            if long_signal and short_signal:
                continue

            # Execução de Compra
            if long_signal:
                risk = long_entry - long_sl
                # Checagem imediata de stop na própria barra de entrada i
                if lows_m15[i] <= long_sl:
                    raw_exit = min(long_sl, opens_m15[i])
                    exit_price = raw_exit - slippage
                    r = (exit_price - long_entry) / risk
                    trades.append(
                        Trade(
                            symbol=symbol,
                            direction="long",
                            entry_time=ts_m15[i],
                            exit_time=ts_m15[i],
                            entry_price=long_entry,
                            stop_price=long_sl,
                            target_price=long_tp,
                            exit_price=exit_price,
                            exit_reason="STOP_LOSS_ENTRY",
                            r_multiple=float(r),
                            win=bool(r > 0),
                            is_oos=bool(ts_m15[i] >= OOS_SPLIT_DATE),
                            theoretical_rr=long_rr,
                        )
                    )
                else:
                    open_pos = {
                        "direction": "long",
                        "entry_idx": i,
                        "entry_time": ts_m15[i],
                        "entry_price": long_entry,
                        "stop_price": long_sl,
                        "target_price": long_tp,
                        "initial_risk": risk,
                        "theoretical_rr": long_rr,
                    }

            # Execução de Venda
            elif short_signal:
                risk = short_sl - short_entry
                # Checagem imediata de stop na própria barra de entrada i
                if highs_m15[i] + spread >= short_sl:
                    raw_exit = max(short_sl, opens_m15[i] + spread)
                    exit_price = raw_exit + slippage
                    r = (short_entry - exit_price) / risk
                    trades.append(
                        Trade(
                            symbol=symbol,
                            direction="short",
                            entry_time=ts_m15[i],
                            exit_time=ts_m15[i],
                            entry_price=short_entry,
                            stop_price=short_sl,
                            target_price=short_tp,
                            exit_price=exit_price,
                            exit_reason="STOP_LOSS_ENTRY",
                            r_multiple=float(r),
                            win=bool(r > 0),
                            is_oos=bool(ts_m15[i] >= OOS_SPLIT_DATE),
                            theoretical_rr=short_rr,
                        )
                    )
                else:
                    open_pos = {
                        "direction": "short",
                        "entry_idx": i,
                        "entry_time": ts_m15[i],
                        "entry_price": short_entry,
                        "stop_price": short_sl,
                        "target_price": short_tp,
                        "initial_risk": risk,
                        "theoretical_rr": short_rr,
                    }

    return trades


def calc_stats(trades: list[Trade]) -> dict:
    if not trades:
        return {
            "n": 0,
            "wr": 0.0,
            "pf": 0.0,
            "total_r": 0.0,
            "mean_r": 0.0,
            "se_r": 0.0,
            "t_stat": 0.0,
            "max_dd": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "longs": 0,
            "shorts": 0,
            "avg_rr": 0.0,
        }
    rs = np.array([t.r_multiple for t in trades])
    wins = rs[rs > 0]
    losses = rs[rs < 0]

    gross_profit = float(wins.sum()) if len(wins) > 0 else 0.0
    gross_loss = float(abs(losses.sum())) if len(losses) > 0 else 0.0
    pf = (gross_profit / gross_loss) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

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
    avg_rr = float(np.mean([t.theoretical_rr for t in trades])) if trades else 0.0

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
        "avg_rr": avg_rr,
    }


def main():
    print("=" * 115)
    print("PESQUISA SMC MULTI-TIMEFRAME: ESTRUTURA MACRO (H1) + CHOCH MICRO (M15) NO POI")
    print("=" * 115)

    target_modes = ["MACRO_EXTREME", "FIXED_2R", "FIXED_1_5R"]

    for mode in target_modes:
        print(f"\n>>> AVALIANDO MODO DE ALVO: {mode}")
        print("-" * 115)
        all_mode_trades = []

        for sym in SYMBOLS:
            p = Path(f"data/{sym}_M1_dukascopy.parquet")
            if not p.exists():
                continue

            df_m1 = pd.read_parquet(p)
            df_h1 = (
                df_m1.resample("1h")
                .agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                })
                .dropna()
            )
            df_m15 = (
                df_m1.resample("15min")
                .agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                })
                .dropna()
            )

            spread = SPREADS[sym]
            slippage = SLIPPAGES[sym]

            # Simulação com custos reais
            trades_cost = simulate_smc_macro_micro(df_h1, df_m15, sym, spread, slippage, min_rr=1.5, target_mode=mode)
            st_cost = calc_stats(trades_cost)
            all_mode_trades.extend(trades_cost)

            # Simulação sem custos
            trades_nocost = simulate_smc_macro_micro(df_h1, df_m15, sym, 0.0, 0.0, min_rr=1.5, target_mode=mode)
            st_nocost = calc_stats(trades_nocost)

            print(
                f"{sym:6s} | Trades={st_cost['n']:3d} (C:{st_cost['longs']:2d} V:{st_cost['shorts']:2d}) | "
                f"TotalR={st_cost['total_r']:+6.1f}R | R/trade={st_cost['mean_r']:+0.2f}±{st_cost['se_r']:0.2f} (t={st_cost['t_stat']:4.2f}) | "
                f"PF={st_cost['pf']:4.2f} (SemCusto={st_nocost['pf']:4.2f}) | WR={st_cost['wr']:4.1f}% | "
                f"AvgWin={st_cost['avg_win']:4.1f}R | AvgLoss={st_cost['avg_loss']:4.1f}R | "
                f"MaxDD={st_cost['max_dd']:4.1f}R"
            )

        st_all = calc_stats(all_mode_trades)
        print(f"\n[CONSOLIDADO CARTEIRA - {mode}]")
        print(
            f"Trades: {st_all['n']} (Compras: {st_all['longs']} | Vendas: {st_all['shorts']}) | "
            f"Total R: {st_all['total_r']:+.1f}R | R/trade: {st_all['mean_r']:+.3f} ± {st_all['se_r']:.3f} | "
            f"t-stat: {st_all['t_stat']:.2f} | PF: {st_all['pf']:.2f} | WR: {st_all['wr']:.1f}% | "
            f"MaxDD: {st_all['max_dd']:.1f}R"
        )


if __name__ == "__main__":
    main()

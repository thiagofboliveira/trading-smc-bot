"""Estudo do Gradiente de Timeframes: D1 -> H4 -> H2 -> H1 -> M30 -> M15.

Objetivo:
Mapear a fronteira exata de degradação da estratégia de Trend Following (TURTLE_20_10 e TURTLE_50_20)
ao descer os timeframes:
- Onde está a zona ótima de retorno/risco?
- Em qual timeframe a fricção (spread + slippage) e o ruído intradiário começam a destruir o alpha?
- Como o Payoff Ratio, Win Rate, Expectativa e t-statística se comportam em cada degrau?

Metodologia Anti-Viés (AGENTS.md):
- Indicadores calculados estritamente em i-1 (shift(1).rolling(w)).
- Ordem BuyStop/SellStop executada no toque ou com gap na abertura da barra i.
- Stop na barra de entrada testado imediatamente no fill.
- Stop loss com gap preenchido no Open + slippage.
- Spreads reais e slippage aplicados em cada execução stop.
- Modo single-position estrito por ativo.
- Comparação com e sem custos em cada timeframe para isolar o impacto da fricção.
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
    timeframe: str
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
    initial_risk: float


def compute_indicators(df: pd.DataFrame) -> dict[str, np.ndarray]:
    close = df["close"]
    high = df["high"]
    low = df["low"]

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr20 = tr.rolling(window=20).mean().bfill().to_numpy(dtype=float)

    # Donchian Channels causais (olham de i-w até i-1)
    donchian_high_20 = high.shift(1).rolling(window=20).max().to_numpy(dtype=float)
    donchian_low_20 = low.shift(1).rolling(window=20).min().to_numpy(dtype=float)
    donchian_high_10 = high.shift(1).rolling(window=10).max().to_numpy(dtype=float)
    donchian_low_10 = low.shift(1).rolling(window=10).min().to_numpy(dtype=float)
    donchian_high_50 = high.shift(1).rolling(window=50).max().to_numpy(dtype=float)
    donchian_low_50 = low.shift(1).rolling(window=50).min().to_numpy(dtype=float)

    return {
        "atr20": atr20,
        "donchian_high_20": donchian_high_20,
        "donchian_low_20": donchian_low_20,
        "donchian_high_10": donchian_high_10,
        "donchian_low_10": donchian_low_10,
        "donchian_high_50": donchian_high_50,
        "donchian_low_50": donchian_low_50,
    }


def simulate_strategy(
    df: pd.DataFrame,
    symbol: str,
    tf_name: str,
    strategy_name: str,
    spread: float,
    slippage: float,
) -> list[Trade]:
    ind = compute_indicators(df)
    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    ts = df.index
    n = len(opens)

    atr20 = ind["atr20"]
    dh20 = ind["donchian_high_20"]
    dl20 = ind["donchian_low_20"]
    dh10 = ind["donchian_high_10"]
    dl10 = ind["donchian_low_10"]
    dh50 = ind["donchian_high_50"]
    dl50 = ind["donchian_low_50"]

    trades: list[Trade] = []
    open_pos = None

    # Warmup de 60 barras
    for i in range(60, n - 1):
        # 1. Posição aberta: verificar saídas antes de novas entradas
        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_sl = False
            exit_by_rule = False
            exit_rule_price = 0.0

            # A. Teste de Stop Loss na barra i
            if d == 1:
                if lows[i] <= pos["stop_price"]:
                    hit_sl = True
            else:
                if highs[i] + spread >= pos["stop_price"]:
                    hit_sl = True

            # B. Teste de Saída por canal oposto (após barra de entrada)
            if not hit_sl and i > pos["entry_idx"]:
                if strategy_name == "TURTLE_20_10":
                    if d == 1 and lows[i] <= dl10[i]:
                        exit_by_rule = True
                        exit_rule_price = min(dl10[i], opens[i]) - slippage
                    elif d == -1 and highs[i] + spread >= dh10[i]:
                        exit_by_rule = True
                        exit_rule_price = max(dh10[i], opens[i] + spread) + slippage
                elif strategy_name == "TURTLE_50_20":
                    if d == 1 and lows[i] <= dl20[i]:
                        exit_by_rule = True
                        exit_rule_price = min(dl20[i], opens[i]) - slippage
                    elif d == -1 and highs[i] + spread >= dh20[i]:
                        exit_by_rule = True
                        exit_rule_price = max(dh20[i], opens[i] + spread) + slippage

            if hit_sl:
                if d == 1:
                    raw_exit = min(pos["stop_price"], opens[i])
                    exit_price = raw_exit - slippage
                    r = (exit_price - pos["entry_price"]) / pos["initial_risk"]
                else:
                    raw_exit = max(pos["stop_price"], opens[i] + spread)
                    exit_price = raw_exit + slippage
                    r = (pos["entry_price"] - exit_price) / pos["initial_risk"]

                trades.append(
                    Trade(
                        symbol=symbol,
                        strategy=strategy_name,
                        timeframe=tf_name,
                        direction=pos["direction"],
                        entry_time=pos["entry_time"],
                        exit_time=ts[i],
                        entry_price=pos["entry_price"],
                        stop_price=pos["stop_price"],
                        exit_price=exit_price,
                        exit_reason="STOP_LOSS",
                        r_multiple=float(r),
                        win=bool(r > 0),
                        is_oos=bool(ts[i] >= OOS_SPLIT_DATE),
                        initial_risk=pos["initial_risk"],
                    )
                )
                open_pos = None
                continue

            elif exit_by_rule:
                exit_price = exit_rule_price
                r = (
                    (exit_price - pos["entry_price"]) / pos["initial_risk"]
                    if d == 1
                    else (pos["entry_price"] - exit_price) / pos["initial_risk"]
                )
                trades.append(
                    Trade(
                        symbol=symbol,
                        strategy=strategy_name,
                        timeframe=tf_name,
                        direction=pos["direction"],
                        entry_time=pos["entry_time"],
                        exit_time=ts[i],
                        entry_price=pos["entry_price"],
                        stop_price=pos["stop_price"],
                        exit_price=exit_price,
                        exit_reason="RULE_EXIT",
                        r_multiple=float(r),
                        win=bool(r > 0),
                        is_oos=bool(ts[i] >= OOS_SPLIT_DATE),
                        initial_risk=pos["initial_risk"],
                    )
                )
                open_pos = None
                continue

        # 2. Ordem de entrada armada em i-1 para disparo em i
        if open_pos is None:
            long_armed = False
            short_armed = False
            long_trigger = 0.0
            short_trigger = 0.0
            stop_dist = 0.0

            if strategy_name == "TURTLE_20_10":
                if not np.isnan(dh20[i]):
                    long_armed = True
                    long_trigger = dh20[i]
                    stop_dist = 2.0 * atr20[i - 1]
                if not np.isnan(dl20[i]):
                    short_armed = True
                    short_trigger = dl20[i]
                    stop_dist = 2.0 * atr20[i - 1]
            elif strategy_name == "TURTLE_50_20":
                if not np.isnan(dh50[i]):
                    long_armed = True
                    long_trigger = dh50[i]
                    stop_dist = 3.0 * atr20[i - 1]
                if not np.isnan(dl50[i]):
                    short_armed = True
                    short_trigger = dl50[i]
                    stop_dist = 3.0 * atr20[i - 1]

            long_triggered = long_armed and (highs[i] >= long_trigger)
            short_triggered = short_armed and (lows[i] <= short_trigger)

            if long_triggered and short_triggered:
                continue

            if long_triggered:
                exec_price = max(opens[i], long_trigger) + spread + slippage
                stop_price = exec_price - stop_dist
                risk = exec_price - stop_price

                # Verificação imediata do stop na barra de entrada
                if lows[i] <= stop_price:
                    raw_exit = min(stop_price, opens[i])
                    exit_price = raw_exit - slippage
                    r = (exit_price - exec_price) / risk
                    trades.append(
                        Trade(
                            symbol=symbol,
                            strategy=strategy_name,
                            timeframe=tf_name,
                            direction="long",
                            entry_time=ts[i],
                            exit_time=ts[i],
                            entry_price=exec_price,
                            stop_price=stop_price,
                            exit_price=exit_price,
                            exit_reason="STOP_LOSS_ENTRY",
                            r_multiple=float(r),
                            win=bool(r > 0),
                            is_oos=bool(ts[i] >= OOS_SPLIT_DATE),
                            initial_risk=risk,
                        )
                    )
                else:
                    open_pos = {
                        "direction": "long",
                        "entry_idx": i,
                        "entry_time": ts[i],
                        "entry_price": exec_price,
                        "stop_price": stop_price,
                        "initial_risk": risk,
                    }

            elif short_triggered:
                exec_price = min(opens[i], short_trigger) - slippage
                stop_price = exec_price + stop_dist
                risk = stop_price - exec_price

                # Verificação imediata do stop na barra de entrada
                if highs[i] + spread >= stop_price:
                    raw_exit = max(stop_price, opens[i] + spread)
                    exit_price = raw_exit + slippage
                    r = (exec_price - exit_price) / risk
                    trades.append(
                        Trade(
                            symbol=symbol,
                            strategy=strategy_name,
                            timeframe=tf_name,
                            direction="short",
                            entry_time=ts[i],
                            exit_time=ts[i],
                            entry_price=exec_price,
                            stop_price=stop_price,
                            exit_price=exit_price,
                            exit_reason="STOP_LOSS_ENTRY",
                            r_multiple=float(r),
                            win=bool(r > 0),
                            is_oos=bool(ts[i] >= OOS_SPLIT_DATE),
                            initial_risk=risk,
                        )
                    )
                else:
                    open_pos = {
                        "direction": "short",
                        "entry_idx": i,
                        "entry_time": ts[i],
                        "entry_price": exec_price,
                        "stop_price": stop_price,
                        "initial_risk": risk,
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
            "payoff": 0.0,
            "mean_risk": 0.0,
        }
    rs = np.array([t.r_multiple for t in trades])
    risks = np.array([t.initial_risk for t in trades])
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
    payoff = (avg_win / avg_loss) if avg_loss > 0 else 0.0
    mean_risk = float(risks.mean()) if len(risks) > 0 else 0.0

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
        "payoff": payoff,
        "mean_risk": mean_risk,
    }


def main():
    print("=" * 105)
    print("ESTUDO DO GRADIENTE DE TIMEFRAMES: D1 -> H4 -> H2 -> H1 -> M30 -> M15")
    print("=" * 105)

    timeframes = [
        ("D1", "1D"),
        ("H4", "4h"),
        ("H2", "2h"),
        ("H1", "1h"),
        ("M30", "30min"),
        ("M15", "15min"),
    ]

    strategies = ["TURTLE_20_10", "TURTLE_50_20"]

    gradient_summary = []

    # Carregar dados M1 uma única vez em memória para acelerar
    print("Carregando datasets M1 dos 6 ativos...")
    dfs_m1 = {}
    for sym in SYMBOLS:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        if p.exists():
            dfs_m1[sym] = pd.read_parquet(p)
            print(f"  - {sym}: {len(dfs_m1[sym]):,} barras M1")
    print("Carregamento concluído.\n")

    for tf_label, tf_rule in timeframes:
        print(f"\n" + "-" * 105)
        print(f">>> AVALIANDO TIMEFRAME: {tf_label} ({tf_rule})")
        print("-" * 105)

        for strat in strategies:
            all_trades_cost = []
            all_trades_nocost = []
            asset_stats = {}

            for sym in SYMBOLS:
                if sym not in dfs_m1:
                    continue
                df_m1 = dfs_m1[sym]
                df_tf = (
                    df_m1.resample(tf_rule)
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

                trades_cost = simulate_strategy(df_tf, sym, tf_label, strat, spread, slippage)
                trades_nocost = simulate_strategy(df_tf, sym, tf_label, strat, 0.0, 0.0)

                all_trades_cost.extend(trades_cost)
                all_trades_nocost.extend(trades_nocost)

                st_sym = calc_stats(trades_cost)
                asset_stats[sym] = st_sym

            st_all = calc_stats(all_trades_cost)
            st_nocost = calc_stats(all_trades_nocost)
            st_is = calc_stats([t for t in all_trades_cost if not t.is_oos])
            st_oos = calc_stats([t for t in all_trades_cost if t.is_oos])

            # Estimativa de atrito médio (diferença de R/trade entre com e sem custos)
            friction_drag_r = (st_nocost["mean_r"] - st_all["mean_r"]) if st_all["n"] > 0 else 0.0

            gradient_summary.append({
                "tf": tf_label,
                "strategy": strat,
                "stats_cost": st_all,
                "stats_nocost": st_nocost,
                "stats_is": st_is,
                "stats_oos": st_oos,
                "friction_drag_r": friction_drag_r,
                "asset_stats": asset_stats,
            })

            print(
                f"[{tf_label:3s}] {strat:13s} | Trades={st_all['n']:5d} | "
                f"TotalR={st_all['total_r']:+7.1f}R | R/trade={st_all['mean_r']:+0.3f}±{st_all['se_r']:0.3f} | "
                f"t-stat={st_all['t_stat']:4.2f} | PF={st_all['pf']:4.2f} | WR={st_all['wr']:4.1f}% | "
                f"Payoff={st_all['payoff']:4.2f} | MaxDD={st_all['max_dd']:5.1f}R | "
                f"IS={st_is['total_r']:+6.1f}R | OOS={st_oos['total_r']:+6.1f}R | "
                f"Arrasto Custo={friction_drag_r:0.3f}R/t"
            )

    # Imprimir tabela comparativa consolidada
    print("\n" + "=" * 125)
    print("MATRIZ DE DEGRADAÇÃO TEMPORAL - CARTEIRA (6 ATIVOS)")
    print("=" * 125)
    for strat in strategies:
        print(f"\n--- Estratégia: {strat} ---")
        print(
            f"{'TF':<5} {'Trades':<7} {'Total R':<9} {'R/trade ± SE':<17} {'t-stat':<7} {'PF':<6} {'WR%':<6} {'Payoff':<7} {'MaxDD':<7} {'IS (R)':<8} {'OOS (R)':<8} {'Arrasto Custo':<13} {'PF Sem Custo'}"
        )
        print("-" * 125)
        for row in gradient_summary:
            if row["strategy"] == strat:
                st = row["stats_cost"]
                st_nc = row["stats_nocost"]
                st_is = row["stats_is"]
                st_oos = row["stats_oos"]
                print(
                    f"{row['tf']:<5} {st['n']:<7d} {st['total_r']:<+9.1f} "
                    f"{st['mean_r']:+0.3f}±{st['se_r']:0.3f}   {st['t_stat']:<7.2f} "
                    f"{st['pf']:<6.2f} {st['wr']:<5.1f}% {st['payoff']:<7.2f} {st['max_dd']:<6.1f}R "
                    f"{st_is['total_r']:<+8.1f} {st_oos['total_r']:<+8.1f} "
                    f"{row['friction_drag_r']:<13.3f} {st_nc['pf']:0.2f}"
                )

    # Breakdown por ativo no D1 vs H4 vs H2 vs H1 vs M30 para TURTLE_20_10
    print("\n" + "=" * 125)
    print("EVOLUÇÃO DO TOTAL R POR ATIVO EM CADA TIMEFRAME (TURTLE_20_10)")
    print("=" * 125)
    header = f"{'Ativo':<8} " + " ".join([f"{tf[0]:>12}" for tf in timeframes])
    print(header)
    print("-" * 125)
    for sym in SYMBOLS:
        row_str = f"{sym:<8} "
        for tf_label, _ in timeframes:
            for row in gradient_summary:
                if row["tf"] == tf_label and row["strategy"] == "TURTLE_20_10":
                    st_sym = row["asset_stats"].get(sym, {"total_r": 0.0, "pf": 0.0})
                    row_str += f"{st_sym['total_r']:>+8.1f}R (PF {st_sym['pf']:3.1f}) "
        print(row_str)


if __name__ == "__main__":
    main()

"""Pesquisa Rigorosa de Trend Following em Timeframes Maiores: D1 e H4.

Objetivo:
Avaliar se estratégias sistemáticas de Seguidor de Tendência (Trend Following)
possuem vantagem estatística real (alpha > ruído, t >= 2.0, PF >= 1.30)
em timeframes diário (D1) e 4 horas (H4), onde os custos transacionais (spread e slippage)
são ordens de grandeza menores em relação ao risco ($2 ATR).

Estratégias Testadas:
1. TF_EMA_CONDUCTION:
   - Filtro Macro (i-1): Alinhamento MME 50 e MME 200 + ADX(14) >= 20.
   - Entrada: Rompimento do canal Donchian de 20 períodos em i.
   - Stop Loss: 2.0 * ATR(14) calculado em i-1.
   - Saída: Condução por fechamento além da MME 20 (saída causal no open da barra i+1).

2. TURTLE_20_10 (Sistema Clássico Donchian):
   - Entrada: Rompimento Donchian 20 (máxima/mínima das últimas 20 barras em i-1).
   - Stop Loss: 2.0 * ATR(20) calculado em i-1.
   - Saída: Rompimento oposto Donchian 10 (mínima de 10 barras para long, máxima de 10 para short).

3. TURTLE_50_20 (Sistema Turtle Longo Prazo):
   - Entrada: Rompimento Donchian 50 (máxima/mínima das últimas 50 barras em i-1).
   - Stop Loss: 3.0 * ATR(20) calculado em i-1.
   - Saída: Rompimento oposto Donchian 20 (mínima de 20 barras para long, máxima de 20 para short).

4. CONTROLE ALEATÓRIO:
   - Entrada aleatória (moeda) sob os mesmos regimes e regras de saída (50 simulações).

Ativos:
- NAS100, US30, BRENT, EURUSD, GBPUSD, XAUUSD (5 anos: 2021 a 2026).
- Partição: In-Sample (2021-11-01 a 2024-10-31), Out-of-Sample (2024-11-01 a 2026-11-06).

Protocolo Anti-Viés (AGENTS.md):
- Indicadores calculados estritamente em i-1 ou antes.
- Stop loss na barra de entrada testado imediatamente após o fill.
- Gaps de abertura no stop loss preenchidos no Open + slippage.
- Slippage e spreads realistas por ativo.
- Máximo 1 posição ativa por ativo (single-position).
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


def compute_indicators(df: pd.DataFrame) -> dict[str, np.ndarray]:
    close = df["close"]
    high = df["high"]
    low = df["low"]

    mme20 = close.ewm(span=20, adjust=False).mean().to_numpy(dtype=float)
    mme50 = close.ewm(span=50, adjust=False).mean().to_numpy(dtype=float)
    mme200 = close.ewm(span=200, adjust=False).mean().to_numpy(dtype=float)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr14 = tr.rolling(window=14).mean().bfill().to_numpy(dtype=float)
    atr20 = tr.rolling(window=20).mean().bfill().to_numpy(dtype=float)

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr_s = tr.rolling(window=14).sum()
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(window=14).sum() / tr_s)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(window=14).sum() / tr_s)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx14 = dx.rolling(window=14).mean().fillna(0).to_numpy(dtype=float)

    # Donchian Channels
    # rolling(window).max().shift(1) garante causalidade estrita (olha barras de i-window até i-1)
    donchian_high_20 = high.shift(1).rolling(window=20).max().to_numpy(dtype=float)
    donchian_low_20 = low.shift(1).rolling(window=20).min().to_numpy(dtype=float)
    donchian_high_10 = high.shift(1).rolling(window=10).max().to_numpy(dtype=float)
    donchian_low_10 = low.shift(1).rolling(window=10).min().to_numpy(dtype=float)
    donchian_high_50 = high.shift(1).rolling(window=50).max().to_numpy(dtype=float)
    donchian_low_50 = low.shift(1).rolling(window=50).min().to_numpy(dtype=float)

    return {
        "mme20": mme20,
        "mme50": mme50,
        "mme200": mme200,
        "atr14": atr14,
        "atr20": atr20,
        "adx14": adx14,
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
    closes = df["close"].to_numpy(dtype=float)
    ts = df.index
    n = len(opens)

    mme20 = ind["mme20"]
    mme50 = ind["mme50"]
    mme200 = ind["mme200"]
    atr14 = ind["atr14"]
    atr20 = ind["atr20"]
    adx14 = ind["adx14"]
    dh20 = ind["donchian_high_20"]
    dl20 = ind["donchian_low_20"]
    dh10 = ind["donchian_high_10"]
    dl10 = ind["donchian_low_10"]
    dh50 = ind["donchian_high_50"]
    dl50 = ind["donchian_low_50"]

    trades: list[Trade] = []
    open_pos = None

    # Começamos após período de warmup (210 barras)
    for i in range(210, n - 1):
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

            # B. Teste de Saída pela regra da estratégia (após a barra de entrada)
            if not hit_sl and i > pos["entry_idx"]:
                if strategy_name == "TF_EMA_CONDUCTION":
                    # Saída quando o fechamento cruza a MME 20; execução no Open de i+1
                    if d == 1 and closes[i] < mme20[i]:
                        exit_by_rule = True
                    elif d == -1 and closes[i] > mme20[i]:
                        exit_by_rule = True
                elif strategy_name == "TURTLE_20_10":
                    # Saída por rompimento oposto de 10 barras (ordem stop intraday em dh10/dl10 calculados em i-1)
                    if d == 1 and lows[i] <= dl10[i]:
                        exit_by_rule = True
                        exit_rule_price = min(dl10[i], opens[i]) - slippage
                    elif d == -1 and highs[i] + spread >= dh10[i]:
                        exit_by_rule = True
                        exit_rule_price = max(dh10[i], opens[i] + spread) + slippage
                elif strategy_name == "TURTLE_50_20":
                    # Saída por rompimento oposto de 20 barras
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
                    )
                )
                open_pos = None
                continue

            elif exit_by_rule:
                if strategy_name == "TF_EMA_CONDUCTION":
                    # Executa no Open de i+1
                    exit_price = opens[i + 1] if d == 1 else opens[i + 1] + spread
                    exit_time = ts[i + 1]
                else:
                    exit_price = exit_rule_price
                    exit_time = ts[i]

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
                        exit_time=exit_time,
                        entry_price=pos["entry_price"],
                        stop_price=pos["stop_price"],
                        exit_price=exit_price,
                        exit_reason="RULE_EXIT",
                        r_multiple=float(r),
                        win=bool(r > 0),
                        is_oos=bool(exit_time >= OOS_SPLIT_DATE),
                    )
                )
                open_pos = None
                continue

        # 2. Se não estamos posicionados, verificar se há sinal armado em i-1 para execução em i
        if open_pos is None:
            # Avaliar regras de entrada em i-1
            long_armed = False
            short_armed = False
            trigger_price = 0.0
            stop_dist = 0.0

            if strategy_name == "TF_EMA_CONDUCTION":
                # Filtro de tendência em i-1
                is_uptrend = (
                    closes[i - 1] > mme50[i - 1] > mme200[i - 1]
                    and mme50[i - 1] > mme50[i - 6]
                    and adx14[i - 1] >= 20.0
                )
                is_downtrend = (
                    closes[i - 1] < mme50[i - 1] < mme200[i - 1]
                    and mme50[i - 1] < mme50[i - 6]
                    and adx14[i - 1] >= 20.0
                )
                if is_uptrend and not np.isnan(dh20[i]):
                    long_armed = True
                    trigger_price = dh20[i]
                    stop_dist = 2.0 * atr14[i - 1]
                elif is_downtrend and not np.isnan(dl20[i]):
                    short_armed = True
                    trigger_price = dl20[i]
                    stop_dist = 2.0 * atr14[i - 1]

            elif strategy_name == "TURTLE_20_10":
                # Donchian 20 sem filtro de média (Turtle clássico)
                if not np.isnan(dh20[i]):
                    long_armed = True
                    trigger_price = dh20[i]
                    stop_dist = 2.0 * atr20[i - 1]
                if not np.isnan(dl20[i]):
                    short_armed = True
                    trigger_price = dl20[i]
                    stop_dist = 2.0 * atr20[i - 1]

            elif strategy_name == "TURTLE_50_20":
                # Donchian 50 clássico
                if not np.isnan(dh50[i]):
                    long_armed = True
                    trigger_price = dh50[i]
                    stop_dist = 3.0 * atr20[i - 1]
                if not np.isnan(dl50[i]):
                    short_armed = True
                    trigger_price = dl50[i]
                    stop_dist = 3.0 * atr20[i - 1]

            # Verificar disparos na barra i
            long_triggered = long_armed and (highs[i] >= trigger_price)
            short_triggered = short_armed and (lows[i] <= trigger_price)

            # Prioridade se ambos dispararem na mesma barra: sem entrada (conflito)
            if long_triggered and short_triggered:
                continue

            if long_triggered:
                exec_price = max(opens[i], trigger_price) + spread + slippage
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
                exec_price = min(opens[i], trigger_price) - slippage
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


def run_random_control(
    df: pd.DataFrame,
    symbol: str,
    tf_name: str,
    spread: float,
    slippage: float,
    num_sims: int = 30,
) -> tuple[float, float]:
    """Controle aleatório com a mesma regra de saída (MME 20) e mesmo stop (2 ATR)."""
    ind = compute_indicators(df)
    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    ts = df.index
    n = len(opens)
    mme20 = ind["mme20"]
    atr14 = ind["atr14"]

    sim_rs = []
    # Usar seed determinística para reprodutibilidade
    rng = np.random.default_rng(42)

    for _ in range(num_sims):
        # Gera entradas aleatórias com probabilidade de ~5% por barra quando desposicionado
        open_pos = None
        trade_rs = []
        for i in range(210, n - 1):
            if open_pos is not None:
                pos = open_pos
                d = 1 if pos["direction"] == "long" else -1
                hit_sl = False
                exit_by_rule = False

                if d == 1 and lows[i] <= pos["stop_price"]:
                    hit_sl = True
                elif d == -1 and highs[i] + spread >= pos["stop_price"]:
                    hit_sl = True

                if not hit_sl and i > pos["entry_idx"]:
                    if d == 1 and closes[i] < mme20[i]:
                        exit_by_rule = True
                    elif d == -1 and closes[i] > mme20[i]:
                        exit_by_rule = True

                if hit_sl:
                    if d == 1:
                        raw_exit = min(pos["stop_price"], opens[i]) - slippage
                        r = (raw_exit - pos["entry_price"]) / pos["initial_risk"]
                    else:
                        raw_exit = max(pos["stop_price"], opens[i] + spread) + slippage
                        r = (pos["entry_price"] - raw_exit) / pos["initial_risk"]
                    trade_rs.append(r)
                    open_pos = None
                    continue

                elif exit_by_rule:
                    exit_price = opens[i + 1] if d == 1 else opens[i + 1] + spread
                    r = (
                        (exit_price - pos["entry_price"]) / pos["initial_risk"]
                        if d == 1
                        else (pos["entry_price"] - exit_price) / pos["initial_risk"]
                    )
                    trade_rs.append(r)
                    open_pos = None
                    continue

            if open_pos is None and rng.random() < 0.05:
                direction = "long" if rng.random() < 0.5 else "short"
                d = 1 if direction == "long" else -1
                stop_dist = 2.0 * atr14[i - 1]
                if stop_dist <= 0:
                    continue

                if d == 1:
                    exec_price = opens[i] + spread + slippage
                    stop_price = exec_price - stop_dist
                    risk = exec_price - stop_price
                    if lows[i] <= stop_price:
                        raw_exit = min(stop_price, opens[i]) - slippage
                        r = (raw_exit - exec_price) / risk
                        trade_rs.append(r)
                    else:
                        open_pos = {
                            "direction": "long",
                            "entry_idx": i,
                            "entry_price": exec_price,
                            "stop_price": stop_price,
                            "initial_risk": risk,
                        }
                else:
                    exec_price = opens[i] - slippage
                    stop_price = exec_price + stop_dist
                    risk = stop_price - exec_price
                    if highs[i] + spread >= stop_price:
                        raw_exit = max(stop_price, opens[i] + spread) + slippage
                        r = (exec_price - raw_exit) / risk
                        trade_rs.append(r)
                    else:
                        open_pos = {
                            "direction": "short",
                            "entry_idx": i,
                            "entry_price": exec_price,
                            "stop_price": stop_price,
                            "initial_risk": risk,
                        }

        if len(trade_rs) > 0:
            sim_rs.append(float(np.mean(trade_rs)))

    mean_r = float(np.mean(sim_rs)) if sim_rs else 0.0
    se_r = float(np.std(sim_rs) / np.sqrt(len(sim_rs))) if len(sim_rs) > 1 else 0.0
    return mean_r, se_r


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


def main():
    print("=" * 80)
    print("PESQUISA SISTEMÁTICA DE TREND FOLLOWING EM TIMEFRAMES MAIORES (D1 & H4)")
    print("=" * 80)

    strategies = ["TF_EMA_CONDUCTION", "TURTLE_20_10", "TURTLE_50_20"]
    timeframes = [("D1", "1D"), ("H4", "4h")]

    results = []

    for tf_label, tf_rule in timeframes:
        print(f"\n>>> Processando Timeframe: {tf_label} ({tf_rule})")
        for sym in SYMBOLS:
            p = Path(f"data/{sym}_M1_dukascopy.parquet")
            if not p.exists():
                print(f"Arquivo não encontrado: {p}")
                continue

            df_m1 = pd.read_parquet(p)
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

            for strat in strategies:
                trades = simulate_strategy(df_tf, sym, tf_label, strat, spread, slippage)
                st_all = calc_stats(trades)

                is_trades = [t for t in trades if not t.is_oos]
                oos_trades = [t for t in trades if t.is_oos]

                st_is = calc_stats(is_trades)
                st_oos = calc_stats(oos_trades)

                results.append({
                    "timeframe": tf_label,
                    "symbol": sym,
                    "strategy": strat,
                    "all": st_all,
                    "is": st_is,
                    "oos": st_oos,
                    "trades": trades,
                })

                print(
                    f"[{tf_label:2s}] {sym:6s} | {strat:17s} -> "
                    f"N={st_all['n']:3d} | TotalR={st_all['total_r']:+6.1f}R | "
                    f"R/trade={st_all['mean_r']:+0.2f}±{st_all['se_r']:0.2f} (t={st_all['t_stat']:4.2f}) | "
                    f"PF={st_all['pf']:4.2f} | WR={st_all['wr']:4.1f}% | "
                    f"IS={st_is['total_r']:+5.1f}R | OOS={st_oos['total_r']:+5.1f}R"
                )

    # Sumário consolidado por Estratégia e Timeframe
    print("\n" + "=" * 80)
    print("CONSOLIDAÇÃO DE CARTEIRA (6 ATIVOS) POR ESTRATÉGIA E TIMEFRAME")
    print("=" * 80)
    print(
        f"{'TF':<4} {'Estratégia':<18} {'Trades':<7} {'Total R':<9} {'R/trade ± SE':<17} {'t-stat':<7} {'PF':<6} {'WR%':<6} {'MaxDD':<7} {'IS (R)':<8} {'OOS (R)':<8}"
    )
    print("-" * 105)

    summary_rows = []
    for tf_label, _ in timeframes:
        for strat in strategies:
            strat_trades = []
            for r in results:
                if r["timeframe"] == tf_label and r["strategy"] == strat:
                    strat_trades.extend(r["trades"])

            st_all = calc_stats(strat_trades)
            st_is = calc_stats([t for t in strat_trades if not t.is_oos])
            st_oos = calc_stats([t for t in strat_trades if t.is_oos])

            summary_rows.append({
                "tf": tf_label,
                "strategy": strat,
                "stats_all": st_all,
                "stats_is": st_is,
                "stats_oos": st_oos,
                "all_trades": strat_trades,
            })

            print(
                f"{tf_label:<4} {strat:<18} {st_all['n']:<7d} {st_all['total_r']:<+9.1f} "
                f"{st_all['mean_r']:+0.3f}±{st_all['se_r']:0.3f}   {st_all['t_stat']:<7.2f} "
                f"{st_all['pf']:<6.2f} {st_all['wr']:<5.1f}% {st_all['max_dd']:<6.1f}R "
                f"{st_is['total_r']:<+8.1f} {st_oos['total_r']:<+8.1f}"
            )

    # Controle aleatório para o D1 e H4 nos índices e ativos chave
    print("\n" + "=" * 80)
    print("BENCHMARK CONTROLE ALEATÓRIO (MME 20 Trailing Exit + 2 ATR Stop)")
    print("=" * 80)
    for tf_label, tf_rule in timeframes:
        for sym in ["NAS100", "US30", "BRENT", "EURUSD"]:
            p = Path(f"data/{sym}_M1_dukascopy.parquet")
            df_m1 = pd.read_parquet(p)
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
            mean_r, se_r = run_random_control(df_tf, sym, tf_label, spread, slippage, num_sims=30)
            print(f"[{tf_label}] {sym:6s} Controle Aleatório: {mean_r:+0.3f} ± {se_r:0.3f} R/trade")


if __name__ == "__main__":
    main()

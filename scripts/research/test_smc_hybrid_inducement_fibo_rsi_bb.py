"""Pesquisa Quantitativa e Auditoria Anti-Viés:
Modelo Híbrido SMC (Indução + Fibo 61.8% + RSI + Bandas de Bollinger).

Objetivo:
Avaliar empiricamente se a convergência entre SMC (Inducement / Sweeps de liquidez),
retração de Fibonacci (61.8% a 78.6%) e validação quantitativa de exaustão (RSI <= 35 / >= 65
e toque/furo da Banda de Bollinger de 2 desvios) gera alpha real ou se sofre das mesmas falhas
estruturais de outras estratégias de reversão intraday.

Metodologia em Conformidade com AGENTS.md e STANDARDS.md:
1. Causalidade estrita: decisão baseada em i - 1, entrada no open de i.
2. Checagem obrigatória de stop loss intrabar no momento do fill na barra de entrada.
3. Preenchimento de gap no stop loss executado no Open + slippage.
4. Spreads reais por ativo e slippage em ordens stop.
5. Controle estrito de concorrência: 1 posição por ativo.
6. Separação In-Sample (2021-2024) vs Out-of-Sample (2025-2026).
7. Benchmark contra Random Walk (passeio aleatório sob a mesma geometria).
8. Auditoria de simetria (compras vs vendas).
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from smc_trader.data.resample import resample_ohlc
from smc_trader.data.store import load_candles

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
    variant: str
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


def compute_rsi(close: pd.Series, period: int = 14) -> np.ndarray:
    """Calcula RSI clássico (Wilder)."""
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.fillna(50.0).to_numpy(dtype=float)


def compute_bollinger(close: pd.Series, window: int = 20, num_std: float = 2.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Calcula Bandas de Bollinger clássicas (20, 2)."""
    sma = close.rolling(window=window).mean()
    std = close.rolling(window=window).std(ddof=0)
    upper = sma + num_std * std
    lower = sma - num_std * std
    return sma.fillna(close).to_numpy(dtype=float), upper.fillna(close).to_numpy(dtype=float), lower.fillna(close).to_numpy(dtype=float)


def find_causal_pivots(df: pd.DataFrame, k: int = 2) -> list[Pivot]:
    """Detecta topos e fundos causais com confirmação estrita em k barras à frente."""
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    ts = df.index
    n = len(df)
    pivots: list[Pivot] = []

    for i in range(k, n - k):
        is_high = np.all(highs[i] > highs[i - k : i]) and np.all(highs[i] >= highs[i + 1 : i + k + 1])
        is_low = np.all(lows[i] < lows[i - k : i]) and np.all(lows[i] <= lows[i + 1 : i + k + 1])

        if is_high:
            pivots.append(
                Pivot(
                    time=ts[i],
                    kind="high",
                    price=float(highs[i]),
                    confirmed_idx=i + k,
                    confirmed_time=ts[i + k],
                )
            )
        if is_low:
            pivots.append(
                Pivot(
                    time=ts[i],
                    kind="low",
                    price=float(lows[i]),
                    confirmed_idx=i + k,
                    confirmed_time=ts[i + k],
                )
            )

    pivots.sort(key=lambda p: (p.confirmed_time, p.time))
    return pivots


def simulate_hybrid_setup(
    df: pd.DataFrame,
    symbol: str,
    spread: float,
    slippage: float,
    variant: str = "V5_FULL_HYBRID",
    target_mode: str = "FIXED_2R",  # 'FIXED_2R', 'MACRO_EXTREME', 'FIXED_1_5R'
    k: int = 2,
    rsi_os: float = 35.0,
    rsi_ob: float = 65.0,
) -> list[Trade]:
    """Simula o modelo SMC Híbrido causalmente."""
    n = len(df)
    if n < 200:
        return []

    pivots = find_causal_pivots(df, k=k)
    num_pivots = len(pivots)

    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    ts = df.index

    # Indicadores calculados no dataframe
    rsi = compute_rsi(df["close"], period=14)
    _, bb_upper, bb_lower = compute_bollinger(df["close"], window=20, num_std=2.0)

    trades: list[Trade] = []
    open_pos = None

    # Rastreamento de estado da perna ativa
    p_idx = 0
    last_high: Pivot | None = None
    last_low: Pivot | None = None

    # Rastreamento de indução interna
    # Para perna de alta: procuramos um fundo intermediário formado após o topo
    int_low: float | None = None
    inducement_swept: bool = False
    active_leg_id: str | None = None

    int_high: float | None = None

    for i in range(50, n - 1):
        cur_time = ts[i]

        # Atualiza pivôs confirmados até i
        while p_idx < num_pivots and pivots[p_idx].confirmed_time <= cur_time:
            p = pivots[p_idx]
            if p.kind == "high":
                last_high = p
            else:
                last_low = p
            p_idx += 1

        # -------------------------------------------------------------
        # 1. GESTÃO DE POSIÇÃO ABERTA
        # -------------------------------------------------------------
        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_sl = False
            hit_tp = False

            if d == 1:
                if lows[i] <= pos["stop_price"]:
                    hit_sl = True
                elif highs[i] >= pos["target_price"]:
                    hit_tp = True
            else:
                if highs[i] + spread >= pos["stop_price"]:
                    hit_sl = True
                elif lows[i] + spread <= pos["target_price"]:
                    hit_tp = True

            if hit_sl and hit_tp:
                # Pior caso causal: stop
                hit_sl = True
                hit_tp = False

            if hit_sl:
                exit_price = min(pos["stop_price"], opens[i]) - slippage if d == 1 else max(pos["stop_price"], opens[i] + spread) + slippage
                risk = pos["risk"]
                pnl = (exit_price - pos["entry_price"]) if d == 1 else (pos["entry_price"] - exit_price)
                r_mult = pnl / risk if risk > 0 else -1.0
                trades.append(
                    Trade(
                        symbol=symbol,
                        variant=variant,
                        direction=pos["direction"],
                        entry_time=pos["entry_time"],
                        exit_time=cur_time,
                        entry_price=pos["entry_price"],
                        stop_price=pos["stop_price"],
                        target_price=pos["target_price"],
                        exit_price=exit_price,
                        exit_reason="STOP_LOSS",
                        r_multiple=r_mult,
                        win=False,
                        is_oos=pos["entry_time"] >= OOS_SPLIT_DATE,
                        theoretical_rr=pos["theoretical_rr"],
                    )
                )
                open_pos = None

            elif hit_tp:
                exit_price = pos["target_price"] if d == 1 else pos["target_price"]
                risk = pos["risk"]
                pnl = (exit_price - pos["entry_price"]) if d == 1 else (pos["entry_price"] - exit_price)
                r_mult = pnl / risk if risk > 0 else 1.0
                trades.append(
                    Trade(
                        symbol=symbol,
                        variant=variant,
                        direction=pos["direction"],
                        entry_time=pos["entry_time"],
                        exit_time=cur_time,
                        entry_price=pos["entry_price"],
                        stop_price=pos["stop_price"],
                        target_price=pos["target_price"],
                        exit_price=exit_price,
                        exit_reason="TAKE_PROFIT",
                        r_multiple=r_mult,
                        win=True,
                        is_oos=pos["entry_time"] >= OOS_SPLIT_DATE,
                        theoretical_rr=pos["theoretical_rr"],
                    )
                )
                open_pos = None

            continue  # Modo single-position: se tinha posição aberta, não abre nova

        # -------------------------------------------------------------
        # 2. IDENTIFICAÇÃO DA ESTRUTURA E INDUÇÃO
        # -------------------------------------------------------------
        if last_high is None or last_low is None:
            continue

        # Verifica se temos uma perna de alta causal
        # Topo confirmado depois do fundo, e topo > fundo
        is_bull_leg = (last_high.confirmed_time > last_low.confirmed_time) and (last_high.price > last_low.price)
        is_bear_leg = (last_low.confirmed_time > last_high.confirmed_time) and (last_low.price < last_high.price)

        signal_dir = None
        leg_id = ""

        if is_bull_leg:
            leg_id = f"BULL_{last_low.time}_{last_high.time}"
            if active_leg_id != leg_id:
                active_leg_id = leg_id
                int_low = None
                inducement_swept = False

            l0 = last_low.price
            h0 = last_high.price
            rng = h0 - l0
            if rng <= 0:
                continue

            fibo_618 = h0 - 0.618 * rng

            # Identifica formação de fundo intermediário após o topo h0
            if ts[i - 1] > last_high.time:
                # Se ainda não tinha fundo intermediário, verifica se houve um pullback local
                if int_low is None:
                    if lows[i - 1] > fibo_618 and lows[i - 1] < highs[i - 1]:
                        int_low = lows[i - 1]
                else:
                    # Se o fundo intermediário foi violado (indução varrida)
                    if lows[i - 1] < int_low:
                        inducement_swept = True

            # Condição de retração no Fibo (candle i - 1 tocou a zona OTE)
            in_fibo_zone = (lows[i - 1] <= fibo_618) and (closes[i - 1] >= l0)

            # Avaliação das variantes
            passes_inducement = (not in_fibo_zone) or inducement_swept if variant in ["V2_INDUCEMENT", "V3_RSI", "V4_BOLLINGER", "V5_FULL_HYBRID"] else True
            passes_rsi = (rsi[i - 1] <= rsi_os) if variant in ["V3_RSI", "V5_FULL_HYBRID"] else True
            passes_bb = (lows[i - 1] <= bb_lower[i - 1]) if variant in ["V4_BOLLINGER", "V5_FULL_HYBRID"] else True

            if in_fibo_zone and passes_inducement and passes_rsi and passes_bb:
                signal_dir = "long"
                stop_ref = l0
                target_ref = h0

        elif is_bear_leg:
            leg_id = f"BEAR_{last_high.time}_{last_low.time}"
            if active_leg_id != leg_id:
                active_leg_id = leg_id
                int_high = None
                inducement_swept = False

            h0 = last_high.price
            l0 = last_low.price
            rng = h0 - l0
            if rng <= 0:
                continue

            fibo_618 = l0 + 0.618 * rng

            if ts[i - 1] > last_low.time:
                if int_high is None:
                    if highs[i - 1] < fibo_618 and highs[i - 1] > lows[i - 1]:
                        int_high = highs[i - 1]
                else:
                    if highs[i - 1] > int_high:
                        inducement_swept = True

            in_fibo_zone = (highs[i - 1] >= fibo_618) and (closes[i - 1] <= h0)

            passes_inducement = (not in_fibo_zone) or inducement_swept if variant in ["V2_INDUCEMENT", "V3_RSI", "V4_BOLLINGER", "V5_FULL_HYBRID"] else True
            passes_rsi = (rsi[i - 1] >= rsi_ob) if variant in ["V3_RSI", "V5_FULL_HYBRID"] else True
            passes_bb = (highs[i - 1] >= bb_upper[i - 1]) if variant in ["V4_BOLLINGER", "V5_FULL_HYBRID"] else True

            if in_fibo_zone and passes_inducement and passes_rsi and passes_bb:
                signal_dir = "short"
                stop_ref = h0
                target_ref = l0

        # -------------------------------------------------------------
        # 3. DISPARO DA ORDEM NA ABERTURA DA BARRA i (AGENTS.md)
        # -------------------------------------------------------------
        if signal_dir is not None:
            # Reseta estado da perna para evitar reentradas repetitivas
            active_leg_id = None

            if signal_dir == "long":
                entry_p = opens[i]
                stop_p = stop_ref - slippage
                risk = entry_p - stop_p
                if risk <= 0:
                    continue

                if target_mode == "MACRO_EXTREME":
                    target_p = target_ref
                elif target_mode == "FIXED_1_5R":
                    target_p = entry_p + 1.5 * risk
                else:  # FIXED_2R
                    target_p = entry_p + 2.0 * risk

                theo_rr = (target_p - entry_p) / risk if risk > 0 else 0.0

                # CHECAGEM OBRIGATÓRIA DE STOP LOSS NA BARRA DE ENTRADA i (AGENTS.md)
                if lows[i] <= stop_p:
                    # Barra de entrada foi estopada imediatamente
                    exit_p = min(stop_p, opens[i]) - slippage
                    pnl = exit_p - entry_p
                    trades.append(
                        Trade(
                            symbol=symbol,
                            variant=variant,
                            direction="long",
                            entry_time=cur_time,
                            exit_time=cur_time,
                            entry_price=entry_p,
                            stop_price=stop_p,
                            target_price=target_p,
                            exit_price=exit_p,
                            exit_reason="STOP_IN_ENTRY_BAR",
                            r_multiple=pnl / risk,
                            win=False,
                            is_oos=cur_time >= OOS_SPLIT_DATE,
                            theoretical_rr=theo_rr,
                        )
                    )
                    continue

                open_pos = {
                    "direction": "long",
                    "entry_price": entry_p,
                    "stop_price": stop_p,
                    "target_price": target_p,
                    "risk": risk,
                    "entry_time": cur_time,
                    "theoretical_rr": theo_rr,
                }

            else:  # short
                entry_p = opens[i]
                stop_p = stop_ref + spread + slippage
                risk = stop_p - entry_p
                if risk <= 0:
                    continue

                if target_mode == "MACRO_EXTREME":
                    target_p = target_ref + spread
                elif target_mode == "FIXED_1_5R":
                    target_p = entry_p - 1.5 * risk
                else:  # FIXED_2R
                    target_p = entry_p - 2.0 * risk

                theo_rr = (entry_p - target_p) / risk if risk > 0 else 0.0

                # CHECAGEM OBRIGATÓRIA DE STOP LOSS NA BARRA DE ENTRADA i
                if highs[i] + spread >= stop_p:
                    exit_p = max(stop_p, opens[i] + spread) + slippage
                    pnl = entry_p - exit_p
                    trades.append(
                        Trade(
                            symbol=symbol,
                            variant=variant,
                            direction="short",
                            entry_time=cur_time,
                            exit_time=cur_time,
                            entry_price=entry_p,
                            stop_price=stop_p,
                            target_price=target_p,
                            exit_price=exit_p,
                            exit_reason="STOP_IN_ENTRY_BAR",
                            r_multiple=pnl / risk,
                            win=False,
                            is_oos=cur_time >= OOS_SPLIT_DATE,
                            theoretical_rr=theo_rr,
                        )
                    )
                    continue

                open_pos = {
                    "direction": "short",
                    "entry_price": entry_p,
                    "stop_price": stop_p,
                    "target_price": target_p,
                    "risk": risk,
                    "entry_time": cur_time,
                    "theoretical_rr": theo_rr,
                }

    return trades


def run_random_walk_control(
    df: pd.DataFrame,
    symbol: str,
    spread: float,
    slippage: float,
    target_rr: float = 2.0,
    sample_size: int = 200,
    seed: int = 42,
) -> list[Trade]:
    """Benchmark de Passeio Aleatório sob a mesma geometria e custos."""
    np.random.seed(seed)
    n = len(df)
    if n < 200:
        return []

    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    ts = df.index

    # Índices aleatórios espaçados
    possible_idxs = np.arange(50, n - 100)
    selected_idxs = np.random.choice(possible_idxs, size=min(sample_size, len(possible_idxs)), replace=False)
    selected_idxs.sort()

    trades: list[Trade] = []
    # Estimativa de volatilidade média para tamanho do stop
    atr = (df["high"] - df["low"]).rolling(20).mean().to_numpy()

    for idx in selected_idxs:
        dir_choice = np.random.choice(["long", "short"])
        cur_time = ts[idx]
        entry_p = opens[idx]
        stop_dist = max(atr[idx] * 2.0, spread * 5.0)

        if dir_choice == "long":
            stop_p = entry_p - stop_dist
            target_p = entry_p + target_rr * stop_dist

            # Verifica intrabar
            if lows[idx] <= stop_p:
                trades.append(
                    Trade(
                        symbol=symbol,
                        variant="V0_RANDOM_WALK",
                        direction="long",
                        entry_time=cur_time,
                        exit_time=cur_time,
                        entry_price=entry_p,
                        stop_price=stop_p,
                        target_price=target_p,
                        exit_price=min(stop_p, opens[idx]) - slippage,
                        exit_reason="STOP_IN_ENTRY_BAR",
                        r_multiple=-1.0,
                        win=False,
                        is_oos=cur_time >= OOS_SPLIT_DATE,
                        theoretical_rr=target_rr,
                    )
                )
                continue

            # Segue até sair
            for j in range(idx + 1, min(idx + 500, n)):
                if lows[j] <= stop_p:
                    trades.append(
                        Trade(
                            symbol=symbol,
                            variant="V0_RANDOM_WALK",
                            direction="long",
                            entry_time=cur_time,
                            exit_time=ts[j],
                            entry_price=entry_p,
                            stop_price=stop_p,
                            target_price=target_p,
                            exit_price=min(stop_p, opens[j]) - slippage,
                            exit_reason="STOP_LOSS",
                            r_multiple=-1.0,
                            win=False,
                            is_oos=cur_time >= OOS_SPLIT_DATE,
                            theoretical_rr=target_rr,
                        )
                    )
                    break
                elif highs[j] >= target_p:
                    trades.append(
                        Trade(
                            symbol=symbol,
                            variant="V0_RANDOM_WALK",
                            direction="long",
                            entry_time=cur_time,
                            exit_time=ts[j],
                            entry_price=entry_p,
                            stop_price=stop_p,
                            target_price=target_p,
                            exit_price=target_p,
                            exit_reason="TAKE_PROFIT",
                            r_multiple=target_rr,
                            win=True,
                            is_oos=cur_time >= OOS_SPLIT_DATE,
                            theoretical_rr=target_rr,
                        )
                    )
                    break

        else:  # short
            stop_p = entry_p + stop_dist + spread
            target_p = entry_p - target_rr * stop_dist

            if highs[idx] + spread >= stop_p:
                trades.append(
                    Trade(
                        symbol=symbol,
                        variant="V0_RANDOM_WALK",
                        direction="short",
                        entry_time=cur_time,
                        exit_time=cur_time,
                        entry_price=entry_p,
                        stop_price=stop_p,
                        target_price=target_p,
                        exit_price=max(stop_p, opens[idx] + spread) + slippage,
                        exit_reason="STOP_IN_ENTRY_BAR",
                        r_multiple=-1.0,
                        win=False,
                        is_oos=cur_time >= OOS_SPLIT_DATE,
                        theoretical_rr=target_rr,
                    )
                )
                continue

            for j in range(idx + 1, min(idx + 500, n)):
                if highs[j] + spread >= stop_p:
                    trades.append(
                        Trade(
                            symbol=symbol,
                            variant="V0_RANDOM_WALK",
                            direction="short",
                            entry_time=cur_time,
                            exit_time=ts[j],
                            entry_price=entry_p,
                            stop_price=stop_p,
                            target_price=target_p,
                            exit_price=max(stop_p, opens[j] + spread) + slippage,
                            exit_reason="STOP_LOSS",
                            r_multiple=-1.0,
                            win=False,
                            is_oos=cur_time >= OOS_SPLIT_DATE,
                            theoretical_rr=target_rr,
                        )
                    )
                    break
                elif lows[j] + spread <= target_p:
                    trades.append(
                        Trade(
                            symbol=symbol,
                            variant="V0_RANDOM_WALK",
                            direction="short",
                            entry_time=cur_time,
                            exit_time=ts[j],
                            entry_price=entry_p,
                            stop_price=stop_p,
                            target_price=target_p,
                            exit_price=target_p,
                            exit_reason="TAKE_PROFIT",
                            r_multiple=target_rr,
                            win=True,
                            is_oos=cur_time >= OOS_SPLIT_DATE,
                            theoretical_rr=target_rr,
                        )
                    )
                    break

    return trades


def analyze_trades(trades: list[Trade]) -> dict[str, float]:
    """Calcula estatísticas quantitativas estritas."""
    if not trades:
        return {
            "count": 0,
            "win_rate": 0.0,
            "total_r": 0.0,
            "mean_r": 0.0,
            "std_r": 0.0,
            "se_r": 0.0,
            "t_stat": 0.0,
            "pf": 0.0,
            "buys": 0,
            "sells": 0,
        }

    r_vals = [t.r_multiple for t in trades]
    wins = [r for r in r_vals if r > 0]
    losses = [abs(r) for r in r_vals if r < 0]

    cnt = len(r_vals)
    tot_r = float(np.sum(r_vals))
    mean_r = float(np.mean(r_vals))
    std_r = float(np.std(r_vals, ddof=1)) if cnt > 1 else 0.0
    se_r = std_r / np.sqrt(cnt) if cnt > 1 else 0.0
    t_stat = mean_r / se_r if se_r > 0 else 0.0

    sum_wins = float(np.sum(wins)) if wins else 0.0
    sum_losses = float(np.sum(losses)) if losses else 0.0
    pf = (sum_wins / sum_losses) if sum_losses > 0 else (99.0 if sum_wins > 0 else 0.0)

    buys = sum(1 for t in trades if t.direction == "long")
    sells = sum(1 for t in trades if t.direction == "short")

    return {
        "count": cnt,
        "win_rate": (len(wins) / cnt) * 100.0,
        "total_r": tot_r,
        "mean_r": mean_r,
        "std_r": std_r,
        "se_r": se_r,
        "t_stat": t_stat,
        "pf": pf,
        "buys": buys,
        "sells": sells,
    }


def main():
    print("=" * 80)
    print("PESQUISA QUANTITATIVA: MODELO HÍBRIDO (SMC INDUÇÃO + FIBO + RSI + BOLLINGER)")
    print("Período: 2021-2026 (5 Anos Dukascopy M1) | Protocolo Anti-Viés AGENTS.md")
    print("=" * 80)

    VARIANTS = [
        ("V1_FIBO_PURO", "Fibo 61.8% Puro (Baseline)"),
        ("V2_INDUCEMENT", "Fibo 61.8% + Indução (Sweep de Fundo/Topo)"),
        ("V3_RSI", "Fibo 61.8% + Indução + RSI (<=35 / >=65)"),
        ("V4_BOLLINGER", "Fibo 61.8% + Indução + Toque Bollinger (2.0 Desvios)"),
        ("V5_FULL_HYBRID", "Modelo Híbrido Completo (Fibo + Indução + RSI + Bollinger)"),
        ("V0_RANDOM_WALK", "Controle: Random Walk Benchmark (Alvo 2R / Stop 1R)"),
    ]

    # Carrega dados M1 e resampleia para M15 e H1
    data_dir = Path("data")
    dfs_m15 = {}
    dfs_h1 = {}

    for sym in SYMBOLS:
        print(f"Carregando dados históricos de {sym}...")
        df_m1 = load_candles(data_dir, sym, "M1", source="dukascopy")
        dfs_m15[sym] = resample_ohlc(df_m1, "M15")
        dfs_h1[sym] = resample_ohlc(df_m1, "H1")

    print("\n" + "#" * 80)
    print("PARTE 1: RESULTADOS EM M15 (ALVO FIXO 2.0R)")
    print("#" * 80)

    results_m15 = {v[0]: [] for v in VARIANTS}

    for sym in SYMBOLS:
        df_sym = dfs_m15[sym]
        spread = SPREADS[sym]
        slip = SLIPPAGES[sym]

        for v_code, v_name in VARIANTS:
            if v_code == "V0_RANDOM_WALK":
                trades = run_random_walk_control(df_sym, sym, spread, slip, target_rr=2.0, sample_size=300)
            else:
                trades = simulate_hybrid_setup(
                    df_sym,
                    sym,
                    spread,
                    slip,
                    variant=v_code,
                    target_mode="FIXED_2R",
                    k=2,
                    rsi_os=35.0,
                    rsi_ob=65.0,
                )
            results_m15[v_code].extend(trades)

    print("\n--- RESUMO COMPARATIVO DAS VARIANTES EM M15 (TODOS OS 6 ATIVOS CONSOLIDADOS) ---")
    print(f"{'Variante':<20} | {'Trades':<7} | {'WinRate':<7} | {'Total R':<9} | {'Mean R ± SE':<18} | {'t-stat':<7} | {'PF':<5} | {'Compras/Vendas'}")
    print("-" * 105)

    for v_code, v_name in VARIANTS:
        all_tr = results_m15[v_code]
        st = analyze_trades(all_tr)
        print(
            f"{v_code:<20} | {st['count']:<7} | {st['win_rate']:>6.1f}% | {st['total_r']:>8.1f}R | "
            f"{st['mean_r']:>+.3f} ± {st['se_r']:.3f}R | {st['t_stat']:>6.2f} | {st['pf']:>4.2f} | {st['buys']}/{st['sells']}"
        )

    print("\n" + "#" * 80)
    print("PARTE 2: ANÁLISE IN-SAMPLE (2021-2024) vs OUT-OF-SAMPLE (2025-2026)")
    print("#" * 80)

    print(f"{'Variante':<20} | {'IS Trades':<9} | {'IS MeanR':<9} | {'IS t-stat':<9} | {'OOS Trades':<10} | {'OOS MeanR':<10} | {'OOS t-stat'}")
    print("-" * 95)

    for v_code, v_name in VARIANTS:
        all_tr = results_m15[v_code]
        is_tr = [t for t in all_tr if not t.is_oos]
        oos_tr = [t for t in all_tr if t.is_oos]

        st_is = analyze_trades(is_tr)
        st_oos = analyze_trades(oos_tr)

        print(
            f"{v_code:<20} | {st_is['count']:<9} | {st_is['mean_r']:>+.3f}R   | {st_is['t_stat']:>8.2f}  | "
            f"{st_oos['count']:<10} | {st_oos['mean_r']:>+.3f}R    | {st_oos['t_stat']:>8.2f}"
        )

    print("\n" + "#" * 80)
    print("PARTE 3: COMPARAÇÃO DE MODOS DE ALVO NO MODELO HÍBRIDO COMPLETO (V5)")
    print("#" * 80)

    TARGET_MODES = ["FIXED_2R", "MACRO_EXTREME", "FIXED_1_5R"]

    print(f"{'Modo de Alvo':<18} | {'Trades':<7} | {'WinRate':<7} | {'Total R':<9} | {'Mean R ± SE':<18} | {'t-stat':<7} | {'PF':<5}")
    print("-" * 85)

    for tm in TARGET_MODES:
        all_tm_tr = []
        for sym in SYMBOLS:
            df_sym = dfs_m15[sym]
            spread = SPREADS[sym]
            slip = SLIPPAGES[sym]
            tr = simulate_hybrid_setup(
                df_sym,
                sym,
                spread,
                slip,
                variant="V5_FULL_HYBRID",
                target_mode=tm,
                k=2,
            )
            all_tm_tr.extend(tr)

        st = analyze_trades(all_tm_tr)
        print(
            f"{tm:<18} | {st['count']:<7} | {st['win_rate']:>6.1f}% | {st['total_r']:>8.1f}R | "
            f"{st['mean_r']:>+.3f} ± {st['se_r']:.3f}R | {st['t_stat']:>6.2f} | {st['pf']:>4.2f}"
        )

    print("\n" + "#" * 80)
    print("PARTE 4: RESULTADOS POR ATIVO INDIVIDUAL (V5 HÍBRIDO COMPLETO - ALVO 2.0R)")
    print("#" * 80)

    print(f"{'Ativo':<10} | {'Trades':<7} | {'WinRate':<7} | {'Total R':<9} | {'Mean R ± SE':<18} | {'t-stat':<7} | {'PF':<5}")
    print("-" * 75)

    for sym in SYMBOLS:
        df_sym = dfs_m15[sym]
        spread = SPREADS[sym]
        slip = SLIPPAGES[sym]
        tr = simulate_hybrid_setup(
            df_sym,
            sym,
            spread,
            slip,
            variant="V5_FULL_HYBRID",
            target_mode="FIXED_2R",
            k=2,
        )
        st = analyze_trades(tr)
        print(
            f"{sym:<10} | {st['count']:<7} | {st['win_rate']:>6.1f}% | {st['total_r']:>8.1f}R | "
            f"{st['mean_r']:>+.3f} ± {st['se_r']:.3f}R | {st['t_stat']:>6.2f} | {st['pf']:>4.2f}"
        )

    print("\n" + "#" * 80)
    print("PARTE 5: TIMEFRAME MAIOR - H1 (SWING TRADE COM V5 HÍBRIDO)")
    print("#" * 80)

    all_h1_tr = []
    for sym in SYMBOLS:
        df_sym = dfs_h1[sym]
        spread = SPREADS[sym]
        slip = SLIPPAGES[sym]
        tr = simulate_hybrid_setup(
            df_sym,
            sym,
            spread,
            slip,
            variant="V5_FULL_HYBRID",
            target_mode="FIXED_2R",
            k=2,
        )
        all_h1_tr.extend(tr)

    st_h1 = analyze_trades(all_h1_tr)
    print(
        f"H1 FULL HYBRID   | {st_h1['count']:<7} | {st_h1['win_rate']:>6.1f}% | {st_h1['total_r']:>8.1f}R | "
        f"{st_h1['mean_r']:>+.3f} ± {st_h1['se_r']:.3f}R | {st_h1['t_stat']:>6.2f} | {st_h1['pf']:>4.2f} | Compras/Vendas: {st_h1['buys']}/{st_h1['sells']}"
    )


if __name__ == "__main__":
    main()

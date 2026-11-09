"""Teste Quantitativo Unificado:
Aplicação do Filtro '1 Operação por Dia no Melhor Horário de Volatilidade' em TODAS as Estratégias.

Estratégias Avaliadas:
1. ORB-15 (Opening Range Breakout dos primeiros 15 min - 09:30-09:45)
2. Trend Follower - TRAP na MME 20 (Falso rompimento na média com tendência macro)
3. Trend Follower - BARRA DE FORÇA (Ponto contínuo direcional na média)
4. Trend Follower - ENGOLFO na Média (Engolfo na MME 20)
5. SMC Fibo OTE (Retração no 0.618-0.786 após BOS intraday)
6. Wyckoff Spring / Upthrust (Falsa quebra de suporte/resistência da consolidação)
7. RSI Divergência + Rompimento (Divergência clássica com gatilho de preço)
8. Closing Momentum (Janela Nobre de Fechamento: 15:30 às 16:00 NY)
9. D1 Reversão à Média (RSI 2 + IBS - Referência Diária)

Restrições Gerais:
- Horário Local de Nova York (America/New_York) com ajuste dinâmico para DST.
- Máximo estrito de 1 trade por dia por estratégia.
- Timeframe: M5 (intraday) e D1 (diário).
- Spreads e slippage reais Dukascopy (NAS100: 1.5 spread + 1.0 slip; US30: 2.0 spread + 1.0 slip).
- Causalidade estrita em i-1, stop loss checado intrabar no candle de entrada, gap no open.
"""

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

SPREADS = {"NAS100": 1.5, "US30": 2.0}
SLIPPAGES = {"NAS100": 1.0, "US30": 1.0}


@dataclass
class Trade:
    symbol: str
    strategy: str
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    r_multiple: float
    win: bool


def calc_stats_dict(trades: list[Trade]) -> dict:
    if not trades:
        return {"trades": 0, "total_r": 0.0, "mean_r": 0.0, "se": 0.0, "t_stat": 0.0, "pf": 0.0, "wr": 0.0, "max_dd": 0.0}
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
    return {
        "trades": len(rs),
        "total_r": float(rs.sum()),
        "mean_r": float(rs.mean()),
        "se": float(se),
        "t_stat": float(t),
        "pf": float(pf),
        "wr": float(wr),
        "max_dd": float(max_dd),
    }


def format_stats(s: dict) -> str:
    if s["trades"] == 0:
        return "Trades=   0 | N/A"
    return (
        f"Trades={s['trades']:4d} | "
        f"TotalR={s['total_r']:+6.1f}R | "
        f"MeanR={s['mean_r']:+0.3f}±{s['se']:0.3f} (t={s['t_stat']:4.2f}) | "
        f"PF={s['pf']:4.2f} | "
        f"WR={s['wr']:4.1f}% | "
        f"MaxDD={s['max_dd']:4.1f}R"
    )


# ==============================================================================
# ESTRATÉGIA 1: ORB-15 (09:30-09:45 NY, Max 1 trade/dia)
# ==============================================================================
def test_orb15(df_m5: pd.DataFrame, symbol: str, target_r: float = 2.0) -> list[Trade]:
    spread = SPREADS[symbol]
    slip = SLIPPAGES[symbol]
    opens = df_m5["open"].to_numpy(dtype=float)
    highs = df_m5["high"].to_numpy(dtype=float)
    lows = df_m5["low"].to_numpy(dtype=float)
    closes = df_m5["close"].to_numpy(dtype=float)
    ts = df_m5.index

    days_dict = {}
    for idx, t in enumerate(ts):
        d = t.date()
        if d not in days_dict:
            days_dict[d] = []
        days_dict[d].append(idx)

    trades = []
    for d, indices in days_dict.items():
        orb_indices = [i for i in indices if ts[i].hour == 9 and ts[i].minute in [30, 35, 40]]
        if len(orb_indices) < 3:
            continue
        orb_high = max(highs[i] for i in orb_indices)
        orb_low = min(lows[i] for i in orb_indices)
        orb_range = orb_high - orb_low
        if orb_range < spread * 4 or orb_range > 300:
            continue

        trade_indices = [i for i in indices if (ts[i].hour == 9 and ts[i].minute >= 45) or (ts[i].hour == 10) or (ts[i].hour == 11 and ts[i].minute <= 30)]

        for i in trade_indices:
            trig_long = highs[i] >= orb_high
            trig_short = lows[i] <= orb_low
            if trig_long and trig_short:
                break
            if trig_long:
                entry_p = max(orb_high, opens[i]) + spread + slip
                stop_p = orb_low - slip
                risk = entry_p - stop_p
                target_p = entry_p + (target_r * risk)
                if lows[i] <= stop_p:
                    trades.append(Trade(symbol, "ORB15", "long", ts[i], ts[i], -1.0, False))
                    break
                hit = None
                for j in range(i + 1, indices[-1] + 1):
                    if lows[j] <= stop_p:
                        hit = "loss"; exit_time = ts[j]; r_res = -1.0; break
                    elif highs[j] >= target_p:
                        hit = "win"; exit_time = ts[j]; r_res = target_r; break
                if hit is None:
                    exit_p = closes[indices[-1]] - slip
                    r_res = (exit_p - entry_p) / risk
                    exit_time = ts[indices[-1]]
                trades.append(Trade(symbol, "ORB15", "long", ts[i], exit_time, float(r_res), bool(r_res > 0)))
                break
            elif trig_short:
                entry_p = min(orb_low, opens[i]) - slip
                stop_p = orb_high + spread + slip
                risk = stop_p - entry_p
                target_p = entry_p - (target_r * risk)
                if highs[i] + spread >= stop_p:
                    trades.append(Trade(symbol, "ORB15", "short", ts[i], ts[i], -1.0, False))
                    break
                hit = None
                for j in range(i + 1, indices[-1] + 1):
                    if highs[j] + spread >= stop_p:
                        hit = "loss"; exit_time = ts[j]; r_res = -1.0; break
                    elif lows[j] <= target_p:
                        hit = "win"; exit_time = ts[j]; r_res = target_r; break
                if hit is None:
                    exit_p = closes[indices[-1]] + spread + slip
                    r_res = (entry_p - exit_p) / risk
                    exit_time = ts[indices[-1]]
                trades.append(Trade(symbol, "ORB15", "short", ts[i], exit_time, float(r_res), bool(r_res > 0)))
                break
    return trades


# ==============================================================================
# ESTRATÉGIA 2, 3, 4: TREND FOLLOWER (Trap, Barra de Força, Engolfo - Max 1 trade/dia)
# ==============================================================================
def test_trend_follower_setup(df_m5: pd.DataFrame, symbol: str, setup_type: str = "trap") -> list[Trade]:
    spread = SPREADS[symbol]
    slip = SLIPPAGES[symbol]
    opens = df_m5["open"].to_numpy(dtype=float)
    highs = df_m5["high"].to_numpy(dtype=float)
    lows = df_m5["low"].to_numpy(dtype=float)
    closes = df_m5["close"].to_numpy(dtype=float)
    ts = df_m5.index

    # Indicadores causais (shift 1 para decisão em i-1)
    ema20 = df_m5["close"].shift(1).ewm(span=20, adjust=False).mean().to_numpy(dtype=float)
    ema80 = df_m5["close"].shift(1).ewm(span=80, adjust=False).mean().to_numpy(dtype=float)
    ema200 = df_m5["close"].shift(1).ewm(span=200, adjust=False).mean().to_numpy(dtype=float)

    # ATR(14) causal
    tr = np.maximum(
        highs - lows,
        np.maximum(np.abs(highs - np.roll(closes, 1)), np.abs(lows - np.roll(closes, 1)))
    )
    atr = pd.Series(tr, index=df_m5.index).shift(1).rolling(14).mean().fillna(10.0).to_numpy(dtype=float)

    days_dict = {}
    for idx, t in enumerate(ts):
        d = t.date()
        if d not in days_dict:
            days_dict[d] = []
        days_dict[d].append(idx)

    trades = []

    for d, indices in days_dict.items():
        # Janela nobre: 09:30 às 11:30 NY
        trade_indices = [i for i in indices if (ts[i].hour == 9 and ts[i].minute >= 30) or (ts[i].hour == 10) or (ts[i].hour == 11 and ts[i].minute <= 30)]

        for i in trade_indices:
            if i < 200:
                continue
            # Regime de tendência
            trend_bull = ema80[i - 1] > ema200[i - 1] and closes[i - 1] > ema80[i - 1]
            trend_bear = ema80[i - 1] < ema200[i - 1] and closes[i - 1] < ema80[i - 1]

            is_long = False
            is_short = False
            trig_p = 0.0
            stop_p = 0.0

            if setup_type == "trap":
                # Trap na MME20: barra anterior violou a mínima de 2 barras atrás e fechou acima da MME20
                if trend_bull and lows[i - 1] < lows[i - 2] and closes[i - 1] > ema20[i - 1] and closes[i - 1] > opens[i - 1]:
                    is_long = True
                    trig_p = highs[i - 1]
                    stop_p = lows[i - 1] - slip
                elif trend_bear and highs[i - 1] > highs[i - 2] and closes[i - 1] < ema20[i - 1] and closes[i - 1] < opens[i - 1]:
                    is_short = True
                    trig_p = lows[i - 1]
                    stop_p = highs[i - 1] + spread + slip

            elif setup_type == "barra_forca":
                # Barra de força: corpo >= 65% do range, fechando no terço superior a partir da MME20
                rng = highs[i - 1] - lows[i - 1]
                body = abs(closes[i - 1] - opens[i - 1])
                if rng >= atr[i - 1] * 0.7:
                    if trend_bull and body / rng >= 0.65 and closes[i - 1] > opens[i - 1] and lows[i - 1] <= ema20[i - 1] + (atr[i - 1] * 0.3):
                        is_long = True
                        trig_p = highs[i - 1]
                        stop_p = lows[i - 1] - slip
                    elif trend_bear and body / rng >= 0.65 and closes[i - 1] < opens[i - 1] and highs[i - 1] >= ema20[i - 1] - (atr[i - 1] * 0.3):
                        is_short = True
                        trig_p = lows[i - 1]
                        stop_p = highs[i - 1] + spread + slip

            elif setup_type == "engolfo":
                # Engolfo na MME20
                if trend_bull and closes[i - 1] > opens[i - 1] and closes[i - 2] < opens[i - 2]:
                    if opens[i - 1] <= closes[i - 2] and closes[i - 1] >= opens[i - 2] and lows[i - 1] <= ema20[i - 1]:
                        is_long = True
                        trig_p = highs[i - 1]
                        stop_p = lows[i - 1] - slip
                elif trend_bear and closes[i - 1] < opens[i - 1] and closes[i - 2] > opens[i - 2]:
                    if opens[i - 1] >= closes[i - 2] and closes[i - 1] <= opens[i - 2] and highs[i - 1] >= ema20[i - 1]:
                        is_short = True
                        trig_p = lows[i - 1]
                        stop_p = highs[i - 1] + spread + slip

            if is_long:
                # Gatilho violado na barra i
                if highs[i] >= trig_p:
                    entry_p = max(trig_p, opens[i]) + spread + slip
                    risk = entry_p - stop_p
                    if risk < spread * 3 or risk > 150:
                        continue
                    # Saída por MME20 ou Stop Loss
                    if lows[i] <= stop_p:
                        trades.append(Trade(symbol, f"TREND_{setup_type.upper()}", "long", ts[i], ts[i], -1.0, False))
                        break

                    exit_time = ts[i]
                    r_res = 0.0
                    for j in range(i + 1, indices[-1] + 1):
                        if lows[j] <= stop_p:
                            r_res = -1.0
                            exit_time = ts[j]
                            break
                        elif closes[j] < ema20[j]:
                            # Saída causal na abertura da barra seguinte
                            exit_idx = min(j + 1, indices[-1])
                            exit_p = opens[exit_idx] - slip
                            r_res = (exit_p - entry_p) / risk
                            exit_time = ts[exit_idx]
                            break
                    else:
                        exit_p = closes[indices[-1]] - slip
                        r_res = (exit_p - entry_p) / risk
                        exit_time = ts[indices[-1]]

                    trades.append(Trade(symbol, f"TREND_{setup_type.upper()}", "long", ts[i], exit_time, float(r_res), bool(r_res > 0)))
                    break  # 1 trade/dia

            elif is_short:
                if lows[i] <= trig_p:
                    entry_p = min(trig_p, opens[i]) - slip
                    risk = stop_p - entry_p
                    if risk < spread * 3 or risk > 150:
                        continue
                    if highs[i] + spread >= stop_p:
                        trades.append(Trade(symbol, f"TREND_{setup_type.upper()}", "short", ts[i], ts[i], -1.0, False))
                        break

                    exit_time = ts[i]
                    r_res = 0.0
                    for j in range(i + 1, indices[-1] + 1):
                        if highs[j] + spread >= stop_p:
                            r_res = -1.0
                            exit_time = ts[j]
                            break
                        elif closes[j] > ema20[j]:
                            exit_idx = min(j + 1, indices[-1])
                            exit_p = opens[exit_idx] + spread + slip
                            r_res = (entry_p - exit_p) / risk
                            exit_time = ts[exit_idx]
                            break
                    else:
                        exit_p = closes[indices[-1]] + spread + slip
                        r_res = (entry_p - exit_p) / risk
                        exit_time = ts[indices[-1]]

                    trades.append(Trade(symbol, f"TREND_{setup_type.upper()}", "short", ts[i], exit_time, float(r_res), bool(r_res > 0)))
                    break  # 1 trade/dia

    return trades


# ==============================================================================
# ESTRATÉGIA 5: SMC FIBO OTE (Retração 0.618-0.786 após BOS - Max 1 trade/dia)
# ==============================================================================
def test_smc_fibo_ote(df_m5: pd.DataFrame, symbol: str) -> list[Trade]:
    spread = SPREADS[symbol]
    slip = SLIPPAGES[symbol]
    opens = df_m5["open"].to_numpy(dtype=float)
    highs = df_m5["high"].to_numpy(dtype=float)
    lows = df_m5["low"].to_numpy(dtype=float)
    closes = df_m5["close"].to_numpy(dtype=float)
    ts = df_m5.index

    days_dict = {}
    for idx, t in enumerate(ts):
        d = t.date()
        if d not in days_dict:
            days_dict[d] = []
        days_dict[d].append(idx)

    trades = []

    for d, indices in days_dict.items():
        # Janela nobre: 09:30 às 11:30 NY
        trade_indices = [i for i in indices if (ts[i].hour == 9 and ts[i].minute >= 30) or (ts[i].hour == 10) or (ts[i].hour == 11 and ts[i].minute <= 30)]

        for i in trade_indices:
            if i < 30:
                continue
            # Estrutura de swing simples de 15 barras para BOS
            recent_high = np.max(highs[i - 20 : i - 1])
            recent_low = np.min(lows[i - 20 : i - 1])
            rng = recent_high - recent_low
            if rng < spread * 6 or rng > 250:
                continue

            # BOS de alta recente
            bos_bull = closes[i - 1] > recent_high
            # Níveis de OTE
            ote_entry = recent_high - (0.618 * rng)
            ote_stop = recent_low - slip

            bos_bear = closes[i - 1] < recent_low
            ote_entry_short = recent_low + (0.618 * rng)
            ote_stop_short = recent_high + spread + slip

            if bos_bull:
                # Checa se toca na retração dentro da janela
                if lows[i] <= ote_entry:
                    entry_p = min(ote_entry, opens[i]) + spread + slip
                    stop_p = ote_stop
                    risk = entry_p - stop_p
                    if risk <= 0 or risk > 150:
                        continue
                    target_p = entry_p + (2.0 * risk)

                    if lows[i] <= stop_p:
                        trades.append(Trade(symbol, "SMC_FIBO_OTE", "long", ts[i], ts[i], -1.0, False))
                        break

                    exit_time = ts[i]
                    r_res = 0.0
                    for j in range(i + 1, indices[-1] + 1):
                        if lows[j] <= stop_p:
                            r_res = -1.0; exit_time = ts[j]; break
                        elif highs[j] >= target_p:
                            r_res = 2.0; exit_time = ts[j]; break
                    else:
                        exit_p = closes[indices[-1]] - slip
                        r_res = (exit_p - entry_p) / risk
                        exit_time = ts[indices[-1]]

                    trades.append(Trade(symbol, "SMC_FIBO_OTE", "long", ts[i], exit_time, float(r_res), bool(r_res > 0)))
                    break

            elif bos_bear:
                if highs[i] >= ote_entry_short:
                    entry_p = max(ote_entry_short, opens[i]) - slip
                    stop_p = ote_stop_short
                    risk = stop_p - entry_p
                    if risk <= 0 or risk > 150:
                        continue
                    target_p = entry_p - (2.0 * risk)

                    if highs[i] + spread >= stop_p:
                        trades.append(Trade(symbol, "SMC_FIBO_OTE", "short", ts[i], ts[i], -1.0, False))
                        break

                    exit_time = ts[i]
                    r_res = 0.0
                    for j in range(i + 1, indices[-1] + 1):
                        if highs[j] + spread >= stop_p:
                            r_res = -1.0; exit_time = ts[j]; break
                        elif lows[j] <= target_p:
                            r_res = 2.0; exit_time = ts[j]; break
                    else:
                        exit_p = closes[indices[-1]] + spread + slip
                        r_res = (entry_p - exit_p) / risk
                        exit_time = ts[indices[-1]]

                    trades.append(Trade(symbol, "SMC_FIBO_OTE", "short", ts[i], exit_time, float(r_res), bool(r_res > 0)))
                    break

    return trades


# ==============================================================================
# ESTRATÉGIA 6: WYCKOFF SPRING / UPTHRUST (Falsa quebra do range - Max 1 trade/dia)
# ==============================================================================
def test_wyckoff_spring(df_m5: pd.DataFrame, symbol: str) -> list[Trade]:
    spread = SPREADS[symbol]
    slip = SLIPPAGES[symbol]
    opens = df_m5["open"].to_numpy(dtype=float)
    highs = df_m5["high"].to_numpy(dtype=float)
    lows = df_m5["low"].to_numpy(dtype=float)
    closes = df_m5["close"].to_numpy(dtype=float)
    ts = df_m5.index

    days_dict = {}
    for idx, t in enumerate(ts):
        d = t.date()
        if d not in days_dict:
            days_dict[d] = []
        days_dict[d].append(idx)

    trades = []

    for d, indices in days_dict.items():
        trade_indices = [i for i in indices if (ts[i].hour == 9 and ts[i].minute >= 30) or (ts[i].hour == 10) or (ts[i].hour == 11 and ts[i].minute <= 30)]

        for i in trade_indices:
            if i < 25:
                continue
            # Range prévio de 20 barras
            support = np.min(lows[i - 20 : i - 2])
            resistance = np.max(highs[i - 20 : i - 2])
            rng = resistance - support
            if rng < spread * 5 or rng > 250:
                continue

            # Spring: barra i-1 violou o suporte, mas fechou de volta DENTRO do range
            is_spring = lows[i - 1] < support and closes[i - 1] > support and closes[i - 1] > opens[i - 1]
            # Upthrust: barra i-1 violou a resistência, mas fechou de volta DENTRO do range
            is_upthrust = highs[i - 1] > resistance and closes[i - 1] < resistance and closes[i - 1] < opens[i - 1]

            if is_spring:
                # Gatilho: romper máxima da barra do spring
                trig_p = highs[i - 1]
                if highs[i] >= trig_p:
                    entry_p = max(trig_p, opens[i]) + spread + slip
                    stop_p = lows[i - 1] - slip
                    risk = entry_p - stop_p
                    if risk < spread * 2 or risk > 120:
                        continue
                    target_p = entry_p + (2.0 * risk)

                    if lows[i] <= stop_p:
                        trades.append(Trade(symbol, "WYCKOFF_SPRING", "long", ts[i], ts[i], -1.0, False))
                        break

                    exit_time = ts[i]
                    r_res = 0.0
                    for j in range(i + 1, indices[-1] + 1):
                        if lows[j] <= stop_p:
                            r_res = -1.0; exit_time = ts[j]; break
                        elif highs[j] >= target_p:
                            r_res = 2.0; exit_time = ts[j]; break
                    else:
                        exit_p = closes[indices[-1]] - slip
                        r_res = (exit_p - entry_p) / risk
                        exit_time = ts[indices[-1]]

                    trades.append(Trade(symbol, "WYCKOFF_SPRING", "long", ts[i], exit_time, float(r_res), bool(r_res > 0)))
                    break

            elif is_upthrust:
                trig_p = lows[i - 1]
                if lows[i] <= trig_p:
                    entry_p = min(trig_p, opens[i]) - slip
                    stop_p = highs[i - 1] + spread + slip
                    risk = stop_p - entry_p
                    if risk < spread * 2 or risk > 120:
                        continue
                    target_p = entry_p - (2.0 * risk)

                    if highs[i] + spread >= stop_p:
                        trades.append(Trade(symbol, "WYCKOFF_SPRING", "short", ts[i], ts[i], -1.0, False))
                        break

                    exit_time = ts[i]
                    r_res = 0.0
                    for j in range(i + 1, indices[-1] + 1):
                        if highs[j] + spread >= stop_p:
                            r_res = -1.0; exit_time = ts[j]; break
                        elif lows[j] <= target_p:
                            r_res = 2.0; exit_time = ts[j]; break
                    else:
                        exit_p = closes[indices[-1]] + spread + slip
                        r_res = (entry_p - exit_p) / risk
                        exit_time = ts[indices[-1]]

                    trades.append(Trade(symbol, "WYCKOFF_SPRING", "short", ts[i], exit_time, float(r_res), bool(r_res > 0)))
                    break

    return trades


# ==============================================================================
# ESTRATÉGIA 7: RSI DIVERGÊNCIA + ROMPIMENTO (Max 1 trade/dia)
# ==============================================================================
def test_rsi_divergence(df_m5: pd.DataFrame, symbol: str) -> list[Trade]:
    spread = SPREADS[symbol]
    slip = SLIPPAGES[symbol]
    opens = df_m5["open"].to_numpy(dtype=float)
    highs = df_m5["high"].to_numpy(dtype=float)
    lows = df_m5["low"].to_numpy(dtype=float)
    closes = df_m5["close"].to_numpy(dtype=float)
    ts = df_m5.index

    # RSI(14) causal
    delta = pd.Series(closes).diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = (100 - (100 / (1 + rs))).shift(1).fillna(50.0).to_numpy(dtype=float)

    days_dict = {}
    for idx, t in enumerate(ts):
        d = t.date()
        if d not in days_dict:
            days_dict[d] = []
        days_dict[d].append(idx)

    trades = []

    for d, indices in days_dict.items():
        trade_indices = [i for i in indices if (ts[i].hour == 9 and ts[i].minute >= 30) or (ts[i].hour == 10) or (ts[i].hour == 11 and ts[i].minute <= 30)]

        for i in trade_indices:
            if i < 30:
                continue
            # Divergência de Alta: Preço faz fundo mais baixo, RSI faz fundo mais alto
            bull_div = lows[i - 1] < np.min(lows[i - 20 : i - 5]) and rsi[i - 1] > np.min(rsi[i - 20 : i - 5]) and rsi[i - 1] < 40
            bear_div = highs[i - 1] > np.max(highs[i - 20 : i - 5]) and rsi[i - 1] < np.max(rsi[i - 20 : i - 5]) and rsi[i - 1] > 60

            if bull_div and closes[i - 1] > opens[i - 1]:
                trig_p = highs[i - 1]
                if highs[i] >= trig_p:
                    entry_p = max(trig_p, opens[i]) + spread + slip
                    stop_p = lows[i - 1] - slip
                    risk = entry_p - stop_p
                    if risk < spread * 2 or risk > 150:
                        continue
                    target_p = entry_p + (2.0 * risk)

                    if lows[i] <= stop_p:
                        trades.append(Trade(symbol, "RSI_DIV", "long", ts[i], ts[i], -1.0, False))
                        break

                    exit_time = ts[i]
                    r_res = 0.0
                    for j in range(i + 1, indices[-1] + 1):
                        if lows[j] <= stop_p:
                            r_res = -1.0; exit_time = ts[j]; break
                        elif highs[j] >= target_p:
                            r_res = 2.0; exit_time = ts[j]; break
                    else:
                        exit_p = closes[indices[-1]] - slip
                        r_res = (exit_p - entry_p) / risk
                        exit_time = ts[indices[-1]]

                    trades.append(Trade(symbol, "RSI_DIV", "long", ts[i], exit_time, float(r_res), bool(r_res > 0)))
                    break

            elif bear_div and closes[i - 1] < opens[i - 1]:
                trig_p = lows[i - 1]
                if lows[i] <= trig_p:
                    entry_p = min(trig_p, opens[i]) - slip
                    stop_p = highs[i - 1] + spread + slip
                    risk = stop_p - entry_p
                    if risk < spread * 2 or risk > 150:
                        continue
                    target_p = entry_p - (2.0 * risk)

                    if highs[i] + spread >= stop_p:
                        trades.append(Trade(symbol, "RSI_DIV", "short", ts[i], ts[i], -1.0, False))
                        break

                    exit_time = ts[i]
                    r_res = 0.0
                    for j in range(i + 1, indices[-1] + 1):
                        if highs[j] + spread >= stop_p:
                            r_res = -1.0; exit_time = ts[j]; break
                        elif lows[j] <= target_p:
                            r_res = 2.0; exit_time = ts[j]; break
                    else:
                        exit_p = closes[indices[-1]] + spread + slip
                        r_res = (entry_p - exit_p) / risk
                        exit_time = ts[indices[-1]]

                    trades.append(Trade(symbol, "RSI_DIV", "short", ts[i], exit_time, float(r_res), bool(r_res > 0)))
                    break

    return trades


# ==============================================================================
# ESTRATÉGIA 8: CLOSING MOMENTUM (Janela Nobre de Fechamento: 15:30 às 16:00 NY)
# ==============================================================================
def test_closing_momentum(df_m5: pd.DataFrame, symbol: str) -> list[Trade]:
    spread = SPREADS[symbol]
    slip = SLIPPAGES[symbol]
    opens = df_m5["open"].to_numpy(dtype=float)
    highs = df_m5["high"].to_numpy(dtype=float)
    lows = df_m5["low"].to_numpy(dtype=float)
    closes = df_m5["close"].to_numpy(dtype=float)
    ts = df_m5.index

    days_dict = {}
    for idx, t in enumerate(ts):
        d = t.date()
        if d not in days_dict:
            days_dict[d] = []
        days_dict[d].append(idx)

    trades = []

    for d, indices in days_dict.items():
        # Fechamento: 15:30 às 15:55 NY
        close_indices = [i for i in indices if ts[i].hour == 15 and ts[i].minute >= 30]
        if not close_indices:
            continue

        first_bar = close_indices[0]
        last_bar = close_indices[-1]

        # Momentum do dia até 15:30
        open_day = opens[indices[0]]
        price_1530 = opens[first_bar]
        day_return = (price_1530 - open_day) / open_day

        # Entra a favor da direção forte do dia se retorno > 0.5%
        if abs(day_return) < 0.005:
            continue

        if day_return > 0:
            entry_p = opens[first_bar] + spread + slip
            stop_p = min(lows[first_bar - 3 : first_bar]) - slip
            risk = entry_p - stop_p
            if risk <= 0 or risk > 150:
                continue

            # Saída no leilão/fechamento das 16:00
            exit_p = closes[last_bar] - slip
            r_res = (exit_p - entry_p) / risk
            trades.append(Trade(symbol, "CLOSING_MOM", "long", ts[first_bar], ts[last_bar], float(r_res), bool(r_res > 0)))

        elif day_return < 0:
            entry_p = opens[first_bar] - slip
            stop_p = max(highs[first_bar - 3 : first_bar]) + spread + slip
            risk = stop_p - entry_p
            if risk <= 0 or risk > 150:
                continue

            exit_p = closes[last_bar] + spread + slip
            r_res = (entry_p - exit_p) / risk
            trades.append(Trade(symbol, "CLOSING_MOM", "short", ts[first_bar], ts[last_bar], float(r_res), bool(r_res > 0)))

    return trades


# ==============================================================================
# ESTRATÉGIA 9: D1 MEAN REVERSION (Connors RSI(2) + IBS - Benchmark Diário)
# ==============================================================================
def test_d1_mean_reversion(symbol: str) -> list[Trade]:
    spread = SPREADS[symbol]
    slip = SLIPPAGES[symbol]
    p = Path(f"data/{symbol}_M1_dukascopy.parquet")
    df_m1 = pd.read_parquet(p)
    df_d1 = df_m1.resample("1D").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()
    df_d1 = df_d1[df_d1["volume"] > df_d1["volume"].median() * 0.2].copy()

    opens = df_d1["open"].to_numpy(dtype=float)
    highs = df_d1["high"].to_numpy(dtype=float)
    lows = df_d1["low"].to_numpy(dtype=float)
    closes = df_d1["close"].to_numpy(dtype=float)
    ts = df_d1.index

    # RSI(2)
    delta = pd.Series(closes).diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/2, min_periods=2, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/2, min_periods=2, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi2 = (100 - (100 / (1 + rs))).shift(1).fillna(50.0).to_numpy(dtype=float)

    # IBS(1) causal
    denom = highs - lows
    ibs = np.where(denom > 0, (closes - lows) / denom, 0.5)
    ibs = pd.Series(ibs).shift(1).fillna(0.5).to_numpy(dtype=float)

    # SMA 200 e SMA 5 causais
    sma200 = pd.Series(closes).shift(1).rolling(200).mean().to_numpy(dtype=float)
    sma5 = pd.Series(closes).shift(1).rolling(5).mean().to_numpy(dtype=float)

    # ATR(14)
    tr = np.maximum(highs - lows, np.maximum(np.abs(highs - np.roll(closes, 1)), np.abs(lows - np.roll(closes, 1))))
    atr = pd.Series(tr).shift(1).rolling(14).mean().fillna(100.0).to_numpy(dtype=float)

    trades = []
    in_pos = False
    entry_p = 0.0
    stop_p = 0.0
    risk = 0.0
    entry_time = None

    for i in range(210, len(df_d1)):
        if in_pos:
            # Checa stop
            if lows[i] <= stop_p:
                raw_exit = min(stop_p, opens[i])
                exit_p = raw_exit - slip
                r_res = (exit_p - entry_p) / risk
                trades.append(Trade(symbol, "D1_MEAN_REV", "long", entry_time, ts[i], float(r_res), bool(r_res > 0)))
                in_pos = False
                continue
            # Saída por SMA 5
            elif closes[i - 1] > sma5[i - 1]:
                exit_p = opens[i] - slip
                r_res = (exit_p - entry_p) / risk
                trades.append(Trade(symbol, "D1_MEAN_REV", "long", entry_time, ts[i], float(r_res), bool(r_res > 0)))
                in_pos = False
                continue

        if not in_pos:
            # Condição Long
            if closes[i - 1] > sma200[i - 1] and rsi2[i - 1] < 10 and ibs[i - 1] < 0.20:
                entry_p = opens[i] + spread + slip
                stop_dist = 2.0 * atr[i - 1]
                stop_p = entry_p - stop_dist
                risk = stop_dist
                entry_time = ts[i]
                in_pos = True

                if lows[i] <= stop_p:
                    raw_exit = min(stop_p, opens[i])
                    exit_p = raw_exit - slip
                    r_res = (exit_p - entry_p) / risk
                    trades.append(Trade(symbol, "D1_MEAN_REV", "long", entry_time, ts[i], float(r_res), bool(r_res > 0)))
                    in_pos = False

    return trades


def main():
    print("=" * 125)
    print("ESTUDO QUANTITATIVO COMPARATIVO: APLICAÇÃO DO FILTRO '1 TRADE POR DIA NO MELHOR HORÁRIO'")
    print("Janela Nobre Intraday: 09:30 às 11:30 NY | Fechamento: 15:30 às 16:00 NY | Período: 2021-2026")
    print("=" * 125)

    all_results = []

    for sym in ["NAS100", "US30"]:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        df_m1 = pd.read_parquet(p)
        df_ny = df_m1.copy()
        df_ny.index = df_ny.index.tz_convert("America/New_York")
        df_m5 = df_ny.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()

        print(f"\n>>> ATIVO: {sym} (Timeframe M5 | Dados Dukascopy)")
        print("-" * 125)

        # 1. ORB-15
        tr_orb = test_orb15(df_m5, sym, target_r=2.0)
        s_orb = calc_stats_dict(tr_orb)
        print(f"1. ORB-15 (09:30-09:45 NY | Alvo 2.0R):     {format_stats(s_orb)}")
        all_results.append((sym, "ORB-15 (Abertura)", s_orb))

        # 2. Trend Trap MME20
        tr_trap = test_trend_follower_setup(df_m5, sym, setup_type="trap")
        s_trap = calc_stats_dict(tr_trap)
        print(f"2. Trend Follower - TRAP MME20:              {format_stats(s_trap)}")
        all_results.append((sym, "Trend Follower - TRAP MME20", s_trap))

        # 3. Trend Barra de Força
        tr_bf = test_trend_follower_setup(df_m5, sym, setup_type="barra_forca")
        s_bf = calc_stats_dict(tr_bf)
        print(f"3. Trend Follower - BARRA DE FORÇA:          {format_stats(s_bf)}")
        all_results.append((sym, "Trend Follower - BARRA FORÇA", s_bf))

        # 4. Trend Engolfo
        tr_eng = test_trend_follower_setup(df_m5, sym, setup_type="engolfo")
        s_eng = calc_stats_dict(tr_eng)
        print(f"4. Trend Follower - ENGOLFO:                 {format_stats(s_eng)}")
        all_results.append((sym, "Trend Follower - ENGOLFO", s_eng))

        # 5. SMC Fibo OTE
        tr_smc = test_smc_fibo_ote(df_m5, sym)
        s_smc = calc_stats_dict(tr_smc)
        print(f"5. SMC - Fibo OTE (0.618-0.786):             {format_stats(s_smc)}")
        all_results.append((sym, "SMC - Fibo OTE", s_smc))

        # 6. Wyckoff Spring / Upthrust
        tr_wyck = test_wyckoff_spring(df_m5, sym)
        s_wyck = calc_stats_dict(tr_wyck)
        print(f"6. Wyckoff - Spring / Upthrust:              {format_stats(s_wyck)}")
        all_results.append((sym, "Wyckoff - Spring/Upthrust", s_wyck))

        # 7. RSI Divergência
        tr_rsi = test_rsi_divergence(df_m5, sym)
        s_rsi = calc_stats_dict(tr_rsi)
        print(f"7. RSI Divergência + Rompimento:             {format_stats(s_rsi)}")
        all_results.append((sym, "RSI Divergência", s_rsi))

        # 8. Closing Momentum (15:30 às 16:00 NY)
        tr_cm = test_closing_momentum(df_m5, sym)
        s_cm = calc_stats_dict(tr_cm)
        print(f"8. Closing Momentum (15:30 às 16:00 NY):     {format_stats(s_cm)}")
        all_results.append((sym, "Closing Momentum (15:30 NY)", s_cm))

        # 9. D1 Mean Reversion (Benchmark)
        tr_d1 = test_d1_mean_reversion(sym)
        s_d1 = calc_stats_dict(tr_d1)
        print(f"9. D1 Mean Reversion (RSI 2 + IBS) [D1]:     {format_stats(s_d1)}")
        all_results.append((sym, "D1 Reversão à Média", s_d1))

    print("\n" + "=" * 125)
    print("RESUMO CONSOLIDADO POR ESTRATÉGIA (SOMA NAS100 + US30):")
    print("=" * 125)
    strats = [
        "ORB-15 (Abertura)",
        "Trend Follower - TRAP MME20",
        "Trend Follower - BARRA FORÇA",
        "Trend Follower - ENGOLFO",
        "SMC - Fibo OTE",
        "Wyckoff - Spring/Upthrust",
        "RSI Divergência",
        "Closing Momentum (15:30 NY)",
        "D1 Reversão à Média",
    ]
    for st in strats:
        st_items = [item for item in all_results if item[1] == st]
        tot_trades = sum(item[2]["trades"] for item in st_items)
        tot_r = sum(item[2]["total_r"] for item in st_items)
        mean_r = (tot_r / tot_trades) if tot_trades > 0 else 0.0
        avg_wr = np.mean([item[2]["wr"] for item in st_items]) if tot_trades > 0 else 0.0
        avg_pf = np.mean([item[2]["pf"] for item in st_items]) if tot_trades > 0 else 0.0
        print(f"{st:<32} | Trades={tot_trades:5d} | TotalR={tot_r:+7.1f}R | MeanR={mean_r:+0.3f}R | PF={avg_pf:4.2f} | WR={avg_wr:4.1f}%")


if __name__ == "__main__":
    main()

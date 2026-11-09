"""Pesquisa Empírica: Divergência de RSI + Rompimento de Estrutura de Fraqueza (Deriva / Cunha).

Mecânica:
- Identificação de Pivôs causais (k=2).
- Divergência de Baixa (Short): Preço faz Topo Mais Alto, mas RSI(14) faz Topo Mais Baixo (exaustão).
  Confirmação / Rompimento: Preço perde o fundo intermediário entre os dois topos (rompimento da deriva).
- Divergência de Alta (Long): Preço faz Fundo Mais Baixo, mas RSI(14) faz Fundo Mais Alto.
  Confirmação / Rompimento: Preço rompe o topo intermediário (rompimento da deriva).
- Entrada: Próxima barra após a confirmação causal (shift(1)).
- Stop: Acima do topo da divergência (Short) ou abaixo do fundo (Long).
- Alvo: 1.5R ou 2.0R.
- Custos: Spread e slippage reais da Dukascopy.
"""

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

SPREADS = {"NAS100": 1.5, "US30": 2.0, "XAUUSD": 0.20, "EURUSD": 0.00008}
SLIPPAGES = {"NAS100": 1.0, "US30": 1.0, "XAUUSD": 0.10, "EURUSD": 0.00005}


@dataclass
class Trade:
    symbol: str
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    exit_price: float
    r_multiple: float
    win: bool


def compute_rsi(series: pd.Series, period: int = 14) -> np.ndarray:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-9)
    rsi = 100.0 - (100.0 / (1.0 + rs))
    return rsi.bfill().to_numpy(dtype=float)


def simulate_rsi_divergence(
    df: pd.DataFrame,
    symbol: str,
    target_rr: float = 1.5,
    rsi_period: int = 14,
    k: int = 2,
    max_div_lookback: int = 30,
) -> list[Trade]:
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    opens = df["open"].to_numpy(dtype=float)
    ts = df.index
    n = len(df)

    rsi = compute_rsi(df["close"].shift(1), period=rsi_period)
    spread = SPREADS.get(symbol, 1.0)
    slippage = SLIPPAGES.get(symbol, 1.0)

    # Identificar pivôs causais com atraso k
    pivot_highs = []  # (idx_piv, price, rsi_val, confirmed_idx)
    pivot_lows = []

    for i in range(k, n - k):
        if np.all(highs[i] > highs[i - k : i]) and np.all(highs[i] >= highs[i + 1 : i + k + 1]):
            pivot_highs.append((i, highs[i], rsi[i], i + k))
        if np.all(lows[i] < lows[i - k : i]) and np.all(lows[i] <= lows[i + 1 : i + k + 1]):
            pivot_lows.append((i, lows[i], rsi[i], i + k))

    trades: list[Trade] = []
    open_pos = None

    ph_ptr = 0
    pl_ptr = 0
    known_phs = []
    known_pls = []

    for i in range(50, n):
        curr_time = ts[i]

        # Atualizar pivôs conhecidos até i-1
        while ph_ptr < len(pivot_highs) and pivot_highs[ph_ptr][3] <= i - 1:
            known_phs.append(pivot_highs[ph_ptr])
            ph_ptr += 1

        while pl_ptr < len(pivot_lows) and pivot_lows[pl_ptr][3] <= i - 1:
            known_pls.append(pivot_lows[pl_ptr])
            pl_ptr += 1

        # 1. Gestão de posição aberta
        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            risk = pos["risk"]

            # Checar stop e alvo
            hit_stop = False
            hit_target = False

            if d == 1:
                if lows[i] <= pos["stop_price"]:
                    hit_stop = True
                elif highs[i] >= pos["target_price"]:
                    hit_target = True
            else:
                if highs[i] + spread >= pos["stop_price"]:
                    hit_stop = True
                elif lows[i] <= pos["target_price"]:
                    hit_target = True

            # Barra de entrada só pode ser estopada, nunca alvejada
            if i == pos["entry_idx"] and hit_target:
                hit_target = False

            if hit_stop:
                if d == 1:
                    raw_exit = min(pos["stop_price"], opens[i])
                    exit_p = raw_exit - slippage
                    r = (exit_p - pos["entry_price"]) / risk
                else:
                    raw_exit = max(pos["stop_price"], opens[i] + spread)
                    exit_p = raw_exit + slippage
                    r = (pos["entry_price"] - exit_p) / risk
                trades.append(Trade(symbol, pos["direction"], pos["entry_time"], curr_time, pos["entry_price"], pos["stop_price"], pos["target_price"], exit_p, float(r), bool(r > 0)))
                open_pos = None
                continue

            if hit_target:
                if d == 1:
                    exit_p = pos["target_price"] - slippage
                    r = (exit_p - pos["entry_price"]) / risk
                else:
                    exit_p = pos["target_price"] + slippage
                    r = (pos["entry_price"] - exit_p) / risk
                trades.append(Trade(symbol, pos["direction"], pos["entry_time"], curr_time, pos["entry_price"], pos["stop_price"], pos["target_price"], exit_p, float(r), bool(r > 0)))
                open_pos = None
                continue

        # 2. Novas entradas (se desposicionado)
        if open_pos is None:
            # Checar Divergência de Baixa (Short)
            if len(known_phs) >= 2 and len(known_pls) >= 1:
                p2 = known_phs[-1]  # topo mais recente
                p1 = known_phs[-2]  # topo anterior

                # Condição de Divergência: Topo2 > Topo1 no Preço, mas RSI2 < RSI1
                # E intervalo entre topos dentro de max_div_lookback
                if (p2[0] - p1[0] <= max_div_lookback) and (p2[1] > p1[1]) and (p2[2] < p1[2]):
                    # Achar o fundo intermediário entre p1 e p2 (suporte da deriva/cunha)
                    pls_between = [pl for pl in known_pls if p1[0] < pl[0] < p2[0]]
                    if pls_between:
                        inter_low = min(pl[1] for pl in pls_between)
                        # Rompimento confirmado no fechamento de i-1: Close[i-1] < inter_low
                        if closes[i - 1] < inter_low and closes[i - 2] >= inter_low:
                            entry_p = opens[i] - slippage  # Venda a mercado
                            stop_p = max(p2[1], highs[i - 1]) + spread + slippage
                            risk = stop_p - entry_p
                            if risk > spread * 2:
                                target_p = entry_p - (target_rr * risk)
                                # Checagem imediata de stop na barra i
                                if highs[i] + spread >= stop_p:
                                    raw_exit = max(stop_p, opens[i] + spread)
                                    exit_p = raw_exit + slippage
                                    r = (entry_p - exit_p) / risk
                                    trades.append(Trade(symbol, "short", curr_time, curr_time, entry_p, stop_p, target_p, exit_p, float(r), bool(r > 0)))
                                else:
                                    open_pos = {"entry_idx": i, "entry_time": curr_time, "direction": "short", "entry_price": entry_p, "stop_price": stop_p, "target_price": target_p, "risk": risk}
                                continue

            # Checar Divergência de Alta (Long)
            if len(known_pls) >= 2 and len(known_phs) >= 1:
                pl2 = known_pls[-1]
                pl1 = known_pls[-2]

                # Condição de Divergência: Fundo2 < Fundo1 no Preço, mas RSI2 > RSI1
                if (pl2[0] - pl1[0] <= max_div_lookback) and (pl2[1] < pl1[1]) and (pl2[2] > pl1[2]):
                    phs_between = [ph for ph in known_phs if pl1[0] < ph[0] < pl2[0]]
                    if phs_between:
                        inter_high = max(ph[1] for ph in phs_between)
                        # Rompimento confirmado no fechamento de i-1: Close[i-1] > inter_high
                        if closes[i - 1] > inter_high and closes[i - 2] <= inter_high:
                            entry_p = opens[i] + spread + slippage  # Compra a mercado
                            stop_p = min(pl2[1], lows[i - 1]) - slippage
                            risk = entry_p - stop_p
                            if risk > spread * 2:
                                target_p = entry_p + (target_rr * risk)
                                if lows[i] <= stop_p:
                                    raw_exit = min(stop_p, opens[i])
                                    exit_p = raw_exit - slippage
                                    r = (exit_p - entry_p) / risk
                                    trades.append(Trade(symbol, "long", curr_time, curr_time, entry_p, stop_p, target_p, exit_p, float(r), bool(r > 0)))
                                else:
                                    open_pos = {"entry_idx": i, "entry_time": curr_time, "direction": "long", "entry_price": entry_p, "stop_price": stop_p, "target_price": target_p, "risk": risk}
                                continue

    return trades


def calc_stats(trades: list[Trade]) -> str:
    if not trades:
        return "N=0"
    rs = np.array([t.r_multiple for t in trades])
    w = rs[rs > 0]
    l = rs[rs < 0]
    pf = (w.sum() / abs(l.sum())) if len(l) > 0 else 99.0
    wr = len(w) / len(rs) * 100.0
    se = rs.std(ddof=1) / np.sqrt(len(rs)) if len(rs) > 1 else 0.0
    t = rs.mean() / se if se > 0 else 0.0
    return f"Trades={len(rs):4d} | TotalR={rs.sum():+6.1f}R | MeanR={rs.mean():+0.3f}±{se:0.3f} (t={t:4.2f}) | PF={pf:4.2f} | WR={wr:4.1f}%"


def main():
    print("=" * 110)
    print("PESQUISA QUANTITATIVA: DIVERGÊNCIA DE RSI(14) + ROMPIMENTO DE ESTRUTURA (DERIVA / CUNHA)")
    print("=" * 110)

    symbols = [
        ("NAS100", "data/NAS100_M1_dukascopy.parquet"),
        ("US30", "data/US30_M1_dukascopy.parquet"),
        ("XAUUSD", "data/XAUUSD_M1_dukascopy.parquet"),
        ("EURUSD", "data/EURUSD_M1_dukascopy.parquet"),
    ]

    for tf_name in ["H1", "M15"]:
        print(f"\n========================== TIMEFRAME: {tf_name} ==========================")
        resample_str = "1h" if tf_name == "H1" else "15min"

        for sym, path in symbols:
            p = Path(path)
            if not p.exists():
                continue
            df_m1 = pd.read_parquet(p)
            df = df_m1.resample(resample_str).agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()

            for rr in [1.5, 2.0]:
                tr = simulate_rsi_divergence(df, sym, target_rr=rr)
                print(f"{sym:<7} ({tf_name} | Alvo {rr:.1f}R): {calc_stats(tr)}")


if __name__ == "__main__":
    main()

"""Pesquisa Empírica: 1 Operação por Dia na Janela Nobre de Volatilidade (09:30 às 11:30 NY).

Restrições Estritas:
- Horário Local de Nova York (America/New_York): 09:30 às 11:30 (pregão matutino de alta liquidez).
- Limite estrito: Máximo de 1 trade por dia (elimina overtrading).
- Timeframe M5.
- Spreads e slippages reais da Dukascopy (NAS100: spread 1.5, slippage 1.0; US30: spread 2.0, slippage 1.0).
- Causalidade estrita em i-1, stop intrabar checado no próprio candle de entrada.

Modelos Testados (1 Trade/Dia):
1. ORB-15 (Rompimento do Range dos Primeiros 15 min: 09:30-09:45)
2. Trend Pullback MME20 (Entrada no primeiro recuo na média móvel após tendência de abertura)
3. Momentum de Abertura (Primeiro rompimento de pivô M5 alinhado com o gap de abertura)
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
    cum = np.cumsum(rs)
    dd = np.maximum.accumulate(cum) - cum
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0
    return f"Trades={len(rs):4d} | TotalR={rs.sum():+6.1f}R | MeanR={rs.mean():+0.3f}±{se:0.3f} (t={t:4.2f}) | PF={pf:4.2f} | WR={wr:4.1f}% | MaxDD={max_dd:4.1f}R"


def test_orb15_one_trade_per_day(df_m5: pd.DataFrame, symbol: str, target_r: float = 2.0) -> list[Trade]:
    """ORB 15 min (09:30-09:45 Range). Entra no rompimento entre 09:45 e 11:30. Max 1 trade/dia."""
    spread = SPREADS[symbol]
    slip = SLIPPAGES[symbol]
    opens = df_m5["open"].to_numpy(dtype=float)
    highs = df_m5["high"].to_numpy(dtype=float)
    lows = df_m5["low"].to_numpy(dtype=float)
    closes = df_m5["close"].to_numpy(dtype=float)
    ts = df_m5.index
    n = len(df_m5)

    # Agrupar índices por dia
    days_dict = {}
    for idx, t in enumerate(ts):
        d = t.date()
        if d not in days_dict:
            days_dict[d] = []
        days_dict[d].append(idx)

    trades: list[Trade] = []

    for d, indices in days_dict.items():
        # Encontrar barras de 09:30 a 09:45 (primeiras 3 barras M5: 09:30, 09:35, 09:40)
        orb_indices = [i for i in indices if ts[i].hour == 9 and ts[i].minute in [30, 35, 40]]
        if len(orb_indices) < 3:
            continue

        orb_high = max(highs[i] for i in orb_indices)
        orb_low = min(lows[i] for i in orb_indices)
        orb_range = orb_high - orb_low

        if orb_range < spread * 4 or orb_range > 300:
            continue

        # Janela de operação: 09:45 às 11:30
        trade_indices = [i for i in indices if (ts[i].hour == 9 and ts[i].minute >= 45) or (ts[i].hour == 10) or (ts[i].hour == 11 and ts[i].minute <= 30)]

        for i in trade_indices:
            long_trigger = orb_high
            short_trigger = orb_low

            trig_long = highs[i] >= long_trigger
            trig_short = lows[i] <= short_trigger

            if trig_long and trig_short:
                break  # Conflito

            if trig_long:
                entry_p = max(long_trigger, opens[i]) + spread + slip
                stop_p = orb_low - slip
                risk = entry_p - stop_p
                target_p = entry_p + (target_r * risk)

                # Checa stop na própria barra
                if lows[i] <= stop_p:
                    trades.append(Trade(symbol, "ORB15_1TRADE", "long", ts[i], ts[i], -1.0, False))
                    break

                hit = None
                # Gestão até o fim do dia
                for j in range(i + 1, indices[-1] + 1):
                    if lows[j] <= stop_p:
                        hit = "loss"
                        exit_time = ts[j]
                        r_res = -1.0
                        break
                    elif highs[j] >= target_p:
                        hit = "win"
                        exit_time = ts[j]
                        r_res = target_r
                        break

                if hit is None:
                    # Encerra no fechamento do dia (16:00)
                    exit_p = closes[indices[-1]] - slip
                    r_res = (exit_p - entry_p) / risk
                    hit = "time"
                    exit_time = ts[indices[-1]]

                trades.append(Trade(symbol, "ORB15_1TRADE", "long", ts[i], exit_time, float(r_res), bool(r_res > 0)))
                break  # Apenas 1 trade por dia

            elif trig_short:
                entry_p = min(short_trigger, opens[i]) - slip
                stop_p = orb_high + spread + slip
                risk = stop_p - entry_p
                target_p = entry_p - (target_r * risk)

                if highs[i] + spread >= stop_p:
                    trades.append(Trade(symbol, "ORB15_1TRADE", "short", ts[i], ts[i], -1.0, False))
                    break

                hit = None
                for j in range(i + 1, indices[-1] + 1):
                    if highs[j] + spread >= stop_p:
                        hit = "loss"
                        exit_time = ts[j]
                        r_res = -1.0
                        break
                    elif lows[j] <= target_p:
                        hit = "win"
                        exit_time = ts[j]
                        r_res = target_r
                        break

                if hit is None:
                    exit_p = closes[indices[-1]] + spread + slip
                    r_res = (entry_p - exit_p) / risk
                    hit = "time"
                    exit_time = ts[indices[-1]]

                trades.append(Trade(symbol, "ORB15_1TRADE", "short", ts[i], exit_time, float(r_res), bool(r_res > 0)))
                break  # Apenas 1 trade por dia

    return trades


def test_pullback_ema20_one_trade(df_m5: pd.DataFrame, symbol: str, target_r: float = 1.5) -> list[Trade]:
    """Primeiro recuo na MME20 entre 09:45 e 11:30 NY. Max 1 trade/dia."""
    spread = SPREADS[symbol]
    slip = SLIPPAGES[symbol]
    opens = df_m5["open"].to_numpy(dtype=float)
    highs = df_m5["high"].to_numpy(dtype=float)
    lows = df_m5["low"].to_numpy(dtype=float)
    closes = df_m5["close"].to_numpy(dtype=float)
    ts = df_m5.index
    n = len(df_m5)

    ema20 = df_m5["close"].shift(1).ewm(span=20, adjust=False).mean().to_numpy(dtype=float)
    ema200 = df_m5["close"].shift(1).ewm(span=200, adjust=False).mean().to_numpy(dtype=float)

    days_dict = {}
    for idx, t in enumerate(ts):
        d = t.date()
        if d not in days_dict:
            days_dict[d] = []
        days_dict[d].append(idx)

    trades: list[Trade] = []

    for d, indices in days_dict.items():
        # Janela nobre: 09:45 às 11:30
        trade_indices = [i for i in indices if (ts[i].hour == 9 and ts[i].minute >= 45) or (ts[i].hour == 10) or (ts[i].hour == 11 and ts[i].minute <= 30)]

        for i in trade_indices:
            # Condição Long: Acima da MME200, vela anterior tocou MME20 e fechou acima
            is_long = closes[i - 1] > ema200[i - 1] and lows[i - 1] <= ema20[i - 1] and closes[i - 1] > ema20[i - 1]
            is_short = closes[i - 1] < ema200[i - 1] and highs[i - 1] >= ema20[i - 1] and closes[i - 1] < ema20[i - 1]

            if is_long:
                entry_p = opens[i] + spread + slip
                stop_p = min(lows[i - 1], lows[i - 2]) - slip
                risk = entry_p - stop_p

                if risk < spread * 3 or risk > 150:
                    continue

                target_p = entry_p + (target_r * risk)

                if lows[i] <= stop_p:
                    trades.append(Trade(symbol, "PULLBACK_1TRADE", "long", ts[i], ts[i], -1.0, False))
                    break

                hit = None
                for j in range(i + 1, indices[-1] + 1):
                    if lows[j] <= stop_p:
                        hit = "loss"
                        exit_time = ts[j]
                        r_res = -1.0
                        break
                    elif highs[j] >= target_p:
                        hit = "win"
                        exit_time = ts[j]
                        r_res = target_r
                        break

                if hit is None:
                    exit_p = closes[indices[-1]] - slip
                    r_res = (exit_p - entry_p) / risk
                    hit = "time"
                    exit_time = ts[indices[-1]]

                trades.append(Trade(symbol, "PULLBACK_1TRADE", "long", ts[i], exit_time, float(r_res), bool(r_res > 0)))
                break  # 1 trade/dia

            elif is_short:
                entry_p = opens[i] - slip
                stop_p = max(highs[i - 1], highs[i - 2]) + spread + slip
                risk = stop_p - entry_p

                if risk < spread * 3 or risk > 150:
                    continue

                target_p = entry_p - (target_r * risk)

                if highs[i] + spread >= stop_p:
                    trades.append(Trade(symbol, "PULLBACK_1TRADE", "short", ts[i], ts[i], -1.0, False))
                    break

                hit = None
                for j in range(i + 1, indices[-1] + 1):
                    if highs[j] + spread >= stop_p:
                        hit = "loss"
                        exit_time = ts[j]
                        r_res = -1.0
                        break
                    elif lows[j] <= target_p:
                        hit = "win"
                        exit_time = ts[j]
                        r_res = target_r
                        break

                if hit is None:
                    exit_p = closes[indices[-1]] + spread + slip
                    r_res = (entry_p - exit_p) / risk
                    hit = "time"
                    exit_time = ts[indices[-1]]

                trades.append(Trade(symbol, "PULLBACK_1TRADE", "short", ts[i], exit_time, float(r_res), bool(r_res > 0)))
                break  # 1 trade/dia

    return trades


def main():
    print("=" * 115)
    print("PESQUISA QUANTITATIVA: FILTRO DE 1 OPERAÇÃO POR DIA NA JANELA NOBRE DE NOVA YORK (09:30 ÀS 11:30)")
    print("=" * 115)

    for sym in ["NAS100", "US30"]:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        df_m1 = pd.read_parquet(p)
        df_ny = df_m1.copy()
        df_ny.index = df_ny.index.tz_convert("America/New_York")
        df_m5 = df_ny.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()

        print(f"\n>>> ATIVO: {sym} (Timeframe M5 | Horário Oficial de NY: 09:30 às 11:30)")
        print("-" * 115)

        for rr in [1.5, 2.0, 3.0]:
            tr_orb = test_orb15_one_trade_per_day(df_m5, sym, target_r=rr)
            print(f"ORB-15 (1 Trade/Dia | Alvo {rr:.1f}R):    {calc_stats(tr_orb)}")

        for rr in [1.5, 2.0]:
            tr_pb = test_pullback_ema20_one_trade(df_m5, sym, target_r=rr)
            print(f"PULLBACK MME20 (1 Trade/Dia | Alvo {rr:.1f}R): {calc_stats(tr_pb)}")


if __name__ == "__main__":
    main()

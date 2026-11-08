"""Estudo de Pesquisa Causal: Seguidor de Super Tendência com Trap na MME8 / MMA9.

Regras do Modelo Proposto pelo Usuário:
1. Regime de Super Tendência:
   - MME 80 e MME 200 alinhadas no candle i - 1.
   - Preço > MME 80 > MME 200 (compra) ou Preço < MME 80 < MME 200 (venda).
   - Inclinação / Slope da MME 80 consistente (ângulo 25° a 45°: slope normalizado por ATR positivo e sem exaustão).
   - Filtro de Força: ADX(14) >= 25 garantindo super tendência direcional.
2. Gatilho de Entrada (Trap na Média Rápida MME8 / MMA9):
   - O preço recua até a MME8 (mínima toca ou aproxima da MME8).
   - Falso rompimento da barra anterior (Trap): viola a mínima da barra anterior (low[i] < low[i-1]),
     mas fecha acima dela (reclaim: close[i] > low[i-1]).
   - Execução Causal: Ordem BuyStop na máxima do candle de trap (high[i] + spread) na barra i + 1.
3. Condução do Trade (Trailing Stop pela Média):
   - Condução livre pela MME8: a posição segue aberta enquanto close[j] >= mme8[j].
   - Saída causal no open[j+1] assim que um candle fechar do lado errado da MME8.
   - Stop Loss Inicial: No extremo oposto do candle de Trap (low[i] para compra).
"""
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

SYMBOLS = ["US30", "NAS100", "BRENT", "XAUUSD", "EURUSD", "GBPUSD"]
SPREADS = {
    "XAUUSD": 0.20,
    "EURUSD": 0.00008,
    "GBPUSD": 0.00010,
    "US30": 2.0,
    "NAS100": 1.5,
    "BRENT": 0.03,
}

@dataclass
class Trade:
    symbol: str
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_price: float
    exit_price: float
    exit_reason: str
    r_multiple: float
    win: bool

def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    close = d["close"]
    high = d["high"]
    low = d["low"]

    # Médias Móveis
    d["mme8"] = close.ewm(span=8, adjust=False).mean()
    d["mma9"] = close.rolling(window=9).mean()
    d["mme80"] = close.ewm(span=80, adjust=False).mean()
    d["mme200"] = close.ewm(span=200, adjust=False).mean()

    # ATR(14)
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    d["atr14"] = tr.rolling(window=14).mean()

    # ADX(14)
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_s = tr.rolling(window=14).sum()
    plus_di = 100 * (pd.Series(plus_dm, index=d.index).rolling(window=14).sum() / tr_s)
    minus_di = 100 * (pd.Series(minus_dm, index=d.index).rolling(window=14).sum() / tr_s)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    d["adx14"] = dx.rolling(window=14).mean().fillna(0)

    # Slope normalizado da MME80 (nas últimas 10 barras em relação ao ATR)
    d["slope80"] = (d["mme80"] - d["mme80"].shift(10)) / (10 * d["atr14"].replace(0, np.nan))

    return d

def run_trend_trap(
    symbol: str,
    df: pd.DataFrame,
    spread: float,
    adx_threshold: float = 25.0,
    use_slope_filter: bool = True,
    session_filter: bool = True,
) -> list[Trade]:
    n = len(df)
    if n < 250:
        return []

    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    ts = df.index

    mme8 = df["mme8"].to_numpy(dtype=float)
    mme80 = df["mme80"].to_numpy(dtype=float)
    mme200 = df["mme200"].to_numpy(dtype=float)
    adx = df["adx14"].to_numpy(dtype=float)
    slope80 = df["slope80"].to_numpy(dtype=float)

    trades = []
    open_pos = None
    pending_order = None

    for i in range(210, n - 1):
        # 1. Gerencia Posição Aberta
        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_sl = False
            exit_by_ma = False

            # Stop Loss Inicial
            if d == 1:
                if lows[i] <= pos["stop_price"]:
                    hit_sl = True
            else:
                if highs[i] + spread >= pos["stop_price"]:
                    hit_sl = True

            # Saída Causal por Média: fecha do lado errado de mme8 na barra i-1 -> encerra no open[i]
            # (Aqui avaliamos a barra i que acabou de fechar para sair na i+1)
            if i > pos["entry_idx"]:
                if d == 1 and closes[i] < mme8[i]:
                    exit_by_ma = True
                elif d == -1 and closes[i] > mme8[i]:
                    exit_by_ma = True

            if hit_sl:
                exit_price = pos["stop_price"]
                r = -1.0
                trades.append(Trade(
                    symbol=symbol,
                    direction=pos["direction"],
                    entry_time=pos["entry_time"],
                    exit_time=ts[i],
                    entry_price=pos["entry_price"],
                    stop_price=pos["stop_price"],
                    exit_price=exit_price,
                    exit_reason="STOP_LOSS",
                    r_multiple=r,
                    win=False,
                ))
                open_pos = None
                pending_order = None
                continue

            elif exit_by_ma and i < n - 1:
                # Executa na abertura do candle seguinte
                exit_price = opens[i + 1] if d == 1 else opens[i + 1] + spread
                r = (exit_price - pos["entry_price"]) / pos["initial_risk"] if d == 1 else (pos["entry_price"] - exit_price) / pos["initial_risk"]
                trades.append(Trade(
                    symbol=symbol,
                    direction=pos["direction"],
                    entry_time=pos["entry_time"],
                    exit_time=ts[i + 1],
                    entry_price=pos["entry_price"],
                    stop_price=pos["stop_price"],
                    exit_price=exit_price,
                    exit_reason="TRAILING_MA",
                    r_multiple=r,
                    win=r > 0,
                ))
                open_pos = None
                pending_order = None
                continue

        # 2. Executa Ordem Armada
        if pending_order is not None and open_pos is None:
            po = pending_order
            d = 1 if po["direction"] == "long" else -1
            triggered = False
            exec_price = 0.0

            if d == 1:
                if highs[i] >= po["trigger_price"]:
                    triggered = True
                    exec_price = max(opens[i], po["trigger_price"]) + spread
            else:
                if lows[i] <= po["trigger_price"]:
                    triggered = True
                    exec_price = min(opens[i], po["trigger_price"])

            if triggered:
                risk = abs(exec_price - po["stop_price"])
                if risk > 0:
                    open_pos = {
                        "direction": po["direction"],
                        "entry_idx": i,
                        "entry_time": ts[i],
                        "entry_price": exec_price,
                        "stop_price": po["stop_price"],
                        "initial_risk": risk,
                    }
                    pending_order = None
                    continue
                else:
                    pending_order = None
            else:
                pending_order = None

        # 3. Filtro de Super Tendência em i-1 (Causal)
        if open_pos is None and pending_order is None:
            in_session = True
            if session_filter:
                h = ts[i].hour
                in_session = (7 <= h < 18)

            if not in_session:
                continue

            # ADX Forte
            strong_trend = adx[i - 1] >= adx_threshold

            # Alinhamento das médias
            bullish_macro = (closes[i - 1] > mme80[i - 1] > mme200[i - 1])
            bearish_macro = (closes[i - 1] < mme80[i - 1] < mme200[i - 1])

            # Inclinação da MME80 (entre 25° e 45°: slope de 0.1 a 0.8 do ATR)
            slope_bullish = True
            slope_bearish = True
            if use_slope_filter:
                slope_bullish = (0.10 <= slope80[i - 1] <= 1.00)
                slope_bearish = (-1.00 <= slope80[i - 1] <= -0.10)

            # 4. Gatilho de Trap na MME8 na barra i
            # Trap de Compra:
            if strong_trend and bullish_macro and slope_bullish:
                # O candle i recua até a MME8
                touched_mme8 = (lows[i] <= mme8[i] * 1.001)
                # Viola a mínima anterior mas fecha acima (Trap de fundo)
                trap_fundo = (lows[i] < lows[i - 1]) and (closes[i] > lows[i - 1]) and (closes[i] > opens[i])

                if touched_mme8 and trap_fundo:
                    # Arma BuyStop na máxima da barra i
                    pending_order = {
                        "direction": "long",
                        "trigger_price": highs[i],
                        "stop_price": lows[i],
                    }

            # Trap de Venda:
            elif strong_trend and bearish_macro and slope_bearish:
                touched_mme8 = (highs[i] >= mme8[i] * 0.999)
                trap_topo = (highs[i] > highs[i - 1]) and (closes[i] < highs[i - 1]) and (closes[i] < opens[i])

                if touched_mme8 and trap_topo:
                    # Arma SellStop na mínima da barra i
                    pending_order = {
                        "direction": "short",
                        "trigger_price": lows[i],
                        "stop_price": highs[i] + spread,
                    }

    return trades

def max_drawdown_r(trades: list[Trade]) -> float:
    if not trades:
        return 0.0
    r_curve = np.cumsum([t.r_multiple for t in trades])
    peak = np.maximum.accumulate(r_curve)
    dd = peak - r_curve
    return float(np.max(dd)) if len(dd) > 0 else 0.0

def main():
    print("=" * 95)
    print("  ESTUDO DE 5 ANOS: SEGUIDOR DE SUPER TENDÊNCIA COM TRAP NA MME8 (2021-2026)")
    print("  Filtros: MME80 + MME200 Alinhadas, Ângulo/Slope 25°-45°, ADX(14) >= 25, Trailing MME8")
    print("=" * 95)

    timeframes = ["5min", "10min", "15min"]

    for tf in timeframes:
        tf_name = "M5" if tf == "5min" else ("M10" if tf == "10min" else "M15")
        print(f"\n>>> TESTANDO TIMEFRAME {tf_name} (TODOS OS ATIVOS NOS 5 ANOS) <<<")
        print(f"{'Ativo':8s} | {'Trades':>6s} | {'R Total':>8s} | {'R/ano':>7s} | {'Acerto %':>8s} | {'PF':>5s} | {'MaxDD':>6s} | {'IS (3a)':>8s} | {'OOS (2a)':>9s}")
        print("-" * 95)

        tot_trades = 0
        tot_r = 0.0
        tot_is_r = 0.0
        tot_oos_r = 0.0

        for sym in SYMBOLS:
            p = Path(f"data/{sym}_M1_dukascopy.parquet")
            if not p.exists():
                continue
            df_m1 = pd.read_parquet(p)
            df_tf = df_m1.resample(tf).agg({
                "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
            }).dropna()
            df_tf = compute_indicators(df_tf)
            spread = SPREADS[sym]

            trades = run_trend_trap(sym, df_tf, spread, adx_threshold=25.0, use_slope_filter=True, session_filter=True)
            n = len(trades)
            if n == 0:
                print(f"{sym:8s} |      0 |     0.0R |    0.0R |     0.0% |  0.00 |   0.0R |     0.0R |      0.0R")
                continue

            r_vals = [t.r_multiple for t in trades]
            r_tot = sum(r_vals)
            r_ano = r_tot / 5.0
            wins = sum(1 for t in trades if t.win)
            wr = 100.0 * wins / n
            gp = sum(r for r in r_vals if r > 0)
            gl = -sum(r for r in r_vals if r < 0)
            pf = gp / gl if gl > 0 else float("inf")
            dd = max_drawdown_r(trades)

            split_dt = pd.Timestamp("2024-11-01", tz="UTC")
            is_r = sum(t.r_multiple for t in trades if t.entry_time < split_dt)
            oos_r = sum(t.r_multiple for t in trades if t.entry_time >= split_dt)

            tot_trades += n
            tot_r += r_tot
            tot_is_r += is_r
            tot_oos_r += oos_r

            print(f"{sym:8s} | {n:6d} | {r_tot:7.1f}R | {r_ano:6.1f}R | {wr:7.1f}% | {pf:5.2f} | {dd:5.1f}R | {is_r:7.1f}R | {oos_r:8.1f}R")

        print("-" * 95)
        tot_r_ano = tot_r / 5.0
        tot_wr = 0.0
        print(f"{'TOTAL':8s} | {tot_trades:6d} | {tot_r:7.1f}R | {tot_r_ano:6.1f}R |       |       |        | {tot_is_r:7.1f}R | {tot_oos_r:8.1f}R")

if __name__ == "__main__":
    main()

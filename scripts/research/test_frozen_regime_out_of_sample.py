"""Teste Fora da Amostra Estrito: Validação da Hipótese de Super Tendência Intraday.

Hipótese Congelada:
- Alpha não decorre de gatilhos visuais (trap, barra de força, engolfo), mas sim
  do momentum intradiário em índices acionários durante a janela de liquidez institucional.
- Regra Macro Causal em i-1:
  * ADX(14) >= 25.0
  * Alinhamento MME 80 e MME 200 (Compra: close > MME80 > MME200; Venda: close < MME80 < MME200)
  * Slope normalizado da MME 80 em 10 barras por ATR(14) entre 0.10 e 1.00
- Sessão:
  * Índices Americanos: 13:00 às 17:30 UTC (Sessão de Wall Street)
  * Índices Europeus (GER40): 07:00 às 15:30 UTC (Sessão de Frankfurt/Londres)
- Execução Causal:
  * Entrada por BuyStop/SellStop na máxima/mínima da barra de sinal
  * Modo single_position estrito (máximo 1 trade ativo por vez)
  * Stop na barra de entrada testado imediatamente após o fill
  * Stop com gap preenchido no Open
  * Slippage de 1.0 ponto por execução stop
  * Condução: saída causal por fechamento além da MME 20 executada no Open da barra seguinte

Ativos / Períodos Fora da Amostra (Nunca avaliados antes):
1. SPX500 (S&P 500) — 2022 a 2025 (3 anos)
2. GER40 (DAX alemão) — 2022 a 2025 (3 anos)
3. NAS100 (Período anterior a 2021) — 2018 a 2021 (3 anos)
"""

from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
import dukascopy_python
import numpy as np
import pandas as pd

from smc_trader.data.dukascopy_source import fetch_m1

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

def compute_indicators(df: pd.DataFrame) -> dict[str, np.ndarray]:
    close = df["close"]
    high = df["high"]
    low = df["low"]

    mme20 = close.ewm(span=20, adjust=False).mean().to_numpy(dtype=float)
    mme80 = close.ewm(span=80, adjust=False).mean().to_numpy(dtype=float)
    mme200 = close.ewm(span=200, adjust=False).mean().to_numpy(dtype=float)

    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=14).mean()

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr_s = tr.rolling(window=14).sum()
    plus_di = 100 * (pd.Series(plus_dm, index=df.index).rolling(window=14).sum() / tr_s)
    minus_di = 100 * (pd.Series(minus_dm, index=df.index).rolling(window=14).sum() / tr_s)
    dx = 100 * ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx14 = dx.rolling(window=14).mean().fillna(0).to_numpy(dtype=float)

    slope80 = (
        (close.ewm(span=80, adjust=False).mean() - close.ewm(span=80, adjust=False).mean().shift(10))
        / (10 * atr.replace(0, np.nan))
    ).fillna(0).to_numpy(dtype=float)

    return {
        "mme20": mme20,
        "mme80": mme80,
        "mme200": mme200,
        "adx14": adx14,
        "slope80": slope80,
        "atr": atr.to_numpy(dtype=float),
    }

def run_pure_regime_sim(
    df: pd.DataFrame,
    symbol: str,
    spread: float,
    t_start: int,
    t_end: int,
    slippage: float = 1.0,
) -> list[Trade]:
    ind = compute_indicators(df)
    opens = df["open"].to_numpy(dtype=float)
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    ts = df.index
    time_vals = (df.index.hour * 60 + df.index.minute).to_numpy(dtype=np.int32)

    mme20 = ind["mme20"]
    mme80 = ind["mme80"]
    mme200 = ind["mme200"]
    adx = ind["adx14"]
    slope80 = ind["slope80"]

    n = len(opens)
    trades: list[Trade] = []
    open_pos = None
    pending_order = None

    for i in range(210, n - 1):
        # 1. Posição Aberta
        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_sl = False
            exit_by_ma = False

            if d == 1:
                if lows[i] <= pos["stop_price"]:
                    hit_sl = True
            else:
                if highs[i] + spread >= pos["stop_price"]:
                    hit_sl = True

            if i > pos["entry_idx"]:
                if d == 1 and closes[i] < mme20[i]:
                    exit_by_ma = True
                elif d == -1 and closes[i] > mme20[i]:
                    exit_by_ma = True

            if hit_sl:
                if d == 1:
                    raw_exit = min(pos["stop_price"], opens[i])
                    exit_price = raw_exit - slippage
                    r = (exit_price - pos["entry_price"]) / pos["initial_risk"]
                else:
                    raw_exit = max(pos["stop_price"], opens[i] + spread)
                    exit_price = raw_exit + slippage
                    r = (pos["entry_price"] - exit_price) / pos["initial_risk"]

                trades.append(Trade(symbol, pos["direction"], pos["entry_time"], ts[i], pos["entry_price"], pos["stop_price"], exit_price, "STOP_LOSS", float(r), bool(r > 0)))
                open_pos = None
                pending_order = None
                continue

            elif exit_by_ma and i < n - 1:
                exit_price = opens[i + 1] if d == 1 else opens[i + 1] + spread
                r = (exit_price - pos["entry_price"]) / pos["initial_risk"] if d == 1 else (pos["entry_price"] - exit_price) / pos["initial_risk"]
                trades.append(Trade(symbol, pos["direction"], pos["entry_time"], ts[i + 1], pos["entry_price"], pos["stop_price"], exit_price, "TRAILING_MA", float(r), bool(r > 0)))
                open_pos = None
                pending_order = None
                continue

        # 2. Ordem Armada
        if pending_order is not None and open_pos is None:
            po = pending_order
            d = 1 if po["direction"] == "long" else -1
            triggered = False
            exec_price = 0.0

            if d == 1:
                if highs[i] >= po["trigger_price"]:
                    triggered = True
                    exec_price = max(opens[i], po["trigger_price"]) + spread + slippage
            else:
                if lows[i] <= po["trigger_price"]:
                    triggered = True
                    exec_price = min(opens[i], po["trigger_price"]) - slippage

            if triggered:
                risk = abs(exec_price - po["stop_price"])
                if risk > 0:
                    entry_stopped = False
                    if d == 1:
                        if lows[i] <= po["stop_price"]:
                            entry_stopped = True
                            raw_exit = min(po["stop_price"], opens[i])
                            exit_price = raw_exit - slippage
                            r = (exit_price - exec_price) / risk
                    else:
                        if highs[i] + spread >= po["stop_price"]:
                            entry_stopped = True
                            raw_exit = max(po["stop_price"], opens[i] + spread)
                            exit_price = raw_exit + slippage
                            r = (exec_price - exit_price) / risk

                    if entry_stopped:
                        trades.append(Trade(symbol, po["direction"], ts[i], ts[i], exec_price, po["stop_price"], exit_price, "STOP_LOSS_ENTRY", float(r), bool(r > 0)))
                        open_pos = None
                        pending_order = None
                        continue
                    else:
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

        # 3. Identificar Sinal do Regime (Rompimento Simples alinhado com o Regime)
        if open_pos is None and pending_order is None:
            if not (t_start <= time_vals[i] <= t_end):
                continue

            strong_trend = adx[i - 1] >= 25.0
            bullish_macro = closes[i - 1] > mme80[i - 1] > mme200[i - 1]
            bearish_macro = closes[i - 1] < mme80[i - 1] < mme200[i - 1]
            slope_bullish = 0.10 <= slope80[i - 1] <= 1.00
            slope_bearish = -1.00 <= slope80[i - 1] <= -0.10

            c_range = highs[i] - lows[i]
            if c_range <= 0 or not strong_trend:
                continue

            # Rompimento simples do extremo da barra de sinal
            if bullish_macro and slope_bullish and closes[i] > opens[i]:
                pending_order = {
                    "direction": "long",
                    "trigger_price": highs[i],
                    "stop_price": lows[i],
                }
            elif bearish_macro and slope_bearish and closes[i] < opens[i]:
                pending_order = {
                    "direction": "short",
                    "trigger_price": lows[i],
                    "stop_price": highs[i] + spread,
                }

    return trades

def print_metrics(name: str, trades: list[Trade]):
    n = len(trades)
    if n == 0:
        print(f"[{name}] 0 trades realizados.")
        return
    tot_r = sum(t.r_multiple for t in trades)
    r_tr = tot_r / n
    std = np.std([t.r_multiple for t in trades])
    se = std / np.sqrt(n) if n > 0 else 0
    t_stat = r_tr / se if se > 0 else 0
    wins = sum(1 for t in trades if t.win)
    wr = 100.0 * wins / n
    gp = sum(t.r_multiple for t in trades if t.r_multiple > 0)
    gl = -sum(t.r_multiple for t in trades if t.r_multiple < 0)
    pf = gp / gl if gl > 0 else float("inf")

    # Drawdown
    r_curve = np.cumsum([t.r_multiple for t in trades])
    peak = np.maximum.accumulate(r_curve)
    dd = float(np.max(peak - r_curve)) if len(r_curve) > 0 else 0.0

    print(f"\n========================================================")
    print(f"  RESULTADO FORA DA AMOSTRA: {name}")
    print(f"========================================================")
    print(f"Trades Totais        : {n}")
    print(f"Retorno Total        : {tot_r:+.1f}R")
    print(f"Expectativa (R/trade): {r_tr:+.3f} ± {se:.3f}R")
    print(f"Estatística t        : {t_stat:.2f} {'(Significativo)' if abs(t_stat) >= 2.0 else '(NÃO SIGNIFICATIVO - RUÍDO)'}")
    print(f"Taxa de Acerto       : {wr:.1f}%")
    print(f"Profit Factor        : {pf:.2f}")
    print(f"Max Drawdown         : {dd:.1f}R")

def get_or_download_data(symbol: str, instrument: str, start: datetime, end: datetime, cache_file: Path) -> pd.DataFrame:
    if cache_file.exists():
        print(f"Carregando {symbol} do cache local {cache_file}...")
        df_m1 = pd.read_parquet(cache_file)
    else:
        print(f"Baixando {symbol} ({instrument}) de {start.date()} a {end.date()} da Dukascopy...")
        df_m1 = fetch_m1(instrument, start, end, "bid")
        df_m1.to_parquet(cache_file)
        print(f"Download concluído: {len(df_m1)} barras salvas em {cache_file}.")

    # Resample para M15
    df_m15 = df_m1.resample("15min").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna()
    return df_m15

def main():
    data_dir = Path("data/holdout")
    data_dir.mkdir(parents=True, exist_ok=True)

    assets_to_test = [
        # (Nome, Símbolo Dukascopy, Início, Fim, Spread, Horário Inicial UTC, Horário Final UTC)
        ("SPX500 (2022-2025)", "USA500.IDX/USD", datetime(2022, 1, 1), datetime(2025, 1, 1), 0.5, 13 * 60, 17 * 60 + 30),
        ("GER40 (2022-2025)", "E_DAAX", datetime(2022, 1, 1), datetime(2025, 1, 1), 1.5, 7 * 60, 15 * 60 + 30),
        ("NAS100 Pré-2021 (2018-2021)", "E_NQ-100", datetime(2018, 1, 1), datetime(2021, 11, 1), 1.5, 13 * 60, 17 * 60 + 30),
    ]

    for name, inst, dt_s, dt_e, spread, t_s, t_e in assets_to_test:
        sym_clean = name.split()[0].replace("(", "").replace(")", "").replace("-", "_")
        cache_path = data_dir / f"{sym_clean}_M1.parquet"
        try:
            df_m15 = get_or_download_data(sym_clean, inst, dt_s, dt_e, cache_path)
            trades = run_pure_regime_sim(df_m15, sym_clean, spread, t_s, t_e, slippage=1.0)
            print_metrics(name, trades)
        except Exception as e:
            print(f"Erro ao testar {name}: {e}")

if __name__ == "__main__":
    main()

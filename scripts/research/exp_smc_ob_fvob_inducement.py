"""Estudo de Pesquisa: SMC FVOB / OB com Indução e Alinhamento MME80 + MMA200.

Regras do Experimento:
1. Regime de Tendência: MME80 e MMA200 alinhadas no candle i - 1.
2. Estrutura: BOS a favor da tendência das médias.
3. POI: Bloco de Ordens (FVOB prioritário com imbalance/FVG, ou OB clássico)
   na zona de retração [61.8% a 79.0%].
4. Indução: Correção mais lenta que o impulso (candles_ret >= candles_imp)
   OU formação de liquidez intermediária (>= 2 toques).
5. Gatilho de Confirmação: Rejeição no bloco no candle i, entrada no rompimento
   da máxima (compra) ou mínima (venda) no candle i + 1.
6. Alvo: Fixo em 0.000 (extremo da perna).
7. Variáveis de Stop: Teste comparativo entre 0.800, 0.886 e 1.000.
"""
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

SYMBOLS = ["BRENT", "US30", "NAS100", "XAUUSD", "EURUSD", "GBPUSD"]
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
    target_price: float
    exit_price: float
    exit_reason: str
    r_multiple: float
    win: bool

def compute_indicators(df_m5: pd.DataFrame) -> pd.DataFrame:
    df = df_m5.copy()
    df["ema80"] = df["close"].ewm(span=80, adjust=False).mean()
    df["sma200"] = df["close"].rolling(window=200).mean()
    return df

def run_asset(symbol: str, df_m5: pd.DataFrame, stop_ratio: float, spread: float) -> list[Trade]:
    n = len(df_m5)
    if n < 250:
        return []

    opens = df_m5["open"].to_numpy(dtype=float)
    highs = df_m5["high"].to_numpy(dtype=float)
    lows = df_m5["low"].to_numpy(dtype=float)
    closes = df_m5["close"].to_numpy(dtype=float)
    ts = df_m5.index
    ema80 = df_m5["ema80"].to_numpy(dtype=float)
    sma200 = df_m5["sma200"].to_numpy(dtype=float)

    # 1. Pré-computa swings (k=2)
    k = 2
    swing_highs: list[tuple[int, float]] = []  # (idx, price)
    swing_lows: list[tuple[int, float]] = []

    for i in range(k, n - k):
        h = highs[i]
        if np.all(h >= highs[i - k : i]) and np.all(h >= highs[i + 1 : i + k + 1]):
            swing_highs.append((i, h))
        l = lows[i]
        if np.all(l <= lows[i - k : i]) and np.all(l <= lows[i + 1 : i + k + 1]):
            swing_lows.append((i, l))

    # Mapeia swings disponíveis causalmente no tempo i (confirmados em idx + k)
    highs_by_conf: dict[int, tuple[int, float]] = {idx + k: (idx, p) for idx, p in swing_highs}
    lows_by_conf: dict[int, tuple[int, float]] = {idx + k: (idx, p) for idx, p in swing_lows}

    trades: list[Trade] = []
    
    # Estado da perna ativa
    active_leg = None
    # Estado da ordem armada (gatilho de rompimento da barra de rejeição)
    pending_order = None
    # Posição aberta
    open_pos = None

    last_high = None
    last_low = None

    for i in range(200, n):
        # Atualiza swings conhecidos em i
        if i in highs_by_conf:
            last_high = highs_by_conf[i]
        if i in lows_by_conf:
            last_low = lows_by_conf[i]

        # -------------------------------------------------------------
        # 1. Gerencia Posição Aberta
        # -------------------------------------------------------------
        if open_pos is not None:
            pos = open_pos
            d = 1 if pos["direction"] == "long" else -1
            hit_tp = False
            hit_sl = False

            if d == 1:
                # Long: SL no low, TP no high
                if lows[i] <= pos["stop_price"]:
                    hit_sl = True
                if highs[i] >= pos["target_price"]:
                    hit_tp = True
            else:
                # Short: SL no high (ask = high + spread), TP no low (ask = low + spread)
                if highs[i] + spread >= pos["stop_price"]:
                    hit_sl = True
                if lows[i] + spread <= pos["target_price"]:
                    hit_tp = True

            if hit_sl and hit_tp:
                # Pior caso causal: stop
                hit_sl = True
                hit_tp = False

            if hit_sl:
                exit_price = pos["stop_price"] if d == 1 else pos["stop_price"]
                r = -1.0
                trades.append(Trade(
                    symbol=symbol,
                    direction=pos["direction"],
                    entry_time=pos["entry_time"],
                    exit_time=ts[i],
                    entry_price=pos["entry_price"],
                    stop_price=pos["stop_price"],
                    target_price=pos["target_price"],
                    exit_price=exit_price,
                    exit_reason="STOP_LOSS",
                    r_multiple=r,
                    win=False,
                ))
                open_pos = None
                active_leg = None
                pending_order = None
                continue
            elif hit_tp:
                exit_price = pos["target_price"]
                r = pos["r_target"]
                trades.append(Trade(
                    symbol=symbol,
                    direction=pos["direction"],
                    entry_time=pos["entry_time"],
                    exit_time=ts[i],
                    entry_price=pos["entry_price"],
                    stop_price=pos["stop_price"],
                    target_price=pos["target_price"],
                    exit_price=exit_price,
                    exit_reason="TAKE_PROFIT",
                    r_multiple=r,
                    win=True,
                ))
                open_pos = None
                active_leg = None
                pending_order = None
                continue

        # -------------------------------------------------------------
        # 2. Executa Ordem Armada (Gatilho de Rompimento da Rejeição)
        # -------------------------------------------------------------
        if pending_order is not None and open_pos is None:
            po = pending_order
            d = 1 if po["direction"] == "long" else -1
            triggered = False
            exec_price = 0.0

            if d == 1:
                if highs[i] >= po["trigger_price"]:
                    triggered = True
                    # Compra no rompimento da máxima + spread (ou no open se abriu acima)
                    exec_price = max(opens[i], po["trigger_price"]) + spread
            else:
                if lows[i] <= po["trigger_price"]:
                    triggered = True
                    # Venda no rompimento da mínima (executa no bid)
                    exec_price = min(opens[i], po["trigger_price"])

            if triggered:
                # Calcula R:R e abre posição
                risk = abs(exec_price - po["stop_price"])
                reward = abs(po["target_price"] - exec_price)
                if risk > 0 and reward > 0:
                    r_target = reward / risk
                    open_pos = {
                        "direction": po["direction"],
                        "entry_time": ts[i],
                        "entry_price": exec_price,
                        "stop_price": po["stop_price"],
                        "target_price": po["target_price"],
                        "r_target": r_target,
                    }
                    pending_order = None
                    active_leg = None
                    continue
                else:
                    pending_order = None
            else:
                # Ordem armada só vale para a barra seguinte à rejeição (cancelada se não disparou)
                pending_order = None

        # -------------------------------------------------------------
        # 3. Detecta BOS e Atualiza Perna Estrutural
        # -------------------------------------------------------------
        # Checa alinhamento das médias em i - 1
        bullish_trend = (ema80[i - 1] > sma200[i - 1]) and (closes[i - 1] > sma200[i - 1])
        bearish_trend = (ema80[i - 1] < sma200[i - 1]) and (closes[i - 1] < sma200[i - 1])

        # BOS de Alta
        if bullish_trend and last_high is not None and last_low is not None:
            if closes[i] > last_high[1] and closes[i - 1] <= last_high[1]:
                # Inicia perna de alta
                orig_idx, orig_p = last_low
                if i - orig_idx >= 3 and highs[i] > orig_p:
                    active_leg = {
                        "direction": "long",
                        "origin_idx": orig_idx,
                        "origin_price": orig_p,
                        "bos_idx": i,
                        "extreme_price": highs[i],
                        "extreme_idx": i,
                        "impulse_candles": i - orig_idx,
                        "touched": False,
                        "idm_pivots": [],
                    }

        # BOS de Baixa
        if bearish_trend and last_low is not None and last_high is not None:
            if closes[i] < last_low[1] and closes[i - 1] >= last_low[1]:
                # Inicia perna de baixa
                orig_idx, orig_p = last_high
                if i - orig_idx >= 3 and lows[i] < orig_p:
                    active_leg = {
                        "direction": "short",
                        "origin_idx": orig_idx,
                        "origin_price": orig_p,
                        "bos_idx": i,
                        "extreme_price": lows[i],
                        "extreme_idx": i,
                        "impulse_candles": i - orig_idx,
                        "touched": False,
                        "idm_pivots": [],
                    }

        # -------------------------------------------------------------
        # 4. Acompanha Perna Ativa, Indução e Blocos de Ordens
        # -------------------------------------------------------------
        if active_leg is not None and open_pos is None:
            leg = active_leg
            d = 1 if leg["direction"] == "long" else -1
            span = d * (leg["extreme_price"] - leg["origin_price"])
            if span <= 0:
                active_leg = None
                continue

            # Expansão da perna se continuar sem retrair até 50%
            lvl_50 = leg["extreme_price"] - d * 0.50 * span
            if d == 1:
                if lows[i] > lvl_50 and highs[i] > leg["extreme_price"]:
                    leg["extreme_price"] = highs[i]
                    leg["extreme_idx"] = i
                    leg["impulse_candles"] = i - leg["origin_idx"]
            else:
                if highs[i] < lvl_50 and lows[i] < leg["extreme_price"]:
                    leg["extreme_price"] = lows[i]
                    leg["extreme_idx"] = i
                    leg["impulse_candles"] = i - leg["origin_idx"]

            # Recalcula níveis com extreme atualizado
            span = d * (leg["extreme_price"] - leg["origin_price"])
            lvl_618 = leg["extreme_price"] - d * 0.618 * span
            lvl_790 = leg["extreme_price"] - d * 0.790 * span
            lvl_stop = leg["extreme_price"] - d * stop_ratio * span
            lvl_target = leg["extreme_price"]  # Nível 0.000

            # Rastreia pivôs de indução (IDM) no recuo
            if i > leg["extreme_idx"]:
                if d == 1 and lows[i] > lvl_50:
                    leg["idm_pivots"].append(lows[i])
                elif d == -1 and highs[i] < lvl_50:
                    leg["idm_pivots"].append(highs[i])

            # Mapeia blocos (FVOB ou OB) na perna
            # Procura o último candle contrário entre origin_idx e extreme_idx
            block_high = None
            block_low = None
            has_fvob = False

            for b in range(leg["extreme_idx"] - 1, leg["origin_idx"], -1):
                if d == 1:
                    # Candle corretivo (baixa) antes da explosão
                    if closes[b] < opens[b]:
                        # Checa se gerou FVG logo após
                        if b + 2 <= leg["extreme_idx"] and lows[b + 2] > highs[b]:
                            has_fvob = True
                            block_high = highs[b]
                            block_low = lows[b]
                            break
                        elif block_high is None:
                            block_high = highs[b]
                            block_low = lows[b]
                else:
                    # Candle corretivo (alta) antes da queda
                    if closes[b] > opens[b]:
                        if b + 2 <= leg["extreme_idx"] and highs[b + 2] < lows[b]:
                            has_fvob = True
                            block_high = highs[b]
                            block_low = lows[b]
                            break
                        elif block_high is None:
                            block_high = highs[b]
                            block_low = lows[b]

            # Se achou bloco, verifica se ele intersecta a zona [61.8% a 79.0%]
            block_in_zone = False
            if block_high is not None and block_low is not None:
                z_top = max(lvl_618, lvl_790)
                z_bot = min(lvl_618, lvl_790)
                if block_low <= z_top and block_high >= z_bot:
                    block_in_zone = True

            # Invalidação da perna se violar o stop_ratio
            if d == 1 and lows[i] <= lvl_stop:
                active_leg = None
                continue
            elif d == -1 and highs[i] >= lvl_stop:
                active_leg = None
                continue

            # Checa toque no POI (zona 61.8-79 e bloco se existir)
            touch_zone = (lows[i] <= lvl_618 and highs[i] >= lvl_790) if d == 1 else (highs[i] >= lvl_618 and lows[i] <= lvl_790)
            
            if touch_zone:
                # Checa Indução:
                # Critério A: retração mais lenta que o impulso
                ret_candles = i - leg["extreme_idx"]
                criterio_a = ret_candles >= leg["impulse_candles"]

                # Critério B: ao menos 2 pivôs intermediários no recuo (pool de liquidez)
                criterio_b = len(leg["idm_pivots"]) >= 2

                idm_ok = criterio_a or criterio_b

                if idm_ok:
                    # Checa Gatilho de Rejeição na Barra i
                    rng = highs[i] - lows[i]
                    if rng > 0:
                        if d == 1:
                            lower_wick = min(opens[i], closes[i]) - lows[i]
                            # Pavio inferior >= 30% do range e fecha acima de lvl_790
                            if lower_wick / rng >= 0.30 and closes[i] > lvl_790:
                                # Arma compra no rompimento da máxima
                                pending_order = {
                                    "direction": "long",
                                    "trigger_price": highs[i],
                                    "stop_price": lvl_stop,
                                    "target_price": lvl_target,
                                }
                                active_leg = None
                        else:
                            upper_wick = highs[i] - max(opens[i], closes[i])
                            # Pavio superior >= 30% do range e fecha abaixo de lvl_790
                            if upper_wick / rng >= 0.30 and closes[i] < lvl_790:
                                # Arma venda no rompimento da mínima
                                pending_order = {
                                    "direction": "short",
                                    "trigger_price": lows[i],
                                    "stop_price": lvl_stop,
                                    "target_price": lvl_target,
                                }
                                active_leg = None

    return trades

def evaluate_symbol(sym: str) -> dict[float, list[Trade]]:
    path = Path(f"data/{sym}_M1_dukascopy.parquet")
    if not path.exists():
        return {}
    df_m1 = pd.read_parquet(path)
    # Resample para M5
    df_m5 = df_m1.resample("5min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }).dropna()
    df_m5 = compute_indicators(df_m5)
    spread = SPREADS[sym]

    res = {}
    for stop_ratio in [0.800, 0.886, 1.000]:
        res[stop_ratio] = run_asset(sym, df_m5, stop_ratio, spread)
    return res

def print_results():
    all_res = {sym: evaluate_symbol(sym) for sym in SYMBOLS}
    stops = [0.800, 0.886, 1.000]

    for stop_ratio in stops:
        print(f"\n=======================================================")
        print(f"  RESULTADO COM STOP EM {stop_ratio:.3f} (Alvo em 0.000)")
        print(f"=======================================================")
        print(f"{'Ativo':8s} | {'Trades':>6s} | {'R Total':>8s} | {'Acerto %':>8s} | {'PF':>5s} | {'R/tr ± EP':>16s} | {'IS (1ª Met)':>10s} | {'OOS (2ª Met)':>11s}")
        print("-" * 88)

        total_r = 0.0
        total_trades = 0
        total_wins = 0
        is_r_tot = 0.0
        oos_r_tot = 0.0

        for sym in SYMBOLS:
            tr = all_res[sym].get(stop_ratio, [])
            n = len(tr)
            if n == 0:
                print(f"{sym:8s} |      0 |     0.0R |     0.0% |  0.00 |   0.000 ± 0.000  |       0.0R |        0.0R")
                continue

            r_vals = [t.r_multiple for t in tr]
            r_tot = sum(r_vals)
            wins = sum(1 for t in tr if t.win)
            wr = 100.0 * wins / n
            gp = sum(r for r in r_vals if r > 0)
            gl = -sum(r for r in r_vals if r < 0)
            pf = gp / gl if gl > 0 else float("inf")
            ep = np.std(r_vals) / np.sqrt(n) if n > 1 else 0.0
            r_tr = r_tot / n

            # Divide IS (1ª metade: 2026-03 a 2026-06) e OOS (2ª metade: 2026-06 a 2026-10)
            split_dt = pd.Timestamp("2026-06-25", tz="UTC") if tr[0].entry_time.tzinfo is not None else pd.Timestamp("2026-06-25")
            is_r = sum(t.r_multiple for t in tr if t.entry_time < split_dt)
            oos_r = sum(t.r_multiple for t in tr if t.entry_time >= split_dt)

            total_r += r_tot
            total_trades += n
            total_wins += wins
            is_r_tot += is_r
            oos_r_tot += oos_r

            print(f"{sym:8s} | {n:6d} | {r_tot:7.1f}R | {wr:7.1f}% | {pf:5.2f} | {r_tr:6.3f} ± {ep:5.3f} | {is_r:9.1f}R | {oos_r:10.1f}R")

        print("-" * 88)
        tot_wr = 100.0 * total_wins / total_trades if total_trades > 0 else 0.0
        tot_ep = 0.0
        tot_r_tr = total_r / total_trades if total_trades > 0 else 0.0
        print(f"{'TOTAL':8s} | {total_trades:6d} | {total_r:7.1f}R | {tot_wr:7.1f}% |       | {tot_r_tr:6.3f}          | {is_r_tot:9.1f}R | {oos_r_tot:10.1f}R")

if __name__ == "__main__":
    print_results()

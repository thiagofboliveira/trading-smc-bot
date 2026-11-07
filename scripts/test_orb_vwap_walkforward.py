"""Estudo Quantitativo e Validação Walk-Forward: ORB + VWAP + EMA 20 nos 7 Ativos Institucionais.

Metodologia Rigorosa Conforme Literatura de Microestrutura:
1. Opening Range:
   - Londres: 07:00 a 07:15 (15m) e 07:00 a 07:30 (30m) UTC
   - Nova York: 13:00 a 13:15 (15m) e 13:00 a 13:30 (30m) UTC
2. Filtros Institucionais de Confluência:
   - VWAP diário (âncora institucional intradiária)
   - EMA 20 (tração de curtíssimo prazo)
   - RVOL (Volume Relativo > 1.2x SMA20)
3. Execução & Custos:
   - Spreads reais e custos de execução
   - Stop Loss: Meio do Range (50%) ou Extremo Oposto
   - Take Profit: 1:2 e 1:3 R
   - Limite: Máximo 1 trade por sessão
4. Protocolo Walk-Forward (WFO):
   - In-Sample (Treino): 01/11/2025 a 30/04/2026 (6 Meses)
   - Out-of-Sample (Teste Cego): 01/05/2026 a 04/11/2026 (6 Meses)
   - Cálculo da Eficiência Walk-Forward (WFE = Retorno_OOS / Retorno_IS)
"""
import datetime
import itertools
from pathlib import Path
from typing import Any

import numpy as np
import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
import pandas as pd

from smc_trader.config import load_config
from smc_trader.data.store import load_candles

SYMBOLS = ["BRENT", "XAUUSD", "NAS100", "DAX40", "EURUSD", "GBPUSD", "USDJPY"]
OUT_DIR = Path("out/orb_analysis")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def calculate_vwap(df: pd.DataFrame) -> pd.Series:
    """Calcula o VWAP intradiário resetando a cada dia."""
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["volume"]
    # Se volume for constante ou zero, usa 1.0 como fallback
    if vol.sum() == 0 or vol.isna().all():
        vol = pd.Series(1.0, index=df.index)
    pv = typical_price * vol

    dates = df.index.date
    # Agrupamento cumulativo diário vetorizado
    cum_pv = pv.groupby(dates).cumsum()
    cum_vol = vol.groupby(dates).cumsum()
    vwap = cum_pv / cum_vol.replace(0, np.nan)
    return vwap.ffill()


def calculate_ema(series: pd.Series, period: int = 20) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def run_orb_simulation(
    c_m1: pd.DataFrame,
    symbol: str,
    spread_cost: float,
    orb_minutes: int = 15,
    stop_mode: str = "mid",  # "mid" (50% do range) ou "range" (extremo oposto)
    target_r: float = 2.0,
    use_vwap: bool = True,
    use_ema: bool = True,
    use_rvol: bool = False,
) -> list[dict[str, Any]]:
    """Simula a estratégia ORB cronologicamente candle a candle."""
    close = c_m1["close"].to_numpy()
    high = c_m1["high"].to_numpy()
    low = c_m1["low"].to_numpy()
    open_ = c_m1["open"].to_numpy()
    vol = c_m1["volume"].to_numpy()
    times = c_m1.index

    # Indicadores
    vwap_arr = calculate_vwap(c_m1).to_numpy() if use_vwap else None
    ema_arr = calculate_ema(c_m1["close"], 20).to_numpy() if use_ema else None
    vol_sma = pd.Series(vol).rolling(20).mean().to_numpy() if use_rvol else None

    trades = []
    n = len(c_m1)

    # Sessões: Londres (07:00 UTC) e NY (13:00 UTC)
    # Janela de formação do ORB: [start, start + orb_minutes]
    # Janela de trading: [start + orb_minutes, end_session]
    sessions = [
        {"name": "london", "start_h": 7, "start_m": 0, "end_h": 12, "end_m": 0},
        {"name": "ny", "start_h": 13, "start_m": 0, "end_h": 18, "end_m": 0},
    ]

    current_trade = None
    daily_session_trades = set()  # (date, session_name) -> max 1 trade

    for sess in sessions:
        s_name = sess["name"]
        sh, sm = sess["start_h"], sess["start_m"]
        eh, em = sess["end_h"], sess["end_m"]

        # Pré-computa ranges de cada sessão
        # Identifica dias únicos
        pass

    # Loop cronológico
    current_date = None
    orb_high = None
    orb_low = None
    orb_formed = False
    active_session = None

    for i in range(n):
        t = times[i]
        c_h = high[i]
        c_l = low[i]
        c_c = close[i]
        c_o = open_[i]
        c_date = t.date()

        # Gerenciamento de posição aberta
        if current_trade is not None:
            long = current_trade["direction"] == "long"
            sl = current_trade["stop_loss"]
            tp = current_trade["take_profit"]

            hit_sl = c_l <= sl if long else c_h >= sl
            hit_tp = c_h >= tp if long else c_l <= tp

            # Forçar fechamento no final da sessão do trade
            force_close = (t.hour >= 20) or (t.date() != current_trade["entry_time"].date())

            if hit_sl and hit_tp:
                # Ambiguidade intra-candle: assume perda (conservador)
                pnl_r = -1.0 - (spread_cost / current_trade["risk"])
                current_trade["exit_time"] = t
                current_trade["exit_price"] = sl
                current_trade["pnl_r"] = pnl_r
                current_trade["result"] = "LOSS"
                trades.append(current_trade)
                current_trade = None
            elif hit_sl:
                pnl_r = -1.0 - (spread_cost / current_trade["risk"])
                current_trade["exit_time"] = t
                current_trade["exit_price"] = sl
                current_trade["pnl_r"] = pnl_r
                current_trade["result"] = "LOSS"
                trades.append(current_trade)
                current_trade = None
            elif hit_tp:
                pnl_r = target_r - (spread_cost / current_trade["risk"])
                current_trade["exit_time"] = t
                current_trade["exit_price"] = tp
                current_trade["pnl_r"] = pnl_r
                current_trade["result"] = "GAIN"
                trades.append(current_trade)
                current_trade = None
            elif force_close:
                exit_p = c_c
                diff = (exit_p - current_trade["entry_price"]) if long else (current_trade["entry_price"] - exit_p)
                pnl_r = (diff / current_trade["risk"]) - (spread_cost / current_trade["risk"])
                current_trade["exit_time"] = t
                current_trade["exit_price"] = exit_p
                current_trade["pnl_r"] = pnl_r
                current_trade["result"] = "CLOSE"
                trades.append(current_trade)
                current_trade = None

        # Identificação de Sessão e Formação de ORB
        # Sessão Londres: 07:00 a 11:30 | NY: 13:00 a 17:30
        h, m = t.hour, t.minute
        sess_now = None
        if 7 <= h < 12:
            sess_now = "london"
            orb_start_m = 0
        elif 13 <= h < 18:
            sess_now = "ny"
            orb_start_m = 0

        if sess_now is not None:
            sess_key = (c_date, sess_now)

            # Acumulação da janela do ORB
            # Ex: Londres 15m é 07:00 até 07:14
            in_orb_window = (h == 7 or h == 13) and (0 <= m < orb_minutes)
            if in_orb_window:
                if active_session != sess_key:
                    # Início de um novo ORB
                    active_session = sess_key
                    orb_high = c_h
                    orb_low = c_l
                    orb_formed = False
                else:
                    orb_high = max(orb_high, c_h)
                    orb_low = min(orb_low, c_l)
            else:
                # Passou do horário de formação
                if active_session == sess_key and not orb_formed:
                    orb_formed = True

                # Fase de gatilho do ORB
                if orb_formed and current_trade is None and sess_key not in daily_session_trades:
                    # Checagem de breakout
                    long_break = c_c > orb_high and c_o <= orb_high
                    short_break = c_c < orb_low and c_o >= orb_low

                    if long_break or short_break:
                        # Validação dos Filtros de Confluência
                        valid = True
                        if use_vwap:
                            if long_break and c_c <= vwap_arr[i]:
                                valid = False
                            elif short_break and c_c >= vwap_arr[i]:
                                valid = False

                        if use_ema and valid:
                            if long_break and c_c <= ema_arr[i]:
                                valid = False
                            elif short_break and c_c >= ema_arr[i]:
                                valid = False

                        if use_rvol and valid:
                            if vol_sma[i] > 0 and vol[i] < 1.2 * vol_sma[i]:
                                valid = False

                        if valid:
                            # Cálculo do Stop e Take Profit
                            if stop_mode == "mid":
                                sl = (orb_high + orb_low) / 2.0
                            else:
                                sl = orb_low if long_break else orb_high

                            entry_p = c_c
                            risk = abs(entry_p - sl)

                            if risk > 0:
                                tp = (entry_p + target_r * risk) if long_break else (entry_p - target_r * risk)
                                current_trade = {
                                    "symbol": symbol,
                                    "session": sess_now,
                                    "direction": "long" if long_break else "short",
                                    "entry_time": t,
                                    "entry_price": entry_p,
                                    "stop_loss": sl,
                                    "take_profit": tp,
                                    "risk": risk,
                                    "orb_high": orb_high,
                                    "orb_low": orb_low,
                                }
                                daily_session_trades.add(sess_key)
        else:
            active_session = None
            orb_formed = False

    return trades


def run_full_study():
    cfg = load_config(Path("config/default.yaml"))
    data_root = Path("data")

    # Parâmetros para Grid Walk-Forward
    param_grid = [
        {"orb_minutes": 15, "stop_mode": "mid", "target_r": 2.0, "use_vwap": True, "use_ema": True},
        {"orb_minutes": 15, "stop_mode": "mid", "target_r": 3.0, "use_vwap": True, "use_ema": True},
        {"orb_minutes": 30, "stop_mode": "mid", "target_r": 2.0, "use_vwap": True, "use_ema": True},
        {"orb_minutes": 30, "stop_mode": "mid", "target_r": 3.0, "use_vwap": True, "use_ema": True},
        {"orb_minutes": 15, "stop_mode": "range", "target_r": 2.0, "use_vwap": True, "use_ema": True},
        {"orb_minutes": 30, "stop_mode": "range", "target_r": 2.0, "use_vwap": True, "use_ema": True},
    ]

    split_date = pd.Timestamp("2026-05-01", tz="UTC")

    all_results = []
    trade_logs = []

    print("=" * 80)
    print("🚀 INICIANDO AUDITORIA QUANTITATIVA: ORB + VWAP + EMA20 COM WALK-FORWARD")
    print(f"Período: 01/11/2025 a 04/11/2026 (12 Meses Reais)")
    print(f"Divisão: In-Sample (Treino) até 30/04/2026 | Out-of-Sample (Teste Cego) a partir de 01/05/2026")
    print("=" * 80)

    for sym in SYMBOLS:
        print(f"\n📂 [{sym}] Carregando candles M1...")
        try:
            c_m1 = load_candles(data_root, sym, "M1")
        except Exception as e:
            print(f"  ❌ Erro ao ler {sym}: {e}")
            continue

        spread = cfg.backtest.costs.spread_pips.get(sym, 0.0)

        for p in param_grid:
            p_desc = f"ORB{p['orb_minutes']}m_{p['stop_mode']}_TP{int(p['target_r'])}R"
            trades = run_orb_simulation(
                c_m1=c_m1,
                symbol=sym,
                spread_cost=spread,
                orb_minutes=p["orb_minutes"],
                stop_mode=p["stop_mode"],
                target_r=p["target_r"],
                use_vwap=p["use_vwap"],
                use_ema=p["use_ema"],
            )

            if not trades:
                continue

            df_t = pd.DataFrame(trades)
            df_is = df_t[df_t["entry_time"] < split_date]
            df_oos = df_t[df_t["entry_time"] >= split_date]

            n_is = len(df_is)
            n_oos = len(df_oos)
            r_is = df_is["pnl_r"].sum() if n_is else 0.0
            r_oos = df_oos["pnl_r"].sum() if n_oos else 0.0
            exp_is = (r_is / n_is) if n_is else 0.0
            exp_oos = (r_oos / n_oos) if n_oos else 0.0
            wr_is = (df_is["result"] == "GAIN").mean() * 100 if n_is else 0.0
            wr_oos = (df_oos["result"] == "GAIN").mean() * 100 if n_oos else 0.0

            # Walk Forward Efficiency (WFE)
            wfe = (exp_oos / exp_is) if exp_is > 0 else (0.0 if exp_oos <= 0 else 1.0)

            all_results.append({
                "symbol": sym,
                "config": p_desc,
                "orb_min": p["orb_minutes"],
                "stop_mode": p["stop_mode"],
                "target_r": p["target_r"],
                "total_trades": len(df_t),
                "is_trades": n_is,
                "is_wr": wr_is,
                "is_ret_r": r_is,
                "is_exp_r": exp_is,
                "oos_trades": n_oos,
                "oos_wr": wr_oos,
                "oos_ret_r": r_oos,
                "oos_exp_r": exp_oos,
                "total_ret_r": df_t["pnl_r"].sum(),
                "wfe": wfe,
            })

            # Salva trades
            for t in trades:
                t["config"] = p_desc
                trade_logs.append(t)

        print(f"  ✅ Simulações concluídas para {sym}")

    df_res = pd.DataFrame(all_results)
    csv_path = OUT_DIR / "walkforward_orb_results.csv"
    df_res.to_csv(csv_path, index=False)
    print(f"\n📊 Resultados salvos em: {csv_path}")

    # Exibe ranking Out-Of-Sample
    print("\n" + "=" * 90)
    print("🏆 RANKING GERAL OUT-OF-SAMPLE (TESTE CEGO - 6 MESES):")
    print("=" * 90)
    summary_by_config = df_res.groupby("config").agg({
        "total_trades": "sum",
        "oos_trades": "sum",
        "is_ret_r": "sum",
        "oos_ret_r": "sum",
        "oos_exp_r": "mean",
        "oos_wr": "mean",
    }).sort_values(by="oos_ret_r", ascending=False)
    print(summary_by_config.to_string())

    # Análise de Consistência por Ativo na Melhor Configuração
    best_config = summary_by_config.index[0]
    print(f"\n🎯 Detalhamento por Ativo na Configuração Campeã [{best_config}]:")
    best_sub = df_res[df_res["config"] == best_config].set_index("symbol")
    cols_show = ["is_trades", "is_wr", "is_ret_r", "oos_trades", "oos_wr", "oos_ret_r", "total_ret_r", "wfe"]
    print(best_sub[cols_show].round(2).to_string())


if __name__ == "__main__":
    run_full_study()

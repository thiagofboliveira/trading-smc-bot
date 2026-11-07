"""
Geração de Análise Mensal Consolidada das 5 Estratégias Vencedoras (1 Ano Completo de Dados Reais)
Período: 01/11/2025 a 04/11/2026 (7 Ativos: NAS100, XAUUSD, DAX40, BRENT, EURUSD, GBPUSD, USDJPY)
"""

import sys
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

SPREADS = {
    "BRENT": 0.04,
    "XAUUSD": 0.30,
    "NAS100": 1.50,
    "DAX40": 1.50,
    "EURUSD": 0.00015,
    "GBPUSD": 0.00020,
    "USDJPY": 0.018
}

SYMBOLS = ["NAS100", "XAUUSD", "DAX40", "BRENT", "EURUSD", "GBPUSD", "USDJPY"]

def load_all_candles():
    raw_m1 = {}
    for sym in SYMBOLS:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if not isinstance(df.index, pd.DatetimeIndex):
            col = "time" if "time" in df.columns else "timestamp"
            df[col] = pd.to_datetime(df[col])
            df.set_index(col, inplace=True)
        raw_m1[sym] = df
    return raw_m1

def run_simulation(
    raw_m1: dict[str, pd.DataFrame],
    tf: str = "5min",
    fibo_entry: float = 0.705,
    fibo_stop: float = 0.790,
    target_mode: str = "0_percent",
    target_r: float = 3.0,
    trailing_ma: str | None = None,
    be_trigger_r: float | None = None,
    be_lock_r: float = 0.0,
    k: int = 3
) -> list[dict[str, Any]]:
    all_trades = []

    for sym in SYMBOLS:
        if sym not in raw_m1:
            continue
        df_m1 = raw_m1[sym]
        spread = SPREADS[sym]

        # Resample
        rule = "15min" if tf in ("M15", "15min", "15m") else "5min"
        df = df_m1.resample(rule).agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        }).dropna()

        if trailing_ma == "ema8":
            df["ema8"] = df["close"].ewm(span=8, adjust=False).mean()

        highs = df["high"].values
        lows = df["low"].values
        closes = df["close"].values
        timestamps = df.index
        ema8s = df["ema8"].values if trailing_ma == "ema8" else None
        n = len(df)

        swing_highs = np.zeros(n, dtype=bool)
        swing_lows = np.zeros(n, dtype=bool)

        for i in range(k, n - k):
            if highs[i] == max(highs[i - k : i + k + 1]):
                swing_highs[i] = True
            if lows[i] == min(lows[i - k : i + k + 1]):
                swing_lows[i] = True

        last_sh = last_sl = None
        last_sh_idx = last_sl_idx = None

        in_pos = False
        pos_dir = 0
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0
        risk = 0.0
        entry_idx = 0
        be_activated = False
        active_leg = None

        for i in range(k + 1, n - 1):
            chk = i - k
            if swing_highs[chk]: last_sh, last_sh_idx = highs[chk], chk
            if swing_lows[chk]: last_sl, last_sl_idx = lows[chk], chk

            if in_pos:
                c_high = highs[i]
                c_low = lows[i]
                c_close = closes[i]

                # 1. Profit Lock / Breakeven trigger
                if be_trigger_r is not None and not be_activated:
                    if pos_dir == 1:
                        fav = c_high - entry_price
                        if fav >= (risk * be_trigger_r):
                            sl_price = entry_price + (risk * be_lock_r)
                            be_activated = True
                    else:
                        fav = entry_price - c_low
                        if fav >= (risk * be_trigger_r):
                            sl_price = entry_price - (risk * be_lock_r)
                            be_activated = True

                # 2. Trailing MA exit
                exit_trailing = False
                trailing_exit_price = 0.0
                if trailing_ma == "ema8" and i > entry_idx:
                    curr_ema = ema8s[i]
                    if pos_dir == 1 and c_close < curr_ema:
                        exit_trailing = True
                        trailing_exit_price = c_close
                    elif pos_dir == -1 and c_close > curr_ema:
                        exit_trailing = True
                        trailing_exit_price = c_close

                # 3. Position outcome
                if pos_dir == 1:
                    hit_sl = c_low <= sl_price
                    hit_tp = c_high >= tp_price

                    if hit_sl and hit_tp:
                        r_res = -1.0 if not be_activated else be_lock_r
                        all_trades.append({
                            "symbol": sym, "time": timestamps[entry_idx], "r": r_res,
                            "win": r_res > 0, "be_act": be_activated
                        })
                        in_pos = False; active_leg = None
                    elif hit_sl:
                        r_res = -1.0 if not be_activated else be_lock_r
                        all_trades.append({
                            "symbol": sym, "time": timestamps[entry_idx], "r": r_res,
                            "win": r_res > 0, "be_act": be_activated
                        })
                        in_pos = False; active_leg = None
                    elif exit_trailing:
                        r_res = (trailing_exit_price - entry_price) / risk
                        all_trades.append({
                            "symbol": sym, "time": timestamps[entry_idx], "r": r_res,
                            "win": r_res > 0, "be_act": be_activated
                        })
                        in_pos = False; active_leg = None
                    elif hit_tp:
                        r_res = (tp_price - entry_price) / risk
                        all_trades.append({
                            "symbol": sym, "time": timestamps[entry_idx], "r": r_res,
                            "win": True, "be_act": be_activated
                        })
                        in_pos = False; active_leg = None
                else:
                    hit_sl = c_high >= sl_price
                    hit_tp = c_low <= tp_price

                    if hit_sl and hit_tp:
                        r_res = -1.0 if not be_activated else be_lock_r
                        all_trades.append({
                            "symbol": sym, "time": timestamps[entry_idx], "r": r_res,
                            "win": r_res > 0, "be_act": be_activated
                        })
                        in_pos = False; active_leg = None
                    elif hit_sl:
                        r_res = -1.0 if not be_activated else be_lock_r
                        all_trades.append({
                            "symbol": sym, "time": timestamps[entry_idx], "r": r_res,
                            "win": r_res > 0, "be_act": be_activated
                        })
                        in_pos = False; active_leg = None
                    elif exit_trailing:
                        r_res = (entry_price - trailing_exit_price) / risk
                        all_trades.append({
                            "symbol": sym, "time": timestamps[entry_idx], "r": r_res,
                            "win": r_res > 0, "be_act": be_activated
                        })
                        in_pos = False; active_leg = None
                    elif hit_tp:
                        r_res = (entry_price - tp_price) / risk
                        all_trades.append({
                            "symbol": sym, "time": timestamps[entry_idx], "r": r_res,
                            "win": True, "be_act": be_activated
                        })
                        in_pos = False; active_leg = None

                continue

            # Signal search
            if last_sh is not None and last_sl is not None:
                # Bullish BOS
                if last_sh_idx > last_sl_idx and closes[i] > last_sh:
                    leg_low = last_sl
                    leg_high = highs[i]
                    diff = leg_high - leg_low
                    if diff >= 10.0 * spread:
                        active_leg = {"dir": 1, "low": leg_low, "high": leg_high, "diff": diff}

                # Bearish BOS
                elif last_sl_idx > last_sh_idx and closes[i] < last_sl:
                    leg_high = last_sh
                    leg_low = lows[i]
                    diff = leg_high - leg_low
                    if diff >= 10.0 * spread:
                        active_leg = {"dir": -1, "low": leg_low, "high": leg_high, "diff": diff}

            if active_leg is not None:
                ldir = active_leg["dir"]
                ldiff = active_leg["diff"]
                lhigh = active_leg["high"]
                llow = active_leg["low"]

                if ldir == 1:
                    f_ent = lhigh - (ldiff * fibo_entry)
                    f_stp = lhigh - (ldiff * fibo_stop)
                    r_pts = f_ent - f_stp
                    if r_pts > 0 and lows[i] <= f_ent <= highs[i]:
                        in_pos = True
                        pos_dir = 1
                        entry_price = f_ent + (spread / 2.0)
                        sl_price = f_stp - (spread / 2.0)
                        risk = entry_price - sl_price
                        if target_mode == "0_percent":
                            tp_price = lhigh
                        elif target_mode == "proj_618":
                            tp_price = lhigh + (ldiff * 0.618)
                        else:
                            tp_price = entry_price + (risk * target_r)
                        entry_idx = i
                        be_activated = False
                else:
                    f_ent = llow + (ldiff * fibo_entry)
                    f_stp = llow + (ldiff * fibo_stop)
                    r_pts = f_stp - f_ent
                    if r_pts > 0 and lows[i] <= f_ent <= highs[i]:
                        in_pos = True
                        pos_dir = -1
                        entry_price = f_ent - (spread / 2.0)
                        sl_price = f_stp + (spread / 2.0)
                        risk = sl_price - entry_price
                        if target_mode == "0_percent":
                            tp_price = llow
                        elif target_mode == "proj_618":
                            tp_price = llow - (ldiff * 0.618)
                        else:
                            tp_price = entry_price - (risk * target_r)
                        entry_idx = i
                        be_activated = False

    return all_trades

def analyze_monthly(trades: list[dict[str, Any]]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    df = pd.DataFrame(trades)
    df["month"] = pd.to_datetime(df["time"]).dt.to_period("M").astype(str)
    
    monthly_stats = []
    grouped = df.groupby("month")
    
    for m, g in grouped:
        total_r = g["r"].sum()
        trades_count = len(g)
        wins = g["win"].sum()
        wr = (wins / trades_count) * 100 if trades_count > 0 else 0.0
        gross_profit = g[g["r"] > 0]["r"].sum()
        gross_loss = abs(g[g["r"] < 0]["r"].sum())
        pf = gross_profit / gross_loss if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
        
        # Max drawdown in month
        equity = g["r"].cumsum()
        peak = equity.cummax()
        dd = (equity - peak).min()
        
        monthly_stats.append({
            "Mês": m,
            "Trades": trades_count,
            "Taxa Acerto %": round(wr, 1),
            "Lucro (R)": round(total_r, 1),
            "Profit Factor": round(pf, 2),
            "Max DD (R)": round(dd, 1)
        })
    return pd.DataFrame(monthly_stats)

def main():
    print("⏳ Carregando dados M1 dos 7 ativos...")
    raw_m1 = load_all_candles()
    print("✅ Dados carregados com sucesso!\n")

    strategies = {
        "smc_fibo_trailing_44pct_2500R_2.23pf_32dd": {
            "name": "1. Campeã Suprema (Trailing MME 8)",
            "tf": "5min", "fibo_entry": 0.705, "fibo_stop": 0.790,
            "target_mode": "0_percent", "trailing_ma": "ema8",
            "be_trigger_r": None, "be_lock_r": 0.0
        },
        "smc_fibo_blindado_50pct_2278R_2.24pf_30dd": {
            "name": "2. Segurança Psicológica (Blindado Trava 2:1)",
            "tf": "5min", "fibo_entry": 0.705, "fibo_stop": 0.790,
            "target_mode": "0_percent", "trailing_ma": "ema8",
            "be_trigger_r": 2.0, "be_lock_r": 1.0
        },
        "smc_fibo_agressivo_25pct_2101R_1.89pf_43dd": {
            "name": "3. Perfil Agressivo (Alvo Topo/Fundo)",
            "tf": "5min", "fibo_entry": 0.705, "fibo_stop": 0.790,
            "target_mode": "0_percent", "trailing_ma": None,
            "be_trigger_r": None, "be_lock_r": 0.0
        },
        "smc_fibo_equilibrado_35pct_1469R_1.64pf_56dd": {
            "name": "4. Perfil Equilibrado (65% Alvo 3R)",
            "tf": "5min", "fibo_entry": 0.650, "fibo_stop": 0.790,
            "target_mode": "3R", "target_r": 3.0, "trailing_ma": None,
            "be_trigger_r": None, "be_lock_r": 0.0
        },
        "smc_fibo_conservador_27pct_1233R_2.23pf_25dd": {
            "name": "5. Perfil Conservador (M15 Topo/Fundo)",
            "tf": "15min", "fibo_entry": 0.705, "fibo_stop": 0.790,
            "target_mode": "0_percent", "trailing_ma": None,
            "be_trigger_r": None, "be_lock_r": 0.0
        }
    }

    results_by_strat = {}
    monthly_dfs = {}

    for sid, sinfo in strategies.items():
        print(f"▶️ Simulando: {sinfo['name']}...")
        trades = run_simulation(
            raw_m1,
            tf=sinfo["tf"],
            fibo_entry=sinfo["fibo_entry"],
            fibo_stop=sinfo["fibo_stop"],
            target_mode=sinfo["target_mode"],
            target_r=sinfo.get("target_r", 3.0),
            trailing_ma=sinfo["trailing_ma"],
            be_trigger_r=sinfo["be_trigger_r"],
            be_lock_r=sinfo["be_lock_r"]
        )
        m_df = analyze_monthly(trades)
        monthly_dfs[sid] = m_df
        results_by_strat[sid] = trades
        total_r = sum(t["r"] for t in trades)
        wr = (sum(1 for t in trades if t["win"]) / len(trades)) * 100 if trades else 0
        print(f"   Total: {len(trades)} trades | WR: {wr:.1f}% | Retorno: +{total_r:.1f} R")

    # Criar tabela consolidada de Retorno Mensal (R) lado a lado
    all_months = sorted(list(set(m for m_df in monthly_dfs.values() for m in m_df["Mês"])))
    
    summary_r_data = {"Mês": all_months}
    for sid, sinfo in strategies.items():
        m_df = monthly_dfs[sid].set_index("Mês")
        col_name = sinfo["name"].split("(")[0].strip()
        summary_r_data[col_name] = [
            m_df.loc[m, "Lucro (R)"] if m in m_df.index else 0.0 for m in all_months
        ]
    
    df_summary_r = pd.DataFrame(summary_r_data)
    print("\n" + "=" * 90)
    print("📊 COMPARATIVO DE RETORNO MENSAL EM R (TODAS AS 5 ESTRATÉGIAS)")
    print("=" * 90)
    print(df_summary_r.to_string(index=False))

    # Salvar em CSV para consulta detalhada
    Path("reports").mkdir(parents=True, exist_ok=True)
    for sid, m_df in monthly_dfs.items():
        m_df.to_csv(f"reports/monthly_{sid}.csv", index=False)
        print(f"\n📈 DETALHAMENTO MENSAL — {sid}:")
        print(m_df.to_string(index=False))
    df_summary_r.to_csv("reports/monthly_comparison_all_strategies.csv", index=False)
    print("\n💾 Relatórios salvos com sucesso em reports/monthly_*.csv!")

if __name__ == "__main__":
    main()

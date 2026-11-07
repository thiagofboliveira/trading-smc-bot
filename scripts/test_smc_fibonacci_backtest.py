"""
Teste Quantitativo: SMC com Fibonacci OTE (61.8% -> Stop 79% + Rejeição no 79% -> Stop 100%)
Período: 1 Ano Completo (Dados M1 Dukascopy resampleados para M5)
Compara 3 Alvos:
1. Alvo Fixo 3R (1:3)
2. Alvo Estrutural no Topo/Fundo prévio (0% Fibo)
3. Alvo na Projeção de 61.8% da correção além do topo
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path

SPREADS = {
    "BRENT": 0.04,     # 4 cents
    "XAUUSD": 0.30,    # 30 cents ($0.30)
    "NAS100": 1.50,    # 1.5 pts
    "DAX40": 1.50,     # 1.5 pts
    "EURUSD": 0.00015, # 1.5 pips
    "GBPUSD": 0.00020, # 2.0 pips
    "USDJPY": 0.018    # 1.8 pips
}

def load_and_resample_m5(symbol: str) -> pd.DataFrame:
    path = Path(f"data/{symbol}_M1_dukascopy.parquet")
    df_m1 = pd.read_parquet(path)
    if not isinstance(df_m1.index, pd.DatetimeIndex):
        if "time" in df_m1.columns:
            df_m1["time"] = pd.to_datetime(df_m1["time"])
            df_m1.set_index("time", inplace=True)
        elif "timestamp" in df_m1.columns:
            df_m1["timestamp"] = pd.to_datetime(df_m1["timestamp"])
            df_m1.set_index("timestamp", inplace=True)
            
    df_m5 = df_m1.resample("5min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }).dropna()
    return df_m5

def simulate_fibo_ote(symbol: str, target_mode: str = "3R", timeframe: str = "5min"):
    """
    target_mode: '3R', '0_percent', 'proj_618'
    """
    df = load_and_resample_m5(symbol)
    spread = SPREADS[symbol]
    
    # Detecção de Swings via fractais (janela de 5 candles: 2 antes, 1 centro, 2 depois)
    n = len(df)
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    opens = df["open"].values
    timestamps = df.index
    
    # Identificar picos e vales
    swing_highs = np.zeros(n, dtype=bool)
    swing_lows = np.zeros(n, dtype=bool)
    
    k = 3 # raio do swing fractal
    for i in range(k, n - k):
        if highs[i] == max(highs[i-k:i+k+1]):
            swing_highs[i] = True
        if lows[i] == min(lows[i-k:i+k+1]):
            swing_lows[i] = True
            
    trades = []
    
    # Estado da simulação
    # Vamos rastrear pernas de BOS (Break of Structure)
    last_sh_price = None
    last_sh_idx = None
    last_sl_price = None
    last_sl_idx = None
    
    # Posição ativa
    in_pos = False
    pos_type = 0 # 1 long, -1 short
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    entry_idx = 0
    risk = 0.0
    trade_stage = 1 # 1: entrada 61.8, 2: reentrada no 79
    
    # Estrutura ativa aguardando retração
    active_leg = None # dict com dados da perna
    
    for i in range(k + 1, n - 1):
        # 1. Atualizar swings conhecidos (com delay k para evitar lookahead)
        idx_to_check = i - k
        if swing_highs[idx_to_check]:
            last_sh_price = highs[idx_to_check]
            last_sh_idx = idx_to_check
        if swing_lows[idx_to_check]:
            last_sl_price = lows[idx_to_check]
            last_sl_idx = idx_to_check
            
        # 2. Gerenciar posição aberta se houver
        if in_pos:
            c_high = highs[i]
            c_low = lows[i]
            
            if pos_type == 1: # LONG
                hit_sl = c_low <= sl_price
                hit_tp = c_high >= tp_price
                
                if hit_sl and hit_tp:
                    # Conservador: stop
                    trades.append({"symbol": symbol, "stage": trade_stage, "type": "LONG", "r": -1.0, "win": False, "entry_time": timestamps[entry_idx], "exit_time": timestamps[i]})
                    in_pos = False
                    if trade_stage == 1:
                        # Habilita monitoramento de rejeição no 79%
                        active_leg["awaiting_79_rejection"] = True
                elif hit_sl:
                    trades.append({"symbol": symbol, "stage": trade_stage, "type": "LONG", "r": -1.0, "win": False, "entry_time": timestamps[entry_idx], "exit_time": timestamps[i]})
                    in_pos = False
                    if trade_stage == 1:
                        # Foi stopado no 79%: agora monitora se haverá rejeição no 79%
                        active_leg["awaiting_79_rejection"] = True
                elif hit_tp:
                    r_mult = 3.0 if target_mode == "3R" else (tp_price - entry_price) / risk
                    trades.append({"symbol": symbol, "stage": trade_stage, "type": "LONG", "r": r_mult, "win": True, "entry_time": timestamps[entry_idx], "exit_time": timestamps[i]})
                    in_pos = False
                    active_leg = None # pernada concluída com sucesso
            else: # SHORT
                hit_sl = c_high >= sl_price
                hit_tp = c_low <= tp_price
                
                if hit_sl and hit_tp:
                    trades.append({"symbol": symbol, "stage": trade_stage, "type": "SHORT", "r": -1.0, "win": False, "entry_time": timestamps[entry_idx], "exit_time": timestamps[i]})
                    in_pos = False
                    if trade_stage == 1:
                        active_leg["awaiting_79_rejection"] = True
                elif hit_sl:
                    trades.append({"symbol": symbol, "stage": trade_stage, "type": "SHORT", "r": -1.0, "win": False, "entry_time": timestamps[entry_idx], "exit_time": timestamps[i]})
                    in_pos = False
                    if trade_stage == 1:
                        active_leg["awaiting_79_rejection"] = True
                elif hit_tp:
                    r_mult = 3.0 if target_mode == "3R" else (entry_price - tp_price) / risk
                    trades.append({"symbol": symbol, "stage": trade_stage, "type": "SHORT", "r": r_mult, "win": True, "entry_time": timestamps[entry_idx], "exit_time": timestamps[i]})
                    in_pos = False
                    active_leg = None
            continue
            
        # 3. Detectar nova perna de BOS se não temos posição e nem perna ativa válida
        # Bullish BOS: Preço rompe acima de last_sh_price
        if active_leg is None and last_sh_price is not None and last_sl_price is not None:
            if last_sh_idx > last_sl_idx: # perna de alta válida do fundo ao topo
                # Rompeu o topo anterior?
                if closes[i] > last_sh_price:
                    # Registra a perna de impulso: Low em last_sl_price, High em closes[i]
                    leg_low = last_sl_price
                    leg_high = highs[i]
                    leg_range = leg_high - leg_low
                    
                    if leg_range > spread * 10: # filtro de perna mínima
                        active_leg = {
                            "dir": 1, # Bullish
                            "low": leg_low,
                            "high": leg_high,
                            "range": leg_range,
                            "fibo_618": leg_high - 0.618 * leg_range,
                            "fibo_790": leg_high - 0.790 * leg_range,
                            "origin_100": leg_low,
                            "touched_618": False,
                            "awaiting_79_rejection": False,
                            "expired": False,
                            "candles_alive": 0
                        }
            elif last_sl_idx > last_sh_idx: # perna de baixa do topo ao fundo
                if closes[i] < last_sl_price:
                    leg_high = last_sh_price
                    leg_low = lows[i]
                    leg_range = leg_high - leg_low
                    if leg_range > spread * 10:
                        active_leg = {
                            "dir": -1, # Bearish
                            "high": leg_high,
                            "low": leg_low,
                            "range": leg_range,
                            "fibo_618": leg_low + 0.618 * leg_range,
                            "fibo_790": leg_low + 0.790 * leg_range,
                            "origin_100": leg_high,
                            "touched_618": False,
                            "awaiting_79_rejection": False,
                            "expired": False,
                            "candles_alive": 0
                        }
                        
        # 4. Avaliar gatilhos na active_leg
        if active_leg is not None:
            active_leg["candles_alive"] += 1
            # Expira perna se demorar mais de 60 candles sem ativar
            if active_leg["candles_alive"] > 60:
                active_leg = None
                continue
                
            # Se romper ainda mais o topo/fundo antes de retrair, expande a perna
            if not active_leg["touched_618"] and not active_leg["awaiting_79_rejection"]:
                if active_leg["dir"] == 1 and highs[i] > active_leg["high"]:
                    active_leg["high"] = highs[i]
                    active_leg["range"] = active_leg["high"] - active_leg["low"]
                    active_leg["fibo_618"] = active_leg["high"] - 0.618 * active_leg["range"]
                    active_leg["fibo_790"] = active_leg["high"] - 0.790 * active_leg["range"]
                elif active_leg["dir"] == -1 and lows[i] < active_leg["low"]:
                    active_leg["low"] = lows[i]
                    active_leg["range"] = active_leg["high"] - active_leg["low"]
                    active_leg["fibo_618"] = active_leg["low"] + 0.618 * active_leg["range"]
                    active_leg["fibo_790"] = active_leg["low"] + 0.790 * active_leg["range"]
                    
            # A) ENTRADA 1: Toque na retração 61.8%
            if not active_leg["touched_618"] and not active_leg["awaiting_79_rejection"]:
                if active_leg["dir"] == 1:
                    # Long: preço caiu até 61.8%
                    if lows[i] <= active_leg["fibo_618"]:
                        active_leg["touched_618"] = True
                        raw_entry = active_leg["fibo_618"]
                        raw_sl = active_leg["fibo_790"]
                        
                        entry_price = raw_entry + spread
                        sl_price = raw_sl
                        risk = entry_price - sl_price
                        
                        if risk > spread * 1.5:
                            # Define TP
                            if target_mode == "3R":
                                tp_price = entry_price + (risk * 3.0)
                            elif target_mode == "0_percent":
                                tp_price = active_leg["high"]
                            elif target_mode == "proj_618":
                                # Topo + 61.8% da correção (0.618 * range)
                                corr_size = active_leg["high"] - active_leg["fibo_618"]
                                tp_price = active_leg["high"] + (corr_size * 0.618)
                                
                            in_pos = True
                            pos_type = 1
                            trade_stage = 1
                            entry_idx = i
                            continue
                else:
                    # Short: preço subiu até 61.8%
                    if highs[i] >= active_leg["fibo_618"]:
                        active_leg["touched_618"] = True
                        raw_entry = active_leg["fibo_618"]
                        raw_sl = active_leg["fibo_790"]
                        
                        entry_price = raw_entry
                        sl_price = raw_sl + spread
                        risk = sl_price - entry_price
                        
                        if risk > spread * 1.5:
                            if target_mode == "3R":
                                tp_price = entry_price - (risk * 3.0)
                            elif target_mode == "0_percent":
                                tp_price = active_leg["low"]
                            elif target_mode == "proj_618":
                                corr_size = active_leg["fibo_618"] - active_leg["low"]
                                tp_price = active_leg["low"] - (corr_size * 0.618)
                                
                            in_pos = True
                            pos_type = -1
                            trade_stage = 1
                            entry_idx = i
                            continue
                            
            # B) ENTRADA 2: Rejeição no nível 79.0% (caso stop no 61.8%)
            elif active_leg["awaiting_79_rejection"]:
                # Se violar o 100% (origem da perna), anula a perna completamente
                if active_leg["dir"] == 1 and lows[i] <= active_leg["origin_100"]:
                    active_leg = None
                    continue
                elif active_leg["dir"] == -1 and highs[i] >= active_leg["origin_100"]:
                    active_leg = None
                    continue
                    
                # Rejeição de Alta no 79%:
                # Candle tocou a região de 79% (ou abaixo dela), mas fechou acima da abertura (candle verde) ou fez sombra inferior
                if active_leg["dir"] == 1:
                    # Rejeição compradora: fechamento > abertura e fechamento > fibo_790
                    if closes[i] > opens[i] and closes[i] > active_leg["fibo_790"]:
                        raw_entry = closes[i]
                        raw_sl = min(lows[i], active_leg["origin_100"]) # Stop no fundo do 100%
                        
                        entry_price = raw_entry + spread
                        sl_price = raw_sl
                        risk = entry_price - sl_price
                        
                        if risk > spread * 1.5:
                            if target_mode == "3R":
                                tp_price = entry_price + (risk * 3.0)
                            elif target_mode == "0_percent":
                                tp_price = active_leg["high"]
                            elif target_mode == "proj_618":
                                corr_size = active_leg["high"] - lows[i]
                                tp_price = active_leg["high"] + (corr_size * 0.618)
                                
                            in_pos = True
                            pos_type = 1
                            trade_stage = 2
                            entry_idx = i
                            active_leg["awaiting_79_rejection"] = False # já entrou
                            continue
                else:
                    # Rejeição vendedora: fechamento < abertura e fechamento < fibo_790
                    if closes[i] < opens[i] and closes[i] < active_leg["fibo_790"]:
                        raw_entry = closes[i]
                        raw_sl = max(highs[i], active_leg["origin_100"])
                        
                        entry_price = raw_entry
                        sl_price = raw_sl + spread
                        risk = sl_price - entry_price
                        
                        if risk > spread * 1.5:
                            if target_mode == "3R":
                                tp_price = entry_price - (risk * 3.0)
                            elif target_mode == "0_percent":
                                tp_price = active_leg["low"]
                            elif target_mode == "proj_618":
                                corr_size = highs[i] - active_leg["low"]
                                tp_price = active_leg["low"] - (corr_size * 0.618)
                                
                            in_pos = True
                            pos_type = -1
                            trade_stage = 2
                            entry_idx = i
                            active_leg["awaiting_79_rejection"] = False
                            continue
                            
    return trades

def main():
    symbols = ["BRENT", "XAUUSD", "NAS100", "DAX40", "EURUSD", "GBPUSD", "USDJPY"]
    modes = ["3R", "0_percent", "proj_618"]
    
    print("================================================================================")
    print("🚀 BACKTEST QUANTITATIVO: SMC FIBONACCI OTE (61.8% -> 79% -> 100%)")
    print("Período: 1 Ano Completo (01/11/2025 a 04/11/2026)")
    print("Modos de Alvo: [3R], [0% Topo/Fundo], [Projeção 61.8% da Correção]")
    print("================================================================================\n")
    
    all_summary = []
    
    for mode in modes:
        print(f"\n👉 TESTANDO ALVO: [{mode}]")
        mode_trades = []
        for sym in symbols:
            try:
                t = simulate_fibo_ote(sym, target_mode=mode)
                if not t:
                    continue
                df_t = pd.DataFrame(t)
                total = len(df_t)
                wins = (df_t["win"] == True).sum()
                wr = (wins / total) * 100
                total_r = df_t["r"].sum()
                exp_r = total_r / total
                
                # Split IS / OOS
                df_t["entry_time"] = pd.to_datetime(df_t["entry_time"])
                split_date = pd.Timestamp("2026-05-01", tz="UTC")
                is_df = df_t[df_t["entry_time"] < split_date]
                oos_df = df_t[df_t["entry_time"] >= split_date]
                
                is_r = is_df["r"].sum() if len(is_df) > 0 else 0
                oos_r = oos_df["r"].sum() if len(oos_df) > 0 else 0
                
                # Desempenho por Estágio (Estágio 1 = 61.8%, Estágio 2 = Rejeição 79%)
                s1_trades = df_t[df_t["stage"] == 1]
                s2_trades = df_t[df_t["stage"] == 2]
                s1_r = s1_trades["r"].sum() if len(s1_trades) > 0 else 0
                s2_r = s2_trades["r"].sum() if len(s2_trades) > 0 else 0
                
                all_summary.append({
                    "mode": mode,
                    "symbol": sym,
                    "total_trades": total,
                    "win_rate": wr,
                    "total_r": total_r,
                    "exp_r": exp_r,
                    "is_r": is_r,
                    "oos_r": oos_r,
                    "s1_trades": len(s1_trades),
                    "s1_r": s1_r,
                    "s2_trades": len(s2_trades),
                    "s2_r": s2_r
                })
                
                print(f"  [{sym:6s}] Trades: {total:4d} | WR: {wr:4.1f}% | Total: {total_r:+6.1f}R | IS: {is_r:+5.1f}R | OOS: {oos_r:+5.1f}R | S1 (61.8%): {s1_r:+5.1f}R | S2 (79%): {s2_r:+5.1f}R")
            except Exception as e:
                print(f"  Erro em {sym}: {e}")
                
    df_res = pd.DataFrame(all_summary)
    out_path = Path("out/fibo_analysis/smc_fibo_ote_results.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_res.to_csv(out_path, index=False)
    
    print("\n" + "="*80)
    print("🏆 RANKING GERAL POR MODO DE ALVO (Soma dos 7 Ativos no Ano):")
    print("="*80)
    grouped = df_res.groupby("mode").agg({
        "total_trades": "sum",
        "total_r": "sum",
        "is_r": "sum",
        "oos_r": "sum"
    }).sort_values(by="oos_r", ascending=False)
    print(grouped.to_string())

if __name__ == "__main__":
    main()

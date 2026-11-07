"""
Teste Quantitativo: Pivô na Média no M2 (Alvo 1:1) com EMA20 + SMA200 alinhadas
Período: 1 Ano Completo (Dados M1 Dukascopy resampleados para M2)
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path

# Definição de spreads realistas por ativo (em preço)
SPREADS = {
    "BRENT": 0.04,     # 4 cents
    "XAUUSD": 0.30,    # 30 cents ($0.30)
    "NAS100": 1.50,    # 1.5 pts
    "DAX40": 1.50,     # 1.5 pts
    "EURUSD": 0.00015, # 1.5 pips
    "GBPUSD": 0.00020, # 2.0 pips
    "USDJPY": 0.018    # 1.8 pips
}

# Janelas de maior volatilidade (em UTC)
VOLATILITY_HOURS = {
    "BRENT": (8, 17),   # Londres / NY
    "XAUUSD": (8, 17),  # Londres / NY
    "NAS100": (13, 20), # NY Cash
    "DAX40": (7, 16),   # Londres / Frankfurt
    "EURUSD": (7, 16),  # Londres / NY overlap
    "GBPUSD": (7, 16),  # Londres / NY overlap
    "USDJPY": (0, 16)   # Tóquio + Londres + NY
}

def load_and_resample_m2(symbol: str) -> pd.DataFrame:
    path = Path(f"data/{symbol}_M1_dukascopy.parquet")
    if not path.exists():
        raise FileNotFoundError(f"{path} not found")
    
    df_m1 = pd.read_parquet(path)
    if not isinstance(df_m1.index, pd.DatetimeIndex):
        if "time" in df_m1.columns:
            df_m1["time"] = pd.to_datetime(df_m1["time"])
            df_m1.set_index("time", inplace=True)
        elif "timestamp" in df_m1.columns:
            df_m1["timestamp"] = pd.to_datetime(df_m1["timestamp"])
            df_m1.set_index("timestamp", inplace=True)
            
    # Resample para M2
    df_m2 = df_m1.resample("2min").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    }).dropna()
    
    return df_m2

def run_pivot_simulation(symbol: str, target_ratio: float = 1.0, min_stop_atr_mult: float = 0.5):
    df = load_and_resample_m2(symbol)
    spread = SPREADS[symbol]
    start_hour, end_hour = VOLATILITY_HOURS[symbol]
    
    # Indicadores
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["sma200"] = df["close"].rolling(window=200).mean()
    
    # ATR de 14 períodos para filtro de stop mínimo
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    
    df = df.dropna().copy()
    
    timestamps = df.index
    opens = df["open"].values
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    ema20s = df["ema20"].values
    sma200s = df["sma200"].values
    atrs = df["atr"].values
    hours = timestamps.hour
    
    trades = []
    in_pos = False
    pos_type = 0  # 1 long, -1 short
    entry_price = 0.0
    sl_price = 0.0
    tp_price = 0.0
    entry_idx = 0
    risk = 0.0
    
    n = len(df)
    
    for i in range(200, n - 1):
        if in_pos:
            # Checar saída no candle i
            c_high = highs[i]
            c_low = lows[i]
            
            if pos_type == 1:
                # Long
                hit_sl = c_low <= sl_price
                hit_tp = c_high >= tp_price
                if hit_sl and hit_tp:
                    # Se ambos ocorreram no mesmo candle, assume stop por conservadorismo
                    trades.append({"symbol": symbol, "type": "LONG", "entry_time": timestamps[entry_idx], "exit_time": timestamps[i], "r": -1.0, "win": False})
                    in_pos = False
                elif hit_sl:
                    trades.append({"symbol": symbol, "type": "LONG", "entry_time": timestamps[entry_idx], "exit_time": timestamps[i], "r": -1.0, "win": False})
                    in_pos = False
                elif hit_tp:
                    trades.append({"symbol": symbol, "type": "LONG", "entry_time": timestamps[entry_idx], "exit_time": timestamps[i], "r": target_ratio, "win": True})
                    in_pos = False
            else:
                # Short
                hit_sl = c_high >= sl_price
                hit_tp = c_low <= tp_price
                if hit_sl and hit_tp:
                    trades.append({"symbol": symbol, "type": "SHORT", "entry_time": timestamps[entry_idx], "exit_time": timestamps[i], "r": -1.0, "win": False})
                    in_pos = False
                elif hit_sl:
                    trades.append({"symbol": symbol, "type": "SHORT", "entry_time": timestamps[entry_idx], "exit_time": timestamps[i], "r": -1.0, "win": False})
                    in_pos = False
                elif hit_tp:
                    trades.append({"symbol": symbol, "type": "SHORT", "entry_time": timestamps[entry_idx], "exit_time": timestamps[i], "r": target_ratio, "win": True})
                    in_pos = False
            continue
            
        # Não estamos posicionados: avaliar gatilho de pivô na média
        h = hours[i]
        if not (start_hour <= h < end_hour):
            continue
            
        # Condição de Tendência Alinhada
        # Alta: EMA20 > SMA200 e Close > SMA200
        # Baixa: EMA20 < SMA200 e Close < SMA200
        is_bull = (ema20s[i] > sma200s[i]) and (closes[i] > sma200s[i])
        is_bear = (ema20s[i] < sma200s[i]) and (closes[i] < sma200s[i])
        
        # Padrão de Pivô de Alta na Média:
        # Candle anterior fez pullback e tocou na EMA20 (low <= ema20), mas fechou acima ou perto
        # E candle atual (ou anterior) rompe para cima
        if is_bull:
            # Pullback na média: candle i-1 tocou a EMA20 (low[i-1] <= ema20s[i-1] e high[i-1] >= ema20s[i-1])
            # E candle i rompe a máxima do candle i-1
            if lows[i-1] <= ema20s[i-1] and closes[i-1] >= lows[i-1]:
                if highs[i] > highs[i-1]:
                    # Entrada na superação da máxima do candle de pullback
                    raw_entry = highs[i-1]
                    raw_sl = min(lows[i-1], lows[i])
                    risk_pts = raw_entry - raw_sl
                    
                    # Filtro de stop mínimo para evitar stops microscópicos com spread fatal
                    if risk_pts >= (atrs[i] * min_stop_atr_mult) and risk_pts > (spread * 2):
                        entry_price = raw_entry + spread  # compra paga ask (+spread)
                        sl_price = raw_sl
                        risk = entry_price - sl_price
                        tp_price = entry_price + (risk * target_ratio)
                        in_pos = True
                        pos_type = 1
                        entry_idx = i
                        continue
                        
        elif is_bear:
            # Pullback na média: candle i-1 tocou a EMA20 vindo de baixo (high[i-1] >= ema20s[i-1])
            if highs[i-1] >= ema20s[i-1] and closes[i-1] <= highs[i-1]:
                if lows[i] < lows[i-1]:
                    # Venda na perda da mínima do candle de pullback
                    raw_entry = lows[i-1]
                    raw_sl = max(highs[i-1], highs[i])
                    risk_pts = raw_sl - raw_entry
                    
                    if risk_pts >= (atrs[i] * min_stop_atr_mult) and risk_pts > (spread * 2):
                        entry_price = raw_entry  # venda executa no bid
                        sl_price = raw_sl + spread  # recompra paga ask
                        risk = sl_price - entry_price
                        tp_price = entry_price - (risk * target_ratio)
                        in_pos = True
                        pos_type = -1
                        entry_idx = i
                        continue
                        
    return trades

def main():
    symbols = ["BRENT", "XAUUSD", "NAS100", "DAX40", "EURUSD", "GBPUSD", "USDJPY"]
    all_results = []
    
    print("=================================================================")
    print("BACKTEST QUANTITATIVO: PIVÔ NA MÉDIA (M2, 1:1, EMA20 + SMA200)")
    print("Período: 1 Ano Real (Dukascopy)")
    print("=================================================================\n")
    
    for sym in symbols:
        try:
            trades = run_pivot_simulation(sym, target_ratio=1.0, min_stop_atr_mult=0.4)
            if not trades:
                print(f"[{sym}] Nenhum trade gerado.")
                continue
                
            df_trades = pd.DataFrame(trades)
            total = len(df_trades)
            wins = (df_trades["win"] == True).sum()
            losses = total - wins
            wr = (wins / total) * 100
            total_r = df_trades["r"].sum()
            exp_r = total_r / total
            
            # Divide em In-Sample e Out-of-Sample
            df_trades["entry_time"] = pd.to_datetime(df_trades["entry_time"])
            split_date = pd.Timestamp("2026-05-01", tz="UTC")
            is_trades = df_trades[df_trades["entry_time"] < split_date]
            oos_trades = df_trades[df_trades["entry_time"] >= split_date]
            
            is_r = is_trades["r"].sum() if len(is_trades) > 0 else 0
            is_wr = (is_trades["win"].sum() / len(is_trades) * 100) if len(is_trades) > 0 else 0
            
            oos_r = oos_trades["r"].sum() if len(oos_trades) > 0 else 0
            oos_wr = (oos_trades["win"].sum() / len(oos_trades) * 100) if len(oos_trades) > 0 else 0
            
            print(f"📊 [{sym:6s}] Trades: {total:4d} | Win Rate: {wr:5.1f}% | Total: {total_r:6.1f}R | Exp: {exp_r:+.3f}R | IS: {is_r:+.1f}R | OOS: {oos_r:+.1f}R")
            
            all_results.append({
                "symbol": sym,
                "total_trades": total,
                "win_rate": wr,
                "total_r": total_r,
                "exp_r": exp_r,
                "is_trades": len(is_trades),
                "is_wr": is_wr,
                "is_r": is_r,
                "oos_trades": len(oos_trades),
                "oos_wr": oos_wr,
                "oos_r": oos_r
            })
        except Exception as e:
            print(f"Erro em {sym}: {e}")
            
    df_res = pd.DataFrame(all_results)
    out_path = Path("out/pivot_analysis/m2_pivot_1x1_results.csv")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df_res.to_csv(out_path, index=False)
    print(f"\nResultados salvos em: {out_path}")
    print("\nRESUMO DO PORTFÓLIO:")
    print(f"Total Trades: {df_res['total_trades'].sum()}")
    print(f"Total PnL 12 Meses: {df_res['total_r'].sum():.1f} R")
    print(f"PnL In-Sample: {df_res['is_r'].sum():.1f} R")
    print(f"PnL Out-of-Sample: {df_res['oos_r'].sum():.1f} R")

if __name__ == "__main__":
    main()

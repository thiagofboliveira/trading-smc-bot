"""Download 1 ano completo de dados M1 para todos os 7 ativos institucionais."""
import datetime
import sys
import time
from pathlib import Path
import pandas as pd
from smc_trader.config import load_config
from smc_trader.data.dukascopy_source import fetch_m1
from smc_trader.data.store import save_m1

cfg = load_config(Path("config/default.yaml"))

SYMBOLS_MAP = {
    "BRENT": "E_Brent",
    "XAUUSD": "XAU/USD",
    "NAS100": "E_NQ-100",
    "DAX40": "DEU.IDX/EUR",
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
}

START_DATE = datetime.datetime(2025, 11, 1, tzinfo=datetime.timezone.utc)
END_DATE = datetime.datetime(2026, 11, 4, tzinfo=datetime.timezone.utc)

def _next_month(dt: datetime.datetime) -> datetime.datetime:
    year = dt.year + 1 if dt.month == 12 else dt.year
    month = 1 if dt.month == 12 else dt.month + 1
    return dt.replace(year=year, month=month, day=1)

def fetch_symbol_year(sym: str, inst: str):
    print(f"\n{'='*60}")
    print(f"📥 INICIANDO DOWNLOAD ANUAL: {sym} ({inst})")
    print(f"Período: {START_DATE.date()} até {END_DATE.date()}")
    print(f"{'='*60}")
    
    cur_start = START_DATE
    total_new = 0
    
    while cur_start < END_DATE:
        cur_end = min(_next_month(cur_start), END_DATE)
        m_label = cur_start.strftime("%Y-%m")
        print(f"  ⏳ Baixando {sym} [{m_label}]...", end=" ", flush=True)
        
        success = False
        for attempt in range(3):
            try:
                df = fetch_m1(inst, cur_start, cur_end, "bid")
                if not df.empty:
                    save_m1(Path("data"), sym, df, source="dukascopy")
                    print(f"✅ {len(df):,} candles salvos", flush=True)
                    total_new += len(df)
                else:
                    print(f"⚠️ vazio", flush=True)
                success = True
                break
            except Exception as e:
                print(f"[tentativa {attempt+1} falhou: {e}]", end=" ", flush=True)
                time.sleep(2)
        if not success:
            print(f"❌ Falha no mês {m_label} após 3 tentativas", flush=True)
        
        cur_start = cur_end
        time.sleep(0.5)
        
    print(f"✨ Concluído download de {sym}! Total processado no lote.")

if __name__ == "__main__":
    t0 = time.time()
    target_syms = sys.argv[1:] if len(sys.argv) > 1 else list(SYMBOLS_MAP.keys())
    print(f"Ativos na fila: {target_syms}")
    for sym in target_syms:
        inst = SYMBOLS_MAP.get(sym)
        if not inst:
            print(f"Símbolo desconhecido: {sym}")
            continue
        fetch_symbol_year(sym, inst)
    print(f"\n🎉 Todos os downloads finalizados em {(time.time() - t0)/60:.1f} minutos!")

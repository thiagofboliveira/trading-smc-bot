"""Download inteligente dos meses faltantes para completar 2 anos de dados nos 7 ativos."""
import datetime
import socket
import sys
import time
from pathlib import Path
import pandas as pd

socket.setdefaulttimeout(15.0)

from smc_trader.config import load_config
from smc_trader.data.dukascopy_source import fetch_m1
from smc_trader.data.store import save_m1

cfg = load_config(Path("config/default.yaml"))

SYMBOLS_MAP = {
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "BRENT": "E_Brent",
    "XAUUSD": "XAU/USD",
    "NAS100": "E_NQ-100",
    "DAX40": "DEU.IDX/EUR",
}

START_DATE = datetime.datetime(2024, 11, 1, tzinfo=datetime.timezone.utc)
END_DATE = datetime.datetime(2025, 11, 1, tzinfo=datetime.timezone.utc)

def _next_month(dt: datetime.datetime) -> datetime.datetime:
    year = dt.year + 1 if dt.month == 12 else dt.year
    month = 1 if dt.month == 12 else dt.month + 1
    return dt.replace(year=year, month=month, day=1)

def get_existing_months(sym: str) -> set[str]:
    p = Path(f"data/{sym}_dukascopy.parquet")
    if not p.exists():
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
    if not p.exists():
        return set()
    df = pd.read_parquet(p)
    return set(df.index.strftime("%Y-%m").unique())

def fetch_symbol_missing(sym: str, inst: str):
    existing = get_existing_months(sym)
    print(f"\n{'='*60}")
    print(f"📥 VERIFICANDO HISTÓRICO: {sym} ({inst})")
    print(f"Meses já presentes: {len(existing)}")
    print(f"{'='*60}")
    
    cur_start = START_DATE
    total_new = 0
    
    while cur_start < END_DATE:
        cur_end = min(_next_month(cur_start), END_DATE)
        m_label = cur_start.strftime("%Y-%m")
        
        if m_label in existing:
            print(f"  ⏭️ {sym} [{m_label}] já existe no disco, pulando...")
            cur_start = cur_end
            continue
            
        print(f"  ⏳ Baixando {sym} [{m_label}]...", end=" ", flush=True)
        
        success = False
        for attempt in range(4):
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
            print(f"❌ Falha no mês {m_label} após tentativas", flush=True)
        
        cur_start = cur_end
        time.sleep(0.3)
        
    print(f"✨ Concluído {sym}! Total novos candles salvos: {total_new:,}")

if __name__ == "__main__":
    t0 = time.time()
    target_syms = sys.argv[1:] if len(sys.argv) > 1 else list(SYMBOLS_MAP.keys())
    print(f"Ativos para verificar/baixar: {target_syms}")
    for sym in target_syms:
        inst = SYMBOLS_MAP.get(sym)
        if not inst:
            print(f"Símbolo desconhecido: {sym}")
            continue
        fetch_symbol_missing(sym, inst)
    elapsed = time.time() - t0
    print(f"\n🎉 Download de 2 anos finalizado em {elapsed/60:.1f} minutos!")

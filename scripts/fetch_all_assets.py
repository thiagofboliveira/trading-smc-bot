"""Baixa dados M1 dos ativos restantes da Dukascopy."""
import datetime
from pathlib import Path
from smc_trader.config import load_config
from smc_trader.data.dukascopy_source import fetch_m1
from smc_trader.data.store import save_m1

cfg = load_config(Path("config/default.yaml"))
start = datetime.datetime(2026, 9, 15, tzinfo=datetime.timezone.utc)
end = datetime.datetime(2026, 11, 4, tzinfo=datetime.timezone.utc)

symbols_to_fetch = ["EURUSD", "GBPUSD", "USDJPY", "NAS100", "DAX40"]

for sym in symbols_to_fetch:
    inst = cfg.dukascopy.instruments.get(sym)
    print(f"Baixando {sym} ({inst}) de {start.date()} a {end.date()}...")
    try:
        df = fetch_m1(inst, start, end, "bid")
        if not df.empty:
            save_m1(Path("data"), sym, df, source="dukascopy")
            print(f"  -> {sym}: {len(df)} candles gravados!")
        else:
            print(f"  -> {sym}: Retornou vazio!")
    except Exception as e:
        print(f"  -> Erro ao baixar {sym}: {e}")

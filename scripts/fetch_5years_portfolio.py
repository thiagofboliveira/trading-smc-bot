"""Download de 5 anos de histórico M1 da Dukascopy para os ativos da carteira.

Ativos:
- US30
- NAS100
- BRENT
- EURUSD
- GBPUSD
- XAUUSD

Utiliza o mecanismo oficial de fetch_history com retomada automática e tolerância a falhas.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

from smc_trader.config import load_config
from smc_trader.data.dukascopy_source import fetch_m1
from smc_trader.data.history import fetch_history, years_back_start

cfg = load_config(Path("config/default.yaml"))
root = Path(cfg.data.root)

SYMBOLS = ["US30", "NAS100", "BRENT", "EURUSD", "GBPUSD", "XAUUSD"]
YEARS = 5

end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
start = years_back_start(end, YEARS)

print(f"=================================================================")
print(f"  INICIANDO DOWNLOAD DE {YEARS} ANOS DE DADOS M1 DUKASCOPY")
print(f"  Período: {start:%Y-%m-%d} até {end:%Y-%m-%d} (60 meses por ativo)")
print(f"  Ativos: {', '.join(SYMBOLS)}")
print(f"=================================================================\n")

for sym in SYMBOLS:
    inst = cfg.dukascopy.instruments.get(sym)
    if not inst:
        print(f"⚠️ Símbolo sem instrumento mapeado: {sym}")
        continue

    print(f"\n>>> [{sym}] Iniciando download de {start:%Y-%m-%d} a {end:%Y-%m-%d}...")
    try:
        res = fetch_history(
            sym,
            inst,
            start,
            end,
            cfg.dukascopy.offer_side,
            root,
            fetcher=fetch_m1,
            pause=0.2,
        )
        print(
            f"✅ [{sym}] Concluído: {res.rows_saved:,} candles novos | "
            f"Meses: {len(res.saved_months)} baixados, {len(res.skipped_months)} já existiam, "
            f"{len(res.empty_months)} vazios, {len(res.failed_months)} falharam."
        )
        if res.failed_months:
            print(f"⚠️ Meses com falha para {sym}: {', '.join(res.failed_months)}")
    except Exception as e:
        print(f"❌ Erro ao baixar {sym}: {e}")

print("\n=================================================================")
print("  DOWNLOAD DE 5 ANOS CONCLUÍDO PARA TODOS OS ATIVOS")
print("=================================================================")

# Importação de histórico do MT5 via Wine

> Atenção: estes passos NÃO foram testados neste ambiente (sem MT5/Wine). Ajuste conforme necessário.

O MT5 é fonte secundária (a primária é a Dukascopy). Use quando quiser os dados exatos da sua corretora.

## 1. Instalar o MT5 no Wine
Instale o MetaTrader 5 da sua corretora com `wine` em um prefixo dedicado (ex.: `~/.wine-mt5`) e faça login na conta.

## 2. Python do Windows no mesmo prefixo
Instale o instalador do Python para Windows com `WINEPREFIX=~/.wine-mt5 wine python-installer.exe` (marque "Add to PATH"). Depois:

```
WINEPREFIX=~/.wine-mt5 wine python -m pip install MetaTrader5
```

## 3. Exportar o histórico
Com o terminal MT5 aberto:

```
WINEPREFIX=~/.wine-mt5 wine python scripts/wine/export_history.py \
  --symbols XAUUSD --from 2024-01-01 --to 2024-02-01 --out out/mt5
```

Gera `out/mt5/XAUUSD_M1.csv` (cabeçalho `time,open,high,low,close,tick_volume,spread,real_volume`; `time` em segundos de época no horário do servidor, não UTC).

## 4. Conferir o fuso do servidor da corretora
A regra padrão é servidor = hora de Nova York + 7h (com horário de verão dos EUA), em `data.server_ny_offset_hours`. Para conferir: compare o horário do candle atual no MT5 com a hora UTC. No inverno (EST) o servidor NY+7 fica em UTC+2; no verão (EDT) em UTC+3. Se a sua corretora seguir outra regra (ex.: Europe/Athens), defina na config `server_timezone: Europe/Athens` e `server_ny_offset_hours: null`.

## 5. Importar no projeto
```
uv run smc import-csv out/mt5/XAUUSD_M1.csv --symbol XAUUSD
```
Horários ambíguos/inexistentes na troca de horário de verão são descartados; duplicados ficam com a última linha do arquivo.

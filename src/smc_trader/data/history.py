"""Download de histórico longo da Dukascopy, mês a mês, com retomada e repetição."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

import pandas as pd

from smc_trader.data.dukascopy_source import _next_month_start, fetch_m1
from smc_trader.data.store import existing_months, save_m1


@dataclass
class HistoryResult:
    rows_saved: int = 0
    saved_months: list[str] = field(default_factory=list)
    skipped_months: list[str] = field(default_factory=list)
    empty_months: list[str] = field(default_factory=list)
    failed_months: list[str] = field(default_factory=list)


def years_back_start(end: datetime, years: int) -> datetime:
    """Primeiro dia do mês de `end` menos `years` anos (alinhado para não gravar mês parcial no início)."""
    return end.replace(
        year=end.year - years,
        month=end.month,
        day=1,
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )


def fetch_history(
    symbol: str,
    instrument: str,
    start: datetime,
    end: datetime,
    offer_side: Literal["bid", "ask"],
    root: Path,
    *,
    fetcher: Callable[..., pd.DataFrame] = fetch_m1,
    retries: int = 4,
    pause: float = 0.3,
    sleep: Callable[[float], None] | None = None,
    log: Callable[[str], None] = print,
) -> HistoryResult:
    """Baixa `start`..`end` mês a mês e grava cada mês assim que chega.

    Retomada: meses já gravados são pulados, exceto o último deles, que pode ter
    ficado parcial (a execução anterior pode ter sido interrompida ou o mês corrente
    estava em andamento). Um mês que falha após todas as tentativas é reportado em
    `failed_months` e não impede os demais.
    """
    sleep = sleep or time.sleep  # resolvido na chamada (permite monkeypatch em testes)
    result = HistoryResult()
    present = sorted(existing_months(root, symbol))
    last_present = present[-1] if present else None
    complete = set(present) - ({last_present} if last_present else set())

    chunk_start = start
    while chunk_start < end:
        chunk_end = min(_next_month_start(chunk_start), end)
        label = chunk_start.strftime("%Y-%m")
        if label in complete:
            result.skipped_months.append(label)
            chunk_start = chunk_end
            continue

        df = None
        for attempt in range(1, retries + 1):
            try:
                df = fetcher(instrument, chunk_start, chunk_end, offer_side)
                break
            except Exception as exc:  # rede/serviço: repetir com espera crescente
                log(f"  {symbol} [{label}] tentativa {attempt}/{retries} falhou: {exc}")
                if attempt < retries:
                    sleep(2.0 * attempt)

        if df is None:
            result.failed_months.append(label)
            log(f"  {symbol} [{label}] FALHOU após {retries} tentativas")
        elif df.empty:
            result.empty_months.append(label)
            log(f"  {symbol} [{label}] sem candles")
        else:
            save_m1(root, symbol, df, source="dukascopy")
            result.saved_months.append(label)
            result.rows_saved += len(df)
            log(f"  {symbol} [{label}] {len(df):,} candles")
        chunk_start = chunk_end
        sleep(pause)
    return result

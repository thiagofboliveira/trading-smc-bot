"""Importa histórico exportado do Profit (Nelogica) e devolve M1 em UTC.

O formato do arquivo varia conforme a versão e as opções de exportação, então o
leitor detecta separador, decimal e nomes de coluna. O que NÃO dá para detectar
é se o horário de cada candle é o de abertura ou o de fechamento: isso é
`bar_label` e muda o resultado do backtest (lookahead se estiver errado).
"""
import csv
import io
import re
import unicodedata
from pathlib import Path
from typing import Literal

import pandas as pd

_OUT_COLUMNS = ["open", "high", "low", "close", "volume", "spread"]

_ALIASES = {
    "date": ("data", "date"),
    "time": ("hora", "time"),
    "open": ("abertura", "open", "abert"),
    "high": ("maximo", "max", "high"),
    "low": ("minimo", "min", "low"),
    "close": ("fechamento", "close", "fech"),
    "quantity": ("quantidade", "qtd", "contratos"),
    "volume": ("volume", "vol"),
}


def _norm(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", text.lower())


def _find_columns(header: list[str]) -> dict[str, str]:
    by_norm = {_norm(h): h for h in header}
    found: dict[str, str] = {}
    for key, aliases in _ALIASES.items():
        for alias in aliases:
            if alias in by_norm:
                found[key] = by_norm[alias]
                break
    return found


def _to_number(series: pd.Series) -> pd.Series:
    """Converte '130.150,0' (pt-BR) ou '130150.0' (ponto decimal) em float."""
    text = series.astype(str).str.strip()
    # Vírgula presente => formato pt-BR: ponto é milhar e vírgula é decimal.
    br = text.str.contains(",", regex=False)
    text = text.where(~br, text.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(text, errors="coerce")


def import_profit_csv(
    path: Path,
    tz: str = "America/Sao_Paulo",
    bar_label: Literal["open", "close"] = "open",
) -> pd.DataFrame:
    """Lê o CSV/TXT exportado do Profit e devolve M1 em UTC.

    tz: fuso do horário do arquivo (B3 = America/Sao_Paulo).
    bar_label: "open" se o horário é o da abertura do candle (convenção do projeto);
        "close" se é o do fechamento, caso em que recua 1 minuto.
    """
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
        sep = dialect.delimiter
    except csv.Error:
        sep = ";"
    raw = pd.read_csv(io.StringIO(text), sep=sep, dtype=str)
    cols = _find_columns(list(raw.columns))

    needed = ["date", "open", "high", "low", "close"]
    missing = [k for k in needed if k not in cols]
    if missing:
        raise ValueError(
            f"colunas não encontradas no arquivo do Profit: {missing}. "
            f"Cabeçalho lido: {list(raw.columns)}"
        )

    stamp = raw[cols["date"]].str.strip()
    if "time" in cols:
        stamp = stamp + " " + raw[cols["time"]].str.strip()
    # Datas com "/" são dia/mês/ano; ISO (aaaa-mm-dd) não tem ambiguidade.
    dayfirst = bool(stamp.str.contains("/", regex=False).any())
    naive = pd.to_datetime(stamp, dayfirst=dayfirst, errors="coerce")

    volume_col = cols.get("quantity", cols.get("volume"))
    df = pd.DataFrame(
        {
            "open": _to_number(raw[cols["open"]]),
            "high": _to_number(raw[cols["high"]]),
            "low": _to_number(raw[cols["low"]]),
            "close": _to_number(raw[cols["close"]]),
            "volume": _to_number(raw[volume_col]) if volume_col else 0.0,
            "spread": 0.0,
        }
    )

    local = naive.dt.tz_localize(tz, ambiguous="NaT", nonexistent="NaT")
    index = pd.DatetimeIndex(local.dt.tz_convert("UTC"), name="time")
    if bar_label == "close":
        index = index - pd.Timedelta(minutes=1)
    df.index = index
    df = df[df.index.notna()]

    prices = df[["open", "high", "low", "close"]]
    invalid = (
        prices.isna().any(axis=1)
        | (prices <= 0).any(axis=1)
        | (df["high"] < df[["open", "close", "low"]].max(axis=1))
        | (df["low"] > df[["open", "close", "high"]].min(axis=1))
    )
    if invalid.any():
        first = df.index[invalid][0]
        raise ValueError(
            f"{int(invalid.sum())} barras inválidas no arquivo (preço ausente, <= 0 ou "
            f"high/low inconsistente); a primeira em {first}"
        )

    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df[_OUT_COLUMNS]

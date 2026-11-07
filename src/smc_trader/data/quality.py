"""Checagem de qualidade de candles M1 (D-04 do backlog).

Separa o que invalida o dado (erros: barra impossível, índice duplicado ou fora de
ordem, horário incompatível com a sessão do ativo) do que apenas pede atenção
(avisos: buracos no meio do dia, saltos de preço, excesso de barras sem variação).
Um backtest sobre dado com erro não é confiável; avisos precisam ser olhados, não
necessariamente corrigidos (feriados, notícias e aberturas geram os dois).
"""

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

_SPIKE_Z = (
    40.0  # desvios robustos (MAD) além dos quais um retorno de 1 barra vira "pico"
)
_OUTSIDE_SESSION_LIMIT = (
    0.01  # >1% das barras fora do horário esperado => provável erro de fuso
)
_FLAT_WARN = 0.40


@dataclass
class QualityReport:
    symbol: str
    n_bars: int
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    invalid_bars: int = 0
    duplicates: int = 0
    unsorted: bool = False
    gaps: list[tuple[pd.Timestamp, pd.Timestamp, int]] = field(default_factory=list)
    daily_breaks: int = 0
    spikes: int = 0
    flat_pct: float = 0.0
    outside_session_pct: float = 0.0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _spans_saturday(start: pd.Timestamp, end: pd.Timestamp) -> bool:
    days = pd.date_range(
        start.normalize() + pd.Timedelta(days=1), end.normalize(), freq="D"
    )
    return bool((days.weekday == 5).any())


def check_quality(
    df: pd.DataFrame,
    symbol: str,
    max_gap_minutes: int = 60,
    expected_hours: set[int] | None = None,
) -> QualityReport:
    """Analisa M1 com índice DatetimeIndex em UTC. `expected_hours` são horas UTC de pregão."""
    if df.empty:
        rep = QualityReport(symbol, 0, None, None)
        rep.errors.append("sem candles")
        return rep

    rep = QualityReport(symbol, len(df), df.index.min(), df.index.max())

    rep.duplicates = int(df.index.duplicated().sum())
    if rep.duplicates:
        rep.errors.append(f"{rep.duplicates} timestamp(s) duplicado(s)")
    rep.unsorted = not df.index.is_monotonic_increasing
    if rep.unsorted:
        rep.errors.append("índice fora de ordem cronológica")

    d = df[~df.index.duplicated(keep="last")].sort_index()

    prices = d[["open", "high", "low", "close"]]
    invalid = (
        prices.isna().any(axis=1)
        | (prices <= 0).any(axis=1)
        | (d["high"] < d[["open", "close", "low"]].max(axis=1))
        | (d["low"] > d[["open", "close", "high"]].min(axis=1))
    )
    rep.invalid_bars = int(invalid.sum())
    if rep.invalid_bars:
        first = d.index[invalid.to_numpy()][0]
        rep.errors.append(
            f"{rep.invalid_bars} barra(s) inválida(s) (preço ausente, <= 0 ou high/low inconsistente); primeira em {first}"
        )

    # Buracos: intervalo entre barras consecutivas maior que o tolerado, exceto fim de semana.
    minutes = d.index.to_series().diff().dt.total_seconds().div(60)
    big = minutes > max_gap_minutes
    gap_pos = np.flatnonzero(big.to_numpy())
    for pos in gap_pos:
        g_start, g_end = d.index[pos - 1], d.index[pos]
        if _spans_saturday(g_start, g_end):
            continue
        rep.gaps.append((g_start, g_end, int(round(minutes.iloc[pos]))))
    # Pausa diária do mercado: buracos que começam sempre na mesma hora e têm duração parecida.
    if len(rep.gaps) >= 20:
        hours = pd.Series([g[0].hour for g in rep.gaps])
        top_hour, top_n = int(hours.mode().iloc[0]), int(hours.value_counts().iloc[0])
        if top_n / len(rep.gaps) >= 0.6:
            typical = float(
                np.median([g[2] for g in rep.gaps if g[0].hour == top_hour])
            )
            keep = [
                g
                for g in rep.gaps
                if not (g[0].hour == top_hour and g[2] <= 2 * typical)
            ]
            rep.daily_breaks = len(rep.gaps) - len(keep)
            rep.gaps = keep
    if rep.gaps:
        largest = max(rep.gaps, key=lambda g: g[2])
        rep.warnings.append(
            f"{len(rep.gaps)} buraco(s) maior(es) que {max_gap_minutes} min "
            f"(maior: {largest[2]} min a partir de {largest[0]})"
        )

    # Picos: retorno de 1 barra muito acima do ruído típico (ignora a barra logo após um buraco).
    log_ret = np.log(d["close"].where(d["close"] > 0)).diff()
    after_gap = big.to_numpy()
    valid = log_ret.notna().to_numpy() & ~after_gap
    r = log_ret.to_numpy()[valid]
    if len(r) > 20:
        med = np.median(r)
        mad = np.median(np.abs(r - med))
        if mad > 0:
            z = np.abs(r - med) / (1.4826 * mad)
            rep.spikes = int((z > _SPIKE_Z).sum())
    if rep.spikes:
        rep.warnings.append(
            f"{rep.spikes} pico(s) de preço (retorno de 1 barra > {_SPIKE_Z:.0f} desvios robustos)"
        )

    rep.flat_pct = float((d["high"] == d["low"]).mean())
    if rep.flat_pct > _FLAT_WARN:
        rep.warnings.append(f"{rep.flat_pct:.0%} das barras sem variação (high == low)")

    if expected_hours is not None:
        outside = ~pd.Index(d.index.hour).isin(sorted(expected_hours))
        rep.outside_session_pct = float(outside.mean())
        if rep.outside_session_pct > _OUTSIDE_SESSION_LIMIT:
            rep.errors.append(
                f"{rep.outside_session_pct:.1%} das barras fora do horário esperado "
                f"(horas UTC {min(expected_hours)}-{max(expected_hours)}): provável erro de fuso"
            )
    return rep


def format_report(rep: QualityReport) -> str:
    status = "OK" if rep.ok else "ERRO"
    lines = [f"[{status}] {rep.symbol}: {rep.n_bars:,} barras"]
    if rep.n_bars:
        lines[0] += f" | {rep.start:%Y-%m-%d} a {rep.end:%Y-%m-%d}"
    if rep.daily_breaks:
        lines.append(
            f"   info: {rep.daily_breaks} pausa(s) diária(s) do mercado ignorada(s) como buraco"
        )
    for e in rep.errors:
        lines.append(f"   erro: {e}")
    for w in rep.warnings:
        lines.append(f"   aviso: {w}")
    return "\n".join(lines)

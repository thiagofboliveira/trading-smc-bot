"""Pullback na MME80 em tendência (MME80 x MMA200, inclinação mínima), sem Fibonacci.

Regra pedida pelo usuário (2026-11-25), parâmetros fixados antes de qualquer teste:
- Tendência de alta em `i - 1`: MME80 > MMA200 e inclinação da MME80 >= 30°.
  Baixa: espelhado.
- Preço "longe" da média em `i - 1`: a barra `i - 1` inteira acima da MME80 (alta) ou abaixo
  (baixa), ou seja, aguardando o recuo.
- Entrada: ordem limite na MME80[i - 1], válida só para a barra `i`, reenviada a cada barra.
- Stop (duas variantes): "fundo" = último fundo (pivô) confirmado abaixo da entrada;
  "mm200" = MMA200[i - 1]. Ambos com folga de `stop_buffer_atr` × ATR[i - 1].
- Alvo: `target_r` × risco planejado (2R ou 3R).

Inclinação em graus: 30° não existe sem escala no gráfico. Aqui, a escala é "1 ATR de subida
em `slope_bars` barras = 45°": ângulo = atan((MME80[j] - MME80[j - slope_bars]) / ATR[j]).
Com `slope_bars = 10`, 30° equivale a a MME80 subir pelo menos 0,577 ATR em 10 barras.

Causalidade (AGENTS.md, seção 1):
- Todo filtro da entrada usa `i - 1`. O preço da ordem e o stop são fixados antes de `i` abrir.
- Pivô de fundo em `k` só é conhecido em `k + pivot_bars`, e só vale se `k + pivot_bars <= i-1`.
- Barra de entrada só pode ser estopada, nunca alvejada.
- Stop com gap sai no open, com slippage. Stop e alvo na mesma barra: assume o stop.
- Preços são bid; compra entra e venda sai pelo ask (bid + spread).
- Uma posição por ativo; nova entrada só a partir da barra seguinte à saída.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd


@dataclass
class EMA80PullbackConfig:
    ema_period: int = 80
    sma_period: int = 200
    atr_period: int = 14
    slope_bars: int = 10
    min_angle_deg: float = 30.0  # 0 desliga o filtro de inclinação (ablação)
    stop_mode: Literal["fundo", "mm200"] = "fundo"
    target_r: float = 2.0
    stop_buffer_atr: float = 0.10
    pivot_bars: int = 2  # pivô: mínima menor que as `pivot_bars` barras de cada lado
    pivot_lookback: int = 150
    min_risk_atr: float = 0.25  # risco planejado mínimo, evita stop colado
    spread: float = 0.0  # em preço
    slippage: float = 0.0  # em preço, nas ordens stop (stop loss)


@dataclass
class PullbackTrade:
    symbol: str
    direction: Literal["long", "short"]
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_price: float
    target_price: float
    exit_price: float
    exit_reason: str
    r_multiple: float


def indicators(df: pd.DataFrame, cfg: EMA80PullbackConfig) -> dict[str, np.ndarray]:
    close, high, low = df["close"], df["high"], df["low"]
    ema = close.ewm(span=cfg.ema_period, adjust=False).mean()
    sma = close.rolling(cfg.sma_period).mean()
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    atr = tr.rolling(cfg.atr_period).mean()
    angle = np.degrees(np.arctan((ema - ema.shift(cfg.slope_bars)) / atr.replace(0, np.nan)))
    # a MME só é confiável depois de um aquecimento
    warm = np.arange(len(df)) < max(cfg.sma_period, cfg.ema_period * 2)
    ema_v = ema.to_numpy(float).copy()
    ema_v[warm] = np.nan
    return {
        "ema": ema_v,
        "sma": sma.to_numpy(float),
        "atr": atr.to_numpy(float),
        "angle": angle.to_numpy(float),
    }


def _pivots(arr: np.ndarray, k: int, kind: str) -> np.ndarray:
    """Marca em `j` o pivô em `j - k` (só conhecido quando `j` fecha)."""
    n = len(arr)
    out = np.full(n, np.nan)
    for j in range(2 * k, n):
        c = j - k
        win = arr[c - k : c + k + 1]
        v = arr[c]
        if kind == "low" and v == win.min() and (win > v).sum() == 2 * k:
            out[j] = v
        if kind == "high" and v == win.max() and (win < v).sum() == 2 * k:
            out[j] = v
    return out


def _last_pivot_beyond(pivots: np.ndarray, upto: int, level: float, below: bool, lookback: int):
    lo = max(0, upto - lookback)
    for j in range(upto, lo - 1, -1):
        p = pivots[j]
        if np.isnan(p):
            continue
        if (below and p < level) or (not below and p > level):
            return p
    return None


def trend_state(ind: dict, j: int, cfg: EMA80PullbackConfig) -> int:
    """+1 alta, -1 baixa, 0 nada, avaliado com valores da barra `j` (já fechada)."""
    ema, sma, ang = ind["ema"][j], ind["sma"][j], ind["angle"][j]
    if np.isnan(ema) or np.isnan(sma) or np.isnan(ang):
        return 0
    if ema > sma and ang >= cfg.min_angle_deg:
        return 1
    if ema < sma and ang <= -cfg.min_angle_deg:
        return -1
    return 0


def plan_stop(
    d: int, entry: float, i: int, ind: dict, piv_lo, piv_hi, cfg: EMA80PullbackConfig
) -> float | None:
    """Stop planejado para uma entrada em `entry` executada na barra `i` (dados até i-1)."""
    atr = ind["atr"][i - 1]
    buf = cfg.stop_buffer_atr * atr
    if cfg.stop_mode == "mm200":
        base = ind["sma"][i - 1]
        stop = base - buf if d > 0 else base + buf
    else:
        p = _last_pivot_beyond(
            piv_lo if d > 0 else piv_hi, i - 1, entry, below=d > 0, lookback=cfg.pivot_lookback
        )
        if p is None:
            return None
        stop = p - buf if d > 0 else p + buf
    risk = (entry - stop) * d
    if not np.isfinite(risk) or risk < cfg.min_risk_atr * atr:
        return None
    return stop


def manage_exit(
    d: int, i_entry: int, entry: float, stop: float, target: float,
    o: np.ndarray, h: np.ndarray, lo: np.ndarray, cl: np.ndarray, cfg: EMA80PullbackConfig,
):
    """Retorna (índice de saída, preço, motivo). Barra de entrada só pode ser estopada."""
    sp, sl = cfg.spread, cfg.slippage
    n = len(o)
    # barra de entrada: só stop (bid para long, ask para short)
    if d > 0 and lo[i_entry] <= stop:
        return i_entry, stop - sl, "stop"
    if d < 0 and h[i_entry] + sp >= stop:
        return i_entry, stop + sl, "stop"
    for j in range(i_entry + 1, n):
        if d > 0:
            if o[j] <= stop:
                return j, o[j] - sl, "stop_gap"
            if lo[j] <= stop:  # stop e alvo na mesma barra: stop
                return j, stop - sl, "stop"
            if o[j] >= target:
                return j, target, "target"
            if h[j] >= target:
                return j, target, "target"
        else:
            if o[j] + sp >= stop:
                return j, o[j] + sp + sl, "stop_gap"
            if h[j] + sp >= stop:
                return j, stop + sl, "stop"
            if o[j] + sp <= target:
                return j, target, "target"
            if lo[j] + sp <= target:
                return j, target, "target"
    exit_px = cl[n - 1] if d > 0 else cl[n - 1] + sp
    return n - 1, exit_px, "end_of_data"


def prepare(df: pd.DataFrame, cfg: EMA80PullbackConfig) -> dict:
    """Indicadores e pivôs calculados uma vez (todos causais, ver `indicators`/`_pivots`)."""
    o, h, lo, cl = (df[c].to_numpy(float) for c in ("open", "high", "low", "close"))
    ind = indicators(df, cfg)
    states = np.array([trend_state(ind, j, cfg) for j in range(len(df))], dtype=int)
    return {
        "ind": ind, "o": o, "h": h, "lo": lo, "cl": cl, "idx": df.index, "states": states,
        "piv_lo": _pivots(lo, cfg.pivot_bars, "low"),
        "piv_hi": _pivots(h, cfg.pivot_bars, "high"),
    }


def run(
    df: pd.DataFrame, symbol: str, cfg: EMA80PullbackConfig, pre: dict | None = None
) -> list[PullbackTrade]:
    pre = pre or prepare(df, cfg)
    ind, o, h, lo, cl = pre["ind"], pre["o"], pre["h"], pre["lo"], pre["cl"]
    piv_lo, piv_hi, idx = pre["piv_lo"], pre["piv_hi"], pre["idx"]
    sp = cfg.spread
    trades: list[PullbackTrade] = []
    i = 1
    n = len(df)
    states = pre["states"]
    while i < n:
        d = states[i - 1]
        ema_prev = ind["ema"][i - 1]
        if d == 0 or np.isnan(ind["atr"][i - 1]):
            i += 1
            continue
        # aguardando o recuo: barra i-1 inteira do lado da tendência
        if d > 0 and not lo[i - 1] + sp > ema_prev:
            i += 1
            continue
        if d < 0 and not h[i - 1] < ema_prev:
            i += 1
            continue
        limit = ema_prev
        stop = plan_stop(d, limit, i, ind, piv_lo, piv_hi, cfg)
        if stop is None:
            i += 1
            continue
        risk = (limit - stop) * d
        target = limit + d * cfg.target_r * risk
        # execução da limite dentro da barra i
        if d > 0:
            if lo[i] + sp > limit:
                i += 1
                continue
            entry = min(o[i] + sp, limit)
        else:
            if h[i] < limit:
                i += 1
                continue
            entry = max(o[i], limit)
        j, exit_px, reason = manage_exit(d, i, entry, stop, target, o, h, lo, cl, cfg)
        r = d * (exit_px - entry) / risk
        trades.append(
            PullbackTrade(symbol, "long" if d > 0 else "short", idx[i], idx[j], entry, stop,
                          target, exit_px, reason, r)
        )
        i = j + 1
    return trades


def run_random_control(
    df: pd.DataFrame, symbol: str, cfg: EMA80PullbackConfig, p_entry: float,
    rng: np.random.Generator, pre: dict | None = None,
) -> list[PullbackTrade]:
    """Controle: mesma tendência em i-1, mesmo stop e alvo, entrada a mercado no open de
    barras sorteadas com probabilidade `p_entry` (sem esperar o toque na MME80)."""
    pre = pre or prepare(df, cfg)
    ind, o, h, lo, cl = pre["ind"], pre["o"], pre["h"], pre["lo"], pre["cl"]
    piv_lo, piv_hi, idx, states = pre["piv_lo"], pre["piv_hi"], pre["idx"], pre["states"]
    sp = cfg.spread
    out: list[PullbackTrade] = []
    i, n = 1, len(df)
    while i < n:
        d = states[i - 1]
        if d == 0 or np.isnan(ind["atr"][i - 1]) or rng.random() >= p_entry:
            i += 1
            continue
        entry = o[i] + sp if d > 0 else o[i]
        stop = plan_stop(d, entry, i, ind, piv_lo, piv_hi, cfg)
        if stop is None:
            i += 1
            continue
        risk = (entry - stop) * d
        target = entry + d * cfg.target_r * risk
        j, exit_px, reason = manage_exit(d, i, entry, stop, target, o, h, lo, cl, cfg)
        out.append(
            PullbackTrade(symbol, "long" if d > 0 else "short", idx[i], idx[j], entry, stop,
                          target, exit_px, reason, d * (exit_px - entry) / risk)
        )
        i = j + 1
    return out


def eligible_bars(df: pd.DataFrame, cfg: EMA80PullbackConfig, pre: dict | None = None) -> int:
    pre = pre or prepare(df, cfg)
    return int((pre["states"][:-1] != 0).sum())


def summarize(trades: list[PullbackTrade]) -> dict:
    if not trades:
        return {"n": 0}
    r = np.array([t.r_multiple for t in trades])
    n = len(r)
    wins = r[r > 0]
    losses = r[r <= 0]
    eq = np.cumsum(r)
    dd = (eq - np.maximum.accumulate(np.concatenate([[0.0], eq]))[1:]).min()
    sd = r.std(ddof=1) if n > 1 else 0.0
    return {
        "n": n,
        "total_r": float(r.sum()),
        "avg_r": float(r.mean()),
        "se": float(sd / np.sqrt(n)) if n > 1 else float("nan"),
        "t": float(r.mean() / (sd / np.sqrt(n))) if n > 1 and sd > 0 else float("nan"),
        "win_rate": float(len(wins) / n),
        "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "max_dd_r": float(min(dd, 0.0)),
        "pf": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
    }

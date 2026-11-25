"""Cenários anti-viés do pullback na MME80 (AGENTS.md, seções 1 e 4)."""

import numpy as np
import pandas as pd

from smc_trader.strategies.ema80_pullback import (
    EMA80PullbackConfig,
    indicators,
    manage_exit,
    run,
    run_random_control,
    summarize,
    trend_state,
)


def _ohlc(close: np.ndarray, wick: float = 0.3, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    open_ = np.concatenate([[close[0]], close[:-1]])
    w = np.abs(rng.normal(0, wick, (len(close), 2)))
    high = np.maximum(open_, close) + w[:, 0]
    low = np.minimum(open_, close) - w[:, 1]
    idx = pd.date_range("2000-01-03", periods=len(close), freq="D", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close}, index=idx)


def _random_walk(n=3000, seed=3, drift=0.0):
    rng = np.random.default_rng(seed)
    return 1000 + np.cumsum(rng.normal(drift, 1.0, n))


def test_invariancia_de_prefixo():
    df = _ohlc(_random_walk(drift=0.05))
    cfg = EMA80PullbackConfig(min_angle_deg=10.0, spread=0.1, slippage=0.1)
    full = run(df, "X", cfg)
    for cut in (1200, 1900, 2600):
        part = run(df.iloc[:cut], "X", cfg)
        closed = [t for t in full if t.exit_time < df.index[cut - 1]]
        closed_part = [t for t in part if t.exit_time < df.index[cut - 1]]
        assert [(t.entry_time, t.exit_time, round(t.r_multiple, 9)) for t in closed] == [
            (t.entry_time, t.exit_time, round(t.r_multiple, 9)) for t in closed_part
        ]
    assert len(full) > 10


def test_barra_de_entrada_so_pode_ser_estopada():
    """Barra de entrada toca o alvo e o stop: tem de sair no stop; só alvo: não sai nela."""
    cfg = EMA80PullbackConfig()
    o = np.array([100.0, 100.0, 100.0])
    h = np.array([100.0, 130.0, 100.5])
    lo = np.array([100.0, 89.0, 99.5])
    cl = np.array([100.0, 100.0, 100.0])
    j, px, why = manage_exit(1, 1, 100.0, 90.0, 120.0, o, h, lo, cl, cfg)
    assert (j, px, why) == (1, 90.0, "stop")
    lo2 = np.array([100.0, 95.0, 99.5])
    j, px, why = manage_exit(1, 1, 100.0, 90.0, 120.0, o, h, lo2, cl, cfg)
    assert j != 1  # o toque no alvo na barra de entrada não conta


def test_stop_com_gap_sai_no_open_com_slippage():
    cfg = EMA80PullbackConfig(slippage=0.5)
    o = np.array([100.0, 100.0, 85.0])
    h = np.array([100.0, 101.0, 86.0])
    lo = np.array([100.0, 99.0, 84.0])
    cl = np.array([100.0, 100.0, 85.0])
    j, px, why = manage_exit(1, 1, 100.0, 90.0, 120.0, o, h, lo, cl, cfg)
    assert (j, why) == (2, "stop_gap")
    assert px == 85.0 - 0.5


def test_short_sai_pelo_ask():
    cfg = EMA80PullbackConfig(spread=1.0)
    o = np.array([100.0, 100.0, 100.0])
    h = np.array([100.0, 100.0, 109.2])  # bid 109.2 + spread 1 >= stop 110
    lo = np.array([100.0, 99.0, 99.0])
    cl = np.array([100.0, 100.0, 100.0])
    j, px, why = manage_exit(-1, 1, 100.0, 110.0, 80.0, o, h, lo, cl, cfg)
    assert (j, px, why) == (2, 110.0, "stop")


def test_stop_e_alvo_na_mesma_barra_assume_stop():
    cfg = EMA80PullbackConfig()
    o = np.array([100.0, 100.0, 100.0])
    h = np.array([100.0, 101.0, 125.0])
    lo = np.array([100.0, 99.0, 88.0])
    cl = np.array([100.0, 100.0, 100.0])
    j, px, why = manage_exit(1, 1, 100.0, 90.0, 120.0, o, h, lo, cl, cfg)
    assert (j, why) == (2, "stop")


def test_filtro_usa_barra_anterior_e_nao_a_do_toque():
    """Mudar o fechamento da barra do toque não pode mudar se/onde a ordem entra."""
    df = _ohlc(_random_walk(drift=0.08, seed=11))
    cfg = EMA80PullbackConfig(min_angle_deg=10.0)
    base = run(df, "X", cfg)
    assert base
    t0 = base[len(base) // 2]
    i = df.index.get_loc(t0.entry_time)
    df2 = df.copy()
    # a barra do toque fecha muito abaixo (pior para o filtro, se ele olhasse close[i])
    df2.iloc[i, df2.columns.get_loc("close")] = df2["low"].iloc[i]
    alt = run(df2, "X", cfg)
    match = [t for t in alt if t.entry_time == t0.entry_time]
    assert match and match[0].entry_price == t0.entry_price and match[0].stop_price == t0.stop_price


def test_tendencia_avaliada_com_dados_fechados():
    df = _ohlc(_random_walk(drift=0.1, seed=5))
    cfg = EMA80PullbackConfig(min_angle_deg=10.0)
    ind_full = indicators(df, cfg)
    ind_part = indicators(df.iloc[:1500], cfg)
    for j in range(400, 1500, 97):
        assert trend_state(ind_full, j, cfg) == trend_state(ind_part, j, cfg)


def test_controle_aleatorio_roda_e_sumario_fecha():
    df = _ohlc(_random_walk(drift=0.05))
    cfg = EMA80PullbackConfig(min_angle_deg=10.0, target_r=2.0)
    rnd = run_random_control(df, "X", cfg, 0.05, np.random.default_rng(1))
    s = summarize(rnd)
    assert s["n"] > 10
    check = s["win_rate"] * s["avg_win"] + (1 - s["win_rate"]) * s["avg_loss"]
    assert abs(check - s["avg_r"]) < 1e-9

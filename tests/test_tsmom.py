"""Testes anti-viés do TSMOM diário."""

import numpy as np
import pandas as pd

from smc_trader.strategies.tsmom import (
    TSMOMConfig,
    long_only_signal,
    momentum_signal,
    rebalance_mask,
    run_backtest,
    target_weights,
)


def _prices(n=900, k=3, seed=1):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2010-01-01", periods=n)
    r = rng.normal(0, 0.01, (n, k))
    return pd.DataFrame(100 * np.exp(np.cumsum(r, axis=0)), index=idx, columns=list("ABC")[:k])


def test_invariancia_de_prefixo():
    p = _prices()
    cfg = TSMOMConfig(lookback=60, vol_min_obs=20)
    full = run_backtest(p, cfg)
    for cut in (400, 555, 700):
        part = run_backtest(p.iloc[:cut], cfg)
        # o último pregão do prefixo não é fim de mês conhecido: comparar até cut-2
        a = full.portfolio.iloc[: cut - 2]
        b = part.portfolio.iloc[: cut - 2]
        pd.testing.assert_series_equal(a, b)


def test_sinal_nao_muda_com_dado_futuro():
    p = _prices()
    s_full = momentum_signal(p, 60)
    s_part = momentum_signal(p.iloc[:500], 60)
    pd.testing.assert_frame_equal(s_full.iloc[:500], s_part)


def test_salto_no_dia_da_decisao_nao_e_capturado():
    """Um salto no próprio dia do sinal (ou no dia da execução) não pode gerar lucro."""
    p = _prices(n=700, k=1)
    cfg = TSMOMConfig(lookback=20, vol_min_obs=10, execution_lag=1)
    w = target_weights(p, cfg)["A"].dropna()
    pos = run_backtest(p, cfg).positions["A"]
    checked = 0
    for d, new_w in w.iloc[:-1].items():
        d_i = p.index.get_loc(d)
        if d_i + 2 >= len(p) or np.isclose(new_w, pos.iloc[d_i]):
            continue
        # a posição decidida em d não recebe o retorno de d nem o de d+1
        assert pos.iloc[d_i + 1] == pos.iloc[d_i]
        assert pos.iloc[d_i + 2] == new_w
        checked += 1
    assert checked > 5
    # o retorno do dia d+1 (dia da execução) é ganho pela posição antiga
    res = run_backtest(p, cfg)
    rets = p["A"].pct_change().fillna(0.0)
    pd.testing.assert_series_equal(
        res.gross, (res.positions["A"] * rets), check_names=False
    )


def test_fim_de_mes_exige_proximo_pregao():
    idx = pd.bdate_range("2020-01-27", "2020-02-03")
    m = rebalance_mask(idx, "M")
    assert m.loc["2020-01-31"]
    assert not m.iloc[-1]


def test_custo_reduz_retorno_e_zero_custo_bate_bruto():
    p = _prices()
    cfg0 = TSMOMConfig(lookback=60, vol_min_obs=20, default_cost_bps=0.0)
    r0 = run_backtest(p, cfg0)
    pd.testing.assert_series_equal(r0.portfolio, r0.gross, check_names=False)
    r1 = run_backtest(p, TSMOMConfig(lookback=60, vol_min_obs=20, default_cost_bps=10.0))
    assert r1.portfolio.sum() < r0.portfolio.sum()


def test_long_only_acompanha_o_ativo():
    idx = pd.bdate_range("2020-01-01", periods=300)
    p = pd.DataFrame({"A": 100.0 * (1.0005 ** np.arange(300))}, index=idx)
    cfg = TSMOMConfig(lookback=20, vol_min_obs=10, default_cost_bps=0.0)
    res = run_backtest(p, cfg, signal=long_only_signal(p))
    assert (res.positions["A"] >= 0).all()

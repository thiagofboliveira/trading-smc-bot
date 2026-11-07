"""Testes para robustez estatística, Monte Carlo e alarmes (M-06, M-08)."""

from types import SimpleNamespace

import pandas as pd

from smc_trader.backtest.robustness import (
    bonferroni_p_value,
    check_sanity_alarms,
    generate_random_baseline,
    run_monte_carlo_drawdown,
)


def _make_t(r: float, direction: str = "long", same_bar: bool = False):
    t0 = pd.Timestamp("2024-01-01 10:00", tz="UTC")
    t1 = t0 if same_bar else pd.Timestamp("2024-01-01 11:00", tz="UTC")
    return SimpleNamespace(
        r_multiple=r,
        direction=direction,
        entry_time=t0,
        exit_time=t1,
    )


def test_monte_carlo_drawdown_p95():
    # 20 trades com soma positiva, mas contendo sequências de perdas
    trades = [_make_t(2.0), _make_t(-1.0)] * 10
    mc = run_monte_carlo_drawdown(trades, num_simulations=500, seed=123)

    assert "p50_max_dd_r" in mc
    assert "p95_max_dd_r" in mc
    assert mc["p95_max_dd_r"] >= mc["p50_max_dd_r"]
    assert mc["max_simulated_dd_r"] >= mc["p95_max_dd_r"]


def test_sanity_alarms_triggered():
    # PF suspeito > 2.5
    alarms = check_sanity_alarms({"profit_factor": 3.2, "win_rate": 50.0}, [])
    assert any("Profit Factor suspeito" in a for a in alarms)

    # Win rate alto com payoff baixo
    alarms2 = check_sanity_alarms(
        {"profit_factor": 1.2, "win_rate": 75.0, "avg_win_r": 0.5, "avg_loss_r": 1.0},
        [],
    )
    assert any("Win rate anômalo" in a for a in alarms2)

    # Assimetria direcional (10 long vs 2 short -> razão 5x)
    trades_asym = [_make_t(1.0, "long")] * 10 + [_make_t(1.0, "short")] * 2
    alarms3 = check_sanity_alarms({"profit_factor": 1.5}, trades_asym)
    assert any("Forte assimetria direcional" in a for a in alarms3)

    # Saída no mesmo candle (> 20%)
    trades_same_bar = [_make_t(1.0, same_bar=True)] * 5 + [_make_t(1.0, same_bar=False)] * 5
    alarms4 = check_sanity_alarms({"profit_factor": 1.5}, trades_same_bar)
    assert any("saíram na barra de entrada" in a for a in alarms4)


def test_random_baseline_edge_detection():
    # Estratégia vencedora consistente (+3R em todos os trades)
    winning_trades = [_make_t(3.0)] * 30
    res_win = generate_random_baseline(winning_trades, n_simulations=200, seed=42)
    assert res_win["has_statistical_edge"] is True
    assert res_win["p_value"] < 0.05

    # Estratégia sem vantagem (retorno ~ 0)
    flat_trades = [_make_t(1.0), _make_t(-1.0)] * 15
    res_flat = generate_random_baseline(flat_trades, n_simulations=200, seed=42)
    assert res_flat["has_statistical_edge"] is False


def test_bonferroni_adjustment():
    nominal_p = 0.01
    assert bonferroni_p_value(nominal_p, 10) == 0.10
    assert bonferroni_p_value(nominal_p, 200) == 1.0  # limit 1.0

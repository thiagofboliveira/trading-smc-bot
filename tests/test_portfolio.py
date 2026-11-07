"""Testes unitários para simulação realista de portfólio multi-ativos (M-05)."""

from types import SimpleNamespace

import pandas as pd

from smc_trader.backtest.portfolio import PortfolioConfig, simulate_portfolio


def _make_trade(
    symbol: str,
    direction: str,
    entry_str: str,
    exit_str: str,
    r_mult: float,
    entry_price: float = 100.0,
):
    return SimpleNamespace(
        symbol=symbol,
        direction=direction,
        entry_time=pd.Timestamp(entry_str, tz="UTC"),
        exit_time=pd.Timestamp(exit_str, tz="UTC"),
        entry_price=entry_price,
        r_multiple=r_mult,
        exit_reason="tp" if r_mult > 0 else "sl",
    )


def test_portfolio_empty_trades():
    res = simulate_portfolio([], PortfolioConfig(initial_capital=10000.0))
    assert res.total_trades_submitted == 0
    assert res.total_trades_accepted == 0
    assert res.final_capital == 10000.0
    assert res.total_return_pct == 0.0


def test_portfolio_max_open_trades_limit():
    # 3 trades se sobrepõem no tempo; max_open_trades_total = 2
    # Trade 1: 10:00 -> 11:00
    # Trade 2: 10:15 -> 11:15
    # Trade 3: 10:30 -> 11:30 (deve ser pulado pois 1 e 2 estão abertos)
    # Trade 4: 11:05 -> 12:00 (deve ser aceito pois Trade 1 já fechou às 11:00)
    t1 = _make_trade("EURUSD", "long", "2024-01-01 10:00", "2024-01-01 11:00", 2.0)
    t2 = _make_trade("US30", "short", "2024-01-01 10:15", "2024-01-01 11:15", -1.0)
    t3 = _make_trade("NAS100", "long", "2024-01-01 10:30", "2024-01-01 11:30", 3.0)
    t4 = _make_trade("XAUUSD", "long", "2024-01-01 11:05", "2024-01-01 12:00", 1.5)

    cfg = PortfolioConfig(
        initial_capital=10000.0,
        risk_per_trade_pct=0.01,
        max_open_trades_total=2,
    )
    res = simulate_portfolio([t1, t2, t3, t4], cfg)

    assert res.total_trades_submitted == 4
    assert res.total_trades_accepted == 3
    assert res.total_trades_skipped == 1

    accepted_syms = [tr.symbol for tr in res.trades]
    assert "EURUSD" in accepted_syms
    assert "US30" in accepted_syms
    assert "XAUUSD" in accepted_syms
    assert "NAS100" not in accepted_syms


def test_portfolio_drawdown_ordered_by_exit_time():
    # T1 entra 09:00 e sai 12:00 (+2R)
    # T2 entra 09:30 e sai 10:00 (-1R)
    # Na ordem de entrada: +2R depois -1R.
    # Mas na ordem de saída real da conta: -1R sai primeiro às 10:00 (provocando drawdown inicial),
    # depois +2R sai às 12:00.
    t1 = _make_trade("EURUSD", "long", "2024-01-01 09:00", "2024-01-01 12:00", 2.0)
    t2 = _make_trade("GBPUSD", "short", "2024-01-01 09:30", "2024-01-01 10:00", -1.0)

    cfg = PortfolioConfig(
        initial_capital=10000.0,
        risk_per_trade_pct=0.01,
        max_open_trades_total=5,
    )
    res = simulate_portfolio([t1, t2], cfg)

    # A primeira realização deve ser T2 (saída às 10:00)
    assert res.trades[0].symbol == "GBPUSD"
    assert res.trades[0].r_multiple == -1.0
    assert res.trades[1].symbol == "EURUSD"
    assert res.trades[1].r_multiple == 2.0

    # Drawdown máximo deve refletir o stop de 1% que saiu primeiro
    assert res.max_drawdown_pct >= 0.99


def test_portfolio_breakdowns_and_metrics():
    t1 = _make_trade("EURUSD", "long", "2024-01-01 10:00", "2024-01-01 11:00", 2.0)
    t2 = _make_trade("EURUSD", "short", "2024-01-02 10:00", "2024-01-02 11:00", -1.0)
    t3 = _make_trade("US30", "long", "2024-02-01 10:00", "2024-02-01 11:00", 3.0)

    cfg = PortfolioConfig(initial_capital=10000.0, risk_per_trade_pct=0.01)
    res = simulate_portfolio([t1, t2, t3], cfg)

    assert "EURUSD" in res.breakdown_by_symbol
    assert res.breakdown_by_symbol["EURUSD"]["trades"] == 2
    assert res.breakdown_by_symbol["EURUSD"]["win_rate"] == 50.0

    assert "US30" in res.breakdown_by_symbol
    assert res.breakdown_by_symbol["US30"]["trades"] == 1
    assert res.breakdown_by_symbol["US30"]["win_rate"] == 100.0

    assert "long" in res.breakdown_by_direction
    assert res.breakdown_by_direction["long"]["trades"] == 2
    assert "short" in res.breakdown_by_direction
    assert res.breakdown_by_direction["short"]["trades"] == 1

    # Meses positivos (Janeiro teve 2R - 1R = +1R, Fevereiro teve +3R -> 100% positivos)
    assert res.pct_positive_months == 100.0

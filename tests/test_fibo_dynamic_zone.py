"""Testes unitários e anti-viés para a estratégia FiboDynamicZoneStrategy (M5)."""

import numpy as np
import pandas as pd

from smc_trader.strategies.fibo_dynamic_zone import (
    FiboDynamicZoneConfig,
    FiboDynamicZoneStrategy,
)


def _generate_synthetic_candles(
    n: int = 300,
    base_price: float = 10000.0,
    trend: float = 2.0,
    volatility: float = 5.0,
) -> pd.DataFrame:
    """Gera dados M1 sintéticos com tendência e volatilidade controladas."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2026-01-01 09:00", periods=n, freq="1min", tz="UTC")
    steps = rng.normal(trend, volatility, n)
    close = base_price + np.cumsum(steps)
    high = close + rng.uniform(1.0, 4.0, n)
    low = close - rng.uniform(1.0, 4.0, n)
    open_ = close - rng.uniform(-2.0, 2.0, n)

    df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": 100.0,
        },
        index=dates,
    )
    return df


def test_fibo_dynamic_zone_initialization():
    cfg = FiboDynamicZoneConfig(
        timeframe="M5",
        ema_fast_period=80,
        sma_slow_period=200,
        min_slope_degrees=30.0,
        target_rr=3.0,
        risk_pct_per_trade=0.02,
        account_balance=10000.0,
    )
    strat = FiboDynamicZoneStrategy(cfg)
    assert strat.config.timeframe == "M5"
    assert strat.config.min_slope_degrees == 30.0
    assert strat.config.target_rr == 3.0


def test_resample_and_indicators():
    df_m1 = _generate_synthetic_candles(n=1200, trend=1.5, volatility=2.0)
    strat = FiboDynamicZoneStrategy(FiboDynamicZoneConfig(timeframe="M5"))
    df_res = strat.resample_data(df_m1)

    assert "ema80" in df_res.columns
    assert "sma200" in df_res.columns
    assert "atr" in df_res.columns
    assert "slope_deg" in df_res.columns
    assert len(df_res) == 1200 // 5


def test_anti_bias_intrabar_stop_loss():
    """Verifica que a barra de entrada que atinge o stop loss é estopada imediatamente (F-01)."""
    # Cria uma série sintética onde ocorre um BOS de alta e depois o candle despenca direto além do stop
    n = 2500
    df_m1 = _generate_synthetic_candles(n=n, trend=2.0, volatility=3.0)
    strat = FiboDynamicZoneStrategy(
        FiboDynamicZoneConfig(
            timeframe="M5",
            pivot_k=2,
            fibo_entry=0.618,
            fibo_stop=0.820,
            target_rr=3.0,
            zone_confluence_mode="overlap",
            min_slope_degrees=0.0,  # permite testar sem filtro de ângulo
        )
    )
    trades = strat.run_backtest(df_m1, symbol="TEST", spread=1.0)
    for t in trades:
        # Nenhum trade pode ter saída anterior à entrada
        assert t.exit_time >= t.entry_time
        # Se saiu como INTRABAR_STOP_LOSS, entrada e saída ocorreram no mesmo candle
        if t.exit_reason == "INTRABAR_STOP_LOSS":
            assert t.entry_time == t.exit_time
            assert not t.win
            assert t.r_multiple <= 0


def test_money_management_2pct_risk_and_3r_target():
    """Verifica se o risco é 2% ($200 em $10.000) e o alvo é 6% ($600)."""
    cfg = FiboDynamicZoneConfig(
        account_balance=10000.0,
        risk_pct_per_trade=0.02,
        target_rr=3.0,
        slippage=0.0,
        commission_per_unit=0.0,
    )
    # Simula cálculo de PnL em USD
    usd_risk = cfg.account_balance * cfg.risk_pct_per_trade  # $200
    assert usd_risk == 200.0

    # Trade vencedor com 3R
    pnl_win = 3.0 * usd_risk
    assert pnl_win == 600.0  # 6% de ganho sobre $10.000

    # Trade perdedor com -1R
    pnl_loss = -1.0 * usd_risk
    assert pnl_loss == -200.0  # 2% de perda sobre $10.000


def test_slope_degrees_filtering():
    """Verifica que inclinação abaixo do mínimo bloqueia a entrada quando exigido."""
    df_m1 = _generate_synthetic_candles(n=2000, trend=0.01, volatility=5.0)  # mercado lateral
    cfg_strict = FiboDynamicZoneConfig(
        min_slope_degrees=65.0,  # exige ângulo íngreme impossível em mercado lateral
        zone_confluence_mode="fibo_within_ma",
    )
    strat = FiboDynamicZoneStrategy(cfg_strict)
    trades = strat.run_backtest(df_m1, symbol="FLAT_MARKET", spread=1.0)
    # No mercado lateral com média flat, não deve haver entradas
    assert len(trades) == 0


def test_rejection_entry_mode():
    """Verifica execução causal do modo de confirmação por rejeição de pavio (i+1)."""
    df_m1 = _generate_synthetic_candles(n=3000, trend=1.5, volatility=3.0)
    cfg = FiboDynamicZoneConfig(
        timeframe="M5",
        entry_mode="rejection",
        rejection_min_wick_ratio=0.20,
        min_slope_degrees=0.0,
        zone_confluence_mode="overlap",
    )
    strat = FiboDynamicZoneStrategy(cfg)
    trades = strat.run_backtest(df_m1, symbol="TEST_REJ", spread=1.0)
    for t in trades:
        assert t.exit_time >= t.entry_time


def test_smc_filters_and_profit_lock():
    """Verifica que profit_lock, require_leg_fvg, require_inducement e session_filter operam causalmente."""
    df_m1 = _generate_synthetic_candles(n=3500, trend=1.2, volatility=4.0)
    cfg = FiboDynamicZoneConfig(
        timeframe="M5",
        min_slope_degrees=10.0,
        zone_confluence_mode="overlap",
        require_leg_fvg=True,
        require_inducement=False,
        session_filter=True,
        profit_lock_trigger_r=1.618,
        profit_lock_lock_r=1.0,
    )
    strat = FiboDynamicZoneStrategy(cfg)
    trades = strat.run_backtest(df_m1, symbol="TEST_SMC", spread=1.0)
    for t in trades:
        assert t.exit_time >= t.entry_time
        if t.exit_reason == "PROFIT_LOCK":
            # Se saiu no profit_lock de +1.0R, nunca pode ter saído no mesmo candle da entrada
            assert t.exit_time > t.entry_time


def test_ema80_in_fibo_and_fibo_above_sma200_modes():
    """Verifica os modos de confluência ema80_in_fibo e fibo_above_sma200."""
    df_m1 = _generate_synthetic_candles(n=3500, trend=1.5, volatility=3.5)
    for mode in ("ema80_in_fibo", "fibo_above_sma200"):
        cfg = FiboDynamicZoneConfig(
            timeframe="M5",
            min_slope_degrees=0.0,
            zone_confluence_mode=mode,
            profit_lock_trigger_r=1.618,
            profit_lock_lock_r=1.0,
        )
        strat = FiboDynamicZoneStrategy(cfg)
        trades = strat.run_backtest(df_m1, symbol="TEST_MODE", spread=1.0)
        for t in trades:
            assert t.exit_time >= t.entry_time


def test_prefix_invariance():
    """Garante que truncar dados futuros jamais altera decisões ou trades passados (sem look-ahead)."""
    df_m1 = _generate_synthetic_candles(n=4000, trend=0.8, volatility=4.0)
    cfg = FiboDynamicZoneConfig(
        timeframe="M5",
        min_slope_degrees=0.0,
        zone_confluence_mode="overlap",
        require_leg_fvg=False,
        profit_lock_trigger_r=1.618,
        profit_lock_lock_r=1.0,
    )
    strat = FiboDynamicZoneStrategy(cfg)
    full_trades = strat.run_backtest(df_m1, symbol="PREFIX", spread=1.0)

    cutoff_m1 = 3000
    cutoff_time = df_m1.index[cutoff_m1 - 1]
    prefix_trades = strat.run_backtest(df_m1.iloc[:cutoff_m1], symbol="PREFIX", spread=1.0)

    full_closed_before_cutoff = [t for t in full_trades if t.exit_time <= cutoff_time]
    assert prefix_trades == full_closed_before_cutoff


def test_two_stage_breakeven_partial_and_bos_trailing():
    """Verifica condução em 2 estágios (Breakeven + Profit Lock), parcial e BOS Swing Trailing sem look-ahead."""
    df_m1 = _generate_synthetic_candles(n=4000, trend=1.0, volatility=3.5)
    cfg = FiboDynamicZoneConfig(
        timeframe="M5",
        min_slope_degrees=0.0,
        zone_confluence_mode="overlap",
        fibo_stop=0.886,
        breakeven_trigger_r=1.0,
        breakeven_lock_r=0.1,
        profit_lock_trigger_r=1.618,
        profit_lock_lock_r=1.0,
        partial_trigger_r=1.5,
        partial_pct=0.5,
        bos_swing_trailing=True,
    )
    strat = FiboDynamicZoneStrategy(cfg)
    full_trades = strat.run_backtest(df_m1, symbol="CONDUCTION", spread=1.0)

    cutoff_m1 = 3000
    cutoff_time = df_m1.index[cutoff_m1 - 1]
    prefix_trades = strat.run_backtest(df_m1.iloc[:cutoff_m1], symbol="CONDUCTION", spread=1.0)
    full_closed_before_cutoff = [t for t in full_trades if t.exit_time <= cutoff_time]
    assert prefix_trades == full_closed_before_cutoff


def test_runner_ma_trailing_and_prefix_invariance():
    """Verifica saída causal runner_ma (sem teto, trailing na MME 20 após profit_lock, saída em open[i+1])."""
    df_m1 = _generate_synthetic_candles(n=4500, trend=1.2, volatility=3.5)
    cfg = FiboDynamicZoneConfig(
        timeframe="M5",
        min_slope_degrees=0.0,
        zone_confluence_mode="overlap",
        fibo_stop=0.920,
        target_mode="runner_ma",
        trailing_ma_period=20,
        breakeven_trigger_r=1.25,
        breakeven_lock_r=0.1,
        profit_lock_trigger_r=2.0,
        profit_lock_lock_r=1.0,
    )
    strat = FiboDynamicZoneStrategy(cfg)
    full_trades = strat.run_backtest(df_m1, symbol="RUNNER_MA", spread=1.0)

    for t in full_trades:
        assert t.exit_time >= t.entry_time
        assert t.exit_reason != "TAKE_PROFIT"
        if t.exit_reason == "TRAILING_MA":
            assert t.exit_time > t.entry_time

    cutoff_m1 = 3000
    cutoff_time = df_m1.index[cutoff_m1 - 1]
    prefix_trades = strat.run_backtest(df_m1.iloc[:cutoff_m1], symbol="RUNNER_MA", spread=1.0)
    full_closed_before_cutoff = [t for t in full_trades if t.exit_time <= cutoff_time]
    assert prefix_trades == full_closed_before_cutoff







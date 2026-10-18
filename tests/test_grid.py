import pandas as pd
import pytest

from smc_trader.backtest.attribution import VariantExecutionSummary, analyze_attribution, format_attribution_markdown
from smc_trader.backtest.grid import GridVariant, generate_grid_variants
from smc_trader.backtest.runner import compute_breaker_stats, run_grid
from smc_trader.backtest.split import generate_walk_forward_windows, split_is_oos
from smc_trader.config import BacktestConfig
from smc_trader.zones.orderblock import Zone


def test_grid_variants_constraints():
    base_cfg = BacktestConfig()
    variants = generate_grid_variants(base_cfg)

    assert len(variants) > 0

    # Nenhuma variante de Breaker puro com touch
    bb_touch = [v for v in variants if v.blocks_filter == ("BB",) and v.entry_mode == "touch"]
    assert len(bb_touch) == 0

    # Nenhuma variante de touch com m1_swing
    touch_m1_swing = [v for v in variants if v.entry_mode == "touch" and v.stop_mode == "m1_swing"]
    assert len(touch_m1_swing) == 0

    # Determinisno de hash
    v1 = GridVariant.create(("OB",), "confirmation", "ob", "none", "none", base_cfg)
    v2 = GridVariant.create(("OB",), "confirmation", "ob", "none", "none", base_cfg)
    assert v1.config_hash == v2.config_hash


def test_split_is_oos():
    idx = pd.date_range("2026-01-01", periods=100, freq="1min", tz="UTC")
    df = pd.DataFrame({"close": range(100)}, index=idx)

    is_df, oos_df = split_is_oos(df, is_ratio=0.7)
    assert len(is_df) == 70
    assert len(oos_df) == 30
    assert is_df.index[-1] < oos_df.index[0]


def test_walk_forward_windows():
    idx = pd.date_range("2026-01-01", periods=180, freq="1D", tz="UTC")
    df = pd.DataFrame({"close": range(180)}, index=idx)

    windows = generate_walk_forward_windows(df, train_days=60, test_days=30, step_days=30)
    assert len(windows) >= 3
    for w in windows:
        assert w.train_end == w.test_start
        assert len(w.train_df) > 0
        assert len(w.test_df) > 0


def test_attribution_and_markdown():
    s1 = VariantExecutionSummary(
        config_hash="hash1",
        blocks_filter="OB",
        entry_mode="confirmation",
        stop_mode="ob",
        trailing_mode="none",
        confluence_profile="none",
        is_metrics={"total_trades": 35, "expectancy": 0.5, "win_rate": 40.0, "max_drawdown_r": 3.0, "profit_factor": 1.5},
        oos_metrics={"total_trades": 15, "expectancy": 0.4, "win_rate": 38.0, "max_drawdown_r": 2.5, "profit_factor": 1.4},
        wf_metrics=[],
        is_qualified=True,
        oos_profitable=True,
        performance_drop_pct=-20.0,
    )
    s2 = VariantExecutionSummary(
        config_hash="hash2",
        blocks_filter="OB",
        entry_mode="touch",
        stop_mode="ob",
        trailing_mode="none",
        confluence_profile="none",
        is_metrics={"total_trades": 20, "expectancy": 0.1, "win_rate": 30.0, "max_drawdown_r": 5.0, "profit_factor": 1.1},
        oos_metrics={"total_trades": 10, "expectancy": -0.1, "win_rate": 25.0, "max_drawdown_r": 4.0, "profit_factor": 0.8},
        wf_metrics=[],
        is_qualified=False,  # < 30 trades
        oos_profitable=False,
        performance_drop_pct=None,
    )

    attr = analyze_attribution([s1, s2], min_trades=30)
    assert attr["total_variants"] == 2
    assert attr["qualified_variants"] == 1
    assert attr["robust_variants"] == 1
    assert len(attr["ranking"]) == 1
    assert attr["ranking"][0].config_hash == "hash1"

    md = format_attribution_markdown(attr, symbol="TEST")
    assert "Relatório de Refinamento e Atribuição" in md
    assert "hash1" in md


def test_compute_breaker_stats():
    idx = pd.date_range("2026-01-01 00:00", periods=5, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [10.0, 11.0, 12.0, 13.0, 14.0],
            "high": [10.5, 11.5, 12.5, 13.5, 14.5],
            "low": [9.5, 10.5, 11.5, 12.5, 13.5],
            "close": [10.2, 11.2, 12.2, 13.2, 14.2],
        },
        index=idx,
    )

    b1 = Zone(
        candle_time=idx[0],
        direction="long",
        high=11.0,
        low=10.0,
        range_low=10.0,
        range_high=11.0,
        kind="BREAKER",
        swept_liquidity=False,
        in_discount=True,
        created_at=idx[1],  # criado no candle 1
        end_time=None,
        end_reason=None,
    )
    # Candle 2 tem low=11.5 > b1.high (11.0) -> não toca no primeiro candle
    stats = compute_breaker_stats(df, [b1])
    assert stats["total_breakers"] == 1
    assert stats["early_mitigated"] == 0


def test_run_grid_integration():
    # 200 candles M1 sintéticos
    idx = pd.date_range("2026-01-01 00:00", periods=200, freq="1min", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [100.0 + i * 0.1 for i in range(200)],
            "high": [101.0 + i * 0.1 for i in range(200)],
            "low": [99.0 + i * 0.1 for i in range(200)],
            "close": [100.5 + i * 0.1 for i in range(200)],
            "volume": [1000.0] * 200,
        },
        index=idx,
    )

    base_cfg = BacktestConfig()
    result = run_grid(
        candles_m1=df,
        symbol="XAUUSD",
        base_config=base_cfg,
        pivot_k_htf=2,
        min_trades=0,  # min_trades zero para qualificar mesmo em poucos dados
        run_walk_forward=False,
    )

    assert result.symbol == "XAUUSD"
    assert len(result.summaries) > 0
    assert "Relatório de Refinamento" in result.markdown_report


"""Testes para a metodologia de validação estatística e walk-forward (M-01 e M-02 do backlog)."""
import pandas as pd

from smc_trader.backtest.attribution import VariantExecutionSummary, analyze_attribution, format_attribution_markdown
from smc_trader.backtest.runner import run_grid
from smc_trader.config import BacktestConfig


def test_m01_ranking_seleciona_estritamente_pelo_is():
    """M-01: A escolha da estratégia campeã deve ser feita estritamente pelo In-Sample (IS).

    Variante A: Campeã no treino (IS +1.0R), mas no teste OOS deu -0.2R.
    Variante B: Mediana no treino (IS +0.5R), mas no teste OOS deu +0.8R.
    Variante C: Fraca no treino (IS +0.1R), mas no teste OOS deu +1.5R por sorte.

    No modelo enviesado antigo, a variante C era escolhida (data snooping no OOS).
    No modelo correto M-01, a variante A DEVE ser a #1 do ranking de escolha.
    """
    s_a = VariantExecutionSummary(
        config_hash="var_A",
        blocks_filter="OB",
        entry_mode="confirmation",
        stop_mode="ob",
        trailing_mode="none",
        confluence_profile="none",
        is_metrics={"total_trades": 50, "expectancy": 1.0, "win_rate": 60.0, "max_drawdown_r": 3.0, "profit_factor": 2.0},
        oos_metrics={"total_trades": 20, "expectancy": -0.2, "win_rate": 35.0, "max_drawdown_r": 5.0, "profit_factor": 0.8},
        wf_metrics=[],
        is_qualified=True,
        oos_profitable=False,
        performance_drop_pct=-120.0,
    )
    s_b = VariantExecutionSummary(
        config_hash="var_B",
        blocks_filter="FVOB",
        entry_mode="touch",
        stop_mode="swing",
        trailing_mode="none",
        confluence_profile="none",
        is_metrics={"total_trades": 40, "expectancy": 0.5, "win_rate": 50.0, "max_drawdown_r": 4.0, "profit_factor": 1.5},
        oos_metrics={"total_trades": 18, "expectancy": 0.8, "win_rate": 55.0, "max_drawdown_r": 2.0, "profit_factor": 1.8},
        wf_metrics=[],
        is_qualified=True,
        oos_profitable=True,
        performance_drop_pct=60.0,
    )
    s_c = VariantExecutionSummary(
        config_hash="var_C",
        blocks_filter="OB",
        entry_mode="touch",
        stop_mode="ob",
        trailing_mode="ema",
        confluence_profile="none",
        is_metrics={"total_trades": 35, "expectancy": 0.1, "win_rate": 40.0, "max_drawdown_r": 6.0, "profit_factor": 1.1},
        oos_metrics={"total_trades": 15, "expectancy": 1.5, "win_rate": 70.0, "max_drawdown_r": 1.5, "profit_factor": 3.0},
        wf_metrics=[],
        is_qualified=True,
        oos_profitable=True,
        performance_drop_pct=1400.0,
    )

    attr = analyze_attribution([s_a, s_b, s_c], min_trades=30)

    # #1 DEVE ser a var_A (melhor IS: +1.0R), não var_C
    assert attr["ranking"][0].config_hash == "var_A"
    assert attr["ranking"][1].config_hash == "var_B"
    assert attr["ranking"][2].config_hash == "var_C"

    # Relatório deve citar var_A como campeã selecionada pelo treino
    md = format_attribution_markdown(attr, symbol="TEST")
    assert "var_A" in md
    assert "A configuração campeã selecionada pelo In-Sample foi o hash **`var_A`**" in md


def test_m02_walk_forward_otimiza_no_treino_e_avalia_no_teste():
    """M-02: Walk-forward verdadeiro gera janelas, otimiza no treino e testa no OOS subsequente."""
    # Gera 130 dias de dados (freq 1h para teste rápido)
    idx = pd.date_range("2026-01-01 00:00", periods=24 * 130, freq="1h", tz="UTC")
    n = len(idx)
    df = pd.DataFrame(
        {
            "open": [100.0 + (i % 20) * 0.5 for i in range(n)],
            "high": [102.0 + (i % 20) * 0.5 for i in range(n)],
            "low": [98.0 + (i % 20) * 0.5 for i in range(n)],
            "close": [101.0 + (i % 20) * 0.5 for i in range(n)],
            "volume": [1000.0] * n,
        },
        index=idx,
    )

    base_cfg = BacktestConfig()
    from smc_trader.backtest.grid import GridVariant
    fast_variants = [
        GridVariant.create(blocks_filter=("OB",), entry_mode="touch", stop_mode="ob", trailing_mode="none", confluence_profile="none", base_config=base_cfg),
        GridVariant.create(blocks_filter=("OB",), entry_mode="confirmation", stop_mode="ob", trailing_mode="none", confluence_profile="none", base_config=base_cfg),
    ]
    result = run_grid(
        candles_m1=df,
        symbol="SYN",
        base_config=base_cfg,
        pivot_k_htf=2,
        min_trades=0,
        run_walk_forward=True,
        variants=fast_variants,
    )

    assert result.walk_forward is not None
    assert isinstance(result.walk_forward.wfe, float)
    assert len(result.walk_forward.steps) > 0
    assert "Eficiência de Walk-Forward (WFE — M-02)" in result.markdown_report

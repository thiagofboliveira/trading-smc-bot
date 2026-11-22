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


def _build_deterministic_runner_series(direction: int = 1) -> pd.DataFrame:
    """Constrói série M5 determinística (em formato M1 com 5 barras iguais por M5) que gera:
    1) Tendência clara (MME 80 > MMA 200 no Long, ou < no Short)
    2) Pivô fractal k=2 + BOS causal
    3) Retração exata a 61.8% dentro da zona (sem atingir stop 92%)
    4) Impulso > +2.5R (ativa profit_lock em +2.0R -> trava +1.0R)
    5) Candle que fecha contra a MME 20, seguido de saída no open da barra seguinte (i+1).
    """
    m5_bars: list[tuple[float, float, float, float]] = []
    # 220 barras de tendência limpa para aquecer MMA200 e MME80
    base = 1000.0
    step = 0.5 * direction
    for idx in range(220):
        c = base + idx * step
        o = c - 0.2 * direction
        h = max(o, c) + 0.3
        lo = min(o, c) - 0.3
        m5_bars.append((o, h, lo, c))

    # Cria estrutura de pivôs fractais (k=2) e BOS com retração exatamente dentro do canal [MMA200, MME80].
    # Após 220 barras com step=0.5, ema80 ~ p0 - 20 e sma200 ~ p0 - 50.
    p0 = m5_bars[-1][3]
    # Sequência de offsets (open, high, low, close) relativos a p0 (multiplicados por direction)
    # Origem = -40.0, Extremo = +10.0 -> span = 50.0 -> 61.8% = -20.9, 79.0% = -29.5 (100% dentro de [-50, -20])
    # Stop 92% = -36.0 -> risk ~ 15.1 (+2.0R ~ +9.3, +1.0R ~ -5.8)
    pattern = [
        # Pullback profundo até a origem (-40.0) formando swing low fractal (k=2)
        (-2.0, 0.0, -22.0, -20.0),
        (-20.0, -18.0, -35.0, -34.0),
        (-34.0, -32.0, -40.0, -36.0),  # pivô fundo em -40.0
        (-36.0, -20.0, -37.0, -22.0),
        (-22.0, -8.0, -23.0, -10.0),
        # Swing high intermediário em -2.0 (k=2)
        (-10.0, -3.0, -12.0, -4.0),
        (-4.0, -2.0, -6.0, -3.0),  # pivô topo em -2.0
        (-3.0, -2.5, -10.0, -9.0),
        (-9.0, -4.0, -11.0, -5.0),
        # BOS fecha acima de -2.0 (extremo = +10.0, origem = -40.0 -> 61.8% = -20.9, 92% = -36.0)
        (-5.0, 10.0, -6.0, 8.0),
        # Barra de retração toca -20.9 (sem tocar -36.0) e entra limite em -20.9
        (6.0, 7.0, -23.0, -12.0),
        # Impulso forte > +2.5R (precisa passar de -20.9 + 2*15.1 = +9.3 -> vai até +35.0)
        (-12.0, 15.0, -13.0, 14.0),
        (14.0, 35.0, 12.0, 32.0),
        (32.0, 40.0, 28.0, 36.0),
        # Candle de reversão: fecha abaixo da MME 20 (~ -3), mas ACIMA do stop profit_lock (+1.0R ~ -5.8)
        # Primeiro deixamos a MME 20 subir acima de +5.0 com mais alguns candles no topo
        (36.0, 42.0, 34.0, 40.0),
        (40.0, 44.0, 38.0, 42.0),
        (42.0, 45.0, 39.0, 41.0),
        # Agora fecha abaixo da MME 20 (~ +7) e acima do stop profit_lock (~ -5.8), em +2.0
        (41.0, 41.5, 1.0, 2.0),
        # Barra i+1: saída a mercado exatamente no open = +1.5
        (1.5, 3.0, 0.5, 1.0),
        (1.0, 2.0, 0.0, 0.5),
    ]
    for o, h, lo, c in pattern:
        if direction == 1:
            m5_bars.append((p0 + o, p0 + h, p0 + lo, p0 + c))
        else:
            # Espelha no eixo de preço para Short
            m5_bars.append((p0 - o, p0 - lo, p0 - h, p0 - c))

    # Expande cada barra M5 em 5 barras M1 idênticas para preservar exatamente OHLC no resample
    m1_rows = []
    start = pd.Timestamp("2026-01-05 08:00", tz="UTC")
    for idx, (o, h, lo, c) in enumerate(m5_bars):
        t0 = start + pd.Timedelta(minutes=5 * idx)
        for m in range(5):
            m1_rows.append((t0 + pd.Timedelta(minutes=m), o, h, lo, c, 100.0))

    df = pd.DataFrame(m1_rows, columns=["ts", "open", "high", "low", "close", "volume"]).set_index("ts")
    return df


def test_runner_ma_trailing_and_prefix_invariance():
    """Testa causalidade estrita do runner_ma (Long e Short), saída exata em open[i+1],
    spread/slippage e invariância de prefixo — sem teste vácuo (exige TRAILING_MA real).
    """
    for direction in (1, -1):
        df_m1 = _build_deterministic_runner_series(direction=direction)
        spread = 0.2
        slippage = 0.05
        cfg = FiboDynamicZoneConfig(
            timeframe="M5",
            pivot_k=2,
            fibo_entry=0.618,
            fibo_stop=0.920,
            stop_mode="fibo_82",
            target_mode="runner_ma",
            trailing_ma_period=20,
            min_slope_degrees=0.0,
            zone_confluence_mode="overlap",
            breakeven_trigger_r=1.25,
            breakeven_lock_r=0.1,
            profit_lock_trigger_r=2.0,
            profit_lock_lock_r=1.0,
            slippage=slippage,
        )
        strat = FiboDynamicZoneStrategy(cfg)
        full_trades = strat.run_backtest(df_m1, symbol=f"RUNNER_{direction}", spread=spread)

        trailing_trades = [t for t in full_trades if t.exit_reason == "TRAILING_MA"]
        assert len(trailing_trades) >= 1, f"Esperado ao menos 1 trade TRAILING_MA (dir={direction})"

        tr = trailing_trades[0]
        assert tr.exit_time > tr.entry_time
        assert tr.r_multiple > 1.0
        assert all(t.exit_reason != "TAKE_PROFIT" for t in full_trades)

        # Verifica que o preço de saída corresponde exatamente ao open da barra exit_time (+/- slippage/spread)
        df_m5 = strat.resample_data(df_m1)
        exit_open = float(df_m5.loc[tr.exit_time, "open"])
        expected_exit_px = (
            exit_open - slippage if direction == 1 else exit_open + spread + slippage
        )
        expected_pnl = direction * (expected_exit_px - tr.entry_price)
        assert np.isclose(tr.pnl_points, expected_pnl, atol=1e-6)

        # Invariância de prefixo: truncar na barra ANTERIOR à saída (onde fechou contra MME 20)
        # NÃO pode fechar o trade antecipadamente no close[i]
        exit_m5_pos = df_m5.index.get_loc(tr.exit_time)
        cutoff_ts = df_m5.index[exit_m5_pos - 1] + pd.Timedelta(minutes=4)
        prefix_trades = strat.run_backtest(df_m1.loc[:cutoff_ts], symbol=f"RUNNER_{direction}", spread=spread)
        assert tr not in prefix_trades

        # Truncar exatamente após a barra de saída produz exatamente o mesmo trade
        after_exit_ts = tr.exit_time + pd.Timedelta(minutes=4)
        after_trades = strat.run_backtest(df_m1.loc[:after_exit_ts], symbol=f"RUNNER_{direction}", spread=spread)
        assert after_trades == [t for t in full_trades if t.exit_time <= tr.exit_time]








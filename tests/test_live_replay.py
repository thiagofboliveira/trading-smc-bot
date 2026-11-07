"""Teste de Replay Causal: Live Trading Engine vs FiboOTEStrategy (L-02).

Garante que o motor de execução ao vivo (alimentado barra a barra) reproduza
exatamente os mesmos sinais de entrada, níveis de Stop Loss e Take Profit da
estratégia Fibo OTE de backtest quando alimentados com os mesmos candles.
"""


import pandas as pd
import pytest

from smc_trader.config import (
    BridgeConfig,
    FiboModelConfig,
    KillSwitchConfig,
    ProductionConfig,
    ProductionSymbolConfig,
    TradingProductionConfig,
)
from smc_trader.execution.live_engine import LiveTradingEngine
from smc_trader.execution.mt5_interface import MockMT5Client
from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy


def _generate_synthetic_scenario() -> pd.DataFrame:
    """Cria um cenário M1 determinístico com BOS de alta e retração OTE (70.5%).

    - Perna: Fundo em 2600.0, Topo em 2650.0 (distância = 50.0).
    - Nível 70.5%: 2600.0 + 0.295 * 50.0 = 2614.75.
    - Stop 79.0%: 2600.0 + 0.210 * 50.0 = 2610.50.
    """
    rows = []
    t = pd.Timestamp("2026-11-07 09:00:00", tz="UTC")

    # 1. Base / Fundo (M5 #0 a #5)
    for _ in range(30):
        rows.append({"open": 2605.0, "high": 2606.0, "low": 2600.0, "close": 2604.0, "volume": 100})
        t += pd.Timedelta(minutes=1)

    # 2. Topo intermediário em 2630.0 (M5 #6 a #10)
    for _ in range(25):
        rows.append({"open": 2620.0, "high": 2630.0, "low": 2615.0, "close": 2625.0, "volume": 100})
        t += pd.Timedelta(minutes=1)

    # 3. Recuo fractal (M5 #11 a #14)
    for _ in range(20):
        rows.append({"open": 2615.0, "high": 2620.0, "low": 2610.0, "close": 2612.0, "volume": 100})
        t += pd.Timedelta(minutes=1)

    # 4. Impulso e BOS rompendo 2630.0 até 2650.0 (M5 #15 a #18)
    for _ in range(20):
        rows.append({"open": 2635.0, "high": 2650.0, "low": 2632.0, "close": 2645.0, "volume": 100})
        t += pd.Timedelta(minutes=1)

    # 5. Barra seguinte de retração tocando o Sweet Spot 70.5% (2614.75) (M5 #19)
    for _ in range(5):
        rows.append({"open": 2640.0, "high": 2642.0, "low": 2613.0, "close": 2620.0, "volume": 100})
        t += pd.Timedelta(minutes=1)

    # 6. Continuação
    for _ in range(15):
        rows.append({"open": 2620.0, "high": 2660.0, "low": 2618.0, "close": 2655.0, "volume": 100})
        t += pd.Timedelta(minutes=1)

    times = pd.date_range("2026-11-07 09:00:00", periods=len(rows), freq="1min", tz="UTC")
    df = pd.DataFrame(rows, index=times)
    return df


def test_live_replay_matches_backtest_signals(tmp_path):
    """Valida L-02: LiveTradingEngine gera exatamente os mesmos sinais que FiboOTEStrategy."""
    df_m1 = _generate_synthetic_scenario()

    # 1. Executa no simulador oficial de backtest
    fibo_cfg = FiboOTEConfig(
        timeframe="5min",
        fibo_entry=0.705,
        fibo_stop=0.790,
        pivot_k=2,
        target_mode="0_percent",
        trailing_exit_ma=None,
    )
    strat = FiboOTEStrategy(fibo_cfg)
    backtest_trades = strat.run_backtest(df_m1, symbol="XAUUSD", spread=0.0)
    assert len(backtest_trades) > 0, "Backtest deve encontrar o trade sintético"
    expected_trade = backtest_trades[0]

    # 2. Configura ambiente Live em modo replay bar-by-bar
    prod_cfg = ProductionConfig(
        trading=TradingProductionConfig(risk_pct_per_trade=1.0, max_open_trades_total=4),
        bridge=BridgeConfig(),
        kill_switch=KillSwitchConfig(max_daily_loss_pct=10.0),
        models={
            "smc_fibo_test": FiboModelConfig(
                name="SMC-Fibo-Test",
                strategy="fibo_ote",
                timeframe="M5",
                fibo_entry=0.705,
                fibo_stop=0.790,
                pivot_k=2,
                trailing_exit_ma=None,
            )
        },
        symbols={
            "XAUUSD": ProductionSymbolConfig(
                model="smc_fibo_test",
                macro_tf="M5",
                order_type="market",
            )
        },
    )

    client = MockMT5Client(initial_balance=10000.0)
    client.connect()

    notifications = []
    engine = LiveTradingEngine(
        client=client,
        production_config=prod_cfg,
        notification_callback=lambda msg: notifications.append(msg),
        state_file=tmp_path / "replay_state.json",
        journal_file=tmp_path / "replay_journal.jsonl",
    )

    # Alimenta barra a barra simulando chegada em tempo real
    # Cada iteração adiciona mais 1 barra M1 e executa process_symbol_tick
    for end_idx in range(50, len(df_m1) + 1):
        c_slice = df_m1.iloc[:end_idx]
        client.set_candles("XAUUSD", "M1", c_slice)
        engine.process_symbol_tick("XAUUSD", now_utc=c_slice.index[-1])

    # Verifica ordens executadas pelo motor no cliente MT5
    positions = client.get_open_positions(symbol="XAUUSD")
    assert len(positions) == 1, "Live engine deve ter aberto exatamente 1 posição"
    live_pos = positions[0]

    # Asserção de paridade matemática perfeita (L-02)
    assert live_pos.direction == expected_trade.direction
    assert live_pos.open_price == pytest.approx(expected_trade.entry_price, rel=1e-4)
    assert live_pos.stop_loss == pytest.approx(expected_trade.stop_loss, rel=1e-4)
    assert live_pos.take_profit == pytest.approx(expected_trade.take_profit, rel=1e-4)

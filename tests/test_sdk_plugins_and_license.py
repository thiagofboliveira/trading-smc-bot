"""Testes unitários para SDK de Plugins (E2-7) e Licenciamento Offline (E8-7)."""

import pandas as pd

from smc_trader.commands.strategy_cmd import audit_strategy_causality
from smc_trader.core.license import generate_license_key, verify_license_key
from smc_trader.core.plugin_loader import discover_plugins, load_strategy_from_file, run_strategy_simulation
from smc_trader.core.strategy import BaseStrategy
from smc_trader.core.types import OrderIntent, OrderIntentType


class DummyCrossover(BaseStrategy):
    """Estratégia de teste causal."""

    @property
    def name(self) -> str:
        return "dummy_crossover"

    @property
    def version(self) -> str:
        return "1.0.0"

    def evaluate(self, candles: pd.DataFrame, open_position=None) -> list[OrderIntent]:
        if len(candles) < 20 or open_position is not None:
            return []
        c = candles["close"]
        if float(c.iloc[-1]) > float(c.iloc[-2]):
            last_p = float(c.iloc[-1])
            return [
                OrderIntent(
                    intent_type=OrderIntentType.PLACE_LIMIT,
                    direction="long",
                    price=last_p,
                    stop_loss=last_p - 10.0,
                    take_profit=last_p + 20.0,
                    expiry_bars=2,
                )
            ]
        return []


def test_license_lifecycle():
    """Testa geração, validação e expiração de licenças offline."""
    valid_key = generate_license_key(customer_id="user_123", tier="enterprise", valid_until="2099-12-31")
    is_valid, msg, payload = verify_license_key(valid_key)
    assert is_valid is True
    assert payload is not None
    assert payload["customer_id"] == "user_123"
    assert payload["tier"] == "enterprise"

    # Chave corrompida / adulterada
    corrupted_key = valid_key[:-4] + "ffff"
    is_valid_corr, msg_corr, _ = verify_license_key(corrupted_key)
    assert is_valid_corr is False
    assert "Assinatura" in msg_corr

    # Chave expirada
    expired_key = generate_license_key(customer_id="user_old", tier="basic", valid_until="2020-01-01")
    is_valid_exp, msg_exp, _ = verify_license_key(expired_key)
    assert is_valid_exp is False
    assert "expirada" in msg_exp


def test_plugin_discovery_and_simulation():
    """Testa descoberta de plugins e execução via SimBroker."""
    plugins = discover_plugins("plugins")
    assert "example_sma_cross" in plugins or "sma_cross_plugin" in plugins

    cls = load_strategy_from_file("plugins/example_sma_cross.py")
    assert cls is not None

    strat = cls()
    assert strat.name == "sma_cross_plugin"

    # Simulação causal com SimBroker
    dt_idx = pd.date_range("2024-01-01", periods=100, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "open": [100.0 + i for i in range(100)],
            "high": [105.0 + i for i in range(100)],
            "low": [95.0 + i for i in range(100)],
            "close": [102.0 + i for i in range(100)],
            "volume": 100.0,
        },
        index=dt_idx,
    )
    trades = run_strategy_simulation(strat, df, "ASSET")
    assert isinstance(trades, list)


def test_strategy_auditor_pass_and_reject():
    """Testa aprovação de estratégia causal e reprovação de estratégia com violação."""
    passed, logs = audit_strategy_causality("plugins/example_sma_cross.py")
    assert passed is True

    passed_bad, logs_bad = audit_strategy_causality("plugins/bad_future_leak.py")
    assert passed_bad is False
    assert any("Violação" in log for log in logs_bad)

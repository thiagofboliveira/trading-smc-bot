"""Testes para a Central de Integrações e Conexões Web (E1-2, E4, E6, E8-7)."""


from pathlib import Path

from smc_trader.config import load_config
from smc_trader.ui.server import SMCRequestHandler


def test_api_integrations_status(tmp_path):
    """Testa endpoint GET /api/integrations/status."""
    handler = SMCRequestHandler.__new__(SMCRequestHandler)
    handler.data_root = tmp_path
    handler.app_cfg = load_config(Path("config/default.yaml"))

    sent_data = {}

    def mock_send_json(data, status=200):
        nonlocal sent_data
        sent_data = data

    handler._send_json = mock_send_json
    handler._handle_get_integrations_status()

    assert "telegram" in sent_data
    assert "mt5" in sent_data
    assert "b3_profit" in sent_data
    assert "paper_trading" in sent_data
    assert "license" in sent_data
    assert sent_data["license"]["active"] is True


def test_api_profit_sample_and_auto_source(tmp_path):
    """Testa geração de amostra B3 WIN e auto-detecção de fonte no backtest."""
    handler = SMCRequestHandler.__new__(SMCRequestHandler)
    handler.data_root = tmp_path
    handler.app_cfg = load_config(Path("config/default.yaml"))

    sent_data = {}

    def mock_send_json(data, status=200):
        nonlocal sent_data
        sent_data = data

    handler._send_json = mock_send_json
    handler._handle_post_profit_sample({"symbol": "WIN"})

    assert sent_data.get("status") == "ok"
    assert sent_data.get("symbol") == "WIN"
    assert sent_data.get("candles") > 1000

    # Verifica se o arquivo Parquet foi criado
    parquet_file = tmp_path / "WIN_M1_profit.parquet"
    assert parquet_file.exists()

    # Verifica auto-detecção de fonte
    src = handler._get_candle_source("WIN", {})
    assert src == "profit"


def test_api_license_verify():
    """Testa verificação de licença via endpoint."""
    from smc_trader.core.license import generate_license_key

    handler = SMCRequestHandler.__new__(SMCRequestHandler)
    sent_data = {}

    def mock_send_json(data, status=200):
        nonlocal sent_data
        sent_data = data

    handler._send_json = mock_send_json
    valid_key = generate_license_key("user_b3", tier="enterprise", valid_until="2099-12-31")
    handler._handle_post_license_verify({"key": valid_key})

    assert sent_data.get("valid") is True
    assert sent_data.get("payload", {}).get("tier") == "enterprise"

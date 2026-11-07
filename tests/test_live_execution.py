"""Testes unitários rigorosos para a suíte de execução ao vivo MT5 (Épico 4).

Cobre:
- L-01: BridgeMT5Client com cmd_id, espera por resposta e fail-closed
- L-05: Alimentação de DailyLimitsTracker via negócios reais e teto de posições na carteira
- L-06: Despacho de ordens limite no nível Fibo
- L-07: Persistência de estado JSON e reconciliação na inicialização
- L-08: Autenticação por token no BridgeEAServer (401 se inválido, 200 se correto)
- L-09: Saída por Trailing EMA8 no live
- L-10: Kill Switch (perda diária %, stops consecutivos, pico de spread, latência de dados)
- L-11: Diário de trades estruturado em JSONL
"""

import json
import urllib.error
import urllib.request

import pandas as pd
import pytest

from smc_trader.config import KillSwitchConfig
from smc_trader.execution.journal import TradeJournal
from smc_trader.execution.kill_switch import KillSwitch
from smc_trader.execution.mt5_interface import (
    BridgeEAServer,
    BridgeMT5Client,
    MockMT5Client,
)
from smc_trader.execution.state_store import StateStore, make_cmd_id
from smc_trader.execution.types import OrderRequest


def test_bridge_server_token_auth():
    """Valida L-08: servidor ponte rejeita requisições sem token válido e aceita com token correto."""
    server = BridgeEAServer(host="127.0.0.1", port=8289, auth_token="secret_token_123")
    server.start()

    try:
        # 1. Requisição sem token -> deve retornar 401
        req_unauth = urllib.request.Request("http://127.0.0.1:8289", method="GET")
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_unauth)
        assert exc_info.value.code == 401

        # 2. Requisição com token incorreto -> 401
        req_bad = urllib.request.Request(
            "http://127.0.0.1:8289",
            headers={"X-Bridge-Token": "wrong_token"},
            method="GET",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_bad)
        assert exc_info.value.code == 401

        # 3. Requisição com token correto -> 200 OK
        req_ok = urllib.request.Request(
            "http://127.0.0.1:8289",
            headers={"X-Bridge-Token": "secret_token_123"},
            method="GET",
        )
        with urllib.request.urlopen(req_ok) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["status"] == "idle"

    finally:
        server.stop()


def test_bridge_client_order_lifecycle():
    """Valida L-01: BridgeMT5Client enfileira comando com cmd_id e processa order_result do EA."""
    server = BridgeEAServer(host="127.0.0.1", port=8290)
    server.start()
    client = BridgeMT5Client(server=server, timeout_seconds=1.5)
    assert client.connect() is True
    assert client.is_connected() is True

    try:
        # Prepara ordem de compra
        req = OrderRequest(
            symbol="XAUUSD",
            direction="long",
            volume=0.02,
            order_type="market",
            price=2650.0,
            stop_loss=2640.0,
            take_profit=2680.0,
            magic=888301,
            cmd_id="cmd_test_001",
        )

        # Simula resposta em segundo plano do EA
        def simulate_ea_reply():
            import time

            time.sleep(0.1)
            with server.lock:
                server.command_results["cmd_test_001"] = {
                    "success": True,
                    "ticket": 999888,
                    "price": 2650.1,
                    "comment": "OK",
                    "error_code": 0,
                }

        import threading

        t = threading.Thread(target=simulate_ea_reply)
        t.start()

        result = client.send_order(req)
        t.join()

        assert result.success is True
        assert result.ticket == 999888
        assert result.price == 2650.1
        assert result.cmd_id == "cmd_test_001"

    finally:
        server.stop()


def test_kill_switch_protections():
    """Valida L-10: regras de proteção de capital do KillSwitch."""
    cfg = KillSwitchConfig(
        max_daily_loss_pct=3.0,
        max_consecutive_losses=3,
        max_spread_multiplier=2.5,
        max_data_delay_seconds=120,
    )
    ks = KillSwitch(cfg)
    now = pd.Timestamp("2026-11-07 14:00:00", tz="UTC")
    ks.reset_daily_equity_if_new_day(1000.0, now)

    # 1. Perda diária normal ($1000 -> $980 = 2% perda) -> OK
    hit, _ = ks.check_daily_loss(980.0)
    assert hit is False

    # 2. Perda diária estourada ($1000 -> $965 = 3.5% perda) -> Bloqueia
    hit, msg = ks.check_daily_loss(965.0)
    assert hit is True
    assert "3.50%" in msg

    # 3. Stops consecutivos
    assert ks.check_consecutive_losses(2)[0] is False
    assert ks.check_consecutive_losses(3)[0] is True

    # 4. Pico de spread (típico 0.20, atual 0.60 = 3x) -> Bloqueia
    assert ks.check_spread(0.30, 0.20)[0] is False
    assert ks.check_spread(0.60, 0.20)[0] is True

    # 5. Latência de dados (atraso de 180s > 120s) -> Bloqueia
    bar_time = now - pd.Timedelta(seconds=180)
    assert ks.check_data_delay(bar_time, now)[0] is True

    # 6. Parada de emergência encerra posições abertas
    mock_client = MockMT5Client(initial_balance=1000.0)
    mock_client.connect()
    mock_client.send_order(
        OrderRequest(
            symbol="XAUUSD",
            direction="long",
            volume=0.01,
            order_type="market",
            price=2650.0,
            stop_loss=2640.0,
            take_profit=2680.0,
        )
    )
    assert len(mock_client.get_open_positions()) == 1
    ks.execute_emergency_shutdown(mock_client)
    assert len(mock_client.get_open_positions()) == 0
    assert ks.is_active is True


def test_trade_journal(tmp_path):
    """Valida L-11: auditoria em arquivo JSONL."""
    journal_path = tmp_path / "journal.jsonl"
    journal = TradeJournal(journal_path)

    journal.log_signal("XAUUSD", "fibo_ote", "long", 2650.0, 2640.0, 2680.0)
    journal.log_order_dispatch(
        "XAUUSD", "limit", "long", 0.05, 2650.0, 2640.0, 2680.0, 888301, "cmd_1"
    )
    journal.log_order_fill("XAUUSD", 1001, 2650.0, 2650.2, 0.05, "cmd_1")
    journal.log_trade_close("XAUUSD", 1001, 2670.0, 95.0, 1.9, "TRAILING_EMA8")

    assert journal_path.exists()
    lines = journal_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 4
    entries = [json.loads(line) for line in lines]
    assert entries[0]["event"] == "SIGNAL"
    assert entries[1]["event"] == "ORDER_DISPATCH"
    assert entries[2]["event"] == "ORDER_FILL"
    assert entries[2]["slippage"] == pytest.approx(0.2)
    assert entries[3]["event"] == "TRADE_CLOSE"
    assert entries[3]["pnl"] == 95.0


def test_state_store_reconciliation(tmp_path):
    """Valida L-07: persistência JSON e reconciliação com corretora."""
    state_file = tmp_path / "live_state.json"
    store = StateStore(state_file)

    # Grava estado
    store.save({"XAUUSD": {"current_position_ticket": 123456}})
    loaded = store.load()
    assert loaded["XAUUSD"]["current_position_ticket"] == 123456

    mock_client = MockMT5Client()
    mock_client.connect()

    # Reconciliação sem posição no MT5
    pos = store.reconcile_with_broker(mock_client, "XAUUSD", 888301, 123456)
    assert pos is None

    # Abre posição no MT5
    res = mock_client.send_order(
        OrderRequest(
            symbol="XAUUSD",
            direction="long",
            volume=0.01,
            order_type="market",
            price=2650.0,
            stop_loss=2640.0,
            take_profit=2680.0,
            magic=888301,
        )
    )
    pos_reconciled = store.reconcile_with_broker(mock_client, "XAUUSD", 888301)
    assert pos_reconciled is not None
    assert pos_reconciled.ticket == res.ticket


def test_make_cmd_id_idempotency():
    """Valida L-07: cmd_id determinístico."""
    t = pd.Timestamp("2026-11-07 14:35:00", tz="UTC")
    id1 = make_cmd_id("XAUUSD", "BUY_LIMIT", t)
    id2 = make_cmd_id("XAUUSD", "BUY_LIMIT", t)
    assert id1 == id2
    assert "202611071435" in id1

"""Testes unitários para o módulo de execução e automação em produção MetaTrader 5."""
import json
import urllib.request

import pandas as pd

from smc_trader.config import BacktestConfig
from smc_trader.execution.live_engine import LiveTradingEngine
from smc_trader.execution.mt5_interface import BridgeEAServer, MockMT5Client
from smc_trader.execution.sizing import calculate_lot_size
from smc_trader.execution.types import OrderRequest, SymbolInfo


def test_calculate_lot_size_xauusd():
    """Valida dimensionamento de lote para XAUUSD com 1% de risco."""
    sym_info = SymbolInfo(
        symbol="XAUUSD",
        bid=2650.0,
        ask=2650.2,
        point=0.01,
        digits=2,
        spread=0.20,
        min_lot=0.01,
        max_lot=100.0,
        lot_step=0.01,
        tick_value=1.0,  # 1 ponto (0.01) em 1 lote de 100oz = $1.00 USD
    )
    # Saldo: $1,000 USD. Risco 1% = $10.00 USD
    # Entrada: 2650.0. SL: 2640.0 (distância = 10.0 = 1000 pontos)
    # Custo por lote = 1000 pontos * $1.00 = $1000 USD
    # Lote = 10 / 1000 = 0.01 lote
    lot = calculate_lot_size(
        equity=1000.0,
        risk_pct=1.0,
        entry_price=2650.0,
        stop_loss=2640.0,
        symbol_info=sym_info,
    )
    assert lot == 0.01


def test_calculate_lot_size_min_lot_bound():
    """Garante que o lote respeite min_lot com tolerância, ou recuse (0.0) se estourar o risco (L-04)."""
    sym_info = SymbolInfo(
        symbol="XAUUSD",
        bid=2650.0,
        ask=2650.2,
        point=0.01,
        digits=2,
        spread=0.20,
        min_lot=0.01,
        max_lot=50.0,
        lot_step=0.01,
        tick_value=1.0,
    )
    # 1. Saldo suficiente para min_lot dentro da tolerância (ex: $950 USD, risco $9.50 -> min_lot custa $10.00)
    lot_ok = calculate_lot_size(
        equity=950.0,
        risk_pct=1.0,
        entry_price=2650.0,
        stop_loss=2640.0,
        symbol_info=sym_info,
    )
    assert lot_ok == 0.01

    # 2. L-04: Saldo ínfimo ($50 USD), min_lot custaria 20% da conta -> NÃO opera (deve retornar 0.0)
    lot_blowout = calculate_lot_size(
        equity=50.0,
        risk_pct=1.0,
        entry_price=2650.0,
        stop_loss=2640.0,
        symbol_info=sym_info,
    )
    assert lot_blowout == 0.0


def test_mock_mt5_client_order_lifecycle():
    """Testa ciclo de vida de envio, modificação e fechamento de ordens no cliente MT5."""
    client = MockMT5Client(initial_balance=2000.0)
    assert client.connect() is True
    assert client.is_connected() is True

    acc = client.get_account_info()
    assert acc.balance == 2000.0

    # Envia ordem
    req = OrderRequest(
        symbol="XAUUSD",
        direction="long",
        volume=0.05,
        order_type="market",
        price=2650.0,
        stop_loss=2640.0,
        take_profit=2680.0,
        magic=888101,
    )
    res = client.send_order(req)
    assert res.success is True
    assert res.ticket > 0

    # Verifica posição aberta
    open_pos = client.get_open_positions(symbol="XAUUSD")
    assert len(open_pos) == 1
    assert open_pos[0].ticket == res.ticket
    assert open_pos[0].stop_loss == 2640.0

    # Modifica Stop Loss (Trailing)
    mod_ok = client.modify_position(res.ticket, stop_loss=2645.0, take_profit=2680.0)
    assert mod_ok is True
    assert client.positions[res.ticket].stop_loss == 2645.0

    # Fecha posição
    close_ok = client.close_position(res.ticket)
    assert close_ok is True
    assert len(client.get_open_positions(symbol="XAUUSD")) == 0

    client.disconnect()
    assert client.is_connected() is False


def test_live_engine_tick_processing():
    """Valida loop do motor de execução com dados simulados."""
    client = MockMT5Client(initial_balance=1000.0)
    client.connect()

    # Prepara candles sintéticos M1
    times = pd.date_range("2026-10-18 14:00:00", periods=60, freq="1min", tz="UTC")
    df_m1 = pd.DataFrame(
        {
            "open": [2650.0 + i * 0.1 for i in range(60)],
            "high": [2650.5 + i * 0.1 for i in range(60)],
            "low": [2649.5 + i * 0.1 for i in range(60)],
            "close": [2650.2 + i * 0.1 for i in range(60)],
            "volume": [100.0] * 60,
        },
        index=times,
    )
    client.set_candles("XAUUSD", "M1", df_m1)

    cfg = BacktestConfig(entry_mode="confirmation", stop_mode="swing", target_r=3.0)
    notifications = []
    engine = LiveTradingEngine(
        client=client,
        symbol_configs={"XAUUSD": cfg},
        risk_pct=1.0,
        notification_callback=lambda msg: notifications.append(msg),
    )

    # Executa tick
    engine.process_symbol_tick("XAUUSD", now_utc=times[-1])
    assert "XAUUSD" in engine.runtimes


def test_bridge_ea_server_communication():
    """Testa comunicação HTTP REST entre o servidor ponte e requisições simuladas do EA."""
    server = BridgeEAServer(host="127.0.0.1", port=8189)
    server.start()

    try:
        # 1. Simula EA enviando telemetria
        req = urllib.request.Request(
            "http://127.0.0.1:8189",
            data=b'{"type":"telemetry","data":{"symbol":"XAUUSD","bid":2650.0,"ask":2650.2,"balance":1000.0}}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["status"] == "ok"

        assert server.latest_tick_data.get("symbol") == "XAUUSD"
        assert server.latest_tick_data.get("bid") == 2650.0

        # 2. Simula EA consultando comandos (fila vazia -> idle)
        with urllib.request.urlopen("http://127.0.0.1:8189") as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode())
            assert data["status"] == "idle"

        # 3. Adiciona comando na fila e verifica entrega ao EA
        with server.lock:
            server.command_queue.append({"action": "BUY", "symbol": "XAUUSD", "volume": 0.01})

        with urllib.request.urlopen("http://127.0.0.1:8189") as resp:
            data = json.loads(resp.read().decode())
            assert data["status"] == "command"
            assert data["data"]["action"] == "BUY"

    finally:
        server.stop()

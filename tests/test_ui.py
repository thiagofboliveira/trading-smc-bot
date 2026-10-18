import json
import threading
import time
import urllib.request
from pathlib import Path
import pytest

from smc_trader.config import load_config
from smc_trader.ui.server import SMCRequestHandler, ThreadingHTTPServer


@pytest.fixture(scope="module")
def ui_server():
    cfg = load_config(Path("config/default.yaml"))
    SMCRequestHandler.app_cfg = cfg
    SMCRequestHandler.data_root = Path("data")

    # Inicia em porta efêmera (0 escolhe uma porta livre pelo SO)
    server = ThreadingHTTPServer(("127.0.0.1", 0), SMCRequestHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    yield f"http://127.0.0.1:{port}"

    server.shutdown()
    server.server_close()


def test_ui_index_html(ui_server):
    req = urllib.request.Request(f"{ui_server}/")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        content = resp.read().decode("utf-8")
        assert "SMC Trade Assistant" in content
        assert "plotly-equity" in content


def test_ui_api_symbols(ui_server):
    req = urllib.request.Request(f"{ui_server}/api/symbols")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "symbols" in data
        assert len(data["symbols"]) > 0
        symbols_names = [s["symbol"] for s in data["symbols"]]
        assert "XAUUSD" in symbols_names


def test_ui_api_backtest(ui_server):
    payload = {
        "symbol": "XAUUSD",
        "start": "2026-09-01T00:00:00Z",
        "end": "2026-09-07T00:00:00Z",
        "blocks_filter": ["OB"],
        "entry_mode": "confirmation",
        "stop_mode": "swing",
        "target_r": 3.0,
        "trailing": {"mode": "none"},
        "confluence": {"use_ema80": False},
        "limits_enabled": False,
    }
    req = urllib.request.Request(
        f"{ui_server}/api/backtest",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "metrics" in data
        assert "trades" in data
        assert "equity_curve" in data
        assert len(data["equity_curve"]) > 0


def test_ui_api_chart(ui_server):
    payload = {
        "symbol": "XAUUSD",
        "start": "2026-09-01T00:00:00Z",
        "end": "2026-09-02T00:00:00Z",
        "tf": "M15",
        "blocks_filter": ["OB", "FVOB", "BB"],
    }
    req = urllib.request.Request(
        f"{ui_server}/api/chart",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "chart" in data
        assert "data" in data["chart"]
        assert "layout" in data["chart"]

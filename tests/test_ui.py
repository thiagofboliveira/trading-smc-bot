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
        "start": "2026-09-15T00:00:00Z",
        "end": "2026-09-22T00:00:00Z",
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
        "start": "2026-09-15T00:00:00Z",
        "end": "2026-09-16T00:00:00Z",
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


def test_ui_api_backtest_fibo_trap(ui_server):
    payload = {
        "model": "fibo_trap_mme8",
        "symbol": "NAS100",
        "start": "2024-01-01T00:00:00Z",
        "end": "2024-03-01T00:00:00Z",
        "macro_tf": "M15",
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
        assert data["symbol"] == "NAS100"
        assert data["macro_tf"] == "M15"


def test_ui_api_backtest_trend_follower(ui_server):
    payload = {
        "model": "trend_follower_mme20",
        "symbol": "NAS100",
        "start": "2024-01-01T00:00:00Z",
        "end": "2024-03-01T00:00:00Z",
        "macro_tf": "M15",
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
        assert data["symbol"] == "NAS100"


def test_ui_api_backtest_d1_mean_reversion(ui_server):
    payload = {
        "model": "d1_mean_reversion",
        "symbol": "NAS100",
        "start": "2021-01-01T00:00:00Z",
        "end": "2024-01-01T00:00:00Z",
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
        assert data["macro_tf"] == "D1"
        assert data["metrics"]["total_trades"] > 0


def test_ui_api_backtest_turtle_trend(ui_server):
    payload = {
        "model": "turtle_trend_20_10",
        "symbol": "NAS100",
        "start": "2021-01-01T00:00:00Z",
        "end": "2024-01-01T00:00:00Z",
        "macro_tf": "D1",
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
        assert data["macro_tf"] == "D1"
        assert data["metrics"]["total_trades"] > 0


def test_ui_api_backtest_smc_macro_micro(ui_server):
    payload = {
        "model": "smc_macro_micro",
        "symbol": "NAS100",
        "start": "2024-01-01T00:00:00Z",
        "end": "2024-06-01T00:00:00Z",
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
        assert data["macro_tf"] == "H1"


def test_ui_api_backtest_orb(ui_server):
    payload = {
        "model": "orb_15_ny",
        "symbol": "NAS100",
        "start": "2024-01-01T00:00:00Z",
        "end": "2024-03-01T00:00:00Z",
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
        assert data["macro_tf"] == "M15"
        assert data["metrics"]["total_trades"] > 0


def test_ui_api_chart_with_indicators(ui_server):
    payload = {
        "model": "fibo_trap_mme8",
        "symbol": "NAS100",
        "start": "2024-01-01T00:00:00Z",
        "end": "2024-01-05T00:00:00Z",
        "tf": "M15",
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
        trace_names = [t.get("name") for t in data["chart"]["data"] if "name" in t]
        assert "MME 8" in trace_names
        assert "MME 20" in trace_names
        assert "MME 80" in trace_names
        assert "MME 200" in trace_names


def test_ui_api_company_and_employees(ui_server):
    """Testa endpoints do Telão da Empresa e Funcionários (E5)."""
    # 1. /api/company
    req_comp = urllib.request.Request(f"{ui_server}/api/company")
    with urllib.request.urlopen(req_comp) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "source" in data
        assert "total_virtual_capital" in data
        assert "active_employees" in data

    # 2. /api/employees
    req_emp = urllib.request.Request(f"{ui_server}/api/employees")
    with urllib.request.urlopen(req_emp) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert "employees" in data
        assert len(data["employees"]) >= 8
        emp_ids = [e["id"] for e in data["employees"]]
        assert "arthur-d1-rev" in emp_ids
        assert "victor-orb-ny" in emp_ids

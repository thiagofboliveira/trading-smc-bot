"""Interface de comunicação com o MetaTrader 5 suportando múltiplos backends:
1. Native MT5 (via pacote Python oficial MetaTrader5 no Windows ou Wine).
2. Bridge EA (via microservidor HTTP/REST local compatível com qualquer SO e VPS).
3. Mock MT5 (para testes automatizados e simulação em dry-run).
"""
import abc
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
import pandas as pd

from smc_trader.execution.types import (
    AccountInfo,
    LivePosition,
    OrderRequest,
    OrderResult,
    SymbolInfo,
)

logger = logging.getLogger("smc.execution")


class BaseMT5Client(abc.ABC):
    """Interface abstrata para clientes MT5."""

    @abc.abstractmethod
    def connect(self) -> bool:
        pass

    @abc.abstractmethod
    def disconnect(self) -> None:
        pass

    @abc.abstractmethod
    def is_connected(self) -> bool:
        pass

    @abc.abstractmethod
    def get_account_info(self) -> AccountInfo:
        pass

    @abc.abstractmethod
    def get_symbol_info(self, symbol: str) -> SymbolInfo:
        pass

    @abc.abstractmethod
    def get_candles(self, symbol: str, timeframe: str = "M1", count: int = 300) -> pd.DataFrame:
        pass

    @abc.abstractmethod
    def send_order(self, order: OrderRequest) -> OrderResult:
        pass

    @abc.abstractmethod
    def modify_position(self, ticket: int, stop_loss: float, take_profit: float) -> bool:
        pass

    @abc.abstractmethod
    def close_position(self, ticket: int) -> bool:
        pass

    @abc.abstractmethod
    def get_open_positions(
        self, symbol: str | None = None, magic: int | None = None
    ) -> list[LivePosition]:
        pass


class MockMT5Client(BaseMT5Client):
    """Cliente simulador em memória para testes unitários e modo Dry-Run."""

    def __init__(self, initial_balance: float = 1000.0) -> None:
        self._connected = False
        self.account = AccountInfo(
            balance=initial_balance,
            equity=initial_balance,
            margin=0.0,
            free_margin=initial_balance,
            currency="USD",
        )
        self.symbols: dict[str, SymbolInfo] = {
            "XAUUSD": SymbolInfo("XAUUSD", bid=2650.0, ask=2650.2, point=0.01, digits=2, spread=0.20, tick_value=1.0),
            "NAS100": SymbolInfo("NAS100", bid=19800.0, ask=19801.5, point=0.1, digits=1, spread=1.5, tick_value=1.0),
            "EURUSD": SymbolInfo("EURUSD", bid=1.0850, ask=1.08508, point=0.00001, digits=5, spread=0.00008, tick_value=1.0),
        }
        self.positions: dict[int, LivePosition] = {}
        self.candles_db: dict[tuple[str, str], pd.DataFrame] = {}
        self.ticket_seq = 100000

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def get_account_info(self) -> AccountInfo:
        return self.account

    def get_symbol_info(self, symbol: str) -> SymbolInfo:
        if symbol not in self.symbols:
            self.symbols[symbol] = SymbolInfo(symbol, bid=100.0, ask=100.1, point=0.01, digits=2, spread=0.1)
        return self.symbols[symbol]

    def set_candles(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        self.candles_db[(symbol, timeframe)] = df

    def get_candles(self, symbol: str, timeframe: str = "M1", count: int = 300) -> pd.DataFrame:
        df = self.candles_db.get((symbol, timeframe), pd.DataFrame())
        return df.tail(count)

    def send_order(self, order: OrderRequest) -> OrderResult:
        self.ticket_seq += 1
        ticket = self.ticket_seq
        pos = LivePosition(
            ticket=ticket,
            symbol=order.symbol,
            direction=order.direction,
            volume=order.volume,
            open_price=order.price,
            current_price=order.price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            open_time=pd.Timestamp.now(tz="UTC"),
            initial_risk=abs(order.price - order.stop_loss),
            magic=order.magic,
            comment=order.comment,
        )
        self.positions[ticket] = pos
        return OrderResult(success=True, ticket=ticket, price=order.price, volume=order.volume, comment="OK")

    def modify_position(self, ticket: int, stop_loss: float, take_profit: float) -> bool:
        if ticket in self.positions:
            self.positions[ticket].stop_loss = stop_loss
            self.positions[ticket].take_profit = take_profit
            return True
        return False

    def close_position(self, ticket: int) -> bool:
        if ticket in self.positions:
            del self.positions[ticket]
            return True
        return False

    def get_open_positions(
        self, symbol: str | None = None, magic: int | None = None
    ) -> list[LivePosition]:
        res = list(self.positions.values())
        if symbol is not None:
            res = [p for p in res if p.symbol == symbol]
        if magic is not None:
            res = [p for p in res if p.magic == magic]
        return res


class BridgeEAServer:
    """Servidor HTTP REST local para conectar com o Expert Advisor SMC_Bridge_EA.mq5."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8089) -> None:
        self.host = host
        self.port = port
        self.server: HTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.latest_tick_data: dict[str, Any] = {}
        self.command_queue: list[dict[str, Any]] = []
        self.command_results: dict[str, Any] = {}
        self.lock = threading.Lock()

    def start(self) -> None:
        parent = self

        class RequestHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass  # Silencia logs padrão de HTTP para não poluir o terminal

            def do_GET(self) -> None:
                # O EA faz GET para polling de novas ordens/comandos
                with parent.lock:
                    if parent.command_queue:
                        cmd = parent.command_queue.pop(0)
                        resp = json.dumps({"status": "command", "data": cmd})
                    else:
                        resp = json.dumps({"status": "idle"})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(resp.encode("utf-8"))

            def do_POST(self) -> None:
                # O EA envia cotações atuais, contas ou confirmação de ordem
                length = int(self.headers.get("Content-Length", 0))
                raw_body = self.rfile.read(length).decode("utf-8")
                try:
                    payload = json.loads(raw_body)
                except Exception:
                    payload = {}

                action = payload.get("type", "")
                with parent.lock:
                    if action == "telemetry":
                        parent.latest_tick_data = payload.get("data", {})
                    elif action == "order_result":
                        cmd_id = payload.get("cmd_id", "")
                        parent.command_results[cmd_id] = payload.get("result", {})

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')

        self.server = HTTPServer((self.host, self.port), RequestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        logger.info(f"SMC Bridge Server rodando em http://{self.host}:{self.port}")

    def stop(self) -> None:
        if self.server:
            self.server.shutdown()
            self.server = None

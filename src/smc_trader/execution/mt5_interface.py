"""Interface de comunicação com o MetaTrader 5 suportando múltiplos backends:
1. Native MT5 (via pacote Python oficial MetaTrader5 no Windows ou Wine).
2. Bridge MT5 Client (via microservidor HTTP/REST local e EA MQL5 para Linux/VPS).
3. Mock MT5 (para testes automatizados e simulação em dry-run).
"""

import abc
import json
import logging
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

import pandas as pd

from smc_trader.execution.types import (
    AccountInfo,
    ClosedTradeInfo,
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
    def get_candles(
        self, symbol: str, timeframe: str = "M1", count: int = 300
    ) -> pd.DataFrame:
        pass

    @abc.abstractmethod
    def send_order(self, order: OrderRequest) -> OrderResult:
        pass

    @abc.abstractmethod
    def modify_position(
        self, ticket: int, stop_loss: float, take_profit: float
    ) -> bool:
        pass

    @abc.abstractmethod
    def close_position(self, ticket: int) -> bool:
        pass

    @abc.abstractmethod
    def cancel_order(self, ticket: int) -> bool:
        pass

    @abc.abstractmethod
    def get_open_positions(
        self, symbol: str | None = None, magic: int | None = None
    ) -> list[LivePosition]:
        pass

    @abc.abstractmethod
    def get_closed_deals(
        self, symbol: str | None = None, days: int = 1
    ) -> list[ClosedTradeInfo]:
        pass

    def get_pending_orders(
        self, symbol: str | None = None, magic: int | None = None
    ) -> list[int]:
        """Tickets das ordens pendentes. Backends que não sabem listar devolvem []."""
        return []


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
            trade_mode="demo",
        )
        self.symbols: dict[str, SymbolInfo] = {
            "XAUUSD": SymbolInfo(
                "XAUUSD",
                bid=2650.0,
                ask=2650.2,
                point=0.01,
                digits=2,
                spread=0.20,
                tick_value=1.0,
            ),
            "NAS100": SymbolInfo(
                "NAS100",
                bid=19800.0,
                ask=19801.5,
                point=0.1,
                digits=1,
                spread=1.5,
                tick_value=1.0,
            ),
            "EURUSD": SymbolInfo(
                "EURUSD",
                bid=1.0850,
                ask=1.08508,
                point=0.00001,
                digits=5,
                spread=0.00008,
                tick_value=1.0,
            ),
        }
        self.positions: dict[int, LivePosition] = {}
        self.orders: dict[int, OrderRequest] = {}
        self.order_after: dict[int, pd.Timestamp | None] = {}
        self.closed_deals: list[ClosedTradeInfo] = []
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
            self.symbols[symbol] = SymbolInfo(
                symbol, bid=100.0, ask=100.1, point=0.01, digits=2, spread=0.1
            )
        return self.symbols[symbol]

    def set_candles(self, symbol: str, timeframe: str, df: pd.DataFrame) -> None:
        self.candles_db[(symbol, timeframe)] = df
        if timeframe == "M1":
            self._fill_limit_orders(symbol, df)

    def _fill_limit_orders(self, symbol: str, df: pd.DataFrame) -> None:
        """Preenche ordens limite pelo toque das barras posteriores à ordem (dados são bid).

        Compra: o ask (bid + spread) cai até o preço. Venda: o bid sobe até o preço.
        """
        spread = self.get_symbol_info(symbol).ask - self.get_symbol_info(symbol).bid
        for ticket, order in list(self.orders.items()):
            if order.symbol != symbol:
                continue
            after = self.order_after.get(ticket)
            bars = df if after is None else df[df.index > after]
            if order.direction == "long":
                hit = bars[bars["low"] + spread <= order.price]
            else:
                hit = bars[bars["high"] >= order.price]
            if hit.empty:
                continue
            del self.orders[ticket]
            self.order_after.pop(ticket, None)
            self.positions[ticket] = LivePosition(
                ticket=ticket,
                symbol=symbol,
                direction=order.direction,
                volume=order.volume,
                open_price=order.price,
                current_price=order.price,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                open_time=hit.index[0],
                initial_risk=abs(order.price - order.stop_loss),
                magic=order.magic,
                comment=order.comment,
                cmd_id=order.cmd_id,
            )

    def get_candles(
        self, symbol: str, timeframe: str = "M1", count: int = 300
    ) -> pd.DataFrame:
        df = self.candles_db.get((symbol, timeframe), pd.DataFrame())
        return df.tail(count)

    def send_order(self, order: OrderRequest) -> OrderResult:
        self.ticket_seq += 1
        ticket = self.ticket_seq

        if order.order_type == "limit":
            self.orders[ticket] = order
            m1 = self.candles_db.get((order.symbol, "M1"))
            # a barra corrente (última linha) ainda está em formação: vale a partir dela
            self.order_after[ticket] = (
                m1.index[-2] if m1 is not None and len(m1) >= 2 else None
            )
            return OrderResult(
                success=True,
                ticket=ticket,
                price=order.price,
                volume=order.volume,
                comment="LIMIT_PLACED",
                cmd_id=order.cmd_id,
            )

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
            cmd_id=order.cmd_id,
        )
        self.positions[ticket] = pos
        return OrderResult(
            success=True,
            ticket=ticket,
            price=order.price,
            volume=order.volume,
            comment="OK",
            cmd_id=order.cmd_id,
        )

    def modify_position(
        self, ticket: int, stop_loss: float, take_profit: float
    ) -> bool:
        if ticket in self.positions:
            self.positions[ticket].stop_loss = stop_loss
            self.positions[ticket].take_profit = take_profit
            return True
        return False

    def close_position(self, ticket: int) -> bool:
        if ticket in self.positions:
            pos = self.positions.pop(ticket)
            # Simula fechamento registrando nos negócios concluídos
            close_price = pos.current_price
            sign = 1 if pos.direction == "long" else -1
            pnl = sign * (close_price - pos.open_price) * pos.volume * 100.0
            r_mult = (
                (sign * (close_price - pos.open_price) / pos.initial_risk)
                if pos.initial_risk > 0
                else 0.0
            )
            deal = ClosedTradeInfo(
                ticket=ticket,
                symbol=pos.symbol,
                direction=pos.direction,
                volume=pos.volume,
                open_price=pos.open_price,
                close_price=close_price,
                open_time=pos.open_time,
                close_time=pd.Timestamp.now(tz="UTC"),
                pnl=pnl,
                r_multiple=r_mult,
                magic=pos.magic,
                comment=pos.comment,
                position_id=ticket,
            )
            self.closed_deals.append(deal)
            return True
        return False

    def cancel_order(self, ticket: int) -> bool:
        if ticket in self.orders:
            del self.orders[ticket]
            self.order_after.pop(ticket, None)
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

    def get_closed_deals(
        self, symbol: str | None = None, days: int = 1
    ) -> list[ClosedTradeInfo]:
        deals = list(self.closed_deals)
        if symbol is not None:
            deals = [d for d in deals if d.symbol == symbol]
        return deals

    def get_pending_orders(
        self, symbol: str | None = None, magic: int | None = None
    ) -> list[int]:
        return [
            t
            for t, o in self.orders.items()
            if (symbol is None or o.symbol == symbol)
            and (magic is None or o.magic == magic)
        ]


class BridgeEAServer:
    """Servidor HTTP REST local para conectar com o Expert Advisor SMC_Bridge_EA.mq5."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8089,
        auth_token: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.auth_token = auth_token
        self.server: HTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.latest_tick_data: dict[str, Any] = {}
        self.latest_account_data: dict[str, Any] = {}
        self.latest_positions_data: list[dict[str, Any]] = []
        self.latest_deals_data: list[dict[str, Any]] = []
        self.command_queue: list[dict[str, Any]] = []
        self.command_results: dict[str, Any] = {}
        self.last_heartbeat_time: float = 0.0
        self.lock = threading.Lock()

    def _check_auth(self, handler: BaseHTTPRequestHandler) -> bool:
        if not self.auth_token:
            return True
        token_hdr = handler.headers.get("X-Bridge-Token", "")
        auth_hdr = handler.headers.get("Authorization", "")
        if auth_hdr.startswith("Bearer "):
            auth_hdr = auth_hdr[7:]
        return token_hdr == self.auth_token or auth_hdr == self.auth_token

    def start(self) -> None:
        parent = self

        class RequestHandler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                pass  # Silencia logs padrão HTTP para não poluir terminal

            def do_GET(self) -> None:
                if not parent._check_auth(self):
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'{"error": "Unauthorized"}')
                    return

                with parent.lock:
                    parent.last_heartbeat_time = time.time()
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
                if not parent._check_auth(self):
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'{"error": "Unauthorized"}')
                    return

                length = int(self.headers.get("Content-Length", 0))
                raw_body = self.rfile.read(length).decode("utf-8")
                try:
                    payload = json.loads(raw_body)
                except Exception:
                    payload = {}

                action = payload.get("type", "")
                with parent.lock:
                    parent.last_heartbeat_time = time.time()
                    if action == "telemetry":
                        data = payload.get("data", {})
                        parent.latest_tick_data.update(data)
                        sym = data.get("symbol", "")
                        if sym:
                            parent.latest_tick_data[sym] = data
                        if "balance" in data:
                            parent.latest_account_data = data
                    elif action == "positions":
                        parent.latest_positions_data = payload.get("data", [])
                    elif action == "deals":
                        parent.latest_deals_data.extend(payload.get("data", []))
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


class BridgeMT5Client(BaseMT5Client):
    """Cliente MT5 funcional que opera através do BridgeEAServer e do EA MQL5 (L-01, L-08)."""

    def __init__(
        self,
        server: BridgeEAServer,
        timeout_seconds: float = 6.0,
        candles_provider: Any = None,
    ) -> None:
        self.server = server
        self.timeout = timeout_seconds
        self.candles_provider = candles_provider
        self._connected = False

    def connect(self) -> bool:
        if self.server.server is not None:
            self._connected = True
            return True
        return False

    def disconnect(self) -> None:
        self._connected = False

    def is_connected(self) -> bool:
        # Considera conectado se o servidor estiver rodando e recebeu sinal nos últimos 30 segundos
        if not self._connected or self.server.server is None:
            return False
        if self.server.last_heartbeat_time == 0.0:
            return True  # Aguardando primeiro handshake
        return (time.time() - self.server.last_heartbeat_time) < 30.0

    def get_account_info(self) -> AccountInfo:
        with self.server.lock:
            data = self.server.latest_account_data
        balance = float(data.get("balance", 1000.0))
        equity = float(data.get("equity", balance))
        return AccountInfo(
            balance=balance,
            equity=equity,
            margin=float(data.get("margin", 0.0)),
            free_margin=float(data.get("free_margin", equity)),
            currency=str(data.get("currency", "USD")),
            login=int(data.get("login", 0)),
            server=str(data.get("server", "")),
            trade_mode=str(data.get("trade_mode", "unknown")),
        )

    def get_symbol_info(self, symbol: str) -> SymbolInfo:
        with self.server.lock:
            data = self.server.latest_tick_data.get(symbol, {})
        bid = float(data.get("bid", 100.0))
        ask = float(data.get("ask", bid + 0.1))
        spread = float(data.get("spread", ask - bid))
        point = float(data.get("point", 0.01))
        digits = int(data.get("digits", 2))
        return SymbolInfo(
            symbol=symbol,
            bid=bid,
            ask=ask,
            point=point,
            digits=digits,
            spread=spread,
            min_lot=float(data.get("min_lot", 0.01)),
            max_lot=float(data.get("max_lot", 100.0)),
            lot_step=float(data.get("lot_step", 0.01)),
            tick_value=float(data.get("tick_value", 1.0)),
            tick_size=float(data.get("tick_size", point)),
        )

    def get_candles(
        self, symbol: str, timeframe: str = "M1", count: int = 300
    ) -> pd.DataFrame:
        if self.candles_provider is not None:
            return self.candles_provider(symbol, timeframe, count)
        return pd.DataFrame()

    def _wait_for_result(self, cmd_id: str) -> dict[str, Any] | None:
        start_t = time.time()
        while time.time() - start_t < self.timeout:
            with self.server.lock:
                if cmd_id in self.server.command_results:
                    return self.server.command_results.pop(cmd_id)
            time.sleep(0.05)
        # Timeout: remove da fila para evitar execução atrasada pelo EA
        with self.server.lock:
            self.server.command_queue = [
                c for c in self.server.command_queue if c.get("cmd_id") != cmd_id
            ]
        return None

    def send_order(self, order: OrderRequest) -> OrderResult:
        cmd_id = order.cmd_id or f"ord_{uuid.uuid4().hex[:10]}"
        action = "BUY" if order.direction == "long" else "SELL"
        if order.order_type == "limit":
            action = f"{action}_LIMIT"

        cmd = {
            "action": action,
            "symbol": order.symbol,
            "volume": order.volume,
            "price": order.price,
            "sl": order.stop_loss,
            "tp": order.take_profit,
            "magic": order.magic,
            "comment": order.comment,
            "cmd_id": cmd_id,
        }
        with self.server.lock:
            self.server.command_queue.append(cmd)

        res_dict = self._wait_for_result(cmd_id)
        if res_dict is None:
            return OrderResult(
                success=False,
                comment="TIMEOUT_WAITING_EA_RESULT",
                error_code=-1,
                cmd_id=cmd_id,
            )

        success = bool(res_dict.get("success", False))
        ticket = int(res_dict.get("ticket", 0))
        price = float(res_dict.get("price", order.price))
        comment = str(res_dict.get("comment", "OK" if success else "REJECTED"))
        err_code = int(res_dict.get("error_code", 0 if success else 1))

        return OrderResult(
            success=success,
            ticket=ticket,
            price=price,
            volume=order.volume,
            comment=comment,
            error_code=err_code,
            cmd_id=cmd_id,
        )

    def modify_position(
        self, ticket: int, stop_loss: float, take_profit: float
    ) -> bool:
        cmd_id = f"mod_{uuid.uuid4().hex[:10]}"
        cmd = {
            "action": "MODIFY",
            "ticket": ticket,
            "sl": stop_loss,
            "tp": take_profit,
            "cmd_id": cmd_id,
        }
        with self.server.lock:
            self.server.command_queue.append(cmd)

        res_dict = self._wait_for_result(cmd_id)
        return bool(res_dict and res_dict.get("success", False))

    def close_position(self, ticket: int) -> bool:
        cmd_id = f"cls_{uuid.uuid4().hex[:10]}"
        cmd = {"action": "CLOSE", "ticket": ticket, "cmd_id": cmd_id}
        with self.server.lock:
            self.server.command_queue.append(cmd)

        res_dict = self._wait_for_result(cmd_id)
        return bool(res_dict and res_dict.get("success", False))

    def cancel_order(self, ticket: int) -> bool:
        cmd_id = f"can_{uuid.uuid4().hex[:10]}"
        cmd = {"action": "CANCEL", "ticket": ticket, "cmd_id": cmd_id}
        with self.server.lock:
            self.server.command_queue.append(cmd)

        res_dict = self._wait_for_result(cmd_id)
        return bool(res_dict and res_dict.get("success", False))

    def get_open_positions(
        self, symbol: str | None = None, magic: int | None = None
    ) -> list[LivePosition]:
        with self.server.lock:
            raw_list = list(self.server.latest_positions_data)

        positions = []
        for p in raw_list:
            pos_sym = p.get("symbol", "")
            pos_magic = int(p.get("magic", 0))
            if symbol is not None and pos_sym != symbol:
                continue
            if magic is not None and pos_magic != magic:
                continue
            positions.append(
                LivePosition(
                    ticket=int(p.get("ticket", 0)),
                    symbol=pos_sym,
                    direction=p.get("direction", "long"),
                    volume=float(p.get("volume", 0.01)),
                    open_price=float(p.get("open_price", 0.0)),
                    current_price=float(p.get("current_price", 0.0)),
                    stop_loss=float(p.get("stop_loss", 0.0)),
                    take_profit=float(p.get("take_profit", 0.0)),
                    open_time=pd.Timestamp(p.get("open_time", pd.Timestamp.now(tz="UTC"))),
                    initial_risk=float(p.get("initial_risk", 0.0)),
                    magic=pos_magic,
                    comment=str(p.get("comment", "")),
                )
            )
        return positions

    def get_closed_deals(
        self, symbol: str | None = None, days: int = 1
    ) -> list[ClosedTradeInfo]:
        with self.server.lock:
            raw_deals = list(self.server.latest_deals_data)

        deals = []
        for d in raw_deals:
            d_sym = d.get("symbol", "")
            if symbol is not None and d_sym != symbol:
                continue
            deals.append(
                ClosedTradeInfo(
                    ticket=int(d.get("ticket", 0)),
                    symbol=d_sym,
                    direction=d.get("direction", "long"),
                    volume=float(d.get("volume", 0.01)),
                    open_price=float(d.get("open_price", 0.0)),
                    close_price=float(d.get("close_price", 0.0)),
                    open_time=pd.Timestamp(d.get("open_time", pd.Timestamp.now(tz="UTC"))),
                    close_time=pd.Timestamp(d.get("close_time", pd.Timestamp.now(tz="UTC"))),
                    pnl=float(d.get("pnl", 0.0)),
                    r_multiple=float(d.get("r_multiple", 0.0)),
                    magic=int(d.get("magic", 0)),
                    comment=str(d.get("comment", "")),
                    position_id=int(d.get("position_id", d.get("ticket", 0))),
                )
            )
        return deals


class NativeMT5Client(BaseMT5Client):
    """Cliente nativo via pacote oficial MetaTrader5 no Windows ou Wine.

    Fuso horário: o terminal devolve os horários de candles, posições e negócios no fuso
    do SERVIDOR da corretora (tipicamente UTC+2/UTC+3 com horário de verão), em segundos
    como se fossem UTC. Este cliente converte tudo para UTC real subtraindo o deslocamento
    do servidor. O deslocamento vem de `server_utc_offset_hours` (fixo, recomendado) ou é
    estimado pelo tick do símbolo (arredondado a 30 min), aceito só quando o horário do
    tick MUDOU desde a consulta anterior (mercado ativo): um tick parado, cuja idade caia
    perto de um múltiplo de 30 min, daria um fuso errado. Sem deslocamento conhecido,
    `get_candles` devolve vazio: o motor não opera com horário errado (fail-closed).
    """

    # Tick considerado fresco para estimar o fuso: atraso de até 2 min em relação ao relógio
    _MAX_TICK_AGE_S = 120
    _MAX_TICK_LEAD_S = 5

    def __init__(
        self,
        login: int = 0,
        password: str = "",
        server: str = "",
        server_utc_offset_hours: float | None = None,
    ) -> None:
        self.login = login
        self.password = password
        self.server = server
        self._connected = False
        self._mt5: Any = None
        self._fixed_offset_s: int | None = (
            int(round(server_utc_offset_hours * 3600))
            if server_utc_offset_hours is not None
            else None
        )
        self._offset_s: int | None = None
        self._last_tick_time: dict[str, int] = {}

    def connect(self) -> bool:
        try:
            import MetaTrader5 as mt5  # type: ignore

            self._mt5 = mt5
        except ImportError as exc:
            raise RuntimeError(
                "Pacote oficial 'MetaTrader5' não encontrado ou não suportado no ambiente nativo Linux. "
                "Para execução nativa no Linux, use BridgeMT5Client com o Expert Advisor SMC_Bridge_EA.mq5."
            ) from exc

        if not self._mt5.initialize():
            logger.error(f"Falha ao inicializar MT5 nativo: {self._mt5.last_error()}")
            return False

        if self.login > 0:
            authorized = self._mt5.login(
                self.login, password=self.password, server=self.server
            )
            if not authorized:
                logger.error(f"Falha de login MT5: {self._mt5.last_error()}")
                return False

        self._connected = True
        return True

    def disconnect(self) -> None:
        if self._mt5 and self._connected:
            self._mt5.shutdown()
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------ fuso horário
    @staticmethod
    def estimate_offset_seconds(
        tick_server_time_s: float, now_utc_s: float
    ) -> int | None:
        """Deslocamento servidor-UTC a partir de um tick, ou None se o tick não for fresco."""
        diff = tick_server_time_s - now_utc_s
        offset = int(round(diff / 1800.0)) * 1800
        residual = diff - offset
        if not (
            -NativeMT5Client._MAX_TICK_AGE_S
            <= residual
            <= NativeMT5Client._MAX_TICK_LEAD_S
        ):
            return None
        if not (-12 * 3600 <= offset <= 14 * 3600):
            return None
        return offset

    def server_utc_offset_seconds(self, symbol: str | None = None) -> int | None:
        """Deslocamento do servidor em segundos (servidor = UTC + deslocamento)."""
        if self._fixed_offset_s is not None:
            return self._fixed_offset_s
        if symbol and self._mt5 is not None:
            tick = self._mt5.symbol_info_tick(symbol)
            tick_t = int(getattr(tick, "time", 0) or 0) if tick is not None else 0
            prev_t = self._last_tick_time.get(symbol)
            if tick_t:
                self._last_tick_time[symbol] = tick_t
            if tick_t and prev_t is not None and tick_t != prev_t:
                est = self.estimate_offset_seconds(float(tick_t), time.time())
                if est is not None:
                    if self._offset_s is not None and est != self._offset_s:
                        logger.warning(
                            "Fuso do servidor MT5 mudou de %+.1fh para %+.1fh (horário de verão?)",
                            self._offset_s / 3600,
                            est / 3600,
                        )
                    self._offset_s = est
        return self._offset_s

    def _to_utc(self, server_seconds: Any, offset_s: int) -> Any:
        return pd.to_datetime(server_seconds - offset_s, unit="s", utc=True)

    def _require_offset(self, symbol: str | None = None) -> int | None:
        off = self.server_utc_offset_seconds(symbol)
        if off is None:
            logger.error(
                "Fuso do servidor MT5 desconhecido (sem tick fresco). Informe "
                "server_utc_offset_hours ou aguarde o mercado abrir; operações bloqueadas."
            )
        return off

    # ------------------------------------------------------------------ conta e símbolo
    def get_account_info(self) -> AccountInfo:
        if not self._connected or not self._mt5:
            raise RuntimeError("MT5 nativo desconectado")
        acc = self._mt5.account_info()
        if acc is None:
            raise RuntimeError(f"Falha ao ler conta: {self._mt5.last_error()}")
        trade_mode = {0: "demo", 1: "contest", 2: "real"}.get(
            int(getattr(acc, "trade_mode", -1)), "unknown"
        )
        return AccountInfo(
            balance=acc.balance,
            equity=acc.equity,
            margin=acc.margin,
            free_margin=acc.margin_free,
            currency=acc.currency,
            login=acc.login,
            server=acc.server,
            trade_mode=trade_mode,
        )

    def get_symbol_info(self, symbol: str) -> SymbolInfo:
        if not self._connected or not self._mt5:
            raise RuntimeError("MT5 nativo desconectado")
        s = self._mt5.symbol_info(symbol)
        if s is None:
            raise RuntimeError(f"Símbolo {symbol} não encontrado no MT5")
        return SymbolInfo(
            symbol=symbol,
            bid=s.bid,
            ask=s.ask,
            point=s.point,
            digits=s.digits,
            spread=s.spread * s.point,
            min_lot=s.volume_min,
            max_lot=s.volume_max,
            lot_step=s.volume_step,
            tick_value=s.trade_tick_value,
            tick_size=s.trade_tick_size,
        )

    def get_candles(
        self, symbol: str, timeframe: str = "M1", count: int = 300
    ) -> pd.DataFrame:
        if not self._connected or not self._mt5:
            return pd.DataFrame()
        offset = self._require_offset(symbol)
        if offset is None:
            return pd.DataFrame()
        tf_map = {
            "M1": self._mt5.TIMEFRAME_M1,
            "M5": self._mt5.TIMEFRAME_M5,
            "M15": self._mt5.TIMEFRAME_M15,
            "H1": self._mt5.TIMEFRAME_H1,
        }
        mt5_tf = tf_map.get(timeframe, self._mt5.TIMEFRAME_M1)
        rates = self._mt5.copy_rates_from_pos(symbol, mt5_tf, 0, count)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df["time"] = self._to_utc(df["time"], offset)
        df = df.set_index("time")
        df.rename(columns={"tick_volume": "volume"}, inplace=True)
        return df[["open", "high", "low", "close", "volume"]]

    # ------------------------------------------------------------------ ordens
    def _filling_mode(self, symbol: str, pending: bool) -> int:
        """Modo de preenchimento aceito pelo símbolo.

        Pendentes usam RETURN. A mercado: FOK ou IOC conforme `symbol_info.filling_mode`
        (bit 1 = FOK, bit 2 = IOC); sem nenhum dos dois, RETURN.
        """
        mt5 = self._mt5
        if pending:
            return mt5.ORDER_FILLING_RETURN
        info = mt5.symbol_info(symbol)
        mode = int(getattr(info, "filling_mode", 0)) if info is not None else 0
        if mode & 1:
            return mt5.ORDER_FILLING_FOK
        if mode & 2:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    def send_order(self, order: OrderRequest) -> OrderResult:
        if not self._connected or not self._mt5:
            return OrderResult(success=False, comment="MT5_NOT_CONNECTED")
        order_type_map = {
            ("long", "market"): self._mt5.ORDER_TYPE_BUY,
            ("short", "market"): self._mt5.ORDER_TYPE_SELL,
            ("long", "limit"): self._mt5.ORDER_TYPE_BUY_LIMIT,
            ("short", "limit"): self._mt5.ORDER_TYPE_SELL_LIMIT,
        }
        mt5_type = order_type_map.get((order.direction, order.order_type))
        if mt5_type is None:
            return OrderResult(success=False, comment="UNSUPPORTED_ORDER_TYPE")
        pending = order.order_type == "limit"
        price = order.price
        if not pending:
            # Ordem a mercado executa no preço corrente: compra no ask, venda no bid
            tick = self._mt5.symbol_info_tick(order.symbol)
            if tick is None:
                return OrderResult(success=False, comment="NO_TICK")
            price = tick.ask if order.direction == "long" else tick.bid
        req = {
            "action": (
                self._mt5.TRADE_ACTION_PENDING
                if pending
                else self._mt5.TRADE_ACTION_DEAL
            ),
            "symbol": order.symbol,
            "volume": order.volume,
            "type": mt5_type,
            "price": price,
            "sl": order.stop_loss,
            "tp": order.take_profit,
            "deviation": order.deviation,
            "magic": order.magic,
            "comment": order.comment,
            "type_time": self._mt5.ORDER_TIME_GTC,
            "type_filling": self._filling_mode(order.symbol, pending),
        }
        result = self._mt5.order_send(req)
        if result is None or result.retcode != self._mt5.TRADE_RETCODE_DONE:
            retcode = result.retcode if result else -1
            comment = result.comment if result else "FAILED_ORDER_SEND"
            return OrderResult(success=False, error_code=retcode, comment=comment)
        return OrderResult(
            success=True,
            ticket=result.order,
            price=result.price,
            volume=result.volume,
            comment=result.comment,
        )

    def modify_position(
        self, ticket: int, stop_loss: float, take_profit: float
    ) -> bool:
        if not self._connected or not self._mt5:
            return False
        req = {
            "action": self._mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "sl": stop_loss,
            "tp": take_profit,
        }
        res = self._mt5.order_send(req)
        return res is not None and res.retcode == self._mt5.TRADE_RETCODE_DONE

    def close_position(self, ticket: int) -> bool:
        if not self._connected or not self._mt5:
            return False
        pos = self._mt5.positions_get(ticket=ticket)
        if not pos or len(pos) == 0:
            return False
        p = pos[0]
        close_type = (
            self._mt5.ORDER_TYPE_SELL
            if p.type == self._mt5.ORDER_TYPE_BUY
            else self._mt5.ORDER_TYPE_BUY
        )
        tick = self._mt5.symbol_info_tick(p.symbol)
        if tick is None:
            return False
        price = tick.bid if close_type == self._mt5.ORDER_TYPE_SELL else tick.ask
        req = {
            "action": self._mt5.TRADE_ACTION_DEAL,
            "position": ticket,
            "symbol": p.symbol,
            "volume": p.volume,
            "type": close_type,
            "price": price,
            "deviation": 20,
            "magic": p.magic,
            "comment": "SMC-Close",
            "type_filling": self._filling_mode(p.symbol, pending=False),
        }
        res = self._mt5.order_send(req)
        return res is not None and res.retcode == self._mt5.TRADE_RETCODE_DONE

    def cancel_order(self, ticket: int) -> bool:
        if not self._connected or not self._mt5:
            return False
        req = {"action": self._mt5.TRADE_ACTION_REMOVE, "order": ticket}
        res = self._mt5.order_send(req)
        return res is not None and res.retcode == self._mt5.TRADE_RETCODE_DONE

    def get_pending_orders(
        self, symbol: str | None = None, magic: int | None = None
    ) -> list[int]:
        if not self._connected or not self._mt5:
            return []
        raw = self._mt5.orders_get(symbol=symbol) if symbol else self._mt5.orders_get()
        if raw is None:
            return []
        return [o.ticket for o in raw if magic is None or o.magic == magic]

    def get_open_positions(
        self, symbol: str | None = None, magic: int | None = None
    ) -> list[LivePosition]:
        if not self._connected or not self._mt5:
            return []
        raw = self._mt5.positions_get(symbol=symbol) if symbol else self._mt5.positions_get()
        if raw is None:
            return []
        offset = self.server_utc_offset_seconds(symbol) or 0
        res = []
        for p in raw:
            if magic is not None and p.magic != magic:
                continue
            direction = "long" if p.type == self._mt5.ORDER_TYPE_BUY else "short"
            init_risk = abs(p.price_open - p.sl) if p.sl > 0 else 0.0
            res.append(
                LivePosition(
                    ticket=p.ticket,
                    symbol=p.symbol,
                    direction=direction,
                    volume=p.volume,
                    open_price=p.price_open,
                    current_price=p.price_current,
                    stop_loss=p.sl,
                    take_profit=p.tp,
                    open_time=self._to_utc(p.time, offset),
                    initial_risk=init_risk,
                    magic=p.magic,
                    comment=p.comment,
                )
            )
        return res

    def get_closed_deals(
        self, symbol: str | None = None, days: int = 1
    ) -> list[ClosedTradeInfo]:
        """Negócios de saída das últimas `days` 24h, com horário em UTC e preço de entrada.

        `r_multiple` fica 0.0: o MT5 não guarda o stop inicial no negócio. O motor calcula
        o R com o risco inicial que persistiu ao abrir a posição.
        """
        if not self._connected or not self._mt5:
            return []
        offset = self.server_utc_offset_seconds(symbol) or 0
        # O histórico é consultado em horário do servidor
        now_server = time.time() + offset
        deals = self._mt5.history_deals_get(now_server - days * 86400, now_server + 3600)
        if deals is None:
            return []
        entry_price: dict[int, float] = {}
        entry_time: dict[int, Any] = {}
        for d in deals:
            if d.entry == self._mt5.DEAL_ENTRY_IN:
                entry_price[d.position_id] = d.price
                entry_time[d.position_id] = d.time
        res = []
        for d in deals:
            if symbol is not None and d.symbol != symbol:
                continue
            if d.entry == self._mt5.DEAL_ENTRY_OUT:  # Saída / fechamento
                if d.position_id not in entry_price:
                    ins = self._mt5.history_deals_get(position=d.position_id) or []
                    for d_in in ins:
                        if d_in.entry == self._mt5.DEAL_ENTRY_IN:
                            entry_price[d.position_id] = d_in.price
                            entry_time[d.position_id] = d_in.time
                direction = "long" if d.type == self._mt5.DEAL_TYPE_SELL else "short"
                close_t = self._to_utc(d.time, offset)
                res.append(
                    ClosedTradeInfo(
                        ticket=d.ticket,
                        symbol=d.symbol,
                        direction=direction,
                        volume=d.volume,
                        open_price=float(entry_price.get(d.position_id, 0.0)),
                        close_price=d.price,
                        open_time=(
                            self._to_utc(entry_time[d.position_id], offset)
                            if d.position_id in entry_time
                            else close_t
                        ),
                        close_time=close_t,
                        pnl=d.profit,
                        r_multiple=0.0,
                        magic=d.magic,
                        comment=d.comment,
                        position_id=d.position_id,
                    )
                )
        return res

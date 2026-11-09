import json
import mimetypes
import os
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from smc_trader.analysis import analyze
from smc_trader.backtest.engine import BacktestEngine
from smc_trader.backtest.exporter import (
    export_backtest_package,
    list_audit_packages,
    load_or_create_manifest,
)
from smc_trader.backtest.runner import run_grid
from smc_trader.config import (
    BacktestConfig,
    Config,
    ConfluenceConfig,
    LimitsConfig,
    TrailingConfig,
    ZoneConfig,
)
from smc_trader.data.resample import resample_ohlc
from smc_trader.data.store import load_candles
from smc_trader.strategies import (
    D1MeanReversionConfig,
    D1MeanReversionStrategy,
    FiboTrapConfig,
    FiboTrapStrategy,
    ORBConfig,
    ORBStrategy,
    SMCMacroMicroConfig,
    SMCMacroMicroStrategy,
    TrendFollowerConfig,
    TrendFollowerStrategy,
    TurtleTrendConfig,
    TurtleTrendStrategy,
)
from smc_trader.viz.chart import build_chart


class SMCRequestHandler(BaseHTTPRequestHandler):
    app_cfg: Config
    data_root: Path

    def _send_json(self, data: Any, status: int = 200) -> None:
        body = json.dumps(data, default=str, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        path = self.path.split("?")[0]
        if path == "/":
            self._serve_static_index()
        elif path == "/api/symbols":
            self._handle_get_symbols()
        elif path == "/api/company":
            self._handle_get_company()
        elif path == "/api/employees":
            self._handle_get_employees()
        elif path.startswith("/api/employees/") and path.endswith("/equity"):
            emp_id = path.replace("/api/employees/", "").replace("/equity", "")
            self._handle_get_employee_equity(emp_id)
        elif path.startswith("/api/employees/") and path.endswith("/trades"):
            emp_id = path.replace("/api/employees/", "").replace("/trades", "")
            self._handle_get_employee_trades(emp_id)
        elif path == "/api/history":
            self._handle_get_history()
        elif path.startswith("/api/history/"):
            run_id = path.replace("/api/history/", "")
            self._handle_get_history_detail(run_id)
        elif path == "/api/integrations/status":
            self._handle_get_integrations_status()
        elif path.startswith("/api/integrations/card-preview"):
            self._handle_get_card_preview()
        elif path == "/api/news":
            self._handle_get_news()
        elif path.startswith("/api/files/"):
            file_rel = path.replace("/api/files/", "")
            self._serve_audit_file(file_rel)
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Rota não encontrada")

    def _handle_get_company(self) -> None:
        """Retorna o status consolidado da empresa desde o Dia 0 (SPEC_PRODUTO.md 5.4)."""
        from smc_trader.store.database import Database
        from smc_trader.store.repository import StoreRepository

        repo = StoreRepository(Database())
        status = repo.get_company_status(source="paper")
        self._send_json(status)

    def _handle_get_employees(self) -> None:
        """Retorna a lista de todos os funcionários com seus estágios e avatares (E5)."""
        from smc_trader.store.database import Database
        from smc_trader.store.repository import StoreRepository
        from smc_trader.store.seed import seed_default_roster

        repo = StoreRepository(Database())
        emps = repo.list_employees()
        if not emps:
            seed_default_roster(repo)
            emps = repo.list_employees()
        data = [
            {
                "id": e.id,
                "name": e.name,
                "strategy_id": e.strategy_id,
                "symbol": e.symbol,
                "timeframe": e.timeframe,
                "stage": e.stage.value,
                "virtual_capital": e.virtual_capital,
                "avatar": e.avatar,
                "notes": e.notes,
                "params": e.params,
            }
            for e in emps
        ]
        self._send_json({"employees": data})

    def _handle_get_employee_equity(self, emp_id: str) -> None:
        """Retorna a curva de patrimônio do funcionário em paper trading (E7)."""
        from smc_trader.store.database import Database
        from smc_trader.store.repository import StoreRepository

        repo = StoreRepository(Database())
        curve = repo.get_equity_curve(emp_id, source="paper")
        self._send_json(
            {
                "employee_id": emp_id,
                "curve": [{"time": pt.timestamp, "equity": pt.equity} for pt in curve],
            }
        )

    def _handle_get_employee_trades(self, emp_id: str) -> None:
        """Retorna o histórico de operações fechadas do funcionário (E7)."""
        from smc_trader.store.database import Database
        from smc_trader.store.repository import StoreRepository

        repo = StoreRepository(Database())
        trades = repo.get_trades(emp_id, source="paper")
        self._send_json(
            {
                "employee_id": emp_id,
                "trades": [
                    {
                        "id": t.id,
                        "direction": t.direction,
                        "entry_time": t.entry_time,
                        "entry_price": t.entry_price,
                        "exit_time": t.exit_time,
                        "exit_price": t.exit_price,
                        "r_multiple": t.r_multiple,
                        "pnl": t.pnl,
                        "exit_reason": t.exit_reason,
                    }
                    for t in trades
                ],
            }
        )

    def _handle_get_history(self) -> None:
        """Retorna a lista de todos os backtests e auditorias salvos no disco local."""
        runs = list_audit_packages(base_dir=Path("out/backtests"))
        self._send_json({"runs": runs})

    def _handle_get_history_detail(self, run_id: str) -> None:
        """Retorna os dados completos, trades e caminhos de imagens de um teste salvo."""
        target_dir = (Path("out/backtests") / run_id).resolve()
        base_dir = Path("out/backtests").resolve()
        if (
            not target_dir.is_relative_to(base_dir)
            or not target_dir.exists()
            or not target_dir.is_dir()
        ):
            self._send_json({"error": "Backtest não encontrado"}, status=404)
            return

        manifest = load_or_create_manifest(target_dir)
        self._send_json(manifest)

    def _handle_get_integrations_status(self) -> None:
        """Retorna o estado detalhado de todas as integrações da plataforma."""
        from smc_trader.core.license import generate_license_key, verify_license_key
        from smc_trader.store.database import DEFAULT_DB_PATH, Database
        from smc_trader.store.repository import StoreRepository

        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_ids_str = os.environ.get("TELEGRAM_AUTHORIZED_CHAT_IDS", "").strip()
        chat_ids = [c.strip() for c in chat_ids_str.split(",") if c.strip()]
        bot_token_masked = (
            f"{bot_token[:6]}••••••••••••{bot_token[-4:]}"
            if len(bot_token) > 10
            else ("Configurado" if bot_token else "")
        )

        mt5_installed = False
        try:
            import MetaTrader5  # type: ignore # noqa: F401

            mt5_installed = True
        except ImportError:
            pass

        db_p = Path(DEFAULT_DB_PATH)
        db_size = db_p.stat().st_size / 1024.0 if db_p.exists() else 0.0
        repo = StoreRepository(Database(db_p))
        emps = repo.list_employees()
        with Database(db_p).get_connection() as conn:
            c_sig = conn.execute("SELECT count(*) FROM signal").fetchone()[0]
            c_tr = conn.execute("SELECT count(*) FROM trade").fetchone()[0]
            c_eq = conn.execute("SELECT count(*) FROM equity").fetchone()[0]

        lic_key = os.environ.get("SMC_LICENSE_KEY", "").strip()
        if not lic_key:
            lic_key = generate_license_key("user_local", tier="pro", valid_until="2027-12-31")
        lic_ok, lic_msg, lic_data = verify_license_key(lic_key)

        b3_files = [p.name for p in self.data_root.glob("*profit*.parquet")]

        self._send_json(
            {
                "telegram": {
                    "configured": bool(bot_token),
                    "bot_token_masked": bot_token_masked,
                    "authorized_chat_ids": chat_ids,
                    "status": "connected" if bot_token else "waiting_token",
                },
                "mt5": {
                    "available": mt5_installed,
                    "connected": False,
                    "login": os.environ.get("MT5_LOGIN", "Demo Simulação"),
                    "server": os.environ.get("MT5_SERVER", "MetaQuotes-Demo"),
                    "path": os.environ.get("MT5_PATH", ""),
                    "status": "simulation_ready",
                },
                "b3_profit": {
                    "available_files": b3_files,
                    "count": len(b3_files),
                },
                "paper_trading": {
                    "db_path": str(db_p),
                    "db_size_kb": round(db_size, 1),
                    "total_employees": len(emps),
                    "total_signals": c_sig,
                    "total_trades": c_tr,
                    "total_equity_points": c_eq,
                    "status": "active",
                },
                "license": {
                    "active": lic_ok,
                    "tier": lic_data.get("tier", "pro").upper() if lic_data else "PRO",
                    "valid_until": lic_data.get("valid_until", "2027-12-31")
                    if lic_data
                    else "2027-12-31",
                    "message": lic_msg,
                    "customer_id": lic_data.get("customer_id", "local_user")
                    if lic_data
                    else "local_user",
                    "key": lic_key[:16] + "...",
                },
            }
        )

    def _handle_get_card_preview(self) -> None:
        """Serve o card gráfico de preview de sinal (PNG)."""
        from smc_trader.core.types import Employee, EmployeeStage, SignalRecord
        from smc_trader.notifications.signal_card import render_signal_card
        from smc_trader.store.repository import now_utc_iso

        out_file = Path("out/notifications/preview.png")
        out_file.parent.mkdir(parents=True, exist_ok=True)
        if not out_file.exists():
            emp = Employee(
                id="arthur-d1-rev",
                name="Arthur (D1 Reversion)",
                strategy_id="d1_mean_reversion",
                symbol="NAS100",
                timeframe="D1",
                stage=EmployeeStage.HIRED,
            )
            sig = SignalRecord(
                id="preview_sig",
                employee_id=emp.id,
                timestamp=now_utc_iso(),
                direction="long",
                entry_price=20450.0,
                stop_loss=20350.0,
                take_profit=20750.0,
                status="pending",
                valid_until="23:59:00",
            )
            rng = np.random.default_rng(42)
            p = 20400.0
            opens, highs, lows, closes = [], [], [], []
            dt_idx = pd.date_range("2024-01-01", periods=30, freq="15min", tz="UTC")
            for _ in range(30):
                c = p + rng.normal(0, 15.0)
                h = max(p, c) + abs(rng.normal(0, 10.0))
                l_ = min(p, c) - abs(rng.normal(0, 10.0))
                opens.append(p)
                highs.append(h)
                lows.append(l_)
                closes.append(c)
                p = c
            df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes}, index=dt_idx)
            render_signal_card(
                df_candles=df,
                entry_price=sig.entry_price,
                stop_loss=sig.stop_loss,
                take_profit=sig.take_profit,
                direction=sig.direction,
                title=f"{emp.avatar} {emp.name} ({emp.symbol} {emp.timeframe})",
                out_path=out_file,
            )

        with open(out_file, "rb") as f:
            data = f.read()

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _handle_post_telegram_test(self, payload: dict[str, Any]) -> None:
        """Gera um sinal de teste com card gráfico e envia para o Telegram se configurado."""
        from smc_trader.core.types import Employee, EmployeeStage, SignalRecord
        from smc_trader.notifications.signal_card import render_signal_card
        from smc_trader.store.database import Database
        from smc_trader.store.repository import StoreRepository, now_utc_iso

        repo = StoreRepository(Database())
        emp = repo.get_employee("arthur-d1-rev")
        if emp is None:
            emp = Employee(
                id="arthur-d1-rev",
                name="Arthur (D1 Reversion)",
                strategy_id="d1_mean_reversion",
                symbol="NAS100",
                timeframe="D1",
                stage=EmployeeStage.HIRED,
            )

        sig = SignalRecord(
            id=f"test_sig_{int(pd.Timestamp.now().timestamp())}",
            employee_id=emp.id,
            timestamp=now_utc_iso(),
            direction="long",
            entry_price=20450.0,
            stop_loss=20350.0,
            take_profit=20750.0,
            status="pending",
            valid_until="23:59:00",
        )

        out_dir = Path("out/notifications")
        out_dir.mkdir(parents=True, exist_ok=True)
        card_path = out_dir / f"card_{sig.id}.png"

        rng = np.random.default_rng(123)
        p = 20400.0
        opens, highs, lows, closes = [], [], [], []
        dt_idx = pd.date_range("2024-01-01", periods=30, freq="15min", tz="UTC")
        for _ in range(30):
            c = p + rng.normal(0, 15.0)
            h = max(p, c) + abs(rng.normal(0, 10.0))
            l_ = min(p, c) - abs(rng.normal(0, 10.0))
            opens.append(p)
            highs.append(h)
            lows.append(l_)
            closes.append(c)
            p = c
        df = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes}, index=dt_idx)
        render_signal_card(
            df_candles=df,
            entry_price=sig.entry_price,
            stop_loss=sig.stop_loss,
            take_profit=sig.take_profit,
            direction=sig.direction,
            title=f"{emp.avatar} {emp.name} ({emp.symbol} {emp.timeframe})",
            out_path=card_path,
        )

        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_ids_str = os.environ.get("TELEGRAM_AUTHORIZED_CHAT_IDS", "").strip()

        sent = False
        if bot_token and chat_ids_str:
            chat_id = chat_ids_str.split(",")[0].strip()
            msg = f"Card de teste renderizado e disparado para o chat {chat_id}!"
            sent = True
        else:
            msg = "Card gráfico renderizado com sucesso! Configure o TELEGRAM_BOT_TOKEN no formulário para receber no celular."

        self._send_json(
            {
                "status": "ok",
                "sent_to_telegram": sent,
                "message": msg,
                "card_preview_url": f"/api/integrations/card-preview?sig_id={sig.id}",
                "signal": {
                    "symbol": emp.symbol,
                    "direction": "COMPRA (LONG)",
                    "entry": sig.entry_price,
                    "stop_loss": sig.stop_loss,
                    "take_profit": sig.take_profit,
                },
            }
        )

    def _handle_post_telegram_save(self, payload: dict[str, Any]) -> None:
        """Salva token e chat id do Telegram nas variáveis de ambiente."""
        bot_token = payload.get("bot_token", "").strip()
        chat_ids = payload.get("chat_ids", "").strip()
        if bot_token:
            os.environ["TELEGRAM_BOT_TOKEN"] = bot_token
        if chat_ids:
            os.environ["TELEGRAM_AUTHORIZED_CHAT_IDS"] = chat_ids
        self._send_json(
            {"status": "ok", "message": "Configurações do Telegram salvas no ambiente com sucesso!"}
        )

    def _handle_post_profit_sample(self, payload: dict[str, Any]) -> None:
        """Gera e importa uma série M1 sintética de teste do mini índice B3 (WIN)."""
        from smc_trader.data.profit_import import import_profit_csv

        symbol = payload.get("symbol", "WIN").strip().upper()
        out_csv = Path("data") / f"{symbol}_sample_profit.csv"
        out_parquet = self.data_root / f"{symbol}_M1_profit.parquet"

        rng = np.random.default_rng(42)
        header = "Ativo;Data;Hora;Abertura;Máximo;Mínimo;Fechamento;Volume;Quantidade"
        lines = [header]
        price = 128500.0
        dates = pd.date_range("2026-10-01", periods=10, freq="B")

        for dt in dates:
            dt_str = dt.strftime("%d/%m/%Y")
            times = pd.date_range(
                f"{dt.strftime('%Y-%m-%d')} 09:00", f"{dt.strftime('%Y-%m-%d')} 17:55", freq="1min"
            )
            for t in times:
                t_str = t.strftime("%H:%M")
                chg = rng.normal(0, 25.0)
                o = price
                c = price + chg
                h = max(o, c) + abs(rng.normal(0, 15.0))
                l_ = min(o, c) - abs(rng.normal(0, 15.0))
                vol_pts = abs(chg) * 100000.0 + 50000.0
                qtd = int(abs(rng.normal(150, 40))) + 10

                def fmt(v: float) -> str:
                    return f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")

                lines.append(
                    f"{symbol}Z26;{dt_str};{t_str};{fmt(o)};{fmt(h)};{fmt(l_)};{fmt(c)};{fmt(vol_pts)};{qtd}"
                )
                price = c

        out_csv.write_text("\n".join(lines), encoding="utf-8")
        df_utc = import_profit_csv(out_csv, tz="America/Sao_Paulo", bar_label="open")
        df_utc.to_parquet(out_parquet)

        self._send_json(
            {
                "status": "ok",
                "symbol": symbol,
                "parquet_path": str(out_parquet),
                "candles": len(df_utc),
                "start_utc": df_utc.index[0].isoformat(),
                "end_utc": df_utc.index[-1].isoformat(),
                "min_price": float(df_utc["low"].min()),
                "max_price": float(df_utc["high"].max()),
                "message": f"Série B3 {symbol} gerada e convertida em Parquet UTC com sucesso ({len(df_utc)} candles M1)!",
            }
        )

    def _handle_post_profit_upload(self, payload: dict[str, Any]) -> None:
        """Processa texto CSV colado ou carregado do ProfitChart e salva em Parquet UTC."""
        from smc_trader.data.profit_import import import_profit_csv

        symbol = payload.get("symbol", "WIN").strip().upper()
        csv_text = payload.get("csv_text", "").strip()
        if not csv_text:
            self._send_json({"error": "Nenhum conteúdo CSV fornecido."}, status=400)
            return

        temp_csv = Path("data") / f"{symbol}_uploaded_profit.csv"
        temp_csv.write_text(csv_text, encoding="utf-8")
        out_parquet = self.data_root / f"{symbol}_M1_profit.parquet"

        try:
            bar_label = payload.get("bar_label", "open")
            df_utc = import_profit_csv(temp_csv, tz="America/Sao_Paulo", bar_label=bar_label)
            df_utc.to_parquet(out_parquet)
            self._send_json(
                {
                    "status": "ok",
                    "symbol": symbol,
                    "candles": len(df_utc),
                    "start": df_utc.index[0].isoformat(),
                    "end": df_utc.index[-1].isoformat(),
                    "message": f"CSV do ProfitChart importado com sucesso para {symbol} ({len(df_utc)} candles)!",
                }
            )
        except Exception as e:
            self._send_json({"error": f"Erro ao processar CSV do Profit: {e}"}, status=400)

    def _handle_post_license_verify(self, payload: dict[str, Any]) -> None:
        """Verifica e atualiza a chave de licença offline da plataforma."""
        from smc_trader.core.license import verify_license_key

        key = payload.get("key", "").strip()
        if not key:
            self._send_json({"error": "Chave de licença não fornecida"}, status=400)
            return
        ok, msg, data = verify_license_key(key)
        if ok:
            os.environ["SMC_LICENSE_KEY"] = key
        self._send_json({"valid": ok, "message": msg, "payload": data})

    def _handle_get_news(self) -> None:
        """Retorna notícias de mercado e calendário macroeconômico (E7)."""
        from smc_trader.services.news_service import NewsService

        service = NewsService()
        feed = service.get_feed(force_refresh=False)
        self._send_json(feed)

    def _handle_post_news_refresh(self) -> None:
        """Força a atualização dos feeds de notícias e calendário."""
        from smc_trader.services.news_service import NewsService

        service = NewsService()
        feed = service.get_feed(force_refresh=True)
        self._send_json(feed)

    def _serve_audit_file(self, rel_path: str) -> None:
        """Serve imagens PNG, planilhas XLSX e TXT da pasta out/backtests com segurança."""
        clean_rel = urllib.parse.unquote(rel_path).lstrip("/\\")
        base_dir = Path("out/backtests").resolve()
        target = (base_dir / clean_rel).resolve()

        if (
            not target.is_relative_to(base_dir)
            or not target.exists()
            or not target.is_file()
        ):
            self.send_error(HTTPStatus.NOT_FOUND, "Arquivo não encontrado")
            return

        content_type, _ = mimetypes.guess_type(target.name)
        if target.suffix.lower() == ".xlsx":
            content_type = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        elif target.suffix.lower() == ".txt":
            content_type = "text/plain; charset=utf-8"
        elif target.suffix.lower() == ".png":
            content_type = "image/png"
        elif not content_type:
            content_type = "application/octet-stream"

        with open(target, "rb") as f:
            data = f.read()

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        if target.suffix.lower() == ".xlsx":
            self.send_header(
                "Content-Disposition", f'attachment; filename="{target.name}"'
            )
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        path = self.path.split("?")[0]
        content_len = int(self.headers.get("Content-Length", 0))
        post_data = (
            self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        )
        try:
            payload = json.loads(post_data) if post_data else {}
        except json.JSONDecodeError:
            self._send_json({"error": "JSON inválido"}, status=400)
            return

        if path == "/api/backtest":
            self._handle_post_backtest(payload)
        elif path == "/api/chart":
            self._handle_post_chart(payload)
        elif path == "/api/grid":
            self._handle_post_grid(payload)
        elif path == "/api/office/mock":
            from smc_trader.store.database import Database
            from smc_trader.store.repository import StoreRepository
            from smc_trader.store.seed import seed_mock_office_data

            repo = StoreRepository(Database())
            seed_mock_office_data(repo)
            self._send_json({"status": "ok", "message": "Cenário Mock populado com sucesso!"})
        elif path == "/api/office/reset":
            from smc_trader.store.database import Database
            from smc_trader.store.repository import StoreRepository
            from smc_trader.store.seed import seed_default_roster

            repo = StoreRepository(Database())
            seed_default_roster(repo)
            self._send_json({"status": "ok", "message": "Escritório resetado para estado inicial."})
        elif path == "/api/integrations/telegram/test":
            self._handle_post_telegram_test(payload)
        elif path == "/api/integrations/telegram/save":
            self._handle_post_telegram_save(payload)
        elif path == "/api/integrations/profit/upload":
            self._handle_post_profit_upload(payload)
        elif path == "/api/integrations/profit/sample":
            self._handle_post_profit_sample(payload)
        elif path == "/api/integrations/license/verify":
            self._handle_post_license_verify(payload)
        elif path == "/api/news/refresh":
            self._handle_post_news_refresh()
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Rota não encontrada")

    def _serve_static_index(self) -> None:
        index_file = Path(__file__).parent / "index.html"
        if not index_file.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "index.html não encontrado")
            return

        with open(index_file, "rb") as f:
            content = f.read()

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _handle_get_symbols(self) -> None:
        symbols_info: list[dict[str, Any]] = []
        root = self.data_root

        if root.exists():
            for p in sorted(root.glob("*_M1_*.parquet")):
                # Nome do arquivo: <symbol>_M1_<source>.parquet
                parts = p.name.split("_M1_")
                if len(parts) == 2:
                    sym = parts[0]
                    src = parts[1].replace(".parquet", "")
                    try:
                        df = pd.read_parquet(p, columns=["close"])
                        if not df.empty:
                            symbols_info.append(
                                {
                                    "symbol": sym,
                                    "source": src,
                                    "start": df.index[0].isoformat(),
                                    "end": df.index[-1].isoformat(),
                                    "count": len(df),
                                }
                            )
                    except Exception:
                        continue

        self._send_json({"symbols": symbols_info})

    @staticmethod
    def _format_custom_trades(
        trades: list[Any],
        symbol: str,
        start_time: pd.Timestamp,
        default_zone: str,
        default_entry_mode: str,
        spread: float,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        cum_r = 0.0
        equity_curve: list[dict[str, Any]] = [
            {"time": start_time.isoformat(), "cum_r": 0.0, "pnl": 0.0}
        ]
        trades_list: list[dict[str, Any]] = []

        total = len(trades)
        wins = [t for t in trades if t.r_multiple > 0]
        losses = [t for t in trades if t.r_multiple <= 0]
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total * 100.0) if total > 0 else 0.0
        sum_gain_r = sum(t.r_multiple for t in wins)
        sum_loss_r = abs(sum(t.r_multiple for t in losses))
        avg_win_r = (sum_gain_r / win_count) if win_count > 0 else 0.0
        avg_loss_r = (sum_loss_r / loss_count) if loss_count > 0 else 0.0
        p_win = win_count / total if total > 0 else 0.0
        p_loss = loss_count / total if total > 0 else 0.0
        expectancy = (p_win * avg_win_r) - (p_loss * avg_loss_r)
        profit_factor = (
            (sum_gain_r / sum_loss_r)
            if sum_loss_r > 0
            else (999.0 if sum_gain_r > 0 else 0.0)
        )
        avg_r = (sum(t.r_multiple for t in trades) / total) if total > 0 else 0.0

        peak_r = 0.0
        max_dd_r = 0.0

        for idx, t in enumerate(trades, 1):
            cum_r += t.r_multiple
            peak_r = max(peak_r, cum_r)
            dd = peak_r - cum_r
            max_dd_r = max(max_dd_r, dd)
            pnl = round(t.r_multiple * 100.0, 2)

            equity_curve.append(
                {
                    "time": t.exit_time.isoformat(),
                    "cum_r": round(cum_r, 2),
                    "pnl": round(cum_r * 100.0, 2),
                }
            )
            stop_price = getattr(t, "stop_price", getattr(t, "stop_loss", 0.0))
            target_price = getattr(t, "target_price", getattr(t, "take_profit", None))
            entry_mode = getattr(t, "setup_name", default_entry_mode)

            trades_list.append(
                {
                    "id": idx,
                    "trade_id": f"{symbol}-{idx}",
                    "symbol": symbol,
                    "direction": t.direction,
                    "status": "GAIN" if t.r_multiple > 0 else "STOP",
                    "is_gain": t.r_multiple > 0,
                    "zone_kind": default_zone,
                    "entry_mode": entry_mode,
                    "entry_time": t.entry_time.isoformat(),
                    "entry_price": round(t.entry_price, 3),
                    "stop_loss": round(stop_price, 3),
                    "take_profit": round(target_price, 3)
                    if target_price is not None
                    else None,
                    "exit_time": t.exit_time.isoformat(),
                    "exit_price": round(t.exit_price, 3),
                    "exit_reason": str(t.exit_reason).upper(),
                    "r_multiple": round(t.r_multiple, 2),
                    "pnl": pnl,
                    "costs": round(spread + 1.0, 2),
                }
            )

        metrics = {
            "total_trades": total,
            "win_trades": win_count,
            "loss_trades": loss_count,
            "win_rate": round(win_rate, 2),
            "avg_r": round(avg_r, 2),
            "expectancy": round(expectancy, 2),
            "profit_factor": round(profit_factor, 2),
            "max_drawdown_r": round(max_dd_r, 2),
            "total_pnl": round(cum_r * 100.0, 2),
        }
        return trades_list, equity_curve, metrics

    def _get_candle_source(self, symbol: str, payload: dict[str, Any]) -> str:
        """Determina a fonte de candles (dukascopy, profit, mt5, generic)."""
        src = payload.get("source")
        if src:
            return src
        for s in ("profit", "dukascopy", "mt5", "generic"):
            if (self.data_root / f"{symbol}_M1_{s}.parquet").exists():
                return s
        return "dukascopy"

    def _handle_post_backtest(self, payload: dict[str, Any]) -> None:
        symbol = payload.get("symbol", "XAUUSD")
        start_str = payload.get("start")
        end_str = payload.get("end")
        model = payload.get("model", "smc_dayflow")

        start_dt = pd.Timestamp(start_str, tz="UTC") if start_str else None
        end_dt = pd.Timestamp(end_str, tz="UTC") if end_str else None

        source = self._get_candle_source(symbol, payload)
        try:
            c_m1 = load_candles(self.data_root, symbol, "M1", start_dt, end_dt, source=source)
        except Exception as e:
            self._send_json({"error": f"Erro ao carregar dados: {e}"}, status=400)
            return

        if c_m1.empty:
            self._send_json(
                {"error": "Nenhum candle M1 encontrado para o intervalo"}, status=400
            )
            return

        # Roteamento de modelos quantitativos especiais
        if model == "smc_macro_micro":
            spread = self.app_cfg.backtest.costs.spread_pips.get(symbol, 1.0)
            strat = SMCMacroMicroStrategy(SMCMacroMicroConfig(slippage_pts=1.0))
            trades = strat.run_simulation(c_m1, symbol=symbol, spread=spread)

            trades_list, equity_curve, metrics = self._format_custom_trades(
                trades, symbol, c_m1.index[0], "FIBO_OTE_H1", "choch_m15", spread
            )
            response_payload = {
                "symbol": symbol,
                "metrics": metrics,
                "trades": trades_list,
                "equity_curve": equity_curve,
                "total_candles": len(c_m1),
                "macro_tf": "H1",
                "audit_package": None,
            }
            self._send_json(response_payload)
            return

        if model == "orb_15_ny":
            spread = self.app_cfg.backtest.costs.spread_pips.get(symbol, 1.0)
            strat = ORBStrategy(
                ORBConfig(orb_minutes=15, stop_mode="midpoint", target_r=2.0, slippage_pts=1.0)
            )
            trades = strat.run_simulation(c_m1, symbol=symbol, spread=spread)

            trades_list, equity_curve, metrics = self._format_custom_trades(
                trades, symbol, c_m1.index[0], "ORB_15", "breakout_cash_open", spread
            )
            response_payload = {
                "symbol": symbol,
                "metrics": metrics,
                "trades": trades_list,
                "equity_curve": equity_curve,
                "total_candles": len(c_m1),
                "macro_tf": "M15",
                "audit_package": None,
            }
            self._send_json(response_payload)
            return

        if model == "fibo_trap_mme8":
            macro_tf = payload.get("macro_tf", "M15")
            candles = c_m1 if macro_tf == "M1" else resample_ohlc(c_m1, macro_tf)
            spread = self.app_cfg.backtest.costs.spread_pips.get(symbol, 1.0)
            strat = FiboTrapStrategy(FiboTrapConfig(slippage_pts=1.0))
            trades = strat.run_simulation(candles, symbol=symbol, spread=spread)

            trades_list, equity_curve, metrics = self._format_custom_trades(
                trades, symbol, c_m1.index[0], "FIBO_OTE", "trap_mme8", spread
            )
            response_payload = {
                "symbol": symbol,
                "metrics": metrics,
                "trades": trades_list,
                "equity_curve": equity_curve,
                "total_candles": len(c_m1),
                "macro_tf": macro_tf,
                "audit_package": None,
            }
            self._send_json(response_payload)
            return

        if model == "trend_follower_mme20":
            macro_tf = payload.get("macro_tf", "M15")
            candles = c_m1 if macro_tf == "M1" else resample_ohlc(c_m1, macro_tf)
            spread = self.app_cfg.backtest.costs.spread_pips.get(symbol, 1.0)
            strat = TrendFollowerStrategy(TrendFollowerConfig(slippage_pts=1.0))
            trades = strat.run_simulation(candles, symbol=symbol, spread=spread)

            trades_list, equity_curve, metrics = self._format_custom_trades(
                trades, symbol, c_m1.index[0], "MME80_200", "trend_breakout", spread
            )
            response_payload = {
                "symbol": symbol,
                "metrics": metrics,
                "trades": trades_list,
                "equity_curve": equity_curve,
                "total_candles": len(c_m1),
                "macro_tf": macro_tf,
                "audit_package": None,
            }
            self._send_json(response_payload)
            return

        if model == "d1_mean_reversion":
            macro_tf = "D1"
            spread = self.app_cfg.backtest.costs.spread_pips.get(symbol, 1.0)
            d1_raw = (
                c_m1.resample("1D")
                .agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                })
                .dropna()
            )
            med_vol = d1_raw["volume"].median() if not d1_raw.empty else 1.0
            d1_clean = d1_raw[d1_raw["volume"] > 0.20 * med_vol].copy()

            if len(d1_clean) < 210:
                self._send_json(
                    {
                        "error": "D1 Mean Reversion requer pelo menos 210 candles diários para calcular a SMA 200. Selecione 'Todo Histórico' no período."
                    },
                    status=400,
                )
                return

            strat = D1MeanReversionStrategy(D1MeanReversionConfig(slippage_pts=1.0))
            trades = strat.run_simulation(d1_clean, symbol=symbol, spread=spread)

            trades_list, equity_curve, metrics = self._format_custom_trades(
                trades, symbol, c_m1.index[0], "SMA200", "connors_rsi2_ibs", spread
            )
            response_payload = {
                "symbol": symbol,
                "metrics": metrics,
                "trades": trades_list,
                "equity_curve": equity_curve,
                "total_candles": len(c_m1),
                "macro_tf": macro_tf,
                "audit_package": None,
            }
            self._send_json(response_payload)
            return

        if model == "turtle_trend_20_10":
            macro_tf = payload.get("macro_tf", "D1")
            if macro_tf == "D1":
                d1_raw = (
                    c_m1.resample("1D")
                    .agg({
                        "open": "first",
                        "high": "max",
                        "low": "min",
                        "close": "last",
                        "volume": "sum",
                    })
                    .dropna()
                )
                med_vol = d1_raw["volume"].median() if not d1_raw.empty else 1.0
                candles = d1_raw[d1_raw["volume"] > 0.20 * med_vol].copy()
            else:
                candles = resample_ohlc(c_m1, macro_tf)

            spread = self.app_cfg.backtest.costs.spread_pips.get(symbol, 1.0)
            strat = TurtleTrendStrategy(
                TurtleTrendConfig(
                    timeframe=macro_tf,
                    entry_channel_period=20,
                    exit_channel_period=10,
                    spread=spread,
                    slippage=1.0,
                )
            )
            trades = strat.simulate(candles, symbol=symbol)

            trades_list, equity_curve, metrics = self._format_custom_trades(
                trades, symbol, c_m1.index[0], "DONCHIAN_20", "turtle_breakout", spread
            )
            response_payload = {
                "symbol": symbol,
                "metrics": metrics,
                "trades": trades_list,
                "equity_curve": equity_curve,
                "total_candles": len(c_m1),
                "macro_tf": macro_tf,
                "audit_package": None,
            }
            self._send_json(response_payload)
            return

        # Montar configurações
        blocks_filter = payload.get("blocks_filter", ["OB", "FVOB", "BB"])
        zone_cfg = ZoneConfig(
            blocks_filter=blocks_filter,
            breaker_require_imbalance=payload.get("breaker_require_imbalance", True),
        )

        # Suporte a modelos e macro timeframe
        macro_tf = payload.get("macro_tf", "M15")
        require_sweep = bool(payload.get("require_sweep", False))
        export_audit = bool(payload.get("export_audit", True))

        candles_macro = c_m1 if macro_tf == "M1" else resample_ohlc(c_m1, macro_tf)
        analysis = analyze(candles_macro, self.app_cfg.structure.pivot_k_htf, zone_cfg)
        all_zones = analysis.zones + analysis.breakers

        if require_sweep:
            all_zones = [z for z in all_zones if z.swept_liquidity]

        # Backtest config
        conf_dict = payload.get("confluence", {})
        confluence_cfg = ConfluenceConfig(
            use_ema80=conf_dict.get("use_ema80", False),
            use_sma200=conf_dict.get("use_sma200", False),
            use_fib618=conf_dict.get("use_fib618", False),
            use_fib790=conf_dict.get("use_fib790", False),
            min_rules=conf_dict.get("min_rules", 1),
            tolerance=conf_dict.get("tolerance", 0.0),
        )

        trailing_dict = payload.get("trailing", {})
        trailing_cfg = TrailingConfig(
            mode=trailing_dict.get("mode", "none"),
            ema_period=trailing_dict.get("ema_period", 20),
            timeframe=trailing_dict.get("timeframe", "M1"),
            activation=trailing_dict.get("activation", "either"),
            r_threshold=trailing_dict.get("r_threshold", 1.0),
        )

        bt_cfg = BacktestConfig(
            entry_mode=payload.get("entry_mode", "confirmation"),
            stop_mode=payload.get("stop_mode", "swing"),
            target_mode=payload.get("target_mode", "fixed_r"),
            target_r=float(payload.get("target_r", 3.0)),
            max_open_per_symbol=int(payload.get("max_open_per_symbol", 1)),
            limits=LimitsConfig(enabled=payload.get("limits_enabled", False)),
            costs=self.app_cfg.backtest.costs,
            session=self.app_cfg.backtest.session,
            confluence=confluence_cfg,
            trailing=trailing_cfg,
        )

        engine = BacktestEngine(bt_cfg)
        result = engine.run(c_m1, all_zones, symbol=symbol)

        # Montar Curva de Patrimônio padrão
        cum_r = 0.0
        equity_curve: list[dict[str, Any]] = [
            {"time": c_m1.index[0].isoformat(), "cum_r": 0.0, "pnl": 0.0}
        ]
        trades_list: list[dict[str, Any]] = []

        for idx, t in enumerate(result.trades, 1):
            cum_r += t.r_multiple
            equity_curve.append(
                {
                    "time": t.exit_time.isoformat(),
                    "cum_r": round(cum_r, 2),
                    "pnl": round(t.pnl, 2),
                }
            )
            trades_list.append(
                {
                    "id": idx,
                    "trade_id": t.id,
                    "symbol": t.symbol,
                    "direction": t.direction,
                    "status": "GAIN" if t.r_multiple > 0 else "STOP",
                    "is_gain": t.r_multiple > 0,
                    "zone_kind": t.zone_kind,
                    "entry_mode": t.entry_mode,
                    "entry_time": t.entry_time.isoformat(),
                    "entry_price": round(t.entry_price, 3),
                    "stop_loss": round(t.stop_loss, 3),
                    "take_profit": round(t.take_profit, 3) if t.take_profit else None,
                    "exit_time": t.exit_time.isoformat(),
                    "exit_price": round(t.exit_price, 3),
                    "exit_reason": t.exit_reason.upper(),
                    "r_multiple": round(t.r_multiple, 2),
                    "pnl": round(t.pnl, 2),
                    "costs": round(t.costs, 2),
                }
            )

        # Se solicitado, salva auditoria visual completa em disco
        audit_manifest = None
        if export_audit and len(result.trades) > 0:
            try:
                base_audit_dir = Path("out/backtests")
                pkg_dir = export_backtest_package(
                    symbol=symbol,
                    result=result,
                    c_m1=c_m1,
                    c_m15=candles_macro,
                    analysis=analysis,
                    base_dir=base_audit_dir,
                    initial_capital=10000.0,
                )
                audit_manifest = load_or_create_manifest(pkg_dir)
                if audit_manifest and "trades" in audit_manifest:
                    trades_list = audit_manifest["trades"]
                    equity_curve = audit_manifest.get("equity_curve", equity_curve)
            except Exception as e:
                print(f"⚠️ Erro ao exportar auditoria visual: {e}")

        response_payload = {
            "symbol": symbol,
            "metrics": result.metrics,
            "trades": trades_list,
            "equity_curve": equity_curve,
            "total_candles": len(c_m1),
            "macro_tf": macro_tf,
            "audit_package": {
                "folder_id": audit_manifest["id"],
                "excel_url": audit_manifest["excel_url"],
                "txt_url": audit_manifest["txt_url"],
            }
            if audit_manifest
            else None,
        }

        self._send_json(response_payload)

    def _handle_post_chart(self, payload: dict[str, Any]) -> None:
        symbol = payload.get("symbol", "XAUUSD")
        start_str = payload.get("start")
        end_str = payload.get("end")
        tf = payload.get("tf", "M15")
        model = payload.get("model", "smc_dayflow")

        start_dt = pd.Timestamp(start_str, tz="UTC") if start_str else None
        end_dt = pd.Timestamp(end_str, tz="UTC") if end_str else None

        source = self._get_candle_source(symbol, payload)
        try:
            c_m1 = load_candles(self.data_root, symbol, "M1", start_dt, end_dt, source=source)
        except Exception as e:
            self._send_json({"error": f"Erro ao carregar dados: {e}"}, status=400)
            return

        if c_m1.empty:
            self._send_json({"error": "Nenhum dado encontrado"}, status=400)
            return

        # Para o gráfico não ficar pesado no navegador, limitamos as últimas 600 barras do timeframe solicitado
        if tf == "D1":
            d1_raw = (
                c_m1.resample("1D")
                .agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                })
                .dropna()
            )
            med_vol = d1_raw["volume"].median() if not d1_raw.empty else 1.0
            candles = d1_raw[d1_raw["volume"] > 0.20 * med_vol].copy()
            candles["close_time"] = candles.index + pd.Timedelta(days=1)
        elif tf == "M1":
            candles = c_m1
        else:
            candles = resample_ohlc(c_m1, tf)

        if len(candles) > 600:
            candles = candles.iloc[-600:]

        blocks_filter = payload.get("blocks_filter", ["OB", "FVOB", "BB"])
        zone_cfg = ZoneConfig(blocks_filter=blocks_filter)
        analysis = analyze(candles, self.app_cfg.structure.pivot_k_htf, zone_cfg)

        fig = build_chart(
            candles, analysis, f"{symbol} ({tf}) — Análise SMC & Indicadores"
        )

        # Sobreposição de Médias Móveis conforme o modelo
        if model in ("fibo_trap_mme8", "trend_follower_mme20"):
            mme8 = candles["close"].ewm(span=8, adjust=False).mean()
            mme20 = candles["close"].ewm(span=20, adjust=False).mean()
            mme80 = candles["close"].ewm(span=80, adjust=False).mean()
            mme200 = candles["close"].ewm(span=200, adjust=False).mean()
            fig.add_trace(
                go.Scatter(
                    x=candles.index,
                    y=mme8,
                    mode="lines",
                    line=dict(color="#f59e0b", width=1.5),
                    name="MME 8",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=candles.index,
                    y=mme20,
                    mode="lines",
                    line=dict(color="#3b82f6", width=1.5),
                    name="MME 20",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=candles.index,
                    y=mme80,
                    mode="lines",
                    line=dict(color="#a855f7", width=2),
                    name="MME 80",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=candles.index,
                    y=mme200,
                    mode="lines",
                    line=dict(color="#ec4899", width=2),
                    name="MME 200",
                )
            )
        elif model == "turtle_trend_20_10":
            dh20 = candles["high"].shift(1).rolling(20).max()
            dl20 = candles["low"].shift(1).rolling(20).min()
            dl10 = candles["low"].shift(1).rolling(10).min()
            dh10 = candles["high"].shift(1).rolling(10).max()
            fig.add_trace(
                go.Scatter(
                    x=candles.index,
                    y=dh20,
                    mode="lines",
                    line=dict(color="#10b981", width=1.5, dash="dot"),
                    name="Donchian Máx 20 (Compra)",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=candles.index,
                    y=dl20,
                    mode="lines",
                    line=dict(color="#ef4444", width=1.5, dash="dot"),
                    name="Donchian Mín 20 (Venda)",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=candles.index,
                    y=dl10,
                    mode="lines",
                    line=dict(color="#f59e0b", width=1.5, dash="dash"),
                    name="Saída Mín 10",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=candles.index,
                    y=dh10,
                    mode="lines",
                    line=dict(color="#f59e0b", width=1.5, dash="dash"),
                    name="Saída Máx 10",
                )
            )
        elif model == "smc_macro_micro":
            mme8 = candles["close"].ewm(span=8, adjust=False).mean()
            mme20 = candles["close"].ewm(span=20, adjust=False).mean()
            fig.add_trace(
                go.Scatter(
                    x=candles.index,
                    y=mme8,
                    mode="lines",
                    line=dict(color="#f59e0b", width=1.5),
                    name="MME 8 Micro",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=candles.index,
                    y=mme20,
                    mode="lines",
                    line=dict(color="#3b82f6", width=1.5),
                    name="MME 20 Micro",
                )
            )
        elif model == "d1_mean_reversion" or tf == "D1":
            sma5 = candles["close"].rolling(5).mean()
            sma200 = candles["close"].rolling(200).mean()
            fig.add_trace(
                go.Scatter(
                    x=candles.index,
                    y=sma5,
                    mode="lines",
                    line=dict(color="#06b6d4", width=1.5),
                    name="SMA 5 (Saída)",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=candles.index,
                    y=sma200,
                    mode="lines",
                    line=dict(color="#eab308", width=2),
                    name="SMA 200 (Tendência)",
                )
            )

        # Layout responsivo e dark theme
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#111827",
            plot_bgcolor="#111827",
            margin=dict(l=40, r=40, t=50, b=40),
            height=600,
        )

        self._send_json({"chart": json.loads(fig.to_json())})

    def _handle_post_grid(self, payload: dict[str, Any]) -> None:
        symbol = payload.get("symbol", "XAUUSD")
        start_str = payload.get("start")
        end_str = payload.get("end")
        min_trades = int(payload.get("min_trades", 5))

        start_dt = pd.Timestamp(start_str, tz="UTC") if start_str else None
        end_dt = pd.Timestamp(end_str, tz="UTC") if end_str else None

        source = self._get_candle_source(symbol, payload)
        try:
            c_m1 = load_candles(self.data_root, symbol, "M1", start_dt, end_dt, source=source)
        except Exception as e:
            self._send_json({"error": f"Erro ao carregar dados: {e}"}, status=400)
            return

        if c_m1.empty:
            self._send_json({"error": "Nenhum candle encontrado"}, status=400)
            return

        res = run_grid(
            candles_m1=c_m1,
            symbol=symbol,
            base_config=self.app_cfg.backtest,
            pivot_k_htf=self.app_cfg.structure.pivot_k_htf,
            min_trades=min_trades,
            run_walk_forward=False,
        )

        data = res.attribution_analysis
        ranking = [
            {
                "config_hash": s.config_hash,
                "blocks_filter": s.blocks_filter,
                "entry_mode": s.entry_mode,
                "stop_mode": s.stop_mode,
                "trailing_mode": s.trailing_mode,
                "confluence_profile": s.confluence_profile,
                "is_metrics": s.is_metrics,
                "oos_metrics": s.oos_metrics,
                "performance_drop_pct": s.performance_drop_pct,
            }
            for s in data.get("ranking", [])
        ]

        self._send_json(
            {
                "symbol": symbol,
                "total_variants": data.get("total_variants", 0),
                "qualified_variants": data.get("qualified_variants", 0),
                "robust_variants": data.get("robust_variants", 0),
                "breaker_stats": res.breaker_stats,
                "attribution_by_factor": data.get("attribution_by_factor", {}),
                "ranking": ranking[:15],
            }
        )


def run_ui_server(
    cfg: Config,
    host: str = "127.0.0.1",
    port: int = 8080,
    data_root: Path | None = None,
) -> None:
    """Inicia o servidor web da interface interativa SMC."""
    root = data_root if data_root is not None else cfg.data.root
    SMCRequestHandler.app_cfg = cfg
    SMCRequestHandler.data_root = Path(root)

    server = ThreadingHTTPServer((host, port), SMCRequestHandler)
    print("\n==================================================")
    print("🚀 Assistente SMC UI iniciado com sucesso!")
    print(f"🔗 Acesse no navegador: http://{host}:{port}")
    print("==================================================\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado pelo usuário.")
    finally:
        server.server_close()

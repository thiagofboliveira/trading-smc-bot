import json
import mimetypes
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
import pandas as pd

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
    ConfluenceConfig,
    Config,
    LimitsConfig,
    TrailingConfig,
    ZoneConfig,
)
from smc_trader.data.resample import resample_ohlc
from smc_trader.data.store import load_candles
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
        elif path == "/api/history":
            self._handle_get_history()
        elif path.startswith("/api/history/"):
            run_id = path.replace("/api/history/", "")
            self._handle_get_history_detail(run_id)
        elif path.startswith("/api/files/"):
            file_rel = path.replace("/api/files/", "")
            self._serve_audit_file(file_rel)
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Rota não encontrada")

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

    def _handle_post_backtest(self, payload: dict[str, Any]) -> None:
        symbol = payload.get("symbol", "XAUUSD")
        start_str = payload.get("start")
        end_str = payload.get("end")

        start_dt = pd.Timestamp(start_str, tz="UTC") if start_str else None
        end_dt = pd.Timestamp(end_str, tz="UTC") if end_str else None

        try:
            c_m1 = load_candles(self.data_root, symbol, "M1", start_dt, end_dt)
        except Exception as e:
            self._send_json({"error": f"Erro ao carregar dados: {e}"}, status=400)
            return

        if c_m1.empty:
            self._send_json(
                {"error": "Nenhum candle M1 encontrado para o intervalo"}, status=400
            )
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

        start_dt = pd.Timestamp(start_str, tz="UTC") if start_str else None
        end_dt = pd.Timestamp(end_str, tz="UTC") if end_str else None

        try:
            c_m1 = load_candles(self.data_root, symbol, "M1", start_dt, end_dt)
        except Exception as e:
            self._send_json({"error": f"Erro ao carregar dados: {e}"}, status=400)
            return

        if c_m1.empty:
            self._send_json({"error": "Nenhum dado encontrado"}, status=400)
            return

        # Para o gráfico não ficar pesado no navegador, limitamos as últimas 600 barras do timeframe solicitado
        candles = c_m1 if tf == "M1" else resample_ohlc(c_m1, tf)
        if len(candles) > 600:
            candles = candles.iloc[-600:]

        blocks_filter = payload.get("blocks_filter", ["OB", "FVOB", "BB"])
        zone_cfg = ZoneConfig(blocks_filter=blocks_filter)
        analysis = analyze(candles, self.app_cfg.structure.pivot_k_htf, zone_cfg)

        fig = build_chart(candles, analysis, f"{symbol} ({tf}) — Análise SMC")
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

        try:
            c_m1 = load_candles(self.data_root, symbol, "M1", start_dt, end_dt)
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

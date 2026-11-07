import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import json

from pydantic import ValidationError

from smc_trader.analysis import analyze
from smc_trader.backtest.engine import BacktestEngine
from smc_trader.backtest.exporter import export_backtest_package
from smc_trader.backtest.runner import run_grid
from smc_trader.config import Config, ZoneConfig, load_config
from smc_trader.data.dukascopy_source import fetch_m1
from smc_trader.data.history import fetch_history, years_back_start
from smc_trader.data.mt5_bridge import import_mt5_csv
from smc_trader.data.profit_import import import_profit_csv
from smc_trader.data.quality import check_quality, format_report
from smc_trader.data.resample import resample_ohlc
from smc_trader.data.store import load_candles, save_m1
from smc_trader.viz.chart import build_chart


def _utc(text: str) -> datetime:
    dt = datetime.fromisoformat(text)
    return (
        dt.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None
        else dt.astimezone(timezone.utc)
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="smc")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="baixa M1 da Dukascopy e grava em Parquet")
    fetch.add_argument("symbol")
    fetch.add_argument("--from", dest="start", type=_utc, default=None)
    fetch.add_argument(
        "--to",
        dest="end",
        type=_utc,
        default=None,
        help="padrão com --years: hoje (UTC)",
    )
    fetch.add_argument(
        "--years",
        type=int,
        default=None,
        help="baixa os últimos N anos mês a mês, com retomada (alternativa a --from)",
    )
    fetch.add_argument("--config", type=Path, default=Path("config/default.yaml"))
    fetch.add_argument("--data-root", type=Path, default=None)

    chart = sub.add_parser("chart", help="gera gráfico HTML com estrutura, FVG e zonas")
    chart.add_argument("symbol")
    chart.add_argument("--source", choices=["dukascopy", "mt5"], default="dukascopy")
    chart.add_argument("--tf", choices=["M1", "M5", "M15"], default="M15")
    chart.add_argument("--from", dest="start", type=_utc, default=None)
    chart.add_argument("--to", dest="end", type=_utc, default=None)
    chart.add_argument("--out", type=Path, default=Path("out/chart.html"))
    chart.add_argument("--config", type=Path, default=Path("config/default.yaml"))
    chart.add_argument("--data-root", type=Path, default=None)
    chart.add_argument(
        "--blocks",
        default=None,
        help="tipos de bloco a mostrar, separados por vírgula: OB, FVOB, BB (sobrescreve a config)",
    )

    imp = sub.add_parser(
        "import-csv", help="importa CSV M1 exportado do MT5 ou do Profit"
    )
    imp.add_argument("csv", type=Path)
    imp.add_argument("--symbol", required=True)
    imp.add_argument(
        "--format", choices=["mt5", "profit"], default="mt5", help="origem do arquivo"
    )
    imp.add_argument(
        "--bar-label",
        choices=["open", "close"],
        default="open",
        help="(profit) horário do arquivo é o de abertura ou de fechamento do candle",
    )
    imp.add_argument("--config", type=Path, default=Path("config/default.yaml"))
    imp.add_argument("--data-root", type=Path, default=None)

    chk = sub.add_parser(
        "check-data",
        help="valida a qualidade dos candles M1 gravados (buracos, picos, fuso)",
    )
    chk.add_argument(
        "symbols", nargs="+", help="símbolos, ou 'all' para todos os arquivos da fonte"
    )
    chk.add_argument(
        "--source",
        choices=["dukascopy", "mt5", "profit"],
        default=None,
        help="padrão: profit p/ WIN/WDO, senão dukascopy",
    )
    chk.add_argument(
        "--max-gap",
        type=int,
        default=60,
        help="minutos sem barra a partir dos quais é buraco",
    )
    chk.add_argument("--config", type=Path, default=Path("config/default.yaml"))
    chk.add_argument("--data-root", type=Path, default=None)

    bt = sub.add_parser("backtest", help="executa backtest orientado a eventos no M1")
    bt.add_argument("symbol")
    bt.add_argument("--from", dest="start", type=_utc, default=None)
    bt.add_argument("--to", dest="end", type=_utc, default=None)
    bt.add_argument("--out", type=Path, default=None)
    bt.add_argument("--config", type=Path, default=Path("config/default.yaml"))
    bt.add_argument("--data-root", type=Path, default=None)
    bt.add_argument(
        "--export-audit",
        action="store_true",
        default=False,
        help="exporta pasta {ativo}_{data_hora} com gráficos macro/micro, txt e planilha xlsx de 2 abas",
    )

    grid = sub.add_parser(
        "grid", help="executa grade de parâmetros SMC com divisão IS/OOS e atribuição"
    )
    grid.add_argument("symbol")
    grid.add_argument("--from", dest="start", type=_utc, default=None)
    grid.add_argument("--to", dest="end", type=_utc, default=None)
    grid.add_argument(
        "--min-trades",
        type=int,
        default=30,
        help="piso de trades no IS para qualificação",
    )
    grid.add_argument(
        "--walk-forward",
        action="store_true",
        default=False,
        help="ativa janelas de walk-forward rolante",
    )
    grid.add_argument(
        "--out",
        type=Path,
        default=Path("out/grid_report.md"),
        help="caminho do relatório Markdown de saída",
    )
    grid.add_argument("--config", type=Path, default=Path("config/default.yaml"))
    grid.add_argument("--data-root", type=Path, default=None)

    ui = sub.add_parser("ui", help="inicia servidor web com frontend interativo SMC")
    ui.add_argument(
        "--host", default="127.0.0.1", help="endereço do host (padrão: 127.0.0.1)"
    )
    ui.add_argument(
        "--port", type=int, default=8080, help="porta do servidor (padrão: 8080)"
    )
    ui.add_argument("--config", type=Path, default=Path("config/default.yaml"))
    ui.add_argument("--data-root", type=Path, default=None)

    live = sub.add_parser(
        "live", help="inicia motor de execução autônoma para MetaTrader 5"
    )
    live.add_argument("--config", type=Path, default=Path("config/production.yaml"))
    live.add_argument(
        "--mode",
        choices=["bridge", "mock"],
        default="bridge",
        help="modo de conexão (bridge EA ou mock para teste)",
    )
    live.add_argument(
        "--symbols",
        default=None,
        help="símbolos separados por vírgula (ex: XAUUSD,NAS100)",
    )
    live.add_argument(
        "--risk", type=float, default=None, help="risco percentual por trade (ex: 1.0)"
    )
    live.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="simula ciclo sem loop infinito",
    )

    fibo = sub.add_parser(
        "fibo-backtest",
        help="executa auditoria da estratégia oficial SMC Fibonacci OTE",
    )
    fibo.add_argument(
        "--symbol", default="all", help="símbolo a testar (ex: NAS100 ou 'all')"
    )
    fibo.add_argument(
        "--target",
        choices=["3R", "0_percent", "proj_618"],
        default="3R",
        help="modo de alvo",
    )
    return parser


def _cmd_fetch(args: argparse.Namespace, cfg: Config) -> int:
    instrument = cfg.dukascopy.instruments.get(args.symbol)
    if instrument is None:
        print(
            f"Símbolo sem mapeamento Dukascopy na config: {args.symbol}",
            file=sys.stderr,
        )
        return 2
    root = args.data_root if args.data_root is not None else cfg.data.root
    if args.years is not None:
        if args.start is not None or args.years < 1:
            print("use --years N (N >= 1) sozinho, sem --from", file=sys.stderr)
            return 2
        end = args.end or datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        start = years_back_start(end, args.years)
        print(
            f"{args.symbol}: baixando {start:%Y-%m-%d} a {end:%Y-%m-%d} (mês a mês, retoma de onde parou)"
        )
        res = fetch_history(
            args.symbol,
            instrument,
            start,
            end,
            cfg.dukascopy.offer_side,
            root,
            fetcher=fetch_m1,
        )
        print(
            f"{args.symbol}: {res.rows_saved:,} candles novos | meses: {len(res.saved_months)} baixados, "
            f"{len(res.skipped_months)} já existiam, {len(res.empty_months)} vazios, {len(res.failed_months)} falharam"
        )
        if res.failed_months:
            print(
                f"meses com falha (rode de novo para repetir): {', '.join(res.failed_months)}",
                file=sys.stderr,
            )
            return 1
        return 0
    if args.start is None or args.end is None:
        print("informe --years N ou --from e --to", file=sys.stderr)
        return 2
    if args.start >= args.end:
        print("--from deve ser anterior a --to", file=sys.stderr)
        return 2
    df = fetch_m1(instrument, args.start, args.end, cfg.dukascopy.offer_side)
    if df.empty:
        print(
            f"{args.symbol}: nenhum candle no intervalo {args.start} a {args.end}; nada gravado",
            file=sys.stderr,
        )
        return 1
    save_m1(root, args.symbol, df, source="dukascopy")
    print(f"{args.symbol}: {len(df)} candles M1 gravados em {root}")
    return 0


_B3_SYMBOLS = ("WIN", "WDO")
_B3_HOURS_UTC = set(range(12, 22))  # pregão 09:00-18:xx em São Paulo (UTC-3)


def _cmd_check_data(args: argparse.Namespace, cfg: Config) -> int:
    root = args.data_root if args.data_root is not None else cfg.data.root
    sources = [args.source] if args.source else ["dukascopy", "profit"]
    targets: list[tuple[str, str]] = []
    for sym in args.symbols:
        if sym == "all":
            for src in sources:
                for f in sorted(Path(root).glob(f"*_M1_{src}.parquet")):
                    targets.append((f.name.split("_M1_")[0], src))
        else:
            src = args.source or ("profit" if sym in _B3_SYMBOLS else "dukascopy")
            targets.append((sym, src))

    if not targets:
        print(f"Nenhum dado encontrado em {root}", file=sys.stderr)
        return 2
    exit_code = 0
    for sym, src in targets:
        try:
            df = load_candles(root, sym, "M1", source=src)
        except FileNotFoundError as exc:
            print(exc, file=sys.stderr)
            return 2
        hours = _B3_HOURS_UTC if sym in _B3_SYMBOLS else None
        rep = check_quality(df, sym, max_gap_minutes=args.max_gap, expected_hours=hours)
        print(format_report(rep))
        if not rep.ok:
            exit_code = 1
    return exit_code


def _cmd_chart(args: argparse.Namespace, cfg: Config) -> int:
    zones_cfg = cfg.zones
    if args.blocks is not None:
        parsed = [b.strip().upper() for b in args.blocks.split(",") if b.strip()]
        try:
            zones_cfg = ZoneConfig.model_validate(
                {**cfg.zones.model_dump(), "blocks_filter": parsed}
            )
        except ValidationError:
            print(
                f"--blocks inválido: {args.blocks!r}; use uma lista não vazia de OB, FVOB, BB",
                file=sys.stderr,
            )
            return 2
    root = args.data_root if args.data_root is not None else cfg.data.root
    try:
        candles = load_candles(
            root, args.symbol, args.tf, args.start, args.end, source=args.source
        )
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 2
    k = cfg.structure.pivot_k_ltf if args.tf == "M1" else cfg.structure.pivot_k_htf
    analysis = analyze(candles, k, zones_cfg)
    fig = build_chart(candles, analysis, f"{args.symbol} {args.tf}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(args.out, include_plotlyjs=True)
    print(args.out)
    return 0


def _cmd_import_csv(args: argparse.Namespace, cfg: Config) -> int:
    root = args.data_root if args.data_root is not None else cfg.data.root
    if args.format == "profit":
        df = import_profit_csv(args.csv, bar_label=args.bar_label)
        source = "profit"
    else:
        df = import_mt5_csv(args.csv, cfg.data)
        source = "mt5"
    save_m1(root, args.symbol, df, source=source)
    print(f"{args.symbol}: {len(df)} candles M1 importados em {root} (fonte {source})")
    if len(df):
        first = (
            df.index[0].tz_convert("America/Sao_Paulo")
            if source == "profit"
            else df.index[0]
        )
        print(f"  período: {df.index[0]} a {df.index[-1]} | primeira barra: {first}")
    return 0


def _cmd_backtest(args: argparse.Namespace, cfg: Config) -> int:
    root = args.data_root if args.data_root is not None else cfg.data.root
    try:
        c_m1 = load_candles(root, args.symbol, "M1", args.start, args.end)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 2

    if c_m1.empty:
        print("Nenhum candle encontrado para o período especificado.", file=sys.stderr)
        return 1

    c_m15 = resample_ohlc(c_m1, "M15")
    analysis = analyze(c_m15, cfg.structure.pivot_k_htf, cfg.zones)
    all_zones = analysis.zones + analysis.breakers

    engine = BacktestEngine(cfg.backtest)
    result = engine.run(c_m1, all_zones, symbol=args.symbol)

    m = result.metrics
    print(f"=== Backtest SMC: {args.symbol} ===")
    print(f"Total de trades:   {m['total_trades']}")
    print(
        f"Taxa de acerto:    {m['win_rate']:.1f}% ({m['win_trades']}W / {m['loss_trades']}L)"
    )
    print(f"R Médio:           {m['avg_r']:+.2f}R")
    print(f"Expectativa:       {m['expectancy']:+.2f}R")
    print(f"Profit Factor:     {m['profit_factor']:.2f}")
    print(f"Max Drawdown:      {m['max_drawdown_r']:.2f}R")

    if getattr(args, "export_audit", False):
        export_backtest_package(
            symbol=args.symbol,
            result=result,
            c_m1=c_m1,
            c_m15=c_m15,
            analysis=analysis,
            base_dir=Path("out/backtests"),
        )

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        trades_dict = [
            {
                "id": t.id,
                "symbol": t.symbol,
                "direction": t.direction,
                "zone_kind": t.zone_kind,
                "entry_mode": t.entry_mode,
                "entry_time": t.entry_time.isoformat(),
                "entry_price": t.entry_price,
                "stop_loss": t.stop_loss,
                "take_profit": t.take_profit,
                "exit_time": t.exit_time.isoformat(),
                "exit_price": t.exit_price,
                "exit_reason": t.exit_reason,
                "r_multiple": t.r_multiple,
                "pnl": t.pnl,
                "costs": t.costs,
            }
            for t in result.trades
        ]
        out_payload = {"metrics": m, "trades": trades_dict}
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out_payload, f, indent=2, ensure_ascii=False)
        print(f"Relatório gravado em {args.out}")

    return 0


def _cmd_grid(args: argparse.Namespace, cfg: Config) -> int:
    root = args.data_root if args.data_root is not None else cfg.data.root
    try:
        c_m1 = load_candles(root, args.symbol, "M1", args.start, args.end)
    except FileNotFoundError:
        print(f"Dados M1 não encontrados para {args.symbol} em {root}", file=sys.stderr)
        return 2

    if c_m1.empty:
        print("Nenhum candle encontrado para o período especificado.", file=sys.stderr)
        return 1

    print(f"=== Executando Grade SMC ({args.symbol}): {len(c_m1)} candles M1 ===")
    res = run_grid(
        candles_m1=c_m1,
        symbol=args.symbol,
        base_config=cfg.backtest,
        pivot_k_htf=cfg.structure.pivot_k_htf,
        min_trades=args.min_trades,
        run_walk_forward=args.walk_forward,
    )

    # Imprime sumário no terminal
    data = res.attribution_analysis
    print(f"Total de variantes: {data['total_variants']}")
    print(
        f"Qualificadas (IS trades >= {args.min_trades}): {data['qualified_variants']}"
    )
    print(f"Robustas (OOS Exp > 0): {data['robust_variants']}")

    ranking = data.get("ranking", [])
    if ranking:
        best = ranking[0]
        print(f"\n--- MELHOR COMBINAÇÃO OOS [{best.config_hash}] ---")
        print(f"Blocos:       {best.blocks_filter}")
        print(f"Entrada:      {best.entry_mode}")
        print(f"Stop:         {best.stop_mode}")
        print(f"Trailing:     {best.trailing_mode}")
        print(f"Confluência:  {best.confluence_profile}")
        print(
            f"Expectativa:  {best.oos_metrics.get('expectancy', 0.0):+.2f}R (IS: {best.is_metrics.get('expectancy', 0.0):+.2f}R)"
        )
        print(f"Taxa Acerto:  {best.oos_metrics.get('win_rate', 0.0):.1f}%")
        print(f"Profit Factor:{best.oos_metrics.get('profit_factor', 0.0):.2f}")
        print(f"Max Drawdown: {best.oos_metrics.get('max_drawdown_r', 0.0):.1f}R")

    # Salva relatório Markdown
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(res.markdown_report)
        print(f"\nRelatório completo de atribuição gravado em: {args.out}")

        # Grava JSON estruturado
        json_out = args.out.with_suffix(".json")
        json_payload = {
            "symbol": args.symbol,
            "breaker_stats": res.breaker_stats,
            "total_variants": data["total_variants"],
            "qualified_variants": data["qualified_variants"],
            "robust_variants": data["robust_variants"],
            "ranking": [
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
                for s in ranking
            ],
            "attribution_by_factor": data.get("attribution_by_factor", {}),
        }
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(json_payload, f, indent=2, ensure_ascii=False)
        print(f"Dados estruturados JSON gravados em: {json_out}")

    return 0


def _cmd_ui(args: argparse.Namespace, cfg: Config) -> int:
    from smc_trader.ui.server import run_ui_server

    run_ui_server(cfg, host=args.host, port=args.port, data_root=args.data_root)
    return 0


def _cmd_live(args: argparse.Namespace, cfg: Config) -> int:
    import time
    import yaml
    from smc_trader.config import BacktestConfig
    from smc_trader.execution.live_engine import LiveTradingEngine
    from smc_trader.execution.mt5_interface import MockMT5Client, BridgeEAServer

    prod_cfg_path = (
        args.config if args.config.exists() else Path("config/production.yaml")
    )
    with open(prod_cfg_path, "r", encoding="utf-8") as f:
        prod_data = yaml.safe_load(f)

    symbols_list = (
        args.symbols.split(",")
        if args.symbols
        else list(prod_data.get("symbols", {}).keys())
    )
    risk_pct = (
        args.risk
        if args.risk is not None
        else float(prod_data.get("trading", {}).get("risk_pct_per_trade", 1.0))
    )

    print("=" * 65)
    print("🚀 SMC AUTO-TRADER — MOTOR DE PRODUÇÃO METATRADER 5")
    print(
        f"Modo: {args.mode.upper()} | Ativos: {', '.join(symbols_list)} | Risco: {risk_pct}% por trade"
    )
    print("=" * 65)

    symbol_configs: dict[str, BacktestConfig] = {}
    symbol_blocks: dict[str, list[str]] = {}
    symbol_models: dict[str, str] = {}
    symbol_macro_tfs: dict[str, str] = {}
    symbol_sweeps: dict[str, bool] = {}

    models_catalog = prod_data.get("models", {})
    for sym in symbols_list:
        sym_raw = prod_data.get("symbols", {}).get(sym, {})
        model_key = sym_raw.get("model", "smc_dayflow")
        model_def = models_catalog.get(model_key, {})

        model_name = model_def.get("name", sym_raw.get("model_name", "SMC-DayFlow"))
        macro_tf = sym_raw.get("macro_tf", model_def.get("macro_tf", "M15"))
        require_sweep = sym_raw.get(
            "require_sweep", model_def.get("require_sweep", False)
        )
        entry_mode = sym_raw.get(
            "entry_mode", model_def.get("entry_mode", "confirmation")
        )
        stop_mode = sym_raw.get("stop_mode", model_def.get("stop_mode", "swing"))
        target_r = sym_raw.get("target_r", model_def.get("target_r", 3.0))

        sym_bt = BacktestConfig(
            entry_mode=entry_mode,
            stop_mode=stop_mode,
            target_r=target_r,
        )

        blocks = (
            sym_raw.get("zone", {}).get("blocks_filter")
            or model_def.get("blocks_filter")
            or ["OB"]
        )
        symbol_blocks[sym] = blocks
        symbol_models[sym] = model_name
        symbol_macro_tfs[sym] = macro_tf
        symbol_sweeps[sym] = require_sweep
        if "trailing" in sym_raw and "mode" in sym_raw["trailing"]:
            sym_bt.trailing.mode = sym_raw["trailing"]["mode"]
        symbol_configs[sym] = sym_bt

    bridge_server = None
    if args.mode == "mock":
        client = MockMT5Client(initial_balance=1000.0)
        client.connect()
        print("✅ Cliente Mock MT5 conectado com saldo inicial de $1000.00 USD")
    else:
        bridge_cfg = prod_data.get("bridge", {})
        host = bridge_cfg.get("host", "0.0.0.0")
        port = bridge_cfg.get("port", 8089)
        bridge_server = BridgeEAServer(host=host, port=port)
        bridge_server.start()
        print(f"✅ Ponte MetaTrader 5 iniciada na porta {port} (escutando em {host})")
        print("👉 Se o MT5 estiver na mesma máquina: URL http://127.0.0.1:8089")
        print(
            "👉 Se o MT5 estiver em outra máquina (Windows na rede): URL http://<IP_DESTA_MAQUINA>:8089"
        )
        print(
            "👉 Anexe o Expert Advisor 'mql5/SMC_Bridge_EA.mq5' no gráfico do seu MetaTrader 5!"
        )
        client = MockMT5Client()
        client.connect()

    engine = LiveTradingEngine(
        client=client,
        symbol_configs=symbol_configs,
        symbol_blocks=symbol_blocks,
        symbol_models=symbol_models,
        symbol_macro_tfs=symbol_macro_tfs,
        symbol_sweeps=symbol_sweeps,
        risk_pct=risk_pct,
        notification_callback=lambda msg: print(
            f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        ),
    )

    print("\n🟢 Motor em execução autônoma com Modelos Operacionais Fechados:")
    for sym in symbols_list:
        m_name = symbol_models.get(sym, "SMC-DayFlow")
        m_tf = symbol_macro_tfs.get(sym, "M15")
        s_req = (
            "Sim (Sweep Obrigatório)"
            if symbol_sweeps.get(sym, False)
            else "Não (Fluxo Direto)"
        )
        print(
            f"  📌 {sym:7s} -> Modelo: [{m_name}] | TF: {m_tf}/M1 | Varredura Wyckoff: {s_req}"
        )
    print("\nPressione Ctrl+C para encerrar.\n")
    if args.dry_run:
        print("🔍 Modo Dry-Run ativo: executando ciclo de teste...")
        for sym in symbols_list:
            engine.process_symbol_tick(sym)
        print("✅ Ciclo de teste concluído com sucesso.")
        if bridge_server:
            bridge_server.stop()
        return 0

    try:
        while True:
            for sym in symbols_list:
                engine.process_symbol_tick(sym)
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\n🛑 Encerrando motor autônomo com segurança...")
    finally:
        if bridge_server:
            bridge_server.stop()
    return 0


_FIBO_ALL = ("BRENT", "XAUUSD", "NAS100", "DAX40", "EURUSD", "GBPUSD", "USDJPY")


def _spread_for(symbol: str, cfg: Config) -> float:
    """Spread do ativo vindo de `contracts` na config. Sem contrato, falha: um spread
    inventado (antes: 1.0) distorce o resultado sem avisar."""
    spec = cfg.contracts.get(symbol)
    if spec is None:
        raise KeyError(f"{symbol}: sem entrada em 'contracts' no config/default.yaml")
    return spec.spread


def _cmd_fibo_backtest(args: argparse.Namespace, cfg: Config) -> int:
    import pandas as pd
    from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy

    if args.symbol == "all":
        symbols = list(_FIBO_ALL)  # B3 só quando pedido explicitamente
    else:
        symbols = [args.symbol]
    strat = FiboOTEStrategy(FiboOTEConfig(target_mode=args.target))
    print(
        f"\n🚀 Executando SMC Fibonacci OTE (M5 | Alvo {args.target}) para: {symbols}\n"
    )
    tot_r = 0.0
    for sym in symbols:
        p = next(
            (
                c
                for c in (
                    Path(f"data/{sym}_M1_{src}.parquet")
                    for src in ("dukascopy", "profit")
                )
                if c.exists()
            ),
            Path(f"data/{sym}_M1_dukascopy.parquet"),
        )
        if not p.exists():
            print(f"⚠️ [{sym}] Dados não encontrados em {p}")
            continue
        df = pd.read_parquet(p)
        trades = strat.run_backtest(df, sym, _spread_for(sym, cfg))
        if not trades:
            print(f"[{sym}] Nenhum trade.")
            continue
        n_t = len(trades)
        wins = sum(1 for t in trades if t.win)
        r = sum(t.r_multiple for t in trades)
        tot_r += r
        print(
            f"📊 [{sym:6s}] Trades: {n_t:4d} | Acerto: {(wins / n_t) * 100:5.1f}% | Retorno: {r:+6.1f}R | Exp: {r / n_t:+.3f}R"
        )
    print(f"\n🏆 Total Geral: {tot_r:+.1f}R\n")
    return 0


_COMMANDS = {
    "fetch": _cmd_fetch,
    "check-data": _cmd_check_data,
    "chart": _cmd_chart,
    "import-csv": _cmd_import_csv,
    "backtest": _cmd_backtest,
    "grid": _cmd_grid,
    "ui": _cmd_ui,
    "live": _cmd_live,
    "fibo-backtest": _cmd_fibo_backtest,
}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command in ("live", "fibo-backtest"):
        cfg = load_config(Path("config/default.yaml"))
    else:
        cfg = load_config(args.config)
    return _COMMANDS[args.command](args, cfg)

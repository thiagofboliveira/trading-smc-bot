import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import json

from pydantic import ValidationError

from smc_trader.analysis import analyze
from smc_trader.backtest.engine import BacktestEngine
from smc_trader.config import Config, ZoneConfig, load_config
from smc_trader.data.dukascopy_source import fetch_m1
from smc_trader.data.mt5_bridge import import_mt5_csv
from smc_trader.data.resample import resample_ohlc
from smc_trader.data.store import load_candles, save_m1
from smc_trader.viz.chart import build_chart


def _utc(text: str) -> datetime:
    dt = datetime.fromisoformat(text)
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="smc")
    sub = parser.add_subparsers(dest="command", required=True)
    fetch = sub.add_parser("fetch", help="baixa M1 da Dukascopy e grava em Parquet")
    fetch.add_argument("symbol")
    fetch.add_argument("--from", dest="start", type=_utc, required=True)
    fetch.add_argument("--to", dest="end", type=_utc, required=True)
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

    imp = sub.add_parser("import-csv", help="importa CSV M1 exportado do MT5")
    imp.add_argument("csv", type=Path)
    imp.add_argument("--symbol", required=True)
    imp.add_argument("--config", type=Path, default=Path("config/default.yaml"))
    imp.add_argument("--data-root", type=Path, default=None)

    bt = sub.add_parser("backtest", help="executa backtest orientado a eventos no M1")
    bt.add_argument("symbol")
    bt.add_argument("--from", dest="start", type=_utc, default=None)
    bt.add_argument("--to", dest="end", type=_utc, default=None)
    bt.add_argument("--out", type=Path, default=None)
    bt.add_argument("--config", type=Path, default=Path("config/default.yaml"))
    bt.add_argument("--data-root", type=Path, default=None)
    return parser


def _cmd_fetch(args: argparse.Namespace, cfg: Config) -> int:
    instrument = cfg.dukascopy.instruments.get(args.symbol)
    if instrument is None:
        print(f"Símbolo sem mapeamento Dukascopy na config: {args.symbol}", file=sys.stderr)
        return 2
    if args.start >= args.end:
        print("--from deve ser anterior a --to", file=sys.stderr)
        return 2
    root = args.data_root if args.data_root is not None else cfg.data.root
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


def _cmd_chart(args: argparse.Namespace, cfg: Config) -> int:
    zones_cfg = cfg.zones
    if args.blocks is not None:
        parsed = [b.strip().upper() for b in args.blocks.split(",") if b.strip()]
        try:
            zones_cfg = ZoneConfig.model_validate({**cfg.zones.model_dump(), "blocks_filter": parsed})
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
    df = import_mt5_csv(args.csv, cfg.data)
    save_m1(root, args.symbol, df, source="mt5")
    print(f"{args.symbol}: {len(df)} candles M1 importados em {root}")
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
    print(f"Taxa de acerto:    {m['win_rate']:.1f}% ({m['win_trades']}W / {m['loss_trades']}L)")
    print(f"R Médio:           {m['avg_r']:+.2f}R")
    print(f"Expectativa:       {m['expectancy']:+.2f}R")
    print(f"Profit Factor:     {m['profit_factor']:.2f}")
    print(f"Max Drawdown:      {m['max_drawdown_r']:.2f}R")

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


_COMMANDS = {
    "fetch": _cmd_fetch,
    "chart": _cmd_chart,
    "import-csv": _cmd_import_csv,
    "backtest": _cmd_backtest,
}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    cfg = load_config(args.config)
    return _COMMANDS[args.command](args, cfg)

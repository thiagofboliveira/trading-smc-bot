import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from smc_trader.analysis import analyze
from smc_trader.config import Config, load_config
from smc_trader.data.dukascopy_source import fetch_m1
from smc_trader.data.mt5_bridge import import_mt5_csv
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
    chart.add_argument("--tf", choices=["M1", "M5", "M15"], default="M15")
    chart.add_argument("--from", dest="start", type=_utc, default=None)
    chart.add_argument("--to", dest="end", type=_utc, default=None)
    chart.add_argument("--out", type=Path, default=Path("out/chart.html"))
    chart.add_argument("--config", type=Path, default=Path("config/default.yaml"))
    chart.add_argument("--data-root", type=Path, default=None)

    imp = sub.add_parser("import-csv", help="importa CSV M1 exportado do MT5")
    imp.add_argument("csv", type=Path)
    imp.add_argument("--symbol", required=True)
    imp.add_argument("--config", type=Path, default=Path("config/default.yaml"))
    imp.add_argument("--data-root", type=Path, default=None)
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
    save_m1(root, args.symbol, df)
    print(f"{args.symbol}: {len(df)} candles M1 gravados em {root}")
    return 0


def _cmd_chart(args: argparse.Namespace, cfg: Config) -> int:
    root = args.data_root if args.data_root is not None else cfg.data.root
    try:
        candles = load_candles(root, args.symbol, args.tf, args.start, args.end)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 2
    k = cfg.structure.pivot_k_ltf if args.tf == "M1" else cfg.structure.pivot_k_htf
    analysis = analyze(candles, k, cfg.zones)
    fig = build_chart(candles, analysis, f"{args.symbol} {args.tf}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(args.out, include_plotlyjs=True)
    print(args.out)
    return 0


def _cmd_import_csv(args: argparse.Namespace, cfg: Config) -> int:
    root = args.data_root if args.data_root is not None else cfg.data.root
    df = import_mt5_csv(args.csv, cfg.data)
    save_m1(root, args.symbol, df)
    print(f"{args.symbol}: {len(df)} candles M1 importados em {root}")
    return 0


_COMMANDS = {"fetch": _cmd_fetch, "chart": _cmd_chart, "import-csv": _cmd_import_csv}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    cfg = load_config(args.config)
    return _COMMANDS[args.command](args, cfg)

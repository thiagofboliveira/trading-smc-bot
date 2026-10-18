import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from smc_trader.config import load_config
from smc_trader.data.dukascopy_source import fetch_m1
from smc_trader.data.store import save_m1


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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    cfg = load_config(args.config)
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

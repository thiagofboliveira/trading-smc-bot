"""Exporta histórico M1 do MT5 para CSV. Roda no Python do Windows (Wine).

Usa apenas a biblioteca padrão e MetaTrader5. O horário gravado é o do
servidor da corretora (não UTC).
"""
import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

HEADER = ["time", "open", "high", "low", "close", "tick_volume", "spread", "real_volume"]


def _parse_date(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def _month_chunks(start: datetime, end: datetime):
    cur = start
    while cur < end:
        nxt = cur.replace(year=cur.year + cur.month // 12, month=cur.month % 12 + 1, day=1)
        yield cur, min(nxt, end)
        cur = nxt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exporta M1 do MT5 para CSV")
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--from", dest="start", type=_parse_date, required=True, help="YYYY-MM-DD")
    parser.add_argument("--to", dest="end", type=_parse_date, required=True, help="YYYY-MM-DD")
    parser.add_argument("--out", type=Path, default=Path("."))
    args = parser.parse_args(argv)

    import MetaTrader5 as mt5  # import tardio: permite --help fora do Wine

    if not mt5.initialize():
        print(f"initialize() falhou: {mt5.last_error()}", file=sys.stderr)
        return 1
    try:
        args.out.mkdir(parents=True, exist_ok=True)
        for symbol in args.symbols:
            if not mt5.symbol_select(symbol, True):
                print(f"símbolo indisponível: {symbol}", file=sys.stderr)
                return 1
            target = args.out / f"{symbol}_M1.csv"
            total = 0
            with open(target, "w", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(HEADER)
                for chunk_start, chunk_end in _month_chunks(args.start, args.end):
                    rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, chunk_start, chunk_end)
                    if rates is None:
                        print(
                            f"{symbol}: copy_rates_range falhou em {chunk_start:%Y-%m}: "
                            f"{mt5.last_error()}",
                            file=sys.stderr,
                        )
                        continue
                    for r in rates:
                        writer.writerow([int(r["time"]), r["open"], r["high"], r["low"],
                                         r["close"], int(r["tick_volume"]), int(r["spread"]),
                                         int(r["real_volume"])])
                        total += 1
            print(f"{symbol}: {total} linhas em {target}")
    finally:
        mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

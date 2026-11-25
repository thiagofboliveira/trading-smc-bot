"""Baixa candles D1/H4 (bid e ask) da Dukascopy e grava no formato do estudo da MME80.

Uso (no PC do usuário; a Dukascopy bloqueia o container de nuvem):
    uv run python scripts/fetch_dukascopy_htf.py --out data/htf_export --start 2003-01-01

Saída: <out>/<SIMBOLO>_D1.csv e _H4.csv (time,open,high,low,close,tick_volume,spread), em
preço BID, com `spread` = spread típico em preço (mediana de ask - bid no fechamento, nos
últimos 2 anos, com piso no spread de config/default.yaml), e <out>/symbols_meta.csv com
point = 1 (o spread já está em preço). Depois rode:
    uv run python scripts/research/run_ema80_pullback_study.py --data-dir data/htf_export --tf D1
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]

INTERVALS = {"D1": "INTERVAL_DAY_1", "H4": "INTERVAL_HOUR_4"}


def fetch_side(fetcher, dk, instrument, interval, side, start, end) -> pd.DataFrame:
    """Baixa em blocos de 1 ano (o limite por chamada da biblioteca é de 30 mil barras)."""
    frames = []
    t = start
    while t < end:
        t2 = min(t.replace(year=t.year + 1), end)
        df = fetcher(
            instrument=instrument,
            interval=getattr(dk, INTERVALS[interval]),
            offer_side=dk.OFFER_SIDE_BID if side == "bid" else dk.OFFER_SIDE_ASK,
            start=t,
            end=t2,
        )
        if df is not None and len(df):
            frames.append(df)
        t = t2
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames)
    out.index = pd.DatetimeIndex(out.index, name="time")
    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out[["open", "high", "low", "close", "volume"]].dropna()


def typical_spread(bid: pd.DataFrame, ask: pd.DataFrame, floor: float) -> float:
    both = bid[["close"]].join(ask[["close"]], lsuffix="_bid", rsuffix="_ask", how="inner")
    if both.empty:
        return floor
    recent = both[both.index >= both.index[-1] - pd.Timedelta(days=730)]
    s = (recent["close_ask"] - recent["close_bid"]).clip(lower=0).median()
    return float(max(s, floor))


def export(symbol, instrument, floor, out_dir, start, end, fetcher, dk) -> dict | None:
    spread_ref = None
    for tf in INTERVALS:
        bid = fetch_side(fetcher, dk, instrument, tf, "bid", start, end)
        if bid.empty:
            print(f"{symbol} {tf}: sem dados", file=sys.stderr)
            continue
        if spread_ref is None:  # mede o spread uma vez, no D1
            ask = fetch_side(fetcher, dk, instrument, tf, "ask", start, end)
            spread_ref = typical_spread(bid, ask, floor)
        df = bid.rename(columns={"volume": "tick_volume"})
        df["spread"] = spread_ref
        df.index = df.index.strftime("%Y-%m-%d %H:%M")
        df.to_csv(out_dir / f"{symbol}_{tf}.csv", index_label="time")
        print(f"{symbol} {tf}: {len(df)} barras, {df.index[0]} a {df.index[-1]}, "
              f"spread {spread_ref:g}")
    if spread_ref is None:
        return None
    return {"symbol": symbol, "point": 1.0, "digits": 0, "spread_price": spread_ref}


def main(argv=None, fetcher=None, dk=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "htf_export")
    ap.add_argument("--start", default="2003-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--symbols", default=None, help="lista separada por vírgula")
    ap.add_argument("--config", type=Path, default=ROOT / "config" / "default.yaml")
    args = ap.parse_args(argv)

    if dk is None:
        import dukascopy_python as dk  # noqa: PLC0415
    fetcher = fetcher or dk.fetch
    cfg = yaml.safe_load(args.config.read_text())
    instruments = cfg["dukascopy"]["instruments"]
    floors = cfg.get("backtest", {}).get("costs", {}).get("spread_pips", {})
    symbols = args.symbols.split(",") if args.symbols else list(instruments)
    start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    end = (datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc) if args.end
           else datetime.now(timezone.utc))
    args.out.mkdir(parents=True, exist_ok=True)
    meta = []
    for sym in symbols:
        if sym not in instruments:
            print(f"{sym}: sem instrumento Dukascopy em {args.config}", file=sys.stderr)
            continue
        try:
            row = export(sym, instruments[sym], float(floors.get(sym, 0.0)), args.out,
                         start, end, fetcher, dk)
        except Exception as e:  # um ativo com erro não derruba os outros
            print(f"{sym}: erro {type(e).__name__}: {e}", file=sys.stderr)
            continue
        if row:
            meta.append(row)
    pd.DataFrame(meta).to_csv(args.out / "symbols_meta.csv", index=False)
    print(f"ok: {len(meta)} ativos em {args.out}")


if __name__ == "__main__":
    main()

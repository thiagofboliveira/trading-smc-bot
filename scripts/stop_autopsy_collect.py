"""Coleta trades de 1 ano com features de contexto para autópsia dos stops.

Saída: out/analysis/trades_<SYMBOL>.pkl (DataFrame por ativo, ambos os modelos).
Uso: uv run python scripts/stop_autopsy_collect.py [SYMBOL ...]
"""
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

from smc_trader.analysis import analyze
from smc_trader.backtest.engine import BacktestEngine
from smc_trader.config import BacktestConfig, ZoneConfig, load_config
from smc_trader.data.resample import resample_ohlc
from smc_trader.data.store import load_candles
from smc_trader.structure.market_structure import detect_structure
from smc_trader.structure.pivots import find_pivots

SYMBOLS = ["BRENT", "XAUUSD", "NAS100", "DAX40", "EURUSD", "GBPUSD", "USDJPY"]
MODELS = [
    ("DayFlow", "M15", ["OB"], False),
    ("Wyckoff", "H1", ["OB", "BB"], True),
]
OUT = Path("out/analysis")


def atr(c: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = c["close"].shift(1)
    tr = pd.concat([c["high"] - c["low"], (c["high"] - pc).abs(), (c["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def trend_series(events):
    """Arrays (times, dir_sign) das quebras de estrutura para lookup do último evento."""
    ev = sorted(events, key=lambda e: e.time)
    return (
        np.array([e.time.value for e in ev], dtype="int64"),
        np.array([1 if e.direction == "up" else -1 for e in ev]),
    )


def last_trend(ts, t) -> int:
    i = np.searchsorted(ts[0], t.value, side="right") - 1
    return int(ts[1][i]) if i >= 0 else 0


def run_symbol(sym: str):
    cfg = load_config(Path("config/default.yaml"))
    c1 = load_candles(Path("data"), sym, "M1")
    t0 = time.time()
    piv = find_pivots(c1, k=2)
    ev1 = detect_structure(c1, piv)
    pre = {
        "events": ev1,
        "chochs": {(e.direction, e.time): e for e in ev1 if e.kind == "CHoCH"},
        "bos": {(e.direction, e.time): e for e in ev1 if e.kind == "BOS"},
    }
    c15, c60, c240 = (resample_ohlc(c1, tf) for tf in ("M15", "H1", "H4"))
    zc = ZoneConfig(blocks_filter=["OB"])
    tr_h4 = trend_series(analyze(c240, k=3, zones_cfg=zc).events)
    tr_h1 = trend_series(analyze(c60, k=3, zones_cfg=zc).events)
    atr15 = atr(c15)
    atr_idx = atr15.index
    hi, lo = c1["high"].to_numpy(), c1["low"].to_numpy()
    idx1 = c1.index
    rows = []
    for model, tf, blocks, sweep in MODELS:
        cm = c15 if tf == "M15" else c60
        an = analyze(cm, k=3, zones_cfg=ZoneConfig(blocks_filter=blocks))
        zones = an.zones if blocks == ["OB"] else an.zones + an.breakers
        if sweep:
            zones = [z for z in zones if z.swept_liquidity]
        ev_kind = {e.time: e.kind for e in an.events}
        zmap = {(z.created_at, z.direction): z for z in zones}
        bt = BacktestConfig(
            entry_mode="confirmation", stop_mode="swing", target_mode="fixed_r", target_r=3.0,
            costs=cfg.backtest.costs, session=cfg.backtest.session, limits=cfg.backtest.limits,
        )
        res = BacktestEngine(bt).run(c1, zones, symbol=sym, precomputed_m1=pre)
        for t in res.trades:
            long = t.direction == "long"
            sgn = 1 if long else -1
            risk = abs(t.entry_price - t.stop_loss)
            z = zmap.get((t.zone_created_at, t.direction))
            a_i = atr_idx.searchsorted(t.entry_time, side="left") - 1
            a = float(atr15.iloc[a_i]) if a_i >= 0 else np.nan
            i0, i1 = idx1.searchsorted(t.entry_time), idx1.searchsorted(t.exit_time)
            seg_h, seg_l = hi[i0 : i1 + 1], lo[i0 : i1 + 1]
            mfe = ((seg_h.max() - t.entry_price) if long else (t.entry_price - seg_l.min())) / risk if len(seg_h) else 0
            j1 = idx1.searchsorted(t.exit_time + pd.Timedelta(hours=4))
            post_h, post_l = hi[i1 + 1 : j1], lo[i1 + 1 : j1]
            tp = t.take_profit
            rev = bool((post_h.max() >= tp) if long else (post_l.min() <= tp)) if len(post_h) and tp else False
            rows.append(
                dict(
                    symbol=sym, model=model, id=t.id, direction=t.direction,
                    entry_time=t.entry_time, exit_time=t.exit_time, entry=t.entry_price,
                    stop=t.stop_loss, tp=tp, exit_reason=t.exit_reason, r=t.r_multiple,
                    risk=risk, risk_atr=risk / a if a else np.nan,
                    hour=t.entry_time.hour, dow=t.entry_time.dayofweek,
                    month=t.entry_time.strftime("%Y-%m"),
                    dur_min=(t.exit_time - t.entry_time).total_seconds() / 60,
                    age_h=(t.entry_time - t.zone_created_at).total_seconds() / 3600,
                    zone_kind=t.zone_kind,
                    struct=ev_kind.get(t.zone_created_at, "BREAKER"),
                    swept=bool(z.swept_liquidity) if z else False,
                    h4_align=last_trend(tr_h4, t.entry_time) * sgn,
                    h1_align=last_trend(tr_h1, t.entry_time) * sgn,
                    zone_size_atr=((z.high - z.low) / a) if (z and a) else np.nan,
                    mfe_r=float(mfe), reversed_after_stop=rev,
                )
            )
    df = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    df.to_pickle(OUT / f"trades_{sym}.pkl")
    print(f"{sym}: {len(df)} trades em {time.time() - t0:.0f}s", flush=True)
    return sym


if __name__ == "__main__":
    syms = sys.argv[1:] or SYMBOLS
    with Pool(min(4, len(syms))) as p:
        p.map(run_symbol, syms)
    print("OK", flush=True)

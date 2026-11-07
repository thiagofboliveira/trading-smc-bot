"""Compara o motor Fibo antigo (commit informado) com o atual, ativo a ativo.

Uso: uv run python scripts/compare_fibo_engines.py [--old-rev e62b98f]

Serve para quantificar quanto do resultado antigo vinha de vieses do simulador.
O motor antigo é lido do git, não fica no repositório.
"""
import argparse
import importlib.util
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd

from smc_trader.config import load_config
from smc_trader.strategies import fibo_ote as new

PROFILES = {
    "estrutural (61,8% / stop 100% / MME8)": dict(fibo_entry=0.618, fibo_stop=1.0, trailing_exit_ma="ema8"),
    "trailing   (61,8% / stop 79%  / MME8)": dict(fibo_entry=0.618, fibo_stop=0.79, trailing_exit_ma="ema8"),
    "blindado   (61,8% / stop 100% / trava)": dict(fibo_entry=0.618, fibo_stop=1.0, trailing_exit_ma="ema8", use_lock_2to1=True),
}
SYMBOLS = ["XAUUSD", "NAS100", "US30", "BRENT", "EURUSD", "GBPUSD"]


def load_old(rev: str):
    src = subprocess.check_output(["git", "show", f"{rev}:src/smc_trader/strategies/fibo_ote.py"], text=True)
    tmp = Path(tempfile.mkdtemp()) / "fibo_ote_old.py"
    tmp.write_text(src)
    spec = importlib.util.spec_from_file_location("fibo_ote_old", tmp)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["fibo_ote_old"] = mod  # dataclasses precisa achar o módulo
    spec.loader.exec_module(mod)
    return mod


def summarize(trades) -> tuple[int, float, float, float]:
    n = len(trades)
    if n == 0:
        return 0, 0.0, 0.0, 0.0
    r = sum(t.r_multiple for t in trades)
    gp = sum(t.r_multiple for t in trades if t.r_multiple > 0)
    gl = -sum(t.r_multiple for t in trades if t.r_multiple < 0)
    return n, r, 100 * sum(t.win for t in trades) / n, (gp / gl if gl else float("inf"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-rev", default="e62b98f")
    args = ap.parse_args()
    cfg = load_config(Path("config/default.yaml"))
    old = load_old(args.old_rev)
    data = {s: pd.read_parquet(f"data/{s}_M1_dukascopy.parquet") for s in SYMBOLS}

    for name, params in PROFILES.items():
        print(f"\n=== {name} ===")
        print(f"{'ativo':8s} | {'ANTIGO: n':>9s} {'R':>8s} {'acerto':>7s} {'PF':>5s} | {'NOVO: n':>8s} {'R':>8s} {'acerto':>7s} {'PF':>5s} | {'long R':>8s} {'short R':>8s}")
        tot_o = tot_n = 0.0
        for sym in SYMBOLS:
            spread = cfg.contracts[sym].spread
            kw = dict(target_mode="0_percent", pivot_k=2, **params)
            t_old = old.FiboOTEStrategy(old.FiboOTEConfig(**kw)).run_backtest(data[sym], sym, spread)
            t_new = new.FiboOTEStrategy(new.FiboOTEConfig(**kw)).run_backtest(data[sym], sym, spread)
            on, orr, ow, opf = summarize(t_old)
            nn, nr, nw, npf = summarize(t_new)
            lr = sum(t.r_multiple for t in t_new if t.direction == "long")
            sr = sum(t.r_multiple for t in t_new if t.direction == "short")
            tot_o += orr
            tot_n += nr
            print(f"{sym:8s} | {on:9d} {orr:+8.1f} {ow:6.1f}% {opf:5.2f} | {nn:8d} {nr:+8.1f} {nw:6.1f}% {npf:5.2f} | {lr:+8.1f} {sr:+8.1f}")
        print(f"{'TOTAL':8s} | {'':9s} {tot_o:+8.1f} {'':7s} {'':5s} | {'':8s} {tot_n:+8.1f}")


if __name__ == "__main__":
    main()

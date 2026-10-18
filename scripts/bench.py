"""Benchmark dos detectores: `uv run python scripts/bench.py`. Só imprime."""

import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tests"))

from helpers import random_walk_candles  # noqa: E402

from smc_trader.analysis import analyze  # noqa: E402
from smc_trader.config import ZoneConfig  # noqa: E402
from smc_trader.structure.market_structure import detect_structure  # noqa: E402
from smc_trader.structure.pivots import find_pivots  # noqa: E402
from smc_trader.zones.breaker import build_breakers  # noqa: E402
from smc_trader.zones.fvg import find_fvgs  # noqa: E402
from smc_trader.zones.liquidity import find_sweeps  # noqa: E402
from smc_trader.zones.orderblock import build_zones  # noqa: E402

CASES = [(2000, "M15", 3), (12000, "M15", 3), (30000, "M1", 2)]
COLUMNS = [
    "analyze",
    "find_pivots",
    "detect_structure",
    "find_fvgs",
    "find_sweeps",
    "build_zones",
    "build_breakers",
]


def timed(fn):
    start = perf_counter()
    result = fn()
    return result, perf_counter() - start


def bench(n: int, tf: str, k: int) -> dict[str, float]:
    candles = random_walk_candles(n, seed=5, tf=tf)
    cfg = ZoneConfig()
    times: dict[str, float] = {}
    _, times["analyze"] = timed(lambda: analyze(candles, k, cfg))
    pivots, times["find_pivots"] = timed(lambda: find_pivots(candles, k))
    events, times["detect_structure"] = timed(lambda: detect_structure(candles, pivots))
    fvgs, times["find_fvgs"] = timed(lambda: find_fvgs(candles, cfg.fvg_min_size))
    sweeps, times["find_sweeps"] = timed(lambda: find_sweeps(candles, pivots))
    zones, times["build_zones"] = timed(
        lambda: build_zones(candles, events, fvgs, sweeps, cfg)
    )
    _, times["build_breakers"] = timed(
        lambda: build_breakers(candles, zones, events, fvgs, sweeps, cfg)
    )
    return times


def main() -> None:
    print(f"{'caso':<18}" + "".join(f"{c:>18}" for c in COLUMNS), flush=True)
    for n, tf, k in CASES:
        times = bench(n, tf, k)
        label = f"{n} {tf} k={k}"
        print(f"{label:<18}" + "".join(f"{times[c]:>17.3f}s" for c in COLUMNS), flush=True)


if __name__ == "__main__":
    main()

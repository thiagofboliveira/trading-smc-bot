"""Diagnóstico da vantagem do Fibo OTE: custo real x custo zero, em M5, M15 e H1.

Reproduz as tabelas da seção 2.3 de docs/PESQUISA_ESTRATEGIAS_INTRADAY.md.
Leitura: com alvo fixo de 3R, um passeio aleatório acerta 25%. Se o acerto sem custo
fica em ~25% e o R por trade em ~0, a entrada não tem vantagem.

Uso: uv run python scripts/research/exp_custo_timeframe_fibo.py
"""

from pathlib import Path

import pandas as pd

from smc_trader.config import load_config
from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy

ZERO = 1e-9  # spread "zero" (o motor exige spread > 0 em alguns filtros)

MODELS = {
    "trailing": dict(fibo_entry=0.705, fibo_stop=0.79),
    "estrutural": dict(fibo_entry=0.705, fibo_stop=1.0),
    "alvo3R_estr": dict(fibo_entry=0.705, fibo_stop=1.0, target_mode="3R", trailing_exit_ma=None),
}
TIMEFRAMES = ("5min", "15min", "60min")


def main() -> None:
    cfg = load_config(Path("config/default.yaml"))
    data = {
        p.name.split("_M1")[0]: pd.read_parquet(p)
        for p in sorted(Path("data").glob("*_M1_dukascopy.parquet"))
    }
    rows = []
    for tf in TIMEFRAMES:
        for name, kw in MODELS.items():
            for label in ("real", "zero"):
                total = n = wins = 0
                for sym, df in data.items():
                    if sym not in cfg.contracts:
                        continue
                    spread = cfg.contracts[sym].spread
                    s = spread if label == "real" else ZERO
                    # mantém o mesmo filtro de perna mínima (10 x spread real) nos dois cenários
                    leg_mult = 10.0 if label == "real" else 10.0 * spread / ZERO
                    params = {"trailing_exit_ma": "ema8", **kw}
                    c = FiboOTEConfig(timeframe=tf, pivot_k=3, min_leg_spread_mult=leg_mult, **params)
                    trades = FiboOTEStrategy(c).run_backtest(df, sym, s)
                    total += sum(t.r_multiple for t in trades)
                    n += len(trades)
                    wins += sum(t.r_multiple > 0 for t in trades)
                rows.append((tf, name, label, n, round(total, 1), round(total / max(n, 1), 3),
                             round(100 * wins / max(n, 1), 1)))
    cols = ["tf", "modelo", "custo", "trades", "R", "R/trade", "acerto%"]
    print(pd.DataFrame(rows, columns=cols).to_string(index=False))


if __name__ == "__main__":
    main()

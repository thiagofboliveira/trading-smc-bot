"""B0-4: invariância de prefixo, o detector genérico de lookahead.

Rodar o backtest com os dados completos e com os dados truncados num instante `t` não
pode mudar nenhum trade já encerrado antes de `t`. Se mudar, a decisão daquele trade
usou informação posterior a ele.

O corte cai sempre numa fronteira de 15 minutos, para que todas as barras M5/M15 do
prefixo sejam idênticas às do dado completo.
"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from smc_trader.analysis import analyze
from smc_trader.backtest.engine import BacktestEngine
from smc_trader.config import BacktestConfig, ZoneConfig
from smc_trader.data.candles import with_close_time
from smc_trader.data.resample import resample_ohlc
from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy

N_CUTS = 20
SLACK = pd.Timedelta(minutes=15)  # tolerância na borda: o último trecho não é comparado


def synthetic_m1(n: int = 30_000, seed: int = 7) -> pd.DataFrame:
    """Passeio aleatório com volatilidade em regimes, M1 contínuo a partir de uma segunda-feira."""
    rng = np.random.default_rng(seed)
    vol = np.repeat(rng.choice([0.15, 0.4, 1.0], size=n // 500 + 1), 500)[:n]
    close = 2000 + np.cumsum(rng.normal(0, 1, n) * vol)
    open_ = np.concatenate([[2000.0], close[:-1]])
    wick = np.abs(rng.normal(0, 0.5, (n, 2))) * vol[:, None]
    high = np.maximum(open_, close) + wick[:, 0]
    low = np.minimum(open_, close) - wick[:, 1]
    idx = pd.date_range("2024-06-03 00:00", periods=n, freq="1min", tz="UTC", name="time")
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": 1.0}, index=idx)


def real_m1(symbol: str, rows: int) -> pd.DataFrame:
    path = Path(f"data/{symbol}_M1_dukascopy.parquet")
    if not path.exists():
        pytest.skip("sem dados locais")
    return pd.read_parquet(path).iloc[:rows]


def random_cuts(df: pd.DataFrame, n: int, seed: int = 11) -> list[pd.Timestamp]:
    rng = np.random.default_rng(seed)
    lo, hi = int(len(df) * 0.15), int(len(df) * 0.95)
    cuts = {df.index[int(p)].floor("15min") for p in rng.integers(lo, hi, size=n * 3)}
    return sorted(cuts)[:n] if len(cuts) >= n else sorted(cuts)


def assert_prefix_invariant(run, df: pd.DataFrame, n_cuts: int = N_CUTS) -> int:
    """`run(df)` devolve uma lista de trades com (entry_time, exit_time, direction, exit_reason, r).

    Devolve quantos trades foram efetivamente comparados, para o teste poder exigir
    que a comparação não foi vazia.
    """
    full = run(df)
    compared = 0
    cuts = random_cuts(df, n_cuts)
    assert len(cuts) >= n_cuts, "poucos cortes distintos"
    for cut in cuts:
        horizon = cut - SLACK
        want = [t for t in full if t[1] < horizon]
        got = [t for t in run(df[df.index < cut]) if t[1] < horizon]
        assert got == want, f"corte {cut}: trades do prefixo diferem do dado completo"
        compared += len(want)
    return compared


# --- motor Fibo -------------------------------------------------------------------------------
def fibo_runner(**kw):
    def run(df):
        cfg = FiboOTEConfig(trailing_exit_ma="ema8", pivot_k=2, **kw)
        trades = FiboOTEStrategy(cfg).run_backtest(df, "SYN", 0.3)
        return sorted(
            (t.entry_time, t.exit_time, t.direction, t.exit_reason, round(float(t.r_multiple), 9)) for t in trades
        )

    return run


FIBO_VARIANTS = [
    dict(fibo_entry=0.705, fibo_stop=0.79, target_mode="0_percent"),
    dict(fibo_entry=0.618, fibo_stop=1.0, target_mode="3R", use_lock_2to1=True),
]


@pytest.mark.parametrize("kw", FIBO_VARIANTS)
def test_fibo_invariancia_de_prefixo_sintetico(kw):
    compared = assert_prefix_invariant(fibo_runner(**kw), synthetic_m1())
    assert compared > 50, "o teste precisa comparar trades de verdade"


@pytest.mark.parametrize("symbol", ["XAUUSD", "NAS100"])
def test_fibo_invariancia_de_prefixo_dados_reais(symbol):
    compared = assert_prefix_invariant(fibo_runner(**FIBO_VARIANTS[0]), real_m1(symbol, 60_000))
    assert compared > 50


# --- motor de zonas SMC -----------------------------------------------------------------------
def smc_runner(entry_mode: str):
    def run(df):
        cfg = BacktestConfig(entry_mode=entry_mode, stop_mode="swing")
        df = with_close_time(df, "M1")  # o motor espera candles no formato de `load_candles`
        m15 = resample_ohlc(df, "M15")
        analysis = analyze(m15, 3, ZoneConfig(blocks_filter=["OB", "FVOB"]))
        res = BacktestEngine(cfg).run(df, analysis.zones, symbol="SYN")
        return sorted(
            (t.entry_time, t.exit_time, t.direction, t.exit_reason, round(float(t.r_multiple), 9)) for t in res.trades
        )

    return run


@pytest.mark.parametrize("entry_mode", ["touch", "confirmation"])
def test_smc_invariancia_de_prefixo_sintetico(entry_mode):
    df = synthetic_m1(n=25_000, seed=3)
    compared = assert_prefix_invariant(smc_runner(entry_mode), df)
    assert compared > 20


def test_smc_invariancia_de_prefixo_dados_reais():
    compared = assert_prefix_invariant(smc_runner("touch"), real_m1("XAUUSD", 40_000))
    assert compared > 20

"""Time-series momentum (TSMOM) diversificado, em dados diários de fechamento.

Referência: Moskowitz, Ooi & Pedersen (2012), "Time Series Momentum", e Hurst, Ooi &
Pedersen (2017), "A Century of Evidence on Trend-Following Investing".

Regra (parâmetros fixados pela literatura, NÃO otimizados nestes dados):
- Sinal no fechamento `d`: sinal do retorno dos últimos `lookback` pregões (252 ≈ 12 meses).
- Tamanho: alvo de volatilidade por ativo (`asset_vol_target`, 40% a.a.) dividido pela vol
  estimada por EWMA (centro de massa 60 dias) com dados até `d`, e dividido pelo número de
  ativos ativos em `d`. Alavancagem por ativo limitada por `max_leverage`.
- Rebalanceamento só no último pregão de cada mês.

Causalidade (AGENTS.md, seção 1):
- Toda decisão em `d` usa preços até `close[d]` (retorno passado e EWMA são causais).
- A ordem é executada no fechamento do pregão SEGUINTE (`d + 1`): o custo é cobrado em
  `d + 1` e a posição nova só ganha o retorno de `d + 2` em diante. Isso é mais conservador
  que executar no próprio fechamento que gerou o sinal.
- Custo: `cost_bps[ativo]` sobre o nocional negociado (spread + slippage), em todo ajuste.

Limitações dos dados (FRED): só fechamento; câmbio é spot (sem diferencial de juros/carry);
petróleo e gás são spot (sem custo de rolagem de futuro). Ver o relatório.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TRADING_DAYS = 261


@dataclass
class TSMOMConfig:
    lookback: int = 252
    vol_com: int = 60  # centro de massa da EWMA, em pregões
    vol_min_obs: int = 60
    asset_vol_target: float = 0.40
    max_leverage: float = 4.0  # por ativo, antes de dividir pelo número de ativos
    rebalance: str = "M"  # "M" = último pregão do mês; "D" = todo pregão
    execution_lag: int = 1  # pregões entre a decisão e a execução
    default_cost_bps: float = 3.0
    cost_bps: dict = field(default_factory=dict)
    max_ffill: int = 5  # feriados de um mercado; lacunas maiores ficam sem posição


def daily_returns(prices: pd.DataFrame, max_ffill: int = 5) -> pd.DataFrame:
    p = prices.sort_index().ffill(limit=max_ffill)
    return p.pct_change(fill_method=None)


def momentum_signal(prices: pd.DataFrame, lookback: int, max_ffill: int = 5) -> pd.DataFrame:
    """+1/-1/0 no fechamento de cada dia, usando só preços até aquele dia."""
    p = prices.sort_index().ffill(limit=max_ffill)
    past = p / p.shift(lookback) - 1.0
    return np.sign(past)


def ewma_vol(returns: pd.DataFrame, com: int, min_obs: int) -> pd.DataFrame:
    """Vol anualizada EWMA, causal: o valor em `d` usa retornos até `d`."""
    var = (returns**2).ewm(com=com, min_periods=min_obs).mean()
    return np.sqrt(var * TRADING_DAYS)


def rebalance_mask(index: pd.DatetimeIndex, rule: str) -> pd.Series:
    if rule == "D":
        return pd.Series(True, index=index)
    if rule != "M":
        raise ValueError(f"rebalance desconhecido: {rule}")
    s = pd.Series(index.to_period("M"), index=index)
    # último pregão do mês = o próximo pregão está noutro mês. O último dia da série não é
    # tratado como fim de mês (não sabemos se o mês acabou).
    nxt = s.shift(-1)
    return (s != nxt) & nxt.notna()


def target_weights(
    prices: pd.DataFrame, cfg: TSMOMConfig, signal: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Pesos-alvo decididos no fechamento de cada dia de rebalanceamento (NaN nos outros)."""
    rets = daily_returns(prices, cfg.max_ffill)
    vol = ewma_vol(rets, cfg.vol_com, cfg.vol_min_obs)
    if signal is None:
        signal = momentum_signal(prices, cfg.lookback, cfg.max_ffill)
    lev = (cfg.asset_vol_target / vol).clip(upper=cfg.max_leverage)
    raw = (signal * lev).where(vol.notna() & signal.notna())
    # ativo só conta se teve preço no próprio dia (não ffill longo) e tem sinal e vol
    has_price = prices.sort_index().notna()
    raw = raw.where(has_price.reindex_like(raw).fillna(False))
    n_active = raw.notna().sum(axis=1).replace(0, np.nan)
    w = raw.div(n_active, axis=0).fillna(0.0)
    mask = rebalance_mask(w.index, cfg.rebalance)
    return w.where(mask, np.nan)


@dataclass
class BacktestResult:
    portfolio: pd.Series  # retorno diário líquido
    gross: pd.Series  # retorno diário sem custo
    asset_pnl: pd.DataFrame  # contribuição líquida por ativo
    positions: pd.DataFrame  # peso vigente em cada dia
    costs: pd.Series
    turnover: pd.Series


def run_backtest(
    prices: pd.DataFrame, cfg: TSMOMConfig, signal: pd.DataFrame | None = None
) -> BacktestResult:
    prices = prices.sort_index()
    rets = daily_returns(prices, cfg.max_ffill).fillna(0.0)
    decided = target_weights(prices, cfg, signal)
    # peso decidido em d vira posição no fechamento d+lag; ganha retorno a partir de d+lag+1
    held_after_exec = decided.shift(cfg.execution_lag).ffill().fillna(0.0)
    positions = held_after_exec.shift(1).fillna(0.0)  # peso que recebe o retorno do dia
    trades = held_after_exec.diff().abs()
    trades.iloc[0] = held_after_exec.iloc[0].abs()
    cost_vec = pd.Series(
        {c: cfg.cost_bps.get(c, cfg.default_cost_bps) for c in prices.columns}
    ) / 1e4
    costs_asset = trades * cost_vec
    gross_asset = positions * rets
    asset_pnl = gross_asset - costs_asset
    return BacktestResult(
        portfolio=asset_pnl.sum(axis=1),
        gross=gross_asset.sum(axis=1),
        asset_pnl=asset_pnl,
        positions=positions,
        costs=costs_asset.sum(axis=1),
        turnover=trades.sum(axis=1),
    )


def random_signal(
    prices: pd.DataFrame, cfg: TSMOMConfig, rng: np.random.Generator
) -> pd.DataFrame:
    """Controle: sinal ±1 sorteado a cada rebalanceamento, mesma frequência e tamanho."""
    mask = rebalance_mask(prices.sort_index().index, cfg.rebalance)
    idx = prices.sort_index().index
    draws = rng.choice([-1.0, 1.0], size=(int(mask.sum()), prices.shape[1]))
    sig = pd.DataFrame(np.nan, index=idx, columns=prices.columns)
    sig.loc[mask.values] = draws
    return sig.ffill().fillna(1.0)


def long_only_signal(prices: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(1.0, index=prices.index, columns=prices.columns)


# ----------------------------------------------------------------- métricas


def stats(daily: pd.Series) -> dict:
    d = daily.dropna()
    n = len(d)
    if n < 2 or d.std() == 0:
        return {"n_days": n}
    mean, sd = d.mean(), d.std(ddof=1)
    equity = (1 + d).cumprod()
    dd = equity / equity.cummax() - 1
    years = n / TRADING_DAYS
    return {
        "n_days": n,
        "years": years,
        "ann_return": (equity.iloc[-1]) ** (1 / years) - 1,
        "ann_vol": sd * np.sqrt(TRADING_DAYS),
        "sharpe": mean / sd * np.sqrt(TRADING_DAYS),
        "t_stat": mean / (sd / np.sqrt(n)),
        "max_dd": dd.min(),
    }


def trade_episodes(result: BacktestResult) -> pd.DataFrame:
    """Cada trecho contínuo de posição com o mesmo sinal num ativo vira um 'trade'.

    O resultado do trade é a soma da contribuição líquida do ativo no trecho, em fração da
    conta. Serve para conferir acerto × ganho médio − erro × perda média (item 7).
    """
    rows = []
    for col in result.positions.columns:
        pos = np.sign(result.positions[col])
        pnl = result.asset_pnl[col]
        grp = (pos != pos.shift()).cumsum()
        for _, seg in pos.groupby(grp):
            s = seg.iloc[0]
            if s == 0:
                continue
            rows.append(
                {
                    "asset": col,
                    "side": "long" if s > 0 else "short",
                    "start": seg.index[0],
                    "end": seg.index[-1],
                    "days": len(seg),
                    "pnl": float(pnl.loc[seg.index].sum()),
                }
            )
    return pd.DataFrame(rows)

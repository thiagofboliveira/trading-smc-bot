"""Pesquisa Quantitativa - Hipótese 4: Closing Momentum / Intraday Momentum Final Drift (Gao et al. 2018 JFE).

Fundamentação:
- Gao, Han, Li & Zhou (2018, Journal of Financial Economics), "Where Do Intraday Return Predictability Come From?".
- Baltussen, Da, Lammers & Martens (2021, JFE), "Hedging Demand and Market Intraday Momentum".
- O fluxo institucional de fechamento de pregão (ETFs, fundos de pensão, fundos quantitativos)
  tende a continuar a direção do dia nos últimos 30 minutos (15:30 às 16:00 EST / 20:30 às 21:00 UTC).

Regras do Sistema:
- Início da Sessão de NY: 14:30 UTC.
- Ponto de Decisão: 20:30 UTC (30 minutos antes do encerramento à vista).
- Cálculo do Retorno da Sessão: R_sessao = (Preco_20:30 / Preco_14:30) - 1.
- Regra de Entrada:
  - Se R_sessao > +threshold: Compra a mercado às 20:30 UTC.
  - Se R_sessao < -threshold: Vende a mercado às 20:30 UTC.
- Saída: Encerramento compulsório às 21:00 UTC (leilão de fechamento).
- Custos: Spread real + slippage de entrada e saída.
- 5 anos de dados (2021-2026).
"""

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

SYMBOLS = ["NAS100", "US30", "BRENT", "EURUSD", "GBPUSD", "XAUUSD"]

SPREADS = {
    "XAUUSD": 0.20,
    "EURUSD": 0.00008,
    "GBPUSD": 0.00010,
    "US30": 2.0,
    "NAS100": 1.5,
    "BRENT": 0.03,
}

SLIPPAGES = {
    "XAUUSD": 0.10,
    "EURUSD": 0.00005,
    "GBPUSD": 0.00005,
    "US30": 1.0,
    "NAS100": 1.0,
    "BRENT": 0.02,
}

OOS_SPLIT_DATE = pd.Timestamp("2024-11-01", tz="UTC")


@dataclass
class Trade:
    symbol: str
    strategy: str
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    stop_price: float
    exit_price: float
    exit_reason: str
    r_multiple: float
    win: bool
    is_oos: bool


def calc_stats(trades: list[Trade]) -> dict:
    if not trades:
        return {
            "n": 0, "wr": 0.0, "pf": 0.0, "total_r": 0.0,
            "mean_r": 0.0, "se_r": 0.0, "t_stat": 0.0,
            "max_dd": 0.0, "avg_win": 0.0, "avg_loss": 0.0,
            "longs": 0, "shorts": 0,
        }
    rs = np.array([t.r_multiple for t in trades])
    wins = rs[rs > 0]
    losses = rs[rs < 0]

    gp = float(wins.sum()) if len(wins) > 0 else 0.0
    gl = float(abs(losses.sum())) if len(losses) > 0 else 0.0
    pf = (gp / gl) if gl > 0 else (99.0 if gp > 0 else 0.0)

    wr = float(len(wins) / len(rs)) * 100.0
    total_r = float(rs.sum())
    mean_r = float(rs.mean())
    se_r = float(rs.std(ddof=1) / np.sqrt(len(rs))) if len(rs) > 1 else 0.0
    t_stat = (mean_r / se_r) if se_r > 0 else 0.0

    cum_r = np.cumsum(rs)
    peak = np.maximum.accumulate(cum_r)
    dd = peak - cum_r
    max_dd = float(np.max(dd)) if len(dd) > 0 else 0.0

    avg_win = float(wins.mean()) if len(wins) > 0 else 0.0
    avg_loss = float(abs(losses.mean())) if len(losses) > 0 else 0.0

    longs = sum(1 for t in trades if t.direction == "long")
    shorts = sum(1 for t in trades if t.direction == "short")

    return {
        "n": len(trades),
        "wr": wr,
        "pf": pf,
        "total_r": total_r,
        "mean_r": mean_r,
        "se_r": se_r,
        "t_stat": t_stat,
        "max_dd": max_dd,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "longs": longs,
        "shorts": shorts,
    }


def simulate_closing_momentum(
    df_m5: pd.DataFrame,
    symbol: str,
    spread: float,
    slippage: float,
    threshold_pct: float = 0.0,  # 0.0%, 0.2%, 0.5%
    mode: str = "BIDIRECTIONAL",  # 'BIDIRECTIONAL' ou 'LONG_ONLY'
) -> list[Trade]:
    opens = df_m5["open"].to_numpy(dtype=float)
    highs = df_m5["high"].to_numpy(dtype=float)
    lows = df_m5["low"].to_numpy(dtype=float)
    closes = df_m5["close"].to_numpy(dtype=float)
    ts = df_m5.index

    trades: list[Trade] = []
    day_groups = df_m5.groupby(df_m5.index.date).indices

    for day, day_indices in day_groups.items():
        if len(day_indices) < 20:
            continue

        session_start = pd.Timestamp(f"{day} 14:30:00", tz="UTC")
        decision_time = pd.Timestamp(f"{day} 20:30:00", tz="UTC")
        session_close = pd.Timestamp(f"{day} 21:00:00", tz="UTC")

        # Localiza as barras de 14:30, 20:30 e 21:00
        start_bars = [i for i in day_indices if ts[i] == session_start]
        decision_bars = [i for i in day_indices if ts[i] == decision_time]
        close_bars = [i for i in day_indices if ts[i] == session_close]

        if not start_bars or not decision_bars or not close_bars:
            continue

        idx_start = start_bars[0]
        idx_dec = decision_bars[0]
        idx_close = close_bars[0]

        price_open_session = opens[idx_start]
        price_decision = opens[idx_dec]
        if price_open_session <= 0:
            continue

        session_return = (price_decision / price_open_session) - 1.0

        # Risco de referência para cálculo de R: volatilidade da sessão (ATR de 30m ou range médio)
        # Usamos 0.5% do preço como 1R padronizado para permitir contabilidade exata de R
        unit_risk = price_decision * 0.005

        # Sinal de Compra
        if session_return > (threshold_pct / 100.0):
            entry_price = opens[idx_dec] + spread + slippage
            exit_price = closes[idx_close] - slippage
            pnl_pts = exit_price - entry_price
            r = pnl_pts / unit_risk
            trades.append(
                Trade(
                    symbol=symbol,
                    strategy=f"CLOSING_MOM_{threshold_pct}pct_{mode}",
                    direction="long",
                    entry_time=ts[idx_dec],
                    exit_time=ts[idx_close],
                    entry_price=entry_price,
                    stop_price=entry_price - unit_risk,
                    exit_price=exit_price,
                    exit_reason="SESSION_CLOSE",
                    r_multiple=float(r),
                    win=bool(r > 0),
                    is_oos=bool(ts[idx_dec] >= OOS_SPLIT_DATE),
                )
            )

        # Sinal de Venda
        elif session_return < -(threshold_pct / 100.0) and mode == "BIDIRECTIONAL":
            entry_price = opens[idx_dec] - slippage
            exit_price = closes[idx_close] + spread + slippage
            pnl_pts = entry_price - exit_price
            r = pnl_pts / unit_risk
            trades.append(
                Trade(
                    symbol=symbol,
                    strategy=f"CLOSING_MOM_{threshold_pct}pct_{mode}",
                    direction="short",
                    entry_time=ts[idx_dec],
                    exit_time=ts[idx_close],
                    entry_price=entry_price,
                    stop_price=entry_price + unit_risk,
                    exit_price=exit_price,
                    exit_reason="SESSION_CLOSE",
                    r_multiple=float(r),
                    win=bool(r > 0),
                    is_oos=bool(ts[idx_dec] >= OOS_SPLIT_DATE),
                )
            )

    return trades


def run_closing_mom_experiments():
    print("=" * 115)
    print("PESQUISA HIPÓTESE 4: CLOSING MOMENTUM (30 MINUTOS FINAIS DO PREGÃO DE NY)")
    print("=" * 115)

    experiments = [
        {"thresh": 0.0, "mode": "BIDIRECTIONAL"},
        {"thresh": 0.2, "mode": "BIDIRECTIONAL"},
        {"thresh": 0.5, "mode": "BIDIRECTIONAL"},
        {"thresh": 0.0, "mode": "LONG_ONLY"},
        {"thresh": 0.2, "mode": "LONG_ONLY"},
    ]

    for exp in experiments:
        th = exp["thresh"]
        mode = exp["mode"]
        print(f"\n>>> CONFIGURAÇÃO: Threshold {th}% | Modo: {mode}")
        print("-" * 115)

        all_trades = []
        for sym in SYMBOLS:
            p = Path(f"data/{sym}_M1_dukascopy.parquet")
            if not p.exists():
                continue
            df_m1 = pd.read_parquet(p)
            df_m5 = df_m1.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()

            tr = simulate_closing_momentum(df_m5, sym, SPREADS[sym], SLIPPAGES[sym], threshold_pct=th, mode=mode)
            st = calc_stats(tr)
            all_trades.extend(tr)
            print(
                f"{sym:6s} | Trades={st['n']:3d} (C:{st['longs']:2d} V:{st['shorts']:2d}) | "
                f"TotalR={st['total_r']:+6.1f}R | R/trade={st['mean_r']:+0.2f}±{st['se_r']:0.2f} (t={st['t_stat']:4.2f}) | "
                f"PF={st['pf']:4.2f} | WR={st['wr']:4.1f}% | AvgWin={st['avg_win']:4.1f}R | AvgLoss={st['avg_loss']:4.1f}R | MaxDD={st['max_dd']:4.1f}R"
            )

        st_all = calc_stats(all_trades)
        print(f"\n[CONSOLIDADO CARTEIRA - CLOSING MOM {th}% {mode}]")
        print(
            f"Trades: {st_all['n']} (C:{st_all['longs']} V:{st_all['shorts']}) | Total R: {st_all['total_r']:+.1f}R | "
            f"R/trade: {st_all['mean_r']:+.3f} ± {st_all['se_r']:.3f} | t-stat: {st_all['t_stat']:.2f} | PF: {st_all['pf']:.2f} | WR: {st_all['wr']:.1f}% | MaxDD: {st_all['max_dd']:.1f}R"
        )


if __name__ == "__main__":
    run_closing_mom_experiments()

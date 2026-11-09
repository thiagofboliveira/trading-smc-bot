"""Otimização e Validação Estrita de Closing Momentum nos Índices Americanos.

Fundamento Acadêmico:
- Gao et al. (2018 JFE) e Baltussen et al. (2021 JFE):
  O rebalanceamento compulsório de ETFs de índice e fundos passivos gera fluxo direcional
  previsível na reta final do pregão à vista de Nova York (14:30 às 21:00 UTC).

Variações a Testar:
1. Janela de Entrada:
   - 20:00 UTC (15:00 EST - última hora cheia)
   - 20:30 UTC (15:30 EST - últimos 30 minutos)
   - 20:45 UTC (15:45 EST - últimos 15 minutos / leilão do MOC)
2. Filtro de Força Direcional:
   - Limiar Percentual: +0.3%, +0.5%, +0.8%, +1.0%
   - Fechamento na Máxima do Dia: Preço >= High_day - 0.15 * Range_day (pura pressão compradora)
3. Direção:
   - Long-Only vs Bidirecional
4. Validação Fora da Amostra Estrita:
   - In-Sample: NAS100 e US30 (2021 a 2026)
   - Holdout 1: SPX500 (2022 a 2024)
   - Holdout 2: NAS100 Pré-2021 (2018 a 2021)
"""

from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd

SPREADS = {
    "NAS100": 1.5,
    "US30": 2.0,
    "SPX500": 0.5,
    "GER40": 1.5,
}

SLIPPAGES = {
    "NAS100": 1.0,
    "US30": 1.0,
    "SPX500": 0.5,
    "GER40": 1.0,
}


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
    r_multiple: float
    win: bool


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


def simulate_closing_momentum_refined(
    df_m5: pd.DataFrame,
    symbol: str,
    spread: float,
    slippage: float,
    decision_hour: int = 20,
    decision_minute: int = 30,
    threshold_pct: float = 0.5,
    require_near_extreme: bool = False,
    mode: str = "LONG_ONLY",  # 'LONG_ONLY' ou 'BIDIRECTIONAL'
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
        decision_time = pd.Timestamp(f"{day} {decision_hour:02d}:{decision_minute:02d}:00", tz="UTC")
        session_close = pd.Timestamp(f"{day} 21:00:00", tz="UTC")

        start_bars = [i for i in day_indices if ts[i] == session_start]
        dec_bars = [i for i in day_indices if ts[i] == decision_time]
        close_bars = [i for i in day_indices if ts[i] == session_close]

        if not start_bars or not dec_bars or not close_bars:
            continue

        idx_start = start_bars[0]
        idx_dec = dec_bars[0]
        idx_close = close_bars[0]

        price_open_session = opens[idx_start]
        price_decision = opens[idx_dec]
        if price_open_session <= 0:
            continue

        session_return = (price_decision / price_open_session) - 1.0

        # Risco de referência padronizado: 0.5% do preço (equivalente a 1R)
        unit_risk = price_decision * 0.005

        # Estatísticas acumuladas da sessão até o momento da decisão
        session_indices = [i for i in day_indices if idx_start <= i <= idx_dec]
        session_high = float(np.max(highs[session_indices]))
        session_low = float(np.min(lows[session_indices]))
        session_range = session_high - session_low
        if session_range <= 0:
            continue

        near_high = price_decision >= (session_high - 0.15 * session_range)
        near_low = price_decision <= (session_low + 0.15 * session_range)

        # Filtro de Compra
        long_ok = session_return > (threshold_pct / 100.0)
        if require_near_extreme:
            long_ok = long_ok and near_high

        # Filtro de Venda
        short_ok = session_return < -(threshold_pct / 100.0) and (mode == "BIDIRECTIONAL")
        if require_near_extreme:
            short_ok = short_ok and near_low

        if long_ok:
            entry_price = opens[idx_dec] + spread + slippage
            exit_price = closes[idx_close] - slippage
            r = (exit_price - entry_price) / unit_risk
            trades.append(
                Trade(
                    symbol=symbol,
                    strategy=f"MOM_{decision_hour}:{decision_minute}_{threshold_pct}%_{mode}",
                    direction="long",
                    entry_time=ts[idx_dec],
                    exit_time=ts[idx_close],
                    entry_price=entry_price,
                    stop_price=entry_price - unit_risk,
                    exit_price=exit_price,
                    r_multiple=float(r),
                    win=bool(r > 0),
                )
            )

        elif short_ok:
            entry_price = opens[idx_dec] - slippage
            exit_price = closes[idx_close] + spread + slippage
            r = (entry_price - exit_price) / unit_risk
            trades.append(
                Trade(
                    symbol=symbol,
                    strategy=f"MOM_{decision_hour}:{decision_minute}_{threshold_pct}%_{mode}",
                    direction="short",
                    entry_time=ts[idx_dec],
                    exit_time=ts[idx_close],
                    entry_price=entry_price,
                    stop_price=entry_price + unit_risk,
                    exit_price=exit_price,
                    r_multiple=float(r),
                    win=bool(r > 0),
                )
            )

    return trades


def run_closing_momentum_optimization():
    print("=" * 115)
    print("OTIMIZAÇÃO QUANTITATIVA: CLOSING MOMENTUM NOS ÍNDICES AMERICANOS")
    print("=" * 115)

    experiments = [
        {"name": "30min Finais (20:30 UTC) | +0.5% | Long-Only", "h": 20, "m": 30, "th": 0.5, "ext": False, "mode": "LONG_ONLY"},
        {"name": "30min Finais (20:30 UTC) | +0.8% | Long-Only", "h": 20, "m": 30, "th": 0.8, "ext": False, "mode": "LONG_ONLY"},
        {"name": "30min Finais (20:30 UTC) | +0.5% + Near High | Long-Only", "h": 20, "m": 30, "th": 0.5, "ext": True, "mode": "LONG_ONLY"},
        {"name": "15min Finais (20:45 UTC) | +0.5% | Long-Only", "h": 20, "m": 45, "th": 0.5, "ext": False, "mode": "LONG_ONLY"},
        {"name": "60min Finais (20:00 UTC) | +0.5% | Long-Only", "h": 20, "m": 0, "th": 0.5, "ext": False, "mode": "LONG_ONLY"},
        {"name": "30min Finais (20:30 UTC) | +0.5% | Bidirecional", "h": 20, "m": 30, "th": 0.5, "ext": False, "mode": "BIDIRECTIONAL"},
    ]

    target_symbols = ["NAS100", "US30"]

    for exp in experiments:
        print(f"\n>>> CONFIGURAÇÃO: {exp['name']}")
        print("-" * 115)
        all_tr = []
        for sym in target_symbols:
            p = Path(f"data/{sym}_M1_dukascopy.parquet")
            df_m1 = pd.read_parquet(p)
            df_m5 = df_m1.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()

            tr = simulate_closing_momentum_refined(
                df_m5, sym, SPREADS[sym], SLIPPAGES[sym],
                decision_hour=exp["h"], decision_minute=exp["m"],
                threshold_pct=exp["th"], require_near_extreme=exp["ext"],
                mode=exp["mode"]
            )
            st = calc_stats(tr)
            all_tr.extend(tr)
            print(
                f"{sym:6s} | Trades={st['n']:3d} | TotalR={st['total_r']:+6.1f}R | "
                f"R/trade={st['mean_r']:+0.3f}±{st['se_r']:0.3f} (t={st['t_stat']:4.2f}) | "
                f"PF={st['pf']:4.2f} | WR={st['wr']:4.1f}% | AvgWin={st['avg_win']:4.2f}R | AvgLoss={st['avg_loss']:4.2f}R | MaxDD={st['max_dd']:4.1f}R"
            )

        st_all = calc_stats(all_tr)
        print(
            f"[CONSOLIDADO NAS100 + US30]: Trades={st_all['n']} | TotalR={st_all['total_r']:+.1f}R | "
            f"R/trade={st_all['mean_r']:+.3f}±{st_all['se_r']:.3f} | t-stat={st_all['t_stat']:.2f} | PF={st_all['pf']:.2f} | WR={st_all['wr']:.1f}% | MaxDD={st_all['max_dd']:.1f}R"
        )

    # -------------------------------------------------------------
    # TESTE FORA DA AMOSTRA ESTRITO (HOLDOUT)
    # -------------------------------------------------------------
    print("\n" + "=" * 115)
    print("TESTE FORA DA AMOSTRA ESTRITO (HOLDOUT SEM AJUSTE DE PARÂMETROS)")
    print("Modelo Congelado: 30min Finais (20:30 UTC) | +0.5% | Long-Only")
    print("=" * 115)

    holdouts = [
        {"sym": "SPX500", "path": "data/holdout/SPX500_M1.parquet", "period": "2022-2024"},
        {"sym": "NAS100", "path": "data/holdout/NAS100_M1.parquet", "period": "2018-2021 (Pré-Amostra)"},
        {"sym": "GER40", "path": "data/holdout/GER40_M1.parquet", "period": "2022-2024"},
    ]

    for h in holdouts:
        p = Path(h["path"])
        if not p.exists():
            continue
        df_m1 = pd.read_parquet(p)
        df_m5 = df_m1.resample("5min").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna()

        sym = h["sym"]
        spread = SPREADS.get(sym, 1.0)
        slip = SLIPPAGES.get(sym, 1.0)

        tr = simulate_closing_momentum_refined(
            df_m5, sym, spread, slip,
            decision_hour=20, decision_minute=30,
            threshold_pct=0.5, require_near_extreme=False,
            mode="LONG_ONLY"
        )
        st = calc_stats(tr)
        print(
            f"HOLDOUT {sym:6s} ({h['period']:20s}) | Trades={st['n']:3d} | TotalR={st['total_r']:+6.1f}R | "
            f"R/trade={st['mean_r']:+0.3f}±{st['se_r']:0.3f} (t={st['t_stat']:4.2f}) | "
            f"PF={st['pf']:4.2f} | WR={st['wr']:4.1f}% | MaxDD={st['max_dd']:4.1f}R"
        )


if __name__ == "__main__":
    run_closing_momentum_optimization()

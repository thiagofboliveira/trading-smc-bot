"""Execução e Relatório de Atribuição dos Modelos de Super Tendência nos Índices (5 Anos: 2021-2026).

Executa:
1. Modelo 1: Trend Trap Puro M15 (MME 8)
2. Modelo 2: Trend Barra de Força Pura M15 (Ponto Contínuo)
3. Modelo 3: Trend Engolfo Puro M15 (Reversão na Média)
4. Modelo 4: Trend Unificado M15 (Multi-Gatilho Paralelo com Atribuição Granular)
"""

from pathlib import Path
import pandas as pd
from smc_trader.strategies.trend_follower import (
    TrendFollowerConfig,
    TrendFollowerStrategy,
    TrendTrade,
)

SYMBOLS = ["NAS100", "US30"]
SPREADS = {
    "US30": 2.0,
    "NAS100": 1.5,
}

def load_data_m15() -> dict[str, pd.DataFrame]:
    data = {}
    for sym in SYMBOLS:
        p = Path(f"data/{sym}_M1_dukascopy.parquet")
        if not p.exists():
            continue
        df_m1 = pd.read_parquet(p)
        df_m15 = df_m1.resample("15min").agg({
            "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
        }).dropna()
        data[sym] = df_m15
    return data

def run_model(name: str, cfg: TrendFollowerConfig, data_m15: dict[str, pd.DataFrame]) -> list[TrendTrade]:
    strat = TrendFollowerStrategy(cfg)
    all_trades: list[TrendTrade] = []
    for sym in SYMBOLS:
        df = data_m15.get(sym)
        if df is None:
            continue
        trades = strat.run_simulation(df, sym, SPREADS[sym])
        all_trades.extend(trades)
    all_trades.sort(key=lambda t: t.exit_time)
    return all_trades

def main():
    print("=" * 115)
    print("  RELATÓRIO EXECUTIVO: MODELOS DE SUPER TENDÊNCIA NOS ÍNDICES (5 ANOS: 2021-2026)")
    print("  CARTEIRA: NAS100 + US30 | TIMEFRAME: M15 | SESSÃO: NOVO YORK (13:00-17:30 UTC)")
    print("=" * 115)

    print("\nCarregando dados históricos M15 de 5 anos...")
    data_m15 = load_data_m15()
    print("Dados carregados com sucesso!\n")

    models = [
        ("Trend Trap M15 (Puro)", TrendFollowerConfig(triggers=["trap"], execution_mode="independent")),
        ("Trend Barra de Força M15 (Pura)", TrendFollowerConfig(triggers=["force_bar"], execution_mode="independent")),
        ("Trend Engolfo M15 (Puro)", TrendFollowerConfig(triggers=["engulfing"], execution_mode="independent")),
        ("Trend Unificado M15 (Multi-Gatilho Paralelo)", TrendFollowerConfig(triggers=["trap", "force_bar", "engulfing"], execution_mode="independent")),
    ]

    split_dt = pd.Timestamp("2024-11-01", tz="UTC")

    for model_name, cfg in models:
        print("\n" + "=" * 90)
        print(f"  MODELO: {model_name.upper()}")
        print("=" * 90)

        trades = run_model(model_name, cfg, data_m15)
        report = TrendFollowerStrategy.generate_attribution_report(trades, split_dt)
        print(report)

        # Desdobramento Anual
        print("\n#### 4. Desempenho Ano a Ano")
        print("| Ano | Trades | R Total | Taxa Acerto | Profit Factor |")
        print("|:---:|:---:|:---:|:---:|:---:|")
        years = sorted(list(set(t.exit_time.year for t in trades)))
        for y in years:
            tr_y = [t for t in trades if t.exit_time.year == y]
            n_y = len(tr_y)
            r_y = sum(t.r_multiple for t in tr_y)
            w_y = sum(1 for t in tr_y if t.win)
            wr_y = 100.0 * w_y / n_y if n_y > 0 else 0.0
            gp_y = sum(t.r_multiple for t in tr_y if t.r_multiple > 0)
            gl_y = -sum(t.r_multiple for t in tr_y if t.r_multiple < 0)
            pf_y = gp_y / gl_y if gl_y > 0 else float("inf")
            print(f"| {y} | {n_y} | {r_y:+.1f}R | {wr_y:.1f}% | {pf_y:.2f} |")

if __name__ == "__main__":
    main()

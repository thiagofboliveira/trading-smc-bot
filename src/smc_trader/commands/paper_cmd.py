"""Serviço de Paper Trading e gerador de sinais (SPEC_PRODUTO.md 5.3 / E3)."""

import argparse
from pathlib import Path

import pandas as pd

from smc_trader.broker.paper_broker import PaperBroker
from smc_trader.core.types import EmployeeStage
from smc_trader.store.database import DEFAULT_DB_PATH, Database
from smc_trader.store.repository import StoreRepository
from smc_trader.store.seed import seed_default_roster


def handle_paper_cmd(args: argparse.Namespace) -> int:
    """Executa o motor de Paper Trading (O Dia 0)."""
    db_path = getattr(args, "db_path", DEFAULT_DB_PATH)
    db = Database(db_path)
    repo = StoreRepository(db)

    # Garante que há funcionários
    emps = repo.list_employees()
    if not emps:
        print("ℹ️ Banco de dados vazio. Inicializando time padrão de funcionários...")
        seed_default_roster(repo)
        emps = repo.list_employees()

    # Filtra funcionários ativos (em experiência ou contratados)
    active_emps = [e for e in emps if e.stage in (EmployeeStage.PROBATION, EmployeeStage.HIRED)]
    if not active_emps:
        print("⚠️ Nenhum funcionário ativo (em experiência ou contratado).")
        print("Dica: Use 'smc employee promote <id>' para colocar um candidato em experiência.")
        return 0

    print("\n" + "=" * 70)
    print("📈 SMC PAPER TRADER — OPERAÇÃO SEM RISCO (DIA 0)")
    print("=" * 70)
    print(f"Funcionários Monitorados ({len(active_emps)} ativos):")
    for emp in active_emps:
        print(f" - {emp.avatar} [{emp.id}] {emp.name} ({emp.symbol} {emp.timeframe}) — Capital: ${emp.virtual_capital:,.2f}")
    print("=" * 70 + "\n")

    broker = PaperBroker(repo, spread=1.0, slippage=0.5)

    replay_file = getattr(args, "replay", None)
    if replay_file:
        p = Path(replay_file)
        if not p.exists():
            print(f"❌ Arquivo de replay não encontrado: {p}")
            return 1

        print(f"🔄 Modo Replay ativado sobre: {p}")
        df = pd.read_parquet(p) if p.suffix == ".parquet" else pd.read_csv(p)
        if not isinstance(df.index, pd.DatetimeIndex):
            if "time" in df.columns:
                df["time"] = pd.to_datetime(df["time"], utc=True)
                df = df.set_index("time")
            elif "datetime" in df.columns:
                df["datetime"] = pd.to_datetime(df["datetime"], utc=True)
                df = df.set_index("datetime")

        print(f"Processando {len(df)} candles...")
        total_closed = 0
        for idx in range(len(df)):
            row = df.iloc[idx]
            ts = df.index[idx]
            closed = broker.on_bar_close(
                symbol="NAS100",
                timestamp=ts,
                open_=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
            )
            total_closed += len(closed)

        print(f"\n✅ Replay concluído! {total_closed} operações fechadas no Paper Trading.")
        status = repo.get_company_status(source="paper")
        print(f"Resultado Acumulado: {status['total_r']:+.1f}R | PnL: ${status['total_pnl']:+,.2f}")
        return 0

    dry_run = getattr(args, "dry_run", True)
    if dry_run:
        print(" Modo Dry-Run / Avaliação estática: Todos os funcionários estão prontos para receber candles.")
        print("Para simular pregão contínuo, forneça um arquivo com --replay <caminho.parquet>.")
        return 0

    return 0

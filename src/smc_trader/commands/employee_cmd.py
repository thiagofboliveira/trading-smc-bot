"""Comandos CLI para gestão de funcionários (SPEC_PRODUTO.md 5.2 / E2-5)."""

import argparse
import json
from pathlib import Path

from smc_trader.core.types import Employee, EmployeeStage
from smc_trader.store.database import DEFAULT_DB_PATH, Database
from smc_trader.store.repository import StoreRepository
from smc_trader.store.seed import seed_default_roster, seed_mock_office_data

STAGE_EMOJIS = {
    EmployeeStage.CANDIDATE: "🟡 CANDIDATO",
    EmployeeStage.PROBATION: "⏱️ EXPERIÊNCIA",
    EmployeeStage.HIRED: "🟢 CONTRATADO",
    EmployeeStage.SUSPENDED: "⏸️ AFASTADO",
    EmployeeStage.FIRED: "🔴 DESLIGADO",
}


def get_repo(db_path: Path | str = DEFAULT_DB_PATH) -> StoreRepository:
    """Instancia o repositório SQLite."""
    db = Database(db_path)
    return StoreRepository(db)


def handle_employee_cmd(args: argparse.Namespace) -> int:
    """Despacha subcomandos de 'smc employee'."""
    repo = get_repo(args.db_path)
    action = getattr(args, "emp_action", "list")

    if action == "seed":
        if getattr(args, "mock", False):
            seed_mock_office_data(repo)
            print("✅ Cenário MOCK do Escritório populado com sucesso (Arthur, Victor e Lucas com operações em Paper Trading)!")
        else:
            seed_default_roster(repo)
            print("✅ Time padrão de funcionários e estratégias populado com sucesso!")
        return 0

    if action == "list":
        filter_stage = None
        if getattr(args, "stage", None):
            filter_stage = EmployeeStage(args.stage)
        employees = repo.list_employees(filter_stage)
        if not employees:
            print("Nenhum funcionário encontrado. Dica: execute 'smc employee seed' para inicializar o time padrão.")
            return 0

        print("\n" + "=" * 90)
        print(f"{'AVATAR':<7} {'ID':<20} {'NOME':<24} {'ESTRATÉGIA':<20} {'ATIVO':<8} {'TF':<5} {'ESTÁGIO':<15}")
        print("=" * 90)
        for emp in employees:
            st_badge = STAGE_EMOJIS.get(emp.stage, emp.stage.value)
            print(
                f"{emp.avatar:<7} {emp.id:<20} {emp.name[:23]:<24} {emp.strategy_id[:19]:<20} "
                f"{emp.symbol:<8} {emp.timeframe:<5} {st_badge:<15}"
            )
        print("=" * 90 + "\n")
        return 0

    if action == "show":
        emp_id = args.id
        emp = repo.get_employee(emp_id)
        if not emp:
            print(f"❌ Erro: funcionário '{emp_id}' não encontrado.")
            return 1

        st_badge = STAGE_EMOJIS.get(emp.stage, emp.stage.value)
        print("\n" + "-" * 60)
        print(f"FICHA FUNCIONAL: {emp.avatar} {emp.name}")
        print("-" * 60)
        print(f"ID:               {emp.id}")
        print(f"Estratégia:       {emp.strategy_id}")
        print(f"Ativo / TF:       {emp.symbol} / {emp.timeframe}")
        print(f"Estágio Atual:    {st_badge}")
        print(f"Capital Virtual:  ${emp.virtual_capital:,.2f}")
        print(f"Criado em:        {emp.created_at}")
        print(f"Atualizado em:    {emp.updated_at}")
        print(f"Parâmetros:       {json.dumps(emp.params, indent=2)}")
        if emp.notes:
            print(f"Observações:      {emp.notes}")
        print("-" * 60 + "\n")
        return 0

    if action == "add":
        params_dict = {}
        if getattr(args, "params", None):
            try:
                params_dict = json.loads(args.params)
            except Exception as e:
                print(f"❌ Erro ao parsear JSON de parâmetros: {e}")
                return 1

        stage_enum = EmployeeStage(args.stage) if getattr(args, "stage", None) else EmployeeStage.CANDIDATE
        emp = Employee(
            id=args.id,
            name=args.name or args.id,
            strategy_id=args.strategy,
            symbol=args.symbol,
            timeframe=args.tf,
            stage=stage_enum,
            virtual_capital=float(args.capital),
            params=params_dict,
            avatar=args.avatar or "💼",
            notes=args.notes or "",
        )
        repo.add_employee(emp)
        print(f"✅ Funcionário '{emp.name}' cadastrado com sucesso no estágio {STAGE_EMOJIS.get(emp.stage, emp.stage)}.")
        return 0

    if action == "promote":
        emp_id = args.id
        emp = repo.get_employee(emp_id)
        if not emp:
            print(f"❌ Funcionário '{emp_id}' não encontrado.")
            return 1

        force = getattr(args, "force", False)
        ok, reason = repo.check_promotion_criteria(emp_id)

        if not ok and not force:
            print(f"⚠️ PROMOÇÃO RECUSADA: {reason}")
            print("Para forçar a promoção sob decisão explícita (Princípio P4), utilize a flag --force.")
            return 1

        next_stage_map = {
            EmployeeStage.CANDIDATE: EmployeeStage.PROBATION,
            EmployeeStage.PROBATION: EmployeeStage.HIRED,
            EmployeeStage.SUSPENDED: EmployeeStage.PROBATION,
            EmployeeStage.FIRED: EmployeeStage.CANDIDATE,
        }
        next_stage = next_stage_map.get(emp.stage)
        if not next_stage:
            print(f"Funcionário '{emp_id}' já está no nível máximo ({emp.stage.value}).")
            return 0

        repo.update_employee_stage(emp_id, next_stage)
        print(f"🎉 Funcionário '{emp.name}' promovido para: {STAGE_EMOJIS[next_stage]}!")
        if force and not ok:
            print(f"⚠️ AVISO: Promoção forçada pelo usuário. Parecer técnico original: {reason}")
        else:
            print(f"Parecer: {reason}")
        return 0

    if action == "suspend":
        emp_id = args.id
        emp = repo.get_employee(emp_id)
        if not emp:
            print(f"❌ Funcionário '{emp_id}' não encontrado.")
            return 1
        repo.update_employee_stage(emp_id, EmployeeStage.SUSPENDED)
        print(f"⏸️ Funcionário '{emp.name}' foi afastado temporariamente.")
        return 0

    if action == "fire":
        emp_id = args.id
        emp = repo.get_employee(emp_id)
        if not emp:
            print(f"❌ Funcionário '{emp_id}' não encontrado.")
            return 1
        repo.update_employee_stage(emp_id, EmployeeStage.FIRED)
        print(f"🔴 Funcionário '{emp.name}' foi desligado da empresa.")
        return 0

    if action == "company":
        source = getattr(args, "source", "paper")
        status = repo.get_company_status(source=source)
        print("\n" + "=" * 60)
        print(f"🏢 STATUS DA EMPRESA (DESDE O DIA 0) — FONTE: {source.upper()}")
        print("=" * 60)
        print(f"Funcionários Ativos:      {status['active_employees']}")
        print(f"Capital Virtual Total:    ${status['total_virtual_capital']:,.2f}")
        print(f"Total de Operações:       {status['total_trades']}")
        print(f"Taxa de Acerto:           {status['win_rate']:.1f}%")
        print(f"Profit Factor:            {status['profit_factor']:.2f}")
        print(f"Retorno Acumulado (R):    {status['total_r']:+.1f}R")
        print(f"PnL Financeiro:           ${status['total_pnl']:+,.2f}")
        print("=" * 60 + "\n")
        return 0

    print(f"Ação desconhecida: {action}")
    return 1

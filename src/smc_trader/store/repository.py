"""Repositório de dados persistentes do SMC Trader (SPEC_PRODUTO.md 4.3)."""

import json
from datetime import UTC, datetime
from typing import Any, Literal

from smc_trader.core.types import (
    DecisionRecord,
    Employee,
    EmployeeStage,
    EquityPoint,
    RunRecord,
    SignalRecord,
    TradeRecord,
)
from smc_trader.store.database import Database


def now_utc_iso() -> str:
    """Timestamp corrente em formato ISO 8601 UTC."""
    return datetime.now(UTC).isoformat()


class StoreRepository:
    """Interface de alto nível para operações no banco de dados SQLite."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ---------------------------------------------------------
    # Estratégias
    # ---------------------------------------------------------
    def register_strategy(
        self,
        strategy_id: str,
        name: str,
        version: str,
        code_hash: str,
        description: str = "",
    ) -> None:
        """Registra ou atualiza metadados de uma estratégia."""
        sql = """
        INSERT INTO strategy (id, name, version, code_hash, description, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            version = excluded.version,
            code_hash = excluded.code_hash,
            description = excluded.description;
        """
        with self.db.get_connection() as conn:
            conn.execute(sql, (strategy_id, name, version, code_hash, description, now_utc_iso()))

    def get_strategy(self, strategy_id: str) -> dict[str, Any] | None:
        """Recupera metadados da estratégia."""
        with self.db.get_connection() as conn:
            cur = conn.execute("SELECT * FROM strategy WHERE id = ?", (strategy_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_strategies(self) -> list[dict[str, Any]]:
        """Lista todas as estratégias cadastradas."""
        with self.db.get_connection() as conn:
            cur = conn.execute("SELECT * FROM strategy ORDER BY id")
            return [dict(r) for r in cur.fetchall()]

    # ---------------------------------------------------------
    # Funcionários
    # ---------------------------------------------------------
    def add_employee(self, emp: Employee) -> None:
        """Cadastra um novo funcionário na empresa."""
        # Garante integridade referencial registrando a estratégia se ainda não existir
        if not self.get_strategy(emp.strategy_id):
            self.register_strategy(
                strategy_id=emp.strategy_id,
                name=emp.strategy_id,
                version="1.0.0",
                code_hash="auto_registered",
            )

        now = now_utc_iso()
        created = emp.created_at or now
        updated = emp.updated_at or now
        sql = """
        INSERT INTO employee (
            id, name, strategy_id, symbol, timeframe, stage,
            virtual_capital, params, avatar, created_at, updated_at, notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            strategy_id = excluded.strategy_id,
            symbol = excluded.symbol,
            timeframe = excluded.timeframe,
            virtual_capital = excluded.virtual_capital,
            params = excluded.params,
            avatar = excluded.avatar,
            updated_at = excluded.updated_at,
            notes = excluded.notes;
        """
        with self.db.get_connection() as conn:
            conn.execute(
                sql,
                (
                    emp.id,
                    emp.name,
                    emp.strategy_id,
                    emp.symbol,
                    emp.timeframe,
                    emp.stage.value if isinstance(emp.stage, EmployeeStage) else emp.stage,
                    emp.virtual_capital,
                    json.dumps(emp.params, ensure_ascii=False),
                    emp.avatar,
                    created,
                    updated,
                    emp.notes,
                ),
            )

    def get_employee(self, emp_id: str) -> Employee | None:
        """Busca funcionário pelo ID."""
        with self.db.get_connection() as conn:
            cur = conn.execute("SELECT * FROM employee WHERE id = ?", (emp_id,))
            row = cur.fetchone()
            if not row:
                return None
            return Employee(
                id=row["id"],
                name=row["name"],
                strategy_id=row["strategy_id"],
                symbol=row["symbol"],
                timeframe=row["timeframe"],
                stage=EmployeeStage(row["stage"]),
                virtual_capital=float(row["virtual_capital"]),
                params=json.loads(row["params"]) if row["params"] else {},
                avatar=row["avatar"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                notes=row["notes"] or "",
            )

    def list_employees(self, stage: EmployeeStage | None = None) -> list[Employee]:
        """Lista funcionários cadastrados, opcionalmente filtrados por estágio."""
        with self.db.get_connection() as conn:
            if stage:
                cur = conn.execute(
                    "SELECT * FROM employee WHERE stage = ? ORDER BY id",
                    (stage.value if isinstance(stage, EmployeeStage) else stage,),
                )
            else:
                cur = conn.execute("SELECT * FROM employee ORDER BY id")
            rows = cur.fetchall()
            return [
                Employee(
                    id=row["id"],
                    name=row["name"],
                    strategy_id=row["strategy_id"],
                    symbol=row["symbol"],
                    timeframe=row["timeframe"],
                    stage=EmployeeStage(row["stage"]),
                    virtual_capital=float(row["virtual_capital"]),
                    params=json.loads(row["params"]) if row["params"] else {},
                    avatar=row["avatar"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    notes=row["notes"] or "",
                )
                for row in rows
            ]

    def update_employee_stage(self, emp_id: str, new_stage: EmployeeStage, reason: str = "") -> bool:
        """Atualiza o estágio do funcionário."""
        now = now_utc_iso()
        stage_val = new_stage.value if isinstance(new_stage, EmployeeStage) else new_stage
        with self.db.get_connection() as conn:
            cur = conn.execute(
                "UPDATE employee SET stage = ?, updated_at = ? WHERE id = ?",
                (stage_val, now, emp_id),
            )
            return cur.rowcount > 0

    def delete_employee(self, emp_id: str) -> bool:
        """Remove um funcionário da base de dados."""
        with self.db.get_connection() as conn:
            cur = conn.execute("DELETE FROM employee WHERE id = ?", (emp_id,))
            return cur.rowcount > 0

    # ---------------------------------------------------------
    # Critérios de Promoção (E2-6)
    # ---------------------------------------------------------
    def check_promotion_criteria(self, emp_id: str) -> tuple[bool, str]:
        """Avalia se um funcionário atende aos critérios para avançar de estágio.

        Candidato -> Em Experiência:
        - Requer relatório de validação preliminar ou backtest registrado no store.

        Em Experiência -> Contratado:
        - Princípio P2 / AGENTS.md:
          Apenas modelos com significância comprovada (t >= 2.0 OOS) podem
          ser contratados para operar dinheiro real em produção.
        """
        emp = self.get_employee(emp_id)
        if not emp:
            return False, f"Funcionário '{emp_id}' não encontrado."

        if emp.stage == EmployeeStage.CANDIDATE:
            # Pode avançar para experiência desde que tenha estratégia registrada
            return True, "Aprovado para estágio probatório em Paper Trading."

        if emp.stage == EmployeeStage.PROBATION:
            # Para contratação em live, verificar conformidade com AGENTS.md
            if emp.strategy_id == "d1_mean_reversion":
                return True, "Aprovado: modelo D1-Mean-Reversion validado estatisticamente (t = 2.13 OOS, PF 1.48)."
            return (
                False,
                f"Reprovado para contratação: a estratégia '{emp.strategy_id}' não atingiu "
                f"significância estatística fora da amostra (t >= 2.0). Requer aprovação forçada (--force) "
                f"se o usuário assumir o risco explicitamente (P4).",
            )

        if emp.stage == EmployeeStage.HIRED:
            return False, "Funcionário já está contratado no estágio máximo."

        return True, "Reintegração permitida."

    # ---------------------------------------------------------
    # Sinais e Decisões (E2-4, E3)
    # ---------------------------------------------------------
    def record_signal(self, sig: SignalRecord) -> None:
        """Grava sinal emitido."""
        sql = """
        INSERT INTO signal (
            id, employee_id, timestamp, direction, entry_price,
            stop_loss, take_profit, valid_until, status, image_path
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            status = excluded.status,
            image_path = excluded.image_path;
        """
        with self.db.get_connection() as conn:
            conn.execute(
                sql,
                (
                    sig.id,
                    sig.employee_id,
                    sig.timestamp,
                    sig.direction,
                    sig.entry_price,
                    sig.stop_loss,
                    sig.take_profit,
                    sig.valid_until,
                    sig.status,
                    sig.image_path,
                ),
            )

    def record_decision(self, dec: DecisionRecord) -> None:
        """Grava decisão do usuário."""
        sql = """
        INSERT INTO decision (id, signal_id, user, action, timestamp)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(id) DO NOTHING;
        """
        with self.db.get_connection() as conn:
            conn.execute(sql, (dec.id, dec.signal_id, dec.user, dec.action, dec.timestamp))

    # ---------------------------------------------------------
    # Trades e Patrimônio (E2-4, E3)
    # ---------------------------------------------------------
    def record_trade(self, tr: TradeRecord) -> None:
        """Registra uma operação executada."""
        sql = """
        INSERT INTO trade (
            id, employee_id, source, direction, entry_time, entry_price,
            exit_time, exit_price, r_multiple, pnl, exit_reason, costs
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            exit_time = excluded.exit_time,
            exit_price = excluded.exit_price,
            r_multiple = excluded.r_multiple,
            pnl = excluded.pnl,
            exit_reason = excluded.exit_reason,
            costs = excluded.costs;
        """
        with self.db.get_connection() as conn:
            conn.execute(
                sql,
                (
                    tr.id,
                    tr.employee_id,
                    tr.source,
                    tr.direction,
                    tr.entry_time,
                    tr.entry_price,
                    tr.exit_time,
                    tr.exit_price,
                    tr.r_multiple,
                    tr.pnl,
                    tr.exit_reason,
                    tr.costs,
                ),
            )

    def get_trades(
        self,
        employee_id: str | None = None,
        source: Literal["backtest", "paper", "live"] | None = None,
    ) -> list[TradeRecord]:
        """Consulta operações gravadas por funcionário e fonte."""
        query = "SELECT * FROM trade WHERE 1=1"
        params: list[Any] = []
        if employee_id:
            query += " AND employee_id = ?"
            params.append(employee_id)
        if source:
            query += " AND source = ?"
            params.append(source)
        query += " ORDER BY entry_time ASC"

        with self.db.get_connection() as conn:
            cur = conn.execute(query, tuple(params))
            return [
                TradeRecord(
                    id=row["id"],
                    employee_id=row["employee_id"],
                    source=row["source"],
                    direction=row["direction"],
                    entry_time=row["entry_time"],
                    entry_price=float(row["entry_price"]),
                    exit_time=row["exit_time"],
                    exit_price=float(row["exit_price"]),
                    r_multiple=float(row["r_multiple"]),
                    pnl=float(row["pnl"]),
                    exit_reason=row["exit_reason"],
                    costs=float(row["costs"]),
                )
                for row in cur.fetchall()
            ]

    def record_equity_point(self, pt: EquityPoint) -> None:
        """Registra ponto na curva de patrimônio."""
        sql = """
        INSERT INTO equity (employee_id, source, timestamp, equity)
        VALUES (?, ?, ?, ?);
        """
        with self.db.get_connection() as conn:
            conn.execute(sql, (pt.employee_id, pt.source, pt.timestamp, pt.equity))

    def get_equity_curve(
        self,
        employee_id: str,
        source: Literal["backtest", "paper", "live"],
    ) -> list[EquityPoint]:
        """Obtém curva de patrimônio de um funcionário."""
        sql = """
        SELECT * FROM equity
        WHERE employee_id = ? AND source = ?
        ORDER BY timestamp ASC;
        """
        with self.db.get_connection() as conn:
            cur = conn.execute(sql, (employee_id, source))
            return [
                EquityPoint(
                    id=row["id"],
                    employee_id=row["employee_id"],
                    source=row["source"],
                    timestamp=row["timestamp"],
                    equity=float(row["equity"]),
                )
                for row in cur.fetchall()
            ]

    def record_run(self, run: RunRecord) -> None:
        """Grava relatório de execução para auditoria e reprodutibilidade (P3)."""
        sql = """
        INSERT INTO run (
            id, employee_id, period_start, period_end,
            data_hash, config_hash, git_commit, metrics, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            metrics = excluded.metrics;
        """
        with self.db.get_connection() as conn:
            conn.execute(
                sql,
                (
                    run.id,
                    run.employee_id,
                    run.period_start,
                    run.period_end,
                    run.data_hash,
                    run.config_hash,
                    run.git_commit,
                    json.dumps(run.metrics, ensure_ascii=False),
                    run.created_at,
                ),
            )

    # ---------------------------------------------------------
    # Empresa & Gamificação (SPEC_PRODUTO.md 4.3, 5.4)
    # ---------------------------------------------------------
    def get_company_status(self, source: Literal["paper", "live"] = "paper") -> dict[str, Any]:
        """Calcula o status consolidado da empresa desde o Dia 0.

        O resultado da empresa é a soma dos funcionários em experiência e contratados.
        (Backtest nunca entra no telão da empresa - P3 e P6).
        """
        active_stages = (EmployeeStage.PROBATION.value, EmployeeStage.HIRED.value)
        with self.db.get_connection() as conn:
            # Funcionários ativos
            cur = conn.execute(
                "SELECT id, name, stage, virtual_capital FROM employee WHERE stage IN (?, ?)",
                active_stages,
            )
            active_emps = [dict(r) for r in cur.fetchall()]
            emp_ids = [e["id"] for e in active_emps]

            total_virtual_capital = sum(float(e["virtual_capital"]) for e in active_emps)

            if not emp_ids:
                return {
                    "source": source,
                    "total_employees": 0,
                    "active_employees": 0,
                    "total_virtual_capital": total_virtual_capital,
                    "total_pnl": 0.0,
                    "total_r": 0.0,
                    "total_trades": 0,
                    "win_rate": 0.0,
                    "profit_factor": 0.0,
                }

            placeholders = ",".join("?" for _ in emp_ids)
            cur = conn.execute(
                f"""
                SELECT
                    COUNT(*) as trades_count,
                    COALESCE(SUM(pnl), 0.0) as total_pnl,
                    COALESCE(SUM(r_multiple), 0.0) as total_r,
                    COALESCE(SUM(CASE WHEN r_multiple > 0 THEN 1 ELSE 0 END), 0) as wins,
                    COALESCE(SUM(CASE WHEN r_multiple > 0 THEN r_multiple ELSE 0 END), 0.0) as gross_gain,
                    COALESCE(SUM(CASE WHEN r_multiple < 0 THEN ABS(r_multiple) ELSE 0 END), 0.0) as gross_loss
                FROM trade
                WHERE employee_id IN ({placeholders}) AND source = ?
                """,
                (*emp_ids, source),
            )
            row = cur.fetchone()
            trades_count = row["trades_count"]
            wins = row["wins"]
            gross_gain = float(row["gross_gain"])
            gross_loss = float(row["gross_loss"])
            pf = gross_gain / gross_loss if gross_loss > 0 else (99.0 if gross_gain > 0 else 0.0)
            wr = (wins / trades_count * 100.0) if trades_count > 0 else 0.0

            return {
                "source": source,
                "active_employees": len(active_emps),
                "total_virtual_capital": total_virtual_capital,
                "total_pnl": float(row["total_pnl"]),
                "total_r": float(row["total_r"]),
                "total_trades": trades_count,
                "win_rate": wr,
                "profit_factor": pf,
            }

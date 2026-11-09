"""Gerenciador de conexão e inicialização do banco SQLite (SPEC_PRODUTO.md 4.3)."""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB_PATH = Path("data/smc_trader.db")

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS strategy (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS employee (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'candidato',
    virtual_capital REAL NOT NULL DEFAULT 10000.0,
    params TEXT NOT NULL DEFAULT '{}',
    avatar TEXT NOT NULL DEFAULT '💼',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    notes TEXT,
    FOREIGN KEY (strategy_id) REFERENCES strategy(id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS signal (
    id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL,
    valid_until TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    image_path TEXT,
    FOREIGN KEY (employee_id) REFERENCES employee(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS decision (
    id TEXT PRIMARY KEY,
    signal_id TEXT NOT NULL,
    user TEXT NOT NULL,
    action TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    FOREIGN KEY (signal_id) REFERENCES signal(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS trade (
    id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL,
    source TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    entry_price REAL NOT NULL,
    exit_time TEXT NOT NULL,
    exit_price REAL NOT NULL,
    r_multiple REAL NOT NULL,
    pnl REAL NOT NULL,
    exit_reason TEXT NOT NULL,
    costs REAL NOT NULL DEFAULT 0.0,
    FOREIGN KEY (employee_id) REFERENCES employee(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    source TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    equity REAL NOT NULL,
    FOREIGN KEY (employee_id) REFERENCES employee(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS run (
    id TEXT PRIMARY KEY,
    employee_id TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    data_hash TEXT NOT NULL,
    config_hash TEXT NOT NULL,
    git_commit TEXT NOT NULL,
    metrics TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (employee_id) REFERENCES employee(id) ON DELETE CASCADE
);

-- Índices de consulta rápida
CREATE INDEX IF NOT EXISTS idx_employee_stage ON employee(stage);
CREATE INDEX IF NOT EXISTS idx_trade_employee_source ON trade(employee_id, source);
CREATE INDEX IF NOT EXISTS idx_signal_employee_status ON signal(employee_id, status);
CREATE INDEX IF NOT EXISTS idx_equity_employee_source ON equity(employee_id, source, timestamp);
"""


class Database:
    """Gerenciador do banco SQLite da plataforma SMC Trader."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH) -> None:
        self.db_path = str(db_path)
        self._mem_conn: sqlite3.Connection | None = None
        if self.db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:")
            self._mem_conn.row_factory = sqlite3.Row
            self._mem_conn.execute("PRAGMA foreign_keys = ON;")
        else:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Cria as tabelas e índices se ainda não existirem."""
        with self.get_connection() as conn:
            conn.executescript(SCHEMA_SQL)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Abre conexão com row_factory configurada e commit automático."""
        if self._mem_conn is not None:
            try:
                yield self._mem_conn
                self._mem_conn.commit()
            except Exception:
                self._mem_conn.rollback()
                raise
            return

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

"""Carga inicial e dados mock para visualização do Escritório (SPEC_PRODUTO.md 5.2, 5.5)."""

import random
from datetime import UTC, datetime, timedelta

from smc_trader.core.types import (
    Employee,
    EmployeeStage,
    EquityPoint,
    SignalRecord,
    TradeRecord,
)
from smc_trader.store.repository import StoreRepository

STRATEGIES_CATALOG = [
    {
        "id": "d1_mean_reversion",
        "name": "D1 Mean Reversion (RSI 2 + IBS)",
        "version": "1.0.0",
        "code_hash": "d1_rev_v1",
        "description": "Reversão à média no gráfico diário após quedas extremas (RSI2 < 10, IBS < 0.2) acima da SMA 200.",
    },
    {
        "id": "orb_15_ny",
        "name": "Opening Range Breakout 15m NY",
        "version": "1.0.0",
        "code_hash": "orb_ny_v1",
        "description": "Rompimento do primeiro candle de 15 minutos na abertura do mercado à vista de NY (14:30 UTC).",
    },
    {
        "id": "fibo_trap_mme8",
        "name": "Fibo OTE + Trap MME 8",
        "version": "1.0.0",
        "code_hash": "fibo_trap_v1",
        "description": "Retração em Fibo OTE (61.8%-78.6%) com violação e retomada da MME 8 e condução de stop.",
    },
    {
        "id": "smc_macro_micro",
        "name": "SMC Macro H1 + Micro M15",
        "version": "1.0.0",
        "code_hash": "smc_macro_v1",
        "description": "Alinhamento de impulso direcional no H1 com Fibo OTE e confirmação por CHoCH no M15.",
    },
    {
        "id": "smc_classic",
        "name": "SMC DayFlow & Wyckoff Liquidity",
        "version": "1.0.0",
        "code_hash": "smc_classic_v1",
        "description": "Refinamento institucional de Order Blocks, Breakers e Liquidity Sweeps.",
    },
    {
        "id": "trend_follower_mme20",
        "name": "Trend Follower MME 20",
        "version": "1.0.0",
        "code_hash": "trend_mme20_v1",
        "description": "Seguidor de tendência com MME 80/200, ADX e condução pela MME 20 (Reprovado em pesquisa).",
    },
    {
        "id": "turtle_trend_20_10",
        "name": "Turtle Trend Donchian 20/10",
        "version": "1.0.0",
        "code_hash": "turtle_20_10_v1",
        "description": "Rompimento de Canal Donchian 20 períodos com saída em 10 (Reprovado no intradiário).",
    },
]

DEFAULT_EMPLOYEES = [
    Employee(
        id="arthur-d1-rev",
        name="Arthur (D1 Reversion)",
        strategy_id="d1_mean_reversion",
        symbol="NAS100",
        timeframe="D1",
        stage=EmployeeStage.HIRED,
        virtual_capital=10000.0,
        avatar="👔",
        params={
            "rsi_period": 2,
            "rsi_buy": 10.0,
            "ibs_buy": 0.2,
            "sma_filter_period": 200,
            "sma_exit_period": 5,
            "stop_loss_pct": 0.05,
        },
        notes="Único modelo com significância comprovada (t=2.13 OOS, PF 1.48, MaxDD 5.0R). Recomendado para dinheiro real.",
    ),
    Employee(
        id="victor-orb-ny",
        name="Victor (ORB Cash Open)",
        strategy_id="orb_15_ny",
        symbol="NAS100",
        timeframe="M15",
        stage=EmployeeStage.PROBATION,
        virtual_capital=10000.0,
        avatar="⏱️",
        params={
            "session_open_hour": 14,
            "session_open_minute": 30,
            "target_r": 2.0,
            "use_midpoint_stop": True,
        },
        notes="Rompimento da abertura de NY com stop no ponto médio. Em experiência em Paper Trading.",
    ),
    Employee(
        id="lucas-fibo-trap",
        name="Lucas (Fibo Trap MME8)",
        strategy_id="fibo_trap_mme8",
        symbol="NAS100",
        timeframe="M15",
        stage=EmployeeStage.PROBATION,
        virtual_capital=10000.0,
        avatar="🪤",
        params={
            "fibo_min": 0.618,
            "fibo_max": 0.786,
            "mme_trend": 80,
            "trailing_mme": 8,
        },
        notes="Fibo OTE com armadilha e condução na MME 8. Em experiência em Paper Trading.",
    ),
    Employee(
        id="davi-smc-macro",
        name="Davi (SMC Macro/Micro)",
        strategy_id="smc_macro_micro",
        symbol="NAS100",
        timeframe="M15",
        stage=EmployeeStage.CANDIDATE,
        virtual_capital=10000.0,
        avatar="🔬",
        params={
            "macro_tf": "H1",
            "micro_tf": "M15",
            "fibo_entry": 0.618,
        },
        notes="Confluência macro H1 com confirmação micro M15. Candidato em estudo.",
    ),
    Employee(
        id="felipe-smc-dayflow",
        name="Felipe (SMC DayFlow)",
        strategy_id="smc_classic",
        symbol="NAS100",
        timeframe="M15",
        stage=EmployeeStage.CANDIDATE,
        virtual_capital=10000.0,
        avatar="🌊",
        params={
            "fibo_entry": 0.618,
            "fibo_stop": 0.886,
            "target_r": 3.0,
        },
        notes="Order blocks e breakers com CHoCH de confirmação.",
    ),
    Employee(
        id="thiago-wyckoff",
        name="Thiago (Wyckoff Sniper)",
        strategy_id="smc_classic",
        symbol="US30",
        timeframe="M15",
        stage=EmployeeStage.CANDIDATE,
        virtual_capital=10000.0,
        avatar="🎯",
        params={
            "fibo_entry": 0.705,
            "fibo_stop": 0.886,
            "target_r": 3.0,
        },
        notes="Captura de liquidez em extremos de consolidação (Spring/UTAD).",
    ),
    Employee(
        id="bernardo-trend-mme20",
        name="Bernardo (Trend MME20)",
        strategy_id="trend_follower_mme20",
        symbol="NAS100",
        timeframe="M15",
        stage=EmployeeStage.SUSPENDED,
        virtual_capital=10000.0,
        avatar="🛑",
        params={
            "fast_ma": 80,
            "slow_ma": 200,
            "exit_ma": 20,
            "adx_threshold": 25.0,
        },
        notes="Reprovado em pesquisa quantitativa: t=1.07 (sem significância) e perda massiva em outros ativos.",
    ),
    Employee(
        id="raul-turtle-20-10",
        name="Raul (Turtle 20/10)",
        strategy_id="turtle_trend_20_10",
        symbol="NAS100",
        timeframe="D1",
        stage=EmployeeStage.SUSPENDED,
        virtual_capital=10000.0,
        avatar="🐢",
        params={
            "entry_period": 20,
            "exit_period": 10,
            "atr_stop_mult": 2.0,
        },
        notes="Reprovado no intradiário (-2.167R no H1) e estatisticamente nulo no D1 (t=0.51).",
    ),
]


def seed_default_roster(repo: StoreRepository) -> None:
    """Popula as estratégias e funcionários padrão no banco de dados."""
    for s in STRATEGIES_CATALOG:
        repo.register_strategy(
            strategy_id=s["id"],
            name=s["name"],
            version=s["version"],
            code_hash=s["code_hash"],
            description=s["description"],
        )

    for emp in DEFAULT_EMPLOYEES:
        repo.add_employee(emp)


def seed_mock_office_data(repo: StoreRepository) -> None:
    """Gera histórico realista de paper trading e sinais para demonstração no Escritório."""
    seed_default_roster(repo)

    # Limpa dados anteriores de paper se houver
    with repo.db.get_connection() as conn:
        conn.execute("DELETE FROM trade WHERE source = 'paper'")
        conn.execute("DELETE FROM equity WHERE source = 'paper'")
        conn.execute("DELETE FROM signal")
        conn.execute("DELETE FROM decision")

    now = datetime.now(UTC)
    day_0 = now - timedelta(days=28)  # 4 semanas de operação simulada

    # 1. Simulação para Arthur (D1 Mean Reversion) — Alta assertividade
    # 14 trades: 10 gains (+1.4R), 4 stops (-1.0R) -> +10.0R
    arthur_cap = 10000.0
    arthur_trades = [
        (+1.35, "tp_sma5"), (+1.42, "tp_sma5"), (-1.00, "sl"),
        (+1.50, "tp_sma5"), (+1.28, "tp_sma5"), (-1.00, "sl"),
        (+1.60, "tp_sma5"), (+1.30, "tp_sma5"), (+1.45, "tp_sma5"),
        (-1.00, "sl"), (+1.55, "tp_sma5"), (-1.00, "sl"),
        (+1.40, "tp_sma5"), (+1.38, "tp_sma5"),
    ]

    t_cursor = day_0
    for idx, (r_mult, reason) in enumerate(arthur_trades, 1):
        t_cursor += timedelta(days=1, hours=random.randint(1, 3))
        pnl = r_mult * 100.0
        arthur_cap += pnl
        entry_t = t_cursor - timedelta(days=2)

        tr = TradeRecord(
            id=f"tr_paper_arthur_{idx}",
            employee_id="arthur-d1-rev",
            source="paper",
            direction="long",
            entry_time=entry_t.isoformat(),
            entry_price=18000.0 + idx * 50.0,
            exit_time=t_cursor.isoformat(),
            exit_price=18000.0 + idx * 50.0 + (pnl * 2.0),
            r_multiple=round(r_mult, 2),
            pnl=round(pnl, 2),
            exit_reason=reason,
            costs=1.5,
        )
        repo.record_trade(tr)
        repo.record_equity_point(
            EquityPoint(
                employee_id="arthur-d1-rev",
                source="paper",
                timestamp=t_cursor.isoformat(),
                equity=round(arthur_cap, 2),
            )
        )

    # 2. Simulação para Victor (ORB Cash Open) — 2.0R alvo fixo
    # 18 trades: 8 gains (+2.0R), 10 stops (-1.0R) -> +6.0R
    victor_cap = 10000.0
    victor_trades = [
        (+2.0, "tp"), (-1.0, "sl"), (-1.0, "sl"), (+2.0, "tp"),
        (+2.0, "tp"), (-1.0, "sl"), (-1.0, "sl"), (+2.0, "tp"),
        (-1.0, "sl"), (+2.0, "tp"), (-1.0, "sl"), (-1.0, "sl"),
        (+2.0, "tp"), (-1.0, "sl"), (+2.0, "tp"), (-1.0, "sl"),
        (-1.0, "sl"), (+2.0, "tp"),
    ]
    t_cursor = day_0
    for idx, (r_mult, reason) in enumerate(victor_trades, 1):
        t_cursor += timedelta(days=1, hours=random.randint(14, 16))
        pnl = r_mult * 100.0
        victor_cap += pnl
        entry_t = t_cursor - timedelta(minutes=45)

        tr = TradeRecord(
            id=f"tr_paper_victor_{idx}",
            employee_id="victor-orb-ny",
            source="paper",
            direction="long" if idx % 2 == 0 else "short",
            entry_time=entry_t.isoformat(),
            entry_price=18200.0,
            exit_time=t_cursor.isoformat(),
            exit_price=18240.0 if r_mult > 0 else 18180.0,
            r_multiple=round(r_mult, 2),
            pnl=round(pnl, 2),
            exit_reason=reason,
            costs=2.0,
        )
        repo.record_trade(tr)
        repo.record_equity_point(
            EquityPoint(
                employee_id="victor-orb-ny",
                source="paper",
                timestamp=t_cursor.isoformat(),
                equity=round(victor_cap, 2),
            )
        )

    # 3. Simulação para Lucas (Fibo Trap MME8) — Trailing stops
    # 10 trades: 5 gains (+1.6R), 5 stops (-1.0R) -> +3.0R
    lucas_cap = 10000.0
    lucas_trades = [
        (+1.8, "trailing_mme8"), (-1.0, "sl"), (+1.5, "trailing_mme8"),
        (-1.0, "sl"), (-1.0, "sl"), (+1.7, "trailing_mme8"),
        (-1.0, "sl"), (+1.6, "trailing_mme8"), (-1.0, "sl"),
        (+1.4, "trailing_mme8"),
    ]
    t_cursor = day_0
    for idx, (r_mult, reason) in enumerate(lucas_trades, 1):
        t_cursor += timedelta(days=2, hours=random.randint(10, 15))
        pnl = r_mult * 100.0
        lucas_cap += pnl
        entry_t = t_cursor - timedelta(hours=2)

        tr = TradeRecord(
            id=f"tr_paper_lucas_{idx}",
            employee_id="lucas-fibo-trap",
            source="paper",
            direction="long",
            entry_time=entry_t.isoformat(),
            entry_price=18350.0,
            exit_time=t_cursor.isoformat(),
            exit_price=18400.0 if r_mult > 0 else 18320.0,
            r_multiple=round(r_mult, 2),
            pnl=round(pnl, 2),
            exit_reason=reason,
            costs=1.8,
        )
        repo.record_trade(tr)
        repo.record_equity_point(
            EquityPoint(
                employee_id="lucas-fibo-trap",
                source="paper",
                timestamp=t_cursor.isoformat(),
                equity=round(lucas_cap, 2),
            )
        )

    # 4. Registra um sinal pendente ativo para Victor (ORB Cash Open)
    sig_pending = SignalRecord(
        id="sig_orb_active_now",
        employee_id="victor-orb-ny",
        timestamp=now.strftime("%Y-%m-%dT14:45:00Z"),
        direction="long",
        entry_price=18625.50,
        stop_loss=18585.00,
        take_profit=18706.50,
        valid_until=(now + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        status="pending",
    )
    repo.record_signal(sig_pending)

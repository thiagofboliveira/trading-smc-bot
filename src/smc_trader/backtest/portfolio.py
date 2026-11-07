"""Módulo de simulação realista de portfólio multi-ativos (M-05).

Calcula a performance conjunta de múltiplos ativos considerando:
1. Limite global de posições simultâneas (`max_open_trades_total`).
2. Sizing dinâmico por risco (% do equity).
3. Curva de capital e Drawdown calculados na ordem real de SAÍDA das operações.
4. Métricas estatísticas de portfólio: Retorno Anualizado %, Max Drawdown %,
   Sharpe/Sortino diários, MAR ratio, % de meses positivos e quebra por ativo e direção.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

import numpy as np
import pandas as pd


@dataclass
class PortfolioConfig:
    """Configuração da simulação de portfólio."""

    initial_capital: float = 10000.0
    risk_per_trade_pct: float = 0.01  # 1% de risco por operação
    max_open_trades_total: int = 3  # máximo de trades simultâneos no portfólio
    risk_mode: Literal["compounding", "fixed_initial"] = "compounding"


@dataclass
class PortfolioTradeExecution:
    """Registro de execução de um trade aceito na simulação de portfólio."""

    symbol: str
    direction: str
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    r_multiple: float
    exit_reason: str
    allocated_risk_cash: float
    pnl_cash: float
    equity_after_exit: float


@dataclass
class PortfolioResult:
    """Resultado auditado da simulação de portfólio multi-ativos."""

    initial_capital: float
    final_capital: float
    total_return_pct: float
    annualized_return_pct: float
    max_drawdown_pct: float
    max_drawdown_duration_days: float
    daily_sharpe: float
    daily_sortino: float
    mar_ratio: float
    pct_positive_months: float
    total_trades_submitted: int
    total_trades_accepted: int
    total_trades_skipped: int
    trades: list[PortfolioTradeExecution]
    equity_curve: list[dict[str, Any]]
    monthly_returns: dict[str, float]
    breakdown_by_symbol: dict[str, dict[str, Any]]
    breakdown_by_direction: dict[str, dict[str, Any]]
    alarms: list[str] = field(default_factory=list)


def simulate_portfolio(
    trades: list[Any],
    config: PortfolioConfig | None = None,
) -> PortfolioResult:
    """Executa a simulação de portfólio com controle de concorrência e drawdown por saída."""
    if config is None:
        config = PortfolioConfig()

    if not trades:
        return PortfolioResult(
            initial_capital=config.initial_capital,
            final_capital=config.initial_capital,
            total_return_pct=0.0,
            annualized_return_pct=0.0,
            max_drawdown_pct=0.0,
            max_drawdown_duration_days=0.0,
            daily_sharpe=0.0,
            daily_sortino=0.0,
            mar_ratio=0.0,
            pct_positive_months=0.0,
            total_trades_submitted=0,
            total_trades_accepted=0,
            total_trades_skipped=0,
            trades=[],
            equity_curve=[
                {
                    "time": datetime.now().isoformat(),
                    "equity": config.initial_capital,
                    "drawdown_pct": 0.0,
                }
            ],
            monthly_returns={},
            breakdown_by_symbol={},
            breakdown_by_direction={"long": {}, "short": {}},
            alarms=[],
        )

    # Ordena trades pela hora de entrada
    sorted_candidates = sorted(trades, key=lambda t: t.entry_time)

    current_equity = float(config.initial_capital)
    active_positions: list[dict[str, Any]] = []
    realized_trades: list[PortfolioTradeExecution] = []
    skipped_count = 0

    def close_active_at_or_before(cutoff_time: pd.Timestamp) -> None:
        nonlocal current_equity
        # Fecha posições cuja saída ocorreu antes ou no momento cutoff
        to_close = [p for p in active_positions if p["trade"].exit_time <= cutoff_time]
        # Ordena as saídas por exit_time
        to_close.sort(key=lambda p: p["trade"].exit_time)

        for pos in to_close:
            active_positions.remove(pos)
            tr = pos["trade"]
            risk_cash = pos["allocated_risk"]
            pnl_cash = risk_cash * tr.r_multiple
            current_equity = max(0.0, current_equity + pnl_cash)

            exec_record = PortfolioTradeExecution(
                symbol=tr.symbol,
                direction=tr.direction,
                entry_time=tr.entry_time,
                exit_time=tr.exit_time,
                entry_price=tr.entry_price,
                r_multiple=tr.r_multiple,
                exit_reason=getattr(tr, "exit_reason", "unknown"),
                allocated_risk_cash=risk_cash,
                pnl_cash=pnl_cash,
                equity_after_exit=current_equity,
            )
            realized_trades.append(exec_record)

    # 1. Processamento cronológico por entrada
    for tr in sorted_candidates:
        close_active_at_or_before(tr.entry_time)

        if current_equity <= 0:
            skipped_count += 1
            continue

        if len(active_positions) >= config.max_open_trades_total:
            # Rejeitado por capacidade máxima de posições simultâneas
            skipped_count += 1
            continue

        # Calcula o capital em risco para esta entrada
        base_eq = (
            current_equity
            if config.risk_mode == "compounding"
            else config.initial_capital
        )
        risk_cash = base_eq * config.risk_per_trade_pct

        active_positions.append(
            {
                "trade": tr,
                "allocated_risk": risk_cash,
            }
        )

    # 2. Fecha todas as posições remanescentes ao final
    if active_positions:
        active_positions.sort(key=lambda p: p["trade"].exit_time)
        for pos in list(active_positions):
            tr = pos["trade"]
            risk_cash = pos["allocated_risk"]
            pnl_cash = risk_cash * tr.r_multiple
            current_equity = max(0.0, current_equity + pnl_cash)
            exec_record = PortfolioTradeExecution(
                symbol=tr.symbol,
                direction=tr.direction,
                entry_time=tr.entry_time,
                exit_time=tr.exit_time,
                entry_price=tr.entry_price,
                r_multiple=tr.r_multiple,
                exit_reason=getattr(tr, "exit_reason", "unknown"),
                allocated_risk_cash=risk_cash,
                pnl_cash=pnl_cash,
                equity_after_exit=current_equity,
            )
            realized_trades.append(exec_record)
        active_positions.clear()

    # 3. M-05: Ordena TODAS as realizações estritamente pela data de SAÍDA para curva e DD
    realized_trades.sort(key=lambda t: t.exit_time)

    # Constrói curva de capital e drawdown ordenados por saída
    equity_curve: list[dict[str, Any]] = [
        {
            "time": str(sorted_candidates[0].entry_time),
            "equity": config.initial_capital,
            "drawdown_pct": 0.0,
        }
    ]

    running_eq = float(config.initial_capital)
    peak_eq = running_eq
    max_dd_pct = 0.0
    peak_time = sorted_candidates[0].entry_time
    max_dd_duration_days = 0.0

    for tr_exec in realized_trades:
        running_eq += tr_exec.pnl_cash
        if running_eq > peak_eq:
            peak_eq = running_eq
            peak_time = tr_exec.exit_time
        else:
            dd_pct = (
                ((peak_eq - running_eq) / peak_eq * 100.0) if peak_eq > 0 else 0.0
            )
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct
            dur_days = (tr_exec.exit_time - peak_time).total_seconds() / 86400.0
            if dur_days > max_dd_duration_days:
                max_dd_duration_days = dur_days

        curr_dd = ((peak_eq - running_eq) / peak_eq * 100.0) if peak_eq > 0 else 0.0
        equity_curve.append(
            {
                "time": str(tr_exec.exit_time),
                "equity": round(running_eq, 2),
                "drawdown_pct": round(curr_dd, 2),
            }
        )

    total_return_pct = (
        (running_eq - config.initial_capital) / config.initial_capital * 100.0
    )

    # Anualização real
    first_time = sorted_candidates[0].entry_time
    last_time = realized_trades[-1].exit_time if realized_trades else first_time
    total_days = max(1.0, (last_time - first_time).total_seconds() / 86400.0)
    years = total_days / 365.25

    if years > 0 and running_eq > 0:
        annualized_return_pct = (
            (running_eq / config.initial_capital) ** (1.0 / years) - 1.0
        ) * 100.0
    else:
        annualized_return_pct = 0.0

    mar_ratio = (
        (annualized_return_pct / max_dd_pct)
        if max_dd_pct > 0 and annualized_return_pct > 0
        else 0.0
    )

    # 4. Retornos diários para Sharpe e Sortino
    df_curve = pd.DataFrame(
        [
            {"time": pd.to_datetime(pt["time"]), "equity": pt["equity"]}
            for pt in equity_curve
        ]
    )
    df_curve["time"] = pd.to_datetime(df_curve["time"])
    df_curve = df_curve.set_index("time").sort_index()

    daily_eq = df_curve["equity"].resample("1D").last().ffill()
    daily_returns = daily_eq.pct_change().dropna()

    if len(daily_returns) > 1 and daily_returns.std() > 0:
        mean_ret = daily_returns.mean()
        std_ret = daily_returns.std()
        daily_sharpe = float(mean_ret / std_ret * np.sqrt(252))

        neg_returns = daily_returns[daily_returns < 0]
        downside_std = neg_returns.std() if len(neg_returns) > 1 else std_ret
        daily_sortino = (
            float(mean_ret / downside_std * np.sqrt(252))
            if downside_std > 0
            else daily_sharpe
        )
    else:
        daily_sharpe = 0.0
        daily_sortino = 0.0

    # 5. % de Meses Positivos
    monthly_pnl: dict[str, float] = {}
    for tr_exec in realized_trades:
        m_key = tr_exec.exit_time.strftime("%Y-%m")
        monthly_pnl[m_key] = monthly_pnl.get(m_key, 0.0) + tr_exec.pnl_cash

    pos_months = sum(1 for pnl in monthly_pnl.values() if pnl > 0)
    total_months = len(monthly_pnl)
    pct_positive_months = (
        (pos_months / total_months * 100.0) if total_months > 0 else 0.0
    )

    # 6. Quebra por Ativo e Direção
    breakdown_by_symbol: dict[str, dict[str, Any]] = {}
    breakdown_by_direction: dict[str, dict[str, Any]] = {"long": {}, "short": {}}

    for tr_exec in realized_trades:
        sym = tr_exec.symbol
        d = tr_exec.direction

        if sym not in breakdown_by_symbol:
            breakdown_by_symbol[sym] = {
                "trades": 0,
                "wins": 0,
                "pnl_cash": 0.0,
                "r_total": 0.0,
            }
        breakdown_by_symbol[sym]["trades"] += 1
        if tr_exec.r_multiple > 0:
            breakdown_by_symbol[sym]["wins"] += 1
        breakdown_by_symbol[sym]["pnl_cash"] += tr_exec.pnl_cash
        breakdown_by_symbol[sym]["r_total"] += tr_exec.r_multiple

        if "trades" not in breakdown_by_direction[d]:
            breakdown_by_direction[d] = {
                "trades": 0,
                "wins": 0,
                "pnl_cash": 0.0,
                "r_total": 0.0,
            }
        breakdown_by_direction[d]["trades"] += 1
        if tr_exec.r_multiple > 0:
            breakdown_by_direction[d]["wins"] += 1
        breakdown_by_direction[d]["pnl_cash"] += tr_exec.pnl_cash
        breakdown_by_direction[d]["r_total"] += tr_exec.r_multiple

    for sym_data in breakdown_by_symbol.values():
        t_cnt = sym_data["trades"]
        sym_data["win_rate"] = (sym_data["wins"] / t_cnt * 100.0) if t_cnt > 0 else 0.0
        sym_data["pnl_cash"] = round(sym_data["pnl_cash"], 2)
        sym_data["r_total"] = round(sym_data["r_total"], 2)

    for dir_data in breakdown_by_direction.values():
        if dir_data:
            t_cnt = dir_data["trades"]
            dir_data["win_rate"] = (
                (dir_data["wins"] / t_cnt * 100.0) if t_cnt > 0 else 0.0
            )
            dir_data["pnl_cash"] = round(dir_data["pnl_cash"], 2)
            dir_data["r_total"] = round(dir_data["r_total"], 2)

    return PortfolioResult(
        initial_capital=config.initial_capital,
        final_capital=round(running_eq, 2),
        total_return_pct=round(total_return_pct, 2),
        annualized_return_pct=round(annualized_return_pct, 2),
        max_drawdown_pct=round(max_dd_pct, 2),
        max_drawdown_duration_days=round(max_dd_duration_days, 1),
        daily_sharpe=round(daily_sharpe, 2),
        daily_sortino=round(daily_sortino, 2),
        mar_ratio=round(mar_ratio, 2),
        pct_positive_months=round(pct_positive_months, 1),
        total_trades_submitted=len(sorted_candidates),
        total_trades_accepted=len(realized_trades),
        total_trades_skipped=skipped_count,
        trades=realized_trades,
        equity_curve=equity_curve,
        monthly_returns={k: round(v, 2) for k, v in monthly_pnl.items()},
        breakdown_by_symbol=breakdown_by_symbol,
        breakdown_by_direction=breakdown_by_direction,
        alarms=[],
    )

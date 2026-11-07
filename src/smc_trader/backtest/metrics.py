from typing import Any

from smc_trader.backtest.types import Trade


def calculate_metrics(trades: list[Trade]) -> dict[str, Any]:
    """Calcula estatísticas de desempenho em R e absolutas para a lista de trades."""
    if not trades:
        return {
            "total_trades": 0,
            "win_trades": 0,
            "loss_trades": 0,
            "win_rate": 0.0,
            "avg_r": 0.0,
            "expectancy": 0.0,
            "profit_factor": 0.0,
            "max_drawdown_r": 0.0,
            "total_pnl": 0.0,
            "monthly": {},
        }

    total = len(trades)
    wins = [t for t in trades if t.r_multiple > 0]
    losses = [t for t in trades if t.r_multiple <= 0]

    win_count = len(wins)
    loss_count = len(losses)
    win_rate = (win_count / total) * 100.0

    sum_gain_r = sum(t.r_multiple for t in wins)
    sum_loss_r = abs(sum(t.r_multiple for t in losses))

    avg_win_r = (sum_gain_r / win_count) if win_count > 0 else 0.0
    avg_loss_r = (sum_loss_r / loss_count) if loss_count > 0 else 0.0

    # Expectativa matemática em R por trade:
    # E = (P_win * avg_win) - (P_loss * avg_loss)
    p_win = win_count / total
    p_loss = loss_count / total
    expectancy = (p_win * avg_win_r) - (p_loss * avg_loss_r)

    # Profit Factor
    if sum_loss_r > 0:
        profit_factor = sum_gain_r / sum_loss_r
    else:
        profit_factor = float("inf") if sum_gain_r > 0 else 0.0

    avg_r = sum(t.r_multiple for t in trades) / total
    total_pnl = sum(t.pnl for t in trades)

    # Max drawdown em R acumulado
    cumulative_r = 0.0
    peak_r = 0.0
    max_dd_r = 0.0
    for t in trades:
        cumulative_r += t.r_multiple
        if cumulative_r > peak_r:
            peak_r = cumulative_r
        dd = peak_r - cumulative_r
        if dd > max_dd_r:
            max_dd_r = dd

    # Breakdown mensal
    monthly_data: dict[str, list[Trade]] = {}
    for t in trades:
        m_key = t.exit_time.strftime("%Y-%m")
        if m_key not in monthly_data:
            monthly_data[m_key] = []
        monthly_data[m_key].append(t)

    monthly_summary = {}
    for m_key, m_trades in monthly_data.items():
        m_total = len(m_trades)
        m_wins = sum(1 for t in m_trades if t.r_multiple > 0)
        m_r = sum(t.r_multiple for t in m_trades)
        monthly_summary[m_key] = {
            "trades": m_total,
            "win_rate": (m_wins / m_total * 100.0) if m_total > 0 else 0.0,
            "r_multiple": m_r,
        }

    return {
        "total_trades": total,
        "win_trades": win_count,
        "loss_trades": loss_count,
        "win_rate": round(win_rate, 2),
        "avg_r": round(avg_r, 2),
        "expectancy": round(expectancy, 2),
        "profit_factor": round(profit_factor, 2),
        "max_drawdown_r": round(max_dd_r, 2),
        "total_pnl": round(total_pnl, 2),
        "monthly": monthly_summary,
    }

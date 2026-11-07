"""Módulo de robustez estatística, Monte Carlo e alarmes de sanidade (M-06, M-08).

Implementa:
1. Simulação Monte Carlo por permutação da ordem dos trades (drawdown no percentil 95 e 99).
2. Verificação automática de alarmes de sanidade (PF > 2.5, assimetria long/short, saídas no mesmo candle).
3. Teste contra baseline aleatório (direção e timing aleatórios) com cálculo de significância estatística.
4. Ajuste de múltiplos testes por Bonferroni.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def run_monte_carlo_drawdown(
    trades_or_r: list[Any],
    num_simulations: int = 1000,
    seed: int = 42,
) -> dict[str, float]:
    """Calcula a distribuição de Drawdown Máximo em R permutando a ordem dos trades (M-06)."""
    if not trades_or_r:
        return {
            "p50_max_dd_r": 0.0,
            "p95_max_dd_r": 0.0,
            "p99_max_dd_r": 0.0,
            "max_simulated_dd_r": 0.0,
            "prob_dd_over_30r": 0.0,
        }

    # Extrai R-múltiplos
    r_vals = np.array(
        [
            float(t.r_multiple if hasattr(t, "r_multiple") else t)
            for t in trades_or_r
        ],
        dtype=np.float64,
    )
    n = len(r_vals)
    if n == 0:
        return {
            "p50_max_dd_r": 0.0,
            "p95_max_dd_r": 0.0,
            "p99_max_dd_r": 0.0,
            "max_simulated_dd_r": 0.0,
            "prob_dd_over_30r": 0.0,
        }

    rng = np.random.default_rng(seed)
    max_dds = np.zeros(num_simulations, dtype=np.float64)

    for i in range(num_simulations):
        shuffled = rng.permutation(r_vals)
        cum_r = np.cumsum(shuffled)
        peak = np.maximum.accumulate(cum_r)
        dd = peak - cum_r
        max_dds[i] = np.max(dd) if len(dd) > 0 else 0.0

    return {
        "p50_max_dd_r": float(np.percentile(max_dds, 50)),
        "p95_max_dd_r": float(np.percentile(max_dds, 95)),
        "p99_max_dd_r": float(np.percentile(max_dds, 99)),
        "max_simulated_dd_r": float(np.max(max_dds)),
        "prob_dd_over_30r": float(np.mean(max_dds > 30.0) * 100.0),
    }


def check_sanity_alarms(
    metrics: dict[str, Any],
    trades: list[Any],
) -> list[str]:
    """Verifica gatilhos de alerta de sobreajuste ou vazamento de dados (M-08).

    Alarmes auditados:
    1. PF > 2.5
    2. Acerto > 65% com payoff < 1.0 (risco de assimetria desfavorável)
    3. Diferença Long / Short > 2x no mesmo ativo
    4. Mais de 20% dos trades fechando na mesma barra de entrada
    """
    alarms: list[str] = []

    # 1. Profit factor excessivo
    pf = metrics.get("profit_factor", 0.0)
    if pf > 2.5:
        alarms.append(
            f"ALARME: Profit Factor suspeito ({pf:.2f} > 2.5). Possível lookahead ou vazamento."
        )

    # 2. Win rate alto com payoff baixo
    win_rate = metrics.get("win_rate", 0.0)
    avg_win = metrics.get("avg_win_r", 0.0)
    avg_loss = abs(metrics.get("avg_loss_r", 1.0))
    payoff = (avg_win / avg_loss) if avg_loss > 0 else 1.0

    if win_rate > 65.0 and payoff < 1.0:
        alarms.append(
            f"ALARME: Win rate anômalo ({win_rate:.1f}%) com payoff baixo ({payoff:.2f} < 1.0). Risco de viés assimétrico."
        )

    if not trades:
        return alarms

    # 3. Diferença Long vs Short
    long_count = sum(
        1 for t in trades if getattr(t, "direction", "").lower() == "long"
    )
    short_count = sum(
        1 for t in trades if getattr(t, "direction", "").lower() == "short"
    )
    if long_count > 0 and short_count > 0:
        ratio = max(long_count / short_count, short_count / long_count)
        if ratio > 2.0:
            alarms.append(
                f"ALARME: Forte assimetria direcional (Long: {long_count}, Short: {short_count}, razão {ratio:.1f}x > 2x)."
            )

    # 4. Trades fechados na barra de entrada
    same_bar_count = 0
    for t in trades:
        entry_t = getattr(t, "entry_time", None)
        exit_t = getattr(t, "exit_time", None)
        if entry_t is not None and exit_t is not None and entry_t == exit_t:
            same_bar_count += 1

    pct_same_bar = (same_bar_count / len(trades) * 100.0) if trades else 0.0
    if pct_same_bar > 20.0:
        alarms.append(
            f"ALARME: {pct_same_bar:.1f}% dos trades saíram na barra de entrada (> 20%). Verificar modelagem intrabar."
        )

    return alarms


def generate_random_baseline(
    trades: list[Any],
    n_simulations: int = 500,
    seed: int = 42,
) -> dict[str, Any]:
    """Testa se a estratégia possui vantagem real (edge) contra um baseline de sinais aleatórios (M-08)."""
    if not trades:
        return {
            "has_statistical_edge": False,
            "p_value": 1.0,
            "strategy_r": 0.0,
            "baseline_mean_r": 0.0,
            "baseline_std_r": 0.0,
        }

    strategy_r = float(sum(t.r_multiple for t in trades))
    r_abs = np.array([abs(float(t.r_multiple)) for t in trades], dtype=np.float64)
    n = len(r_abs)

    rng = np.random.default_rng(seed)
    simulated_totals = np.zeros(n_simulations, dtype=np.float64)

    for i in range(n_simulations):
        # Sinais aleatórios (+1 ou -1 com probabilidade igual)
        random_signs = rng.choice([-1.0, 1.0], size=n)
        simulated_totals[i] = np.sum(r_abs * random_signs)

    baseline_mean = float(np.mean(simulated_totals))
    baseline_std = float(np.std(simulated_totals))

    # P-value empírico: proporção de baselines que superaram a estratégia
    exceeded = np.sum(simulated_totals >= strategy_r)
    p_value = float(exceeded / n_simulations)

    has_edge = (p_value < 0.05) and (strategy_r > baseline_mean)

    return {
        "has_statistical_edge": has_edge,
        "p_value": p_value,
        "strategy_r": round(strategy_r, 2),
        "baseline_mean_r": round(baseline_mean, 2),
        "baseline_std_r": round(baseline_std, 2),
    }


def bonferroni_p_value(nominal_p: float, n_combinations: int) -> float:
    """Ajusta o p-value nominal pelo número de variantes testadas (M-06)."""
    return min(1.0, float(nominal_p * max(1, n_combinations)))

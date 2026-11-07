from dataclasses import dataclass
from typing import Any


@dataclass
class VariantExecutionSummary:
    config_hash: str
    blocks_filter: str
    entry_mode: str
    stop_mode: str
    trailing_mode: str
    confluence_profile: str
    is_metrics: dict[str, Any]
    oos_metrics: dict[str, Any]
    wf_metrics: list[dict[str, Any]]
    is_qualified: bool  # trades >= min_trades
    oos_profitable: bool  # oos expectancy > 0
    performance_drop_pct: float | None


def analyze_attribution(
    summaries: list[VariantExecutionSummary],
    min_trades: int = 30,
) -> dict[str, Any]:
    """Calcula a atribuição de performance marginal por fator em IS e OOS."""
    # Filtra as que têm amostra suficiente no IS
    qualified = [s for s in summaries if s.is_qualified]

    factors = [
        "blocks_filter",
        "entry_mode",
        "stop_mode",
        "trailing_mode",
        "confluence_profile",
    ]
    attribution_by_factor: dict[str, dict[str, dict[str, float]]] = {}

    for factor in factors:
        grouped: dict[str, list[VariantExecutionSummary]] = {}
        for s in qualified:
            val = getattr(s, factor)
            grouped.setdefault(val, []).append(s)

        factor_stats: dict[str, dict[str, float]] = {}
        for val, items in grouped.items():
            if not items:
                continue
            count = len(items)
            avg_is_exp = sum(i.is_metrics.get("expectancy", 0.0) for i in items) / count
            avg_oos_exp = (
                sum(i.oos_metrics.get("expectancy", 0.0) for i in items) / count
            )
            avg_is_wr = sum(i.is_metrics.get("win_rate", 0.0) for i in items) / count
            avg_oos_wr = sum(i.oos_metrics.get("win_rate", 0.0) for i in items) / count
            avg_is_dd = (
                sum(i.is_metrics.get("max_drawdown_r", 0.0) for i in items) / count
            )
            avg_oos_dd = (
                sum(i.oos_metrics.get("max_drawdown_r", 0.0) for i in items) / count
            )
            avg_is_trades = (
                sum(i.is_metrics.get("total_trades", 0) for i in items) / count
            )
            avg_oos_trades = (
                sum(i.oos_metrics.get("total_trades", 0) for i in items) / count
            )

            factor_stats[val] = {
                "count": float(count),
                "is_expectancy": avg_is_exp,
                "oos_expectancy": avg_oos_exp,
                "is_win_rate": avg_is_wr,
                "oos_win_rate": avg_oos_wr,
                "is_max_dd": avg_is_dd,
                "oos_max_dd": avg_oos_dd,
                "is_avg_trades": avg_is_trades,
                "oos_avg_trades": avg_oos_trades,
            }

        attribution_by_factor[factor] = factor_stats

    # M-01: Ranquear e escolher estritamente pelo In-Sample (IS) para evitar data snooping no OOS
    rankable = list(qualified)
    rankable.sort(
        key=lambda x: (
            x.is_metrics.get("expectancy", 0.0),
            x.is_metrics.get("profit_factor", 0.0),
        ),
        reverse=True,
    )
    robust_count = sum(1 for s in qualified if s.oos_profitable)

    return {
        "total_variants": len(summaries),
        "qualified_variants": len(qualified),
        "robust_variants": robust_count,
        "attribution_by_factor": attribution_by_factor,
        "ranking": rankable,
    }


def format_attribution_markdown(
    analysis_data: dict[str, Any],
    symbol: str,
    breaker_stats: dict[str, Any] | None = None,
) -> str:
    """Gera um relatório completo de atribuição e refinamento em formato Markdown."""
    lines: list[str] = []
    lines.append(f"# Relatório de Refinamento e Atribuição da Grade SMC — {symbol}")
    lines.append("")
    lines.append("## 1. Visão Geral da Exploração")
    lines.append(
        f"- **Total de variantes testadas:** {analysis_data['total_variants']}"
    )
    lines.append(
        f"- **Variantes com amostra suficiente (IS trades >= min_trades):** {analysis_data['qualified_variants']}"
    )
    lines.append(
        f"- **Variantes robustas (Expectativa OOS > 0):** {analysis_data['robust_variants']}"
    )
    lines.append("")

    if breaker_stats:
        total_bb = breaker_stats.get("total_breakers", 0)
        early_bb = breaker_stats.get("early_mitigated", 0)
        early_pct = (early_bb / total_bb * 100.0) if total_bb > 0 else 0.0
        lines.append("## 2. Estatística de Breakers Precoces")
        lines.append(f"- Total de Breakers formados: **{total_bb}**")
        lines.append(
            f"- Breakers que tocam no 1º candle M15 após criação: **{early_bb}** ({early_pct:.1f}%)"
        )
        lines.append(
            "> *Conforme adendo da spec, cerca de 1/3 dos breakers tocam a zona já no primeiro candle M15 subsequente à quebra, exigindo armamento M1 imediato sem esperar o fechamento M15.*"
        )
        lines.append("")

    lines.append("## 3. Análise Marginal de Atribuição por Fator")
    lines.append(
        "Impacto médio em Amostra (IS) e Fora da Amostra (OOS) isolando cada dimensão:"
    )
    lines.append("")

    factor_names = {
        "blocks_filter": "Tipo de Bloco (POI)",
        "entry_mode": "Modo de Entrada",
        "stop_mode": "Modo de Stop Loss",
        "trailing_mode": "Condução (Trailing Stop)",
        "confluence_profile": "Perfil de Confluência",
    }

    attr = analysis_data.get("attribution_by_factor", {})
    for factor_key, factor_title in factor_names.items():
        stats = attr.get(factor_key, {})
        if not stats:
            continue
        lines.append(f"### {factor_title}")
        lines.append(
            "| Variante | IS Exp (R) | OOS Exp (R) | IS Acerto | OOS Acerto | IS Max DD | OOS Max DD | Amostra |"
        )
        lines.append("|---|---|---|---|---|---|---|---|")
        for val, m in sorted(
            stats.items(), key=lambda kv: kv[1]["oos_expectancy"], reverse=True
        ):
            lines.append(
                f"| `{val}` | {m['is_expectancy']:+.2f}R | {m['oos_expectancy']:+.2f}R | "
                f"{m['is_win_rate']:.1f}% | {m['oos_win_rate']:.1f}% | "
                f"{m['is_max_dd']:.1f}R | {m['oos_max_dd']:.1f}R | {int(m['count'])} |"
            )
        lines.append("")

    lines.append(
        "## 4. Ranking das Melhores Estratégias (Seleção Estrita por In-Sample)"
    )
    lines.append(
        "| # | Hash | Blocos | Entrada | Stop | Trailing | Confluência | IS Exp | IS PF | OOS Exp | OOS Acerto | OOS PF | OOS DD | Queda IS→OOS |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")

    ranking: list[VariantExecutionSummary] = analysis_data.get("ranking", [])
    for idx, s in enumerate(ranking[:10], start=1):
        drop_str = (
            f"{s.performance_drop_pct:+.1f}%"
            if s.performance_drop_pct is not None
            else "N/A"
        )
        lines.append(
            f"| {idx} | `{s.config_hash}` | `{s.blocks_filter}` | `{s.entry_mode}` | "
            f"`{s.stop_mode}` | `{s.trailing_mode}` | `{s.confluence_profile}` | "
            f"{s.is_metrics.get('expectancy', 0.0):+.2f}R | {s.is_metrics.get('profit_factor', 0.0):.2f} | "
            f"{s.oos_metrics.get('expectancy', 0.0):+.2f}R | {s.oos_metrics.get('win_rate', 0.0):.1f}% | "
            f"{s.oos_metrics.get('profit_factor', 0.0):.2f} | {s.oos_metrics.get('max_drawdown_r', 0.0):.1f}R | "
            f"{drop_str} |"
        )
    lines.append("")

    if not ranking:
        lines.append(
            "> [!WARNING]\n> Nenhuma variante atingiu o piso de trades no In-Sample."
        )
    else:
        best = ranking[0]
        lines.append("## 5. Recomendação e Validação Fora da Amostra (OOS)")
        lines.append(
            f"A configuração campeã selecionada pelo In-Sample foi o hash **`{best.config_hash}`**:"
        )
        lines.append(f"- **Blocos:** `{best.blocks_filter}`")
        lines.append(f"- **Entrada:** `{best.entry_mode}`")
        lines.append(f"- **Stop Loss:** `{best.stop_mode}`")
        lines.append(f"- **Trailing Stop:** `{best.trailing_mode}`")
        lines.append(f"- **Confluências:** `{best.confluence_profile}`")
        lines.append(
            f"- **Desempenho no Treino (IS):** `{best.is_metrics.get('expectancy', 0.0):+.2f}R` ({best.is_metrics.get('total_trades', 0)} trades, PF `{best.is_metrics.get('profit_factor', 0.0):.2f}`)"
        )
        lines.append(
            f"- **Desempenho no Teste (OOS):** `{best.oos_metrics.get('expectancy', 0.0):+.2f}R` ({best.oos_metrics.get('total_trades', 0)} trades, PF `{best.oos_metrics.get('profit_factor', 0.0):.2f}`, Acerto `{best.oos_metrics.get('win_rate', 0.0):.1f}%`)"
        )

    return "\n".join(lines)

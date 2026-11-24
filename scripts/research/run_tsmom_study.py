"""Estudo do TSMOM diário diversificado com dados públicos do FRED.

Uso: uv run python scripts/research/run_tsmom_study.py
Baixa as séries para data/fred/ (se faltarem) e escreve reports/tsmom_diario_fred.md.

Protocolo (AGENTS.md, seção 2):
- Variante principal fixada ANTES de olhar os dados: lookback 252, rebalanceamento mensal,
  vol-alvo 40% por ativo, EWMA com centro de massa 60 (parâmetros do artigo de 2012).
- Variantes reportadas, não escolhidas: lookback 63 e 126 (N = 3 no total).
- Dentro da amostra: início até 2012-12-31 (o artigo usou dados até 2009);
  fora da amostra: 2013-01-01 em diante.
- Controles: sinal aleatório (500 sorteios) e comprado sempre, mesmo tamanho e custo.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from smc_trader.strategies.tsmom import (  # noqa: E402
    TSMOMConfig,
    long_only_signal,
    random_signal,
    run_backtest,
    stats,
    trade_episodes,
)

DATA = ROOT / "data" / "fred"
REPORT = ROOT / "reports" / "tsmom_diario_fred.md"

# série FRED -> (nome, custo em bps do nocional por ajuste: spread + slippage, conservador)
ASSETS = {
    "NASDAQ100": ("NAS100", 2.0),
    "DCOILBRENTEU": ("BRENT", 5.0),
    "DEXUSEU": ("EURUSD", 1.5),
    "DEXUSUK": ("GBPUSD", 1.5),
    "DEXJPUS": ("USDJPY", 1.5),
    "DEXUSAL": ("AUDUSD", 1.5),
    "DEXCAUS": ("USDCAD", 1.5),
    "DEXSZUS": ("USDCHF", 1.5),
    "DEXMXUS": ("USDMXN", 5.0),
    "DEXBZUS": ("USDBRL", 5.0),
}
START = "1990-01-01"
IS_END = "2012-12-31"
N_RANDOM = 500


def load() -> pd.DataFrame:
    DATA.mkdir(parents=True, exist_ok=True)
    cols = {}
    for sid, (name, _) in ASSETS.items():
        f = DATA / f"{sid}.csv"
        if not f.exists():
            url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
            urllib.request.urlretrieve(url, f)
        s = pd.read_csv(f, index_col=0, parse_dates=True).iloc[:, 0]
        cols[name] = pd.to_numeric(s, errors="coerce")
    px = pd.DataFrame(cols)
    px = px[px.index >= START]
    return px.dropna(how="all")


def fmt_stats(s: dict) -> str:
    if "sharpe" not in s:
        return "sem dados"
    return (
        f"{s['ann_return']:+.1%} a.a.; vol {s['ann_vol']:.1%}; Sharpe {s['sharpe']:.2f}; "
        f"t {s['t_stat']:.2f}; MaxDD {s['max_dd']:.1%}; {s['years']:.1f} anos"
    )


def main() -> None:
    px = load()
    costs = {name: c for _, (name, c) in ASSETS.items()}
    base = TSMOMConfig(cost_bps=costs)
    out: list[str] = []
    w = out.append

    w("# TSMOM diário diversificado: estudo com dados do FRED\n")
    w("**Fonte:** backtest. **Dados:** FRED, fechamento diário, "
      f"{px.index[0].date()} a {px.index[-1].date()}. "
      "**Custos:** bps do nocional por ajuste (abaixo); execução no fechamento do pregão "
      "seguinte à decisão. **Resultado preliminar, não validado para conta real.**\n")
    w("Ativos e custo por ajuste (bps): " + ", ".join(f"{n} {c}" for n, c in costs.items()) + "\n")

    results = {}
    for lb in (252, 126, 63):
        cfg = TSMOMConfig(lookback=lb, cost_bps=costs)
        results[lb] = run_backtest(px, cfg)
    main_res = results[252]
    port = main_res.portfolio

    w("## 1. Variante principal (lookback 252, fixada antes do teste)\n")
    w(f"- Amostra completa: {fmt_stats(stats(port))}")
    w(f"- Dentro da amostra (até {IS_END}): {fmt_stats(stats(port[:IS_END]))}")
    w(f"- **Fora da amostra (2013 em diante): {fmt_stats(stats(port[IS_END:].iloc[1:]))}**")
    w(f"- Sem custo, amostra completa: {fmt_stats(stats(main_res.gross))}")
    w(f"- Sem custo, fora da amostra: {fmt_stats(stats(main_res.gross[IS_END:].iloc[1:]))}")
    cost_ann = main_res.costs.mean() * 261
    w(f"- Custo médio: {cost_ann:.2%} a.a.; giro médio {main_res.turnover.mean() * 261:.1f}x/ano")
    double = run_backtest(px, TSMOMConfig(cost_bps={k: 2 * v for k, v in costs.items()}))
    w(f"- Custo em dobro, amostra completa: {fmt_stats(stats(double.portfolio))}\n")

    w("## 2. Controles (mesmo tamanho, frequência e custo)\n")
    lo = run_backtest(px, base, signal=long_only_signal(px)).portfolio
    w(f"- Comprado sempre: {fmt_stats(stats(lo))}")
    w(f"- Comprado sempre, fora da amostra: {fmt_stats(stats(lo[IS_END:].iloc[1:]))}")
    rng = np.random.default_rng(12345)
    rand_sh, rand_sh_oos = [], []
    for _ in range(N_RANDOM):
        r = run_backtest(px, base, signal=random_signal(px, base, rng)).portfolio
        rand_sh.append(stats(r)["sharpe"])
        rand_sh_oos.append(stats(r[IS_END:].iloc[1:])["sharpe"])
    rand_sh, rand_sh_oos = np.array(rand_sh), np.array(rand_sh_oos)
    sh, sh_oos = stats(port)["sharpe"], stats(port[IS_END:].iloc[1:])["sharpe"]
    w(f"- Sinal aleatório ({N_RANDOM} sorteios), Sharpe: média {rand_sh.mean():.2f}, "
      f"desvio {rand_sh.std():.2f}, p95 {np.percentile(rand_sh, 95):.2f}, "
      f"máx {rand_sh.max():.2f}")
    w(f"- TSMOM (Sharpe {sh:.2f}) supera {np.mean(rand_sh < sh):.1%} dos sorteios na "
      "amostra completa")
    w(f"- Fora da amostra: aleatório média {rand_sh_oos.mean():.2f} (p95 "
      f"{np.percentile(rand_sh_oos, 95):.2f}); TSMOM {sh_oos:.2f} supera "
      f"{np.mean(rand_sh_oos < sh_oos):.1%}\n")

    w("## 3. Todas as variantes testadas (N = 3; nenhuma foi escolhida pelo resultado)\n")
    w("| Lookback | Amostra completa | Fora da amostra |")
    w("|---|---|---|")
    for lb, res in results.items():
        p = res.portfolio
        w(f"| {lb} | {fmt_stats(stats(p))} | {fmt_stats(stats(p[IS_END:].iloc[1:]))} |")
    w("")

    w("## 4. Por ano (variante principal, líquido)\n")
    yearly = (1 + port).groupby(port.index.year).prod() - 1
    w("| Ano | Retorno |")
    w("|---|---|")
    for y, v in yearly.items():
        w(f"| {y} | {v:+.1%} |")
    neg = int((yearly < 0).sum())
    w(f"\nAnos negativos: {neg} de {len(yearly)}.\n")

    w("## 5. Por ativo (contribuição líquida, soma simples)\n")
    w("| Ativo | Total | Fora da amostra |")
    w("|---|---|---|")
    for c in px.columns:
        a = main_res.asset_pnl[c]
        w(f"| {c} | {a.sum():+.1%} | {a[IS_END:].iloc[1:].sum():+.1%} |")
    w("")

    w("## 6. Trades e conferência dos números (item 7)\n")
    ep = trade_episodes(main_res)
    wins, losses = ep[ep.pnl > 0], ep[ep.pnl <= 0]
    p_win = len(wins) / len(ep)
    avg_w, avg_l = wins.pnl.mean(), -losses.pnl.mean()
    check = p_win * avg_w - (1 - p_win) * avg_l
    w(f"- Trades (trechos de posição): {len(ep)}; duração mediana {ep.days.median():.0f} pregões")
    w(f"- Acerto {p_win:.1%}; ganho médio {avg_w:+.3%}; perda média {-avg_l:+.3%} da conta")
    w(f"- Acerto × ganho − erro × perda = {check:+.4%}; média real {ep.pnl.mean():+.4%}")
    se = ep.pnl.std(ddof=1) / np.sqrt(len(ep))
    w(f"- Erro-padrão do resultado por trade: {se:.4%} (t ≈ {ep.pnl.mean() / se:.2f})")
    w(f"- Payoff (ganho médio / perda média): {avg_w / avg_l:.2f}\n")

    w("## 7. Causalidade e limitações\n")
    w("- Sinal: retorno de `close[d - 252]` a `close[d]`; vol: EWMA de retornos até `d`. "
      "Decisão no fechamento do último pregão do mês, execução no fechamento do pregão "
      "seguinte, retorno a partir do outro. Teste: `tests/test_tsmom.py` "
      "(invariância de prefixo e atraso de execução).")
    w("- Câmbio spot sem diferencial de juros: um CFD real cobra/paga swap, que pode somar "
      "ou subtrair alguns % a.a. em USDMXN, USDBRL, USDJPY e AUDUSD.")
    w("- Brent spot (FRED) não é o futuro/CFD: falta o custo de rolagem.")
    w("- Ouro e DAX não estão no FRED; gás natural spot foi excluído (picos não negociáveis).")
    w("- Universo pesado em câmbio (8 de 10 ativos): o resultado depende disso.")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()

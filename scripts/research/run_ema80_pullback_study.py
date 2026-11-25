"""Estudo: pullback na MME80 em tendência (MME80 x MMA200, inclinação >= 30°), sem Fibo.

Uso:
    uv run python scripts/research/run_ema80_pullback_study.py --data-dir data/mt5_export --tf D1

Entrada: CSVs exportados pelo script `mql5/Export_History.mq5` (`SIMBOLO_TF.csv`, colunas
time,open,high,low,close,tick_volume,spread) e `symbols_meta.csv` (symbol,point,digits,...).
Saída: reports/ema80_pullback_<TF>.md

Protocolo (AGENTS.md, seção 2), fixado antes de ver resultado:
- Variantes pedidas pelo usuário: stop {fundo, mm200} x alvo {2R, 3R} = 4.
- Ablação informada: as mesmas 4 sem o filtro de inclinação (total N = 8).
- Dentro/fora da amostra: os primeiros 60% do histórico de cada ativo / os 40% finais.
- Rodada sem custo (spread e slippage zero) e controle aleatório (mesma tendência, mesmo
  stop e alvo, entrada a mercado em barras sorteadas, frequência calibrada), 200 sorteios.
- Custo: spread mediano da corretora (coluna `spread` × point) e slippage nas ordens stop
  igual a um spread, com mínimo de 1,0 ponto em índices.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from smc_trader.strategies.ema80_pullback import (  # noqa: E402
    EMA80PullbackConfig,
    eligible_bars,
    prepare,
    run,
    run_random_control,
    summarize,
)

INDEX_HINTS = ("NAS", "US30", "US500", "SPX", "DAX", "GER", "DJ", "NDX", "UK100", "JP225", "WIN")
IS_FRACTION = 0.60
N_RANDOM = 200


def load_dir(data_dir: Path, tf: str) -> dict[str, tuple[pd.DataFrame, float, float]]:
    meta_path = data_dir / "symbols_meta.csv"
    meta = pd.read_csv(meta_path).set_index("symbol") if meta_path.exists() else None
    out = {}
    for f in sorted(data_dir.glob(f"*_{tf}.csv")):
        sym = f.name[: -len(f"_{tf}.csv")]
        df = pd.read_csv(f)
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time").sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df = df[(df["high"] >= df["low"]) & (df["close"] > 0)]
        point = float(meta.loc[sym, "point"]) if meta is not None and sym in meta.index else 0.0
        spread_pts = float(df["spread"].median()) if "spread" in df else 0.0
        spread = spread_pts * point
        slip = spread
        if any(h in sym.upper() for h in INDEX_HINTS):
            slip = max(slip, 1.0)
        out[sym] = (df[["open", "high", "low", "close"]], spread, slip)
    return out


def fmt(s: dict) -> str:
    if s.get("n", 0) == 0:
        return "0 trades"
    return (f"{s['n']} trades; {s['total_r']:+.1f}R; {s['avg_r']:+.3f} ± {s['se']:.3f}R/trade "
            f"(t {s['t']:.2f}); acerto {s['win_rate']:.1%}; PF {s['pf']:.2f}; "
            f"MaxDD {s['max_dd_r']:.1f}R")


def split_is_oos(trades, cut_time):
    return ([t for t in trades if t.entry_time < cut_time],
            [t for t in trades if t.entry_time >= cut_time])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, default=ROOT / "data" / "mt5_export")
    ap.add_argument("--tf", default="D1")
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()

    data = load_dir(args.data_dir, args.tf)
    if not data:
        raise SystemExit(f"nenhum arquivo *_{args.tf}.csv em {args.data_dir}")

    out: list[str] = []
    w = out.append
    w(f"# Pullback na MME80 (MME80 x MMA200, inclinação ≥ 30°): {args.tf}\n")
    first = min(d.index[0] for d, _, _ in data.values())
    last = max(d.index[-1] for d, _, _ in data.values())
    w(f"**Fonte:** backtest. **Dados:** export do MT5, {first.date()} a {last.date()}, "
      f"{len(data)} ativos. **Custos:** spread mediano da corretora e slippage nos stops "
      "(mínimo 1 ponto em índices). **Resultado preliminar, não validado.**\n")
    w("| Ativo | Barras | Spread | Slippage |")
    w("|---|---|---|---|")
    for sym, (df, spread, slip) in data.items():
        w(f"| {sym} | {len(df)} | {spread:g} | {slip:g} |")
    w("")

    variants = []
    for angle in (30.0, 0.0):
        for stop in ("fundo", "mm200"):
            for tgt in (2.0, 3.0):
                variants.append((angle, stop, tgt))
    w(f"Variantes testadas: N = {len(variants)} (4 pedidas + 4 de ablação sem inclinação).\n")

    rng = np.random.default_rng(args.seed)
    w("## 1. Resultado por variante (todos os ativos juntos)\n")
    w("| Inclinação | Stop | Alvo | Com custo | Sem custo | Dentro (60%) | **Fora (40%)** |"
      " Empate | Aleatório (média; p95) | Supera aleatório |")
    w("|---|---|---|---|---|---|---|---|---|---|")
    details = {}
    for angle, stop, tgt in variants:
        all_t, all_free, ins, oos = [], [], [], []
        per_sym = {}
        rand_avgs = np.zeros(N_RANDOM)
        rand_n = np.zeros(N_RANDOM)
        for sym, (df, spread, slip) in data.items():
            cfg = EMA80PullbackConfig(min_angle_deg=angle, stop_mode=stop, target_r=tgt,
                                      spread=spread, slippage=slip)
            pre = prepare(df, cfg)
            tr = run(df, sym, cfg, pre)
            free = run(df, sym, replace(cfg, spread=0.0, slippage=0.0), pre)
            cut = df.index[int(len(df) * IS_FRACTION)]
            a, b = split_is_oos(tr, cut)
            all_t += tr
            all_free += free
            ins += a
            oos += b
            per_sym[sym] = tr
            # controle aleatório: calibra a frequência para o mesmo nº de trades
            elig = max(eligible_bars(df, cfg, pre), 1)
            p = min(1.0, max(len(tr), 1) / elig)
            probe = run_random_control(df, sym, cfg, p, np.random.default_rng(0), pre)
            if probe:
                p = min(1.0, p * len(tr) / len(probe)) if len(tr) else p
            for k in range(N_RANDOM):
                rt = run_random_control(df, sym, cfg, p, rng, pre)
                rand_avgs[k] += sum(t.r_multiple for t in rt)
                rand_n[k] += len(rt)
        rand_avg = rand_avgs / np.maximum(rand_n, 1)
        s = summarize(all_t)
        beats = float(np.mean(rand_avg < s.get("avg_r", -np.inf))) if s["n"] else 0.0
        w(f"| {angle:g}° | {stop} | {tgt:g}R | {fmt(s)} | {fmt(summarize(all_free))} | "
          f"{fmt(summarize(ins))} | **{fmt(summarize(oos))}** | {1 / (1 + tgt):.1%} | "
          f"{rand_avg.mean():+.3f}R; {np.percentile(rand_avg, 95):+.3f}R | {beats:.1%} |")
        details[(angle, stop, tgt)] = (all_t, per_sym)
    w("")
    w("*Empate* = taxa de acerto que zera o resultado sem custo com esse alvo. Um passeio "
      "aleatório fica perto desse valor (AGENTS.md, seção 2, item 3).\n")

    w("## 2. Por ativo (variantes pedidas, com custo)\n")
    for angle, stop, tgt in variants[:4]:
        _, per_sym = details[(angle, stop, tgt)]
        w(f"### Stop {stop}, alvo {tgt:g}R\n")
        w("| Ativo | Resultado |")
        w("|---|---|")
        for sym, tr in per_sym.items():
            w(f"| {sym} | {fmt(summarize(tr))} |")
        pos = sum(1 for tr in per_sym.values() if tr and summarize(tr)["total_r"] > 0)
        w(f"\nAtivos positivos: {pos} de {len(per_sym)}.\n")

    w("## 3. Por ano (variantes pedidas, com custo, R somado)\n")
    years = sorted({t.entry_time.year for k in variants[:4] for t in details[k][0]})
    w("| Ano | " + " | ".join(f"{s} {t:g}R" for _, s, t in variants[:4]) + " |")
    w("|---|" + "---|" * 4)
    for y in years:
        row = []
        for k in variants[:4]:
            row.append(f"{sum(t.r_multiple for t in details[k][0] if t.entry_time.year == y):+.1f}")
        w(f"| {y} | " + " | ".join(row) + " |")
    w("")

    w("## 4. Conferência (item 7) e causalidade\n")
    for k in variants[:4]:
        s = summarize(details[k][0])
        if s["n"]:
            chk = s["win_rate"] * s["avg_win"] + (1 - s["win_rate"]) * s["avg_loss"]
            w(f"- {k[1]} {k[2]:g}R: acerto × ganho + erro × perda = {chk:+.3f}R; "
              f"média {s['avg_r']:+.3f}R; ganho médio {s['avg_win']:+.2f}R, "
              f"perda média {s['avg_loss']:+.2f}R")
    w("- Filtros em `i - 1`: MME80, MMA200, ângulo e a barra `i - 1` inteira do lado da "
      "tendência. Preço da limite = MME80[i - 1]; stop fixado antes de `i` abrir; pivô só "
      "conta depois de confirmado. Barra de entrada só pode ser estopada; gap no stop sai "
      "no open com slippage; stop e alvo na mesma barra = stop. Testes: "
      "`tests/test_ema80_pullback.py`.")
    w("- Ângulo: atan(variação da MME80 em 10 barras / ATR14). 30° = subida de 0,577 ATR em "
      "10 barras. Outra escala mudaria o filtro.")
    w("- Swap (custo de dormir posicionado) NÃO está incluído: em D1 ele pode pesar bastante.")

    report = ROOT / "reports" / f"ema80_pullback_{args.tf}.md"
    report.write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()

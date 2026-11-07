"""Autópsia dos stops: amostra, diagnóstico e teste de filtros (treino/teste) em todos os ativos."""
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path("out/analysis")
SYMS = ["BRENT", "XAUUSD", "NAS100", "DAX40", "EURUSD", "GBPUSD", "USDJPY"]
df = pd.concat([pd.read_pickle(OUT / f"trades_{s}.pkl") for s in SYMS], ignore_index=True)
df["stop"] = df["r"] <= -0.5
df["win"] = df["r"] > 0
SPLIT = pd.Timestamp("2026-05-01", tz="UTC")
df["period"] = np.where(df["entry_time"] < SPLIT, "treino", "teste")


def summ(d):
    n = len(d)
    return pd.Series(dict(n=n, wr=100 * d.win.mean() if n else 0, r=d.r.sum(), exp=d.r.mean() if n else 0))


dd = df[df.model == "DayFlow"].copy()

# ---------- 1) Amostra de 15 stops por ativo + diagnóstico por regras ----------
rng = np.random.default_rng(7)
samples = []
for s in SYMS:
    st = dd[(dd.symbol == s) & dd.stop]
    samples.append(st.sample(min(15, len(st)), random_state=7))
sm = pd.concat(samples)


def diag(r):
    tags = []
    if r.mfe_r >= 1.5:
        tags.append("chegou a +1.5R e devolveu")
    elif r.mfe_r >= 0.8:
        tags.append("chegou a +0.8R e devolveu")
    if r.dur_min <= 15:
        tags.append("stop em <=15min (ruido/varrida)")
    if r.reversed_after_stop:
        tags.append("TP atingido em 4h apos o stop (stop curto/varrida)")
    if r.h4_align < 0:
        tags.append("contra tendencia H4")
    if r.struct == "CHoCH":
        tags.append("zona de reversao (CHoCH)")
    if not r.swept:
        tags.append("sem sweep de liquidez")
    if r.risk_atr < 0.8:
        tags.append("stop apertado (<0.8 ATR)")
    if r.risk_atr > 4:
        tags.append("stop muito largo (>4 ATR)")
    if r.age_h > 24:
        tags.append("zona velha (>24h)")
    return "; ".join(tags) if tags else "sem padrao claro"


sm["diagnostico"] = sm.apply(diag, axis=1)
cols = ["symbol", "direction", "entry_time", "exit_reason", "r", "risk_atr", "mfe_r", "dur_min", "age_h", "struct",
        "swept", "h4_align", "h1_align", "reversed_after_stop", "diagnostico"]
sm[cols].to_csv(OUT / "amostra_stops_15_por_ativo.csv", index=False)

print("=== CAUSAS NA AMOSTRA (105 stops) ===")
flags = {
    "mfe>=0.8R": sm.mfe_r >= 0.8,
    "mfe>=1.5R": sm.mfe_r >= 1.5,
    "dur<=15min": sm.dur_min <= 15,
    "TP em 4h pos-stop": sm.reversed_after_stop,
    "contra H4": sm.h4_align < 0,
    "contra H1": sm.h1_align < 0,
    "CHoCH (reversao)": sm.struct == "CHoCH",
    "sem sweep": ~sm.swept,
    "stop<0.8ATR": sm.risk_atr < 0.8,
}
for k, v in flags.items():
    print(f"{k:22} {v.mean()*100:5.1f}%")

# ---------- 2) Universo completo: stops vs wins por feature ----------
print("\n=== FEATURE vs RESULTADO (DayFlow, 7 ativos, 1 ano) ===")
def tab(col, bins=None):
    x = dd.copy()
    if bins is not None:
        x[col] = pd.cut(x[col], bins)
    g = x.groupby(col, observed=True).apply(summ)
    print(f"\n-- {col}"); print(g.round(2).to_string())

tab("h4_align"); tab("h1_align"); tab("struct"); tab("swept")
tab("risk_atr", [0, 0.8, 1.5, 2.5, 4, 100]); tab("age_h", [0, 2, 6, 24, 72, 1e4])
tab("zone_size_atr", [0, 0.5, 1, 2, 100])
tab("hour")

# ---------- 3) Filtros candidatos, pooled, com treino/teste e consistência por ativo ----------
print("\n=== FILTROS CANDIDATOS (DayFlow) ===")
cands = {
    "base (sem filtro)": lambda d: d.r.notna(),
    "H4 a favor": lambda d: d.h4_align > 0,
    "H4+H1 a favor": lambda d: (d.h4_align > 0) & (d.h1_align > 0),
    "BOS (continuacao)": lambda d: d.struct == "BOS",
    "com sweep": lambda d: d.swept,
    "stop >=1.5 ATR": lambda d: d.risk_atr >= 1.5,
    "stop 1.5-4 ATR": lambda d: (d.risk_atr >= 1.5) & (d.risk_atr <= 4),
    "zona fresca <=6h": lambda d: d.age_h <= 6,
    "H4 a favor + BOS": lambda d: (d.h4_align > 0) & (d.struct == "BOS"),
    "H4 a favor + stop>=1.5ATR": lambda d: (d.h4_align > 0) & (d.risk_atr >= 1.5),
    "H4+H1 + BOS + stop>=1.5ATR": lambda d: (d.h4_align > 0) & (d.h1_align > 0) & (d.struct == "BOS") & (d.risk_atr >= 1.5),
}
rows = []
for name, f in cands.items():
    sel = dd[f(dd)]
    tr, te = sel[sel.period == "treino"], sel[sel.period == "teste"]
    per_asset = sel.groupby("symbol").r.sum().reindex(SYMS).fillna(0)
    rows.append(dict(
        filtro=name, trades=len(sel), wr=round(100 * sel.win.mean(), 1), exp=round(sel.r.mean(), 3),
        R_total=round(sel.r.sum(), 1), R_treino=round(tr.r.sum(), 1), exp_treino=round(tr.r.mean(), 3),
        R_teste=round(te.r.sum(), 1), exp_teste=round(te.r.mean(), 3),
        ativos_positivos=int((per_asset > 0).sum()),
    ))
res = pd.DataFrame(rows)
print(res.to_string(index=False))
res.to_csv(OUT / "filtros_candidatos.csv", index=False)

print("\n=== POR ATIVO: base vs melhor filtro combinado (R) ===")
f = cands["H4 a favor + BOS"]
for s in SYMS:
    a = dd[dd.symbol == s]
    print(f"{s:7} base {a.r.sum():+7.1f}R ({len(a)} tr) | H4+BOS {a[f(a)].r.sum():+7.1f}R ({f(a).sum()} tr)")

print("\n=== WYCKOFF (172 trades) por feature ===")
ww = df[df.model == "Wyckoff"]
for col in ["h4_align", "struct"]:
    print(ww.groupby(col).apply(summ).round(2).to_string())

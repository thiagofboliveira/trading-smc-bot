import openpyxl
import pandas as pd

wb = openpyxl.load_workbook("out/estudo_wyckoff_multiativo.xlsx")
ws = wb["Ranking & Campeões"]

data = []
for r in range(2, ws.max_row + 1):
    sym = ws.cell(row=r, column=1).value
    tf = ws.cell(row=r, column=2).value
    strat = ws.cell(row=r, column=3).value
    trades = ws.cell(row=r, column=4).value
    wr = float(str(ws.cell(row=r, column=7).value).replace("%", ""))
    exp = float(str(ws.cell(row=r, column=9).value).replace("R", ""))
    pf = ws.cell(row=r, column=10).value
    data.append({"sym": sym, "tf": tf, "strat": strat, "trades": trades, "wr": wr, "exp": exp, "pf": pf})

df = pd.DataFrame(data)

for s in ["Wyckoff + Breakers com Sweep", "Wyckoff + Trailing BOS (Ativação 1R)", "SMC Padrão (Sem filtro sweep)"]:
    for tf in ["H1/M1", "M15/M1", "H1/M5"]:
        sub = df[(df["strat"] == s) & (df["tf"] == tf)]
        if len(sub) >= 4:
            print(f"=== {s} no {tf} (Total Ativos: {len(sub)}) ===")
            for _, row in sub.iterrows():
                print(f"  {row['sym']}: {row['wr']}% acerto | {row['exp']:+.2f}R | PF: {row['pf']} | {row['trades']} trades")
            print(f"  MÉDIA: {sub['wr'].mean():.1f}% acerto | {sub['exp'].mean():+.2f}R | Total Trades: {sub['trades'].sum()}\n")

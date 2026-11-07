"""
Script Oficial de Auditoria e Backtest: SMC Fibonacci OTE (M5)
Gera planilha Excel profissional de 2 abas, resumo em TXT e registra no painel Web UI.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
import numpy as np

from smc_trader.strategies.fibo_ote import FiboOTEConfig, FiboOTEStrategy

SPREADS = {
    "BRENT": 0.04,     # 4 cents
    "XAUUSD": 0.30,    # 30 cents
    "NAS100": 1.50,    # 1.5 pts
    "DAX40": 1.50,     # 1.5 pts
    "EURUSD": 0.00015, # 1.5 pips
    "GBPUSD": 0.00020, # 2.0 pips
    "USDJPY": 0.018    # 1.8 pips
}

SYMBOLS = ["NAS100", "XAUUSD", "DAX40", "BRENT", "EURUSD", "GBPUSD", "USDJPY"]

def main():
    print("=" * 80)
    print("🚀 EXECUTANDO SUITE OFICIAL DE BACKTEST: SMC FIBONACCI OTE (M5)")
    print("Período: 1 Ano Completo (01/11/2025 a 04/11/2026)")
    print("Regra: M5 | Entrada 61.8% | Stop 79.0% | Alvo Fixo 3R")
    print("=" * 80 + "\n")

    # Configuração Oficial Validada: Entrada 61.8% com stop no 79.0%, Alvo 3R (Sem reentrada faca caindo)
    cfg = FiboOTEConfig(
        timeframe="5min",
        fibo_entry=0.618,
        fibo_stop=0.790,
        target_mode="3R",
        target_r=3.0,
        pivot_k=3,
        enable_reentry_79=False
    )
    strategy = FiboOTEStrategy(cfg)

    all_trades_list = []
    resumo_ativos = []

    split_date = pd.Timestamp("2026-05-01", tz="UTC")

    for sym in SYMBOLS:
        parquet_path = Path(f"data/{sym}_M1_dukascopy.parquet")
        if not parquet_path.exists():
            print(f"⚠️ [{sym}] Arquivo {parquet_path} não encontrado!")
            continue

        print(f"📂 [{sym}] Carregando candles M1...")
        df_m1 = pd.read_parquet(parquet_path)
        spread = SPREADS[sym]

        trades = strategy.run_backtest(df_m1, symbol=sym, spread=spread)
        if not trades:
            print(f"⚠️ [{sym}] Nenhum trade gerado.")
            continue

        rows = []
        for t in trades:
            rows.append({
                "symbol": t.symbol,
                "stage": t.stage,
                "direction": t.direction,
                "entry_time": t.entry_time,
                "exit_time": t.exit_time,
                "entry_price": t.entry_price,
                "stop_loss": t.stop_loss,
                "take_profit": t.take_profit,
                "risk_points": t.risk_points,
                "pnl_points": t.pnl_points,
                "r_multiple": t.r_multiple,
                "win": t.win,
                "exit_reason": t.exit_reason
            })

        df_sym = pd.DataFrame(rows)
        all_trades_list.append(df_sym)

        # Métricas do ativo
        total_trades = len(df_sym)
        wins = df_sym[df_sym["win"] == True]
        losses = df_sym[df_sym["win"] == False]
        wr = (len(wins) / total_trades) * 100
        total_r = df_sym["r_multiple"].sum()
        exp_r = total_r / total_trades

        gross_profit = wins["r_multiple"].sum()
        gross_loss = abs(losses["r_multiple"].sum())
        pf = (gross_profit / gross_loss) if gross_loss > 0 else np.nan

        # Max Drawdown em R
        cum_r = df_sym["r_multiple"].cumsum()
        peak = cum_r.cummax()
        dd = peak - cum_r
        max_dd = dd.max()

        # In-Sample vs Out-of-Sample
        is_df = df_sym[df_sym["entry_time"] < split_date]
        oos_df = df_sym[df_sym["entry_time"] >= split_date]

        is_r = is_df["r_multiple"].sum() if len(is_df) > 0 else 0.0
        is_wr = (is_df["win"].sum() / len(is_df) * 100) if len(is_df) > 0 else 0.0

        oos_r = oos_df["r_multiple"].sum() if len(oos_df) > 0 else 0.0
        oos_wr = (oos_df["win"].sum() / len(oos_df) * 100) if len(oos_df) > 0 else 0.0

        wfe = (oos_r / is_r) if is_r > 0 else (1.0 if oos_r > 0 else 0.0)

        resumo_ativos.append({
            "Ativo": sym,
            "Total Trades": total_trades,
            "Taxa Acerto (%)": round(wr, 1),
            "Retorno Total (R)": round(total_r, 1),
            "Expectativa (R)": round(exp_r, 3),
            "Profit Factor": round(pf, 2),
            "Max Drawdown (R)": round(max_dd, 1),
            "Trades IS": len(is_df),
            "Taxa IS (%)": round(is_wr, 1),
            "Retorno IS (R)": round(is_r, 1),
            "Trades OOS": len(oos_df),
            "Taxa OOS (%)": round(oos_wr, 1),
            "Retorno OOS (R)": round(oos_r, 1),
            "WFE": round(wfe, 2)
        })

        print(f"  ✅ [{sym:6s}] Trades: {total_trades:4d} | WR: {wr:4.1f}% | Total: {total_r:+6.1f}R | IS: {is_r:+5.1f}R | OOS: {oos_r:+5.1f}R | PF: {pf:.2f} | MaxDD: -{max_dd:.1f}R")

    df_resumo = pd.DataFrame(resumo_ativos)
    df_all_trades = pd.concat(all_trades_list, ignore_index=True)
    df_all_trades.sort_values(by="entry_time", inplace=True)

    # Métricas consolidadas
    tot_trades = len(df_all_trades)
    tot_wins = (df_all_trades["win"] == True).sum()
    tot_wr = (tot_wins / tot_trades) * 100
    tot_r = df_all_trades["r_multiple"].sum()
    tot_exp = tot_r / tot_trades
    tot_gp = df_all_trades[df_all_trades["win"] == True]["r_multiple"].sum()
    tot_gl = abs(df_all_trades[df_all_trades["win"] == False]["r_multiple"].sum())
    tot_pf = tot_gp / tot_gl if tot_gl > 0 else np.nan

    cum_port = df_all_trades["r_multiple"].cumsum()
    peak_port = cum_port.cummax()
    max_dd_port = (peak_port - cum_port).max()

    tot_is = df_all_trades[df_all_trades["entry_time"] < split_date]["r_multiple"].sum()
    tot_oos = df_all_trades[df_all_trades["entry_time"] >= split_date]["r_multiple"].sum()

    print("\n" + "=" * 80)
    print("🏆 RESULTADO CONSOLIDADO DO PORTFÓLIO SMC-FIBO-OTE (M5):")
    print(f"Total de Operações: {tot_trades}")
    print(f"Taxa de Acerto Geral: {tot_wr:.1f}%")
    print(f"Retorno Total Líquido: {tot_r:+.1f} R")
    print(f"Expectativa Matemática: {tot_exp:+.3f} R / trade")
    print(f"Profit Factor: {tot_pf:.2f}")
    print(f"Max Drawdown Combinado: -{max_dd_port:.1f} R")
    print(f"In-Sample (Nov/25 - Abr/26): {tot_is:+.1f} R")
    print(f"Out-of-Sample (Mai/26 - Nov/26): {tot_oos:+.1f} R (Eficiência Walk-Forward: {tot_oos/tot_is:.2f})")
    print("=" * 80)

    # 1. Exportar para Excel de 2 Abas
    out_dir = Path("out/backtests/smc_fibo_ote_1ano")
    out_dir.mkdir(parents=True, exist_ok=True)
    excel_path = out_dir / "smc_fibo_ote_1ano_multiativo.xlsx"

    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_resumo.to_excel(writer, sheet_name="Resumo_Por_Ativo", index=False)
        # Formata colunas de trades
        df_trades_export = df_all_trades.copy()
        df_trades_export["entry_time"] = df_trades_export["entry_time"].astype(str)
        df_trades_export["exit_time"] = df_trades_export["exit_time"].astype(str)
        df_trades_export.to_excel(writer, sheet_name="Todas_Operacoes", index=False)

    print(f"\n📊 Planilha Excel oficial salva em: {excel_path}")

    # 2. Exportar Resumo TXT
    txt_path = out_dir / "resumo.txt"
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("================================================================================\n")
        f.write("RELATÓRIO DE AUDITORIA QUANTITATIVA: MODELO SMC-FIBO-OTE (M5)\n")
        f.write("Período: 01/11/2025 a 04/11/2026 (12 Meses com dados reais Dukascopy)\n")
        f.write("Regra: M5 | Perna BOS | Entrada 61.8% | Stop 79.0% | Alvo Fixo 3R\n")
        f.write("================================================================================\n\n")
        f.write(f"Total de Trades: {tot_trades}\n")
        f.write(f"Taxa de Acerto: {tot_wr:.1f}%\n")
        f.write(f"Retorno Total: {tot_r:+.1f} R\n")
        f.write(f"Expectativa: {tot_exp:+.3f} R\n")
        f.write(f"Profit Factor: {tot_pf:.2f}\n")
        f.write(f"Max Drawdown: -{max_dd_port:.1f} R\n")
        f.write(f"In-Sample: {tot_is:+.1f} R\n")
        f.write(f"Out-of-Sample: {tot_oos:+.1f} R\n\n")
        f.write("DETALHAMENTO POR ATIVO:\n")
        f.write(df_resumo.to_string(index=False))
        f.write("\n")

    print(f"📄 Resumo TXT salvo em: {txt_path}")

if __name__ == "__main__":
    main()

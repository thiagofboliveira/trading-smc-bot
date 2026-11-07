import pandas as pd
import pytest

from smc_trader.cli import main
from smc_trader.data.profit_import import import_profit_csv
from smc_trader.data.store import load_candles

HEADER = "Ativo;Data;Hora;Abertura;Máximo;Mínimo;Fechamento;Volume;Quantidade"


def _write(path, rows, header=HEADER, sep=";"):
    lines = [header] + [sep.join(r) for r in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


ROWS = [
    ["WINZ26", "03/11/2026", "09:00", "130.150,0", "130.200,0", "130.100,0", "130.180,0", "26.036.000,00", "200"],
    ["WINZ26", "03/11/2026", "09:01", "130.180,0", "130.220,0", "130.170,0", "130.210,0", "18.000.000,00", "138"],
]


def test_converte_fuso_sao_paulo_para_utc(tmp_path):
    df = import_profit_csv(_write(tmp_path / "w.csv", ROWS))
    # 09:00 em São Paulo (UTC-3, sem horário de verão) = 12:00 UTC
    assert [t.strftime("%Y-%m-%d %H:%M") for t in df.index] == ["2026-11-03 12:00", "2026-11-03 12:01"]
    assert str(df.index.tz) == "UTC"


def test_decimal_virgula_milhar_ponto_e_colunas(tmp_path):
    df = import_profit_csv(_write(tmp_path / "w.csv", ROWS))
    assert list(df.columns) == ["open", "high", "low", "close", "volume", "spread"]
    assert df["open"].iloc[0] == 130150.0
    assert df["low"].iloc[1] == 130170.0
    # volume = quantidade de contratos, não o financeiro
    assert df["volume"].iloc[0] == 200.0


def test_rotulo_pelo_fechamento_recua_um_minuto(tmp_path):
    csv = _write(tmp_path / "w.csv", ROWS)
    abre = import_profit_csv(csv, bar_label="open")
    fecha = import_profit_csv(csv, bar_label="close")
    assert (abre.index - fecha.index == pd.Timedelta(minutes=1)).all()


def test_aceita_virgula_como_separador_e_ponto_decimal(tmp_path):
    rows = [["WDOX26", "2026-11-03", "09:00:00", "5300.5", "5301.0", "5300.0", "5300.5", "100", "10"]]
    csv = _write(tmp_path / "w.csv", rows, header="Ativo,Data,Hora,Abertura,Maximo,Minimo,Fechamento,Volume,Quantidade", sep=",")
    df = import_profit_csv(csv)
    assert df["high"].iloc[0] == 5301.0


def test_remove_duplicatas_e_ordena(tmp_path):
    csv = _write(tmp_path / "w.csv", [ROWS[1], ROWS[0], ROWS[0]])
    df = import_profit_csv(csv)
    assert len(df) == 2
    assert df.index.is_monotonic_increasing


def test_coluna_faltando_da_erro_claro(tmp_path):
    csv = _write(tmp_path / "w.csv", [["x"]], header="Foo")
    with pytest.raises(ValueError, match="colunas"):
        import_profit_csv(csv)


def test_rejeita_barras_invalidas(tmp_path):
    bad = [["WINZ26", "03/11/2026", "09:00", "10,0", "9,0", "11,0", "10,0", "1,00", "1"]]  # high < low
    with pytest.raises(ValueError, match="inválid"):
        import_profit_csv(_write(tmp_path / "w.csv", bad))


def test_cli_import_csv_formato_profit(tmp_path):
    csv = _write(tmp_path / "WIN.csv", ROWS)
    code = main(["import-csv", str(csv), "--symbol", "WIN", "--format", "profit", "--data-root", str(tmp_path)])
    assert code == 0
    df = load_candles(tmp_path, "WIN", source="profit")
    assert len(df) == 2
    assert (tmp_path / "WIN_M1_profit.parquet").exists()


def test_cli_import_csv_formato_generic(tmp_path):
    csv = _write(tmp_path / "GENERIC.csv", ROWS)
    code = main(["import-csv", str(csv), "--symbol", "GENERIC", "--format", "generic", "--data-root", str(tmp_path)])
    assert code == 0
    df = load_candles(tmp_path, "GENERIC", source="generic")
    assert len(df) == 2
    assert (tmp_path / "GENERIC_M1_generic.parquet").exists()

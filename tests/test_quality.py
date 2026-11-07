import numpy as np
import pandas as pd

from smc_trader.cli import main
from smc_trader.data.quality import check_quality
from smc_trader.data.store import save_m1


def _series(start="2024-06-03 00:00", periods=600, freq="1min", seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range(start, periods=periods, freq=freq, tz="UTC", name="time")
    close = 100 + np.cumsum(rng.normal(0, 0.02, periods))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + 0.01
    low = np.minimum(open_, close) - 0.01
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": 1.0, "spread": 0.0}, index=idx
    )


def test_serie_limpa_passa():
    rep = check_quality(_series(), "X")
    assert rep.ok
    assert rep.errors == [] and rep.warnings == []
    assert rep.n_bars == 600


def test_barra_invalida_e_erro():
    df = _series()
    df.iloc[10, df.columns.get_loc("high")] = df["low"].iloc[10] - 1.0
    rep = check_quality(df, "X")
    assert not rep.ok
    assert rep.invalid_bars == 1
    assert any("inválid" in e for e in rep.errors)


def test_preco_nao_positivo_e_erro():
    df = _series()
    df.iloc[5, df.columns.get_loc("low")] = 0.0
    assert not check_quality(df, "X").ok


def test_indice_duplicado_e_fora_de_ordem_sao_erros():
    df = _series()
    dup = pd.concat([df, df.iloc[[3]]])
    assert any("duplic" in e for e in check_quality(dup, "X").errors)
    shuffled = df.iloc[::-1]
    assert any("ordem" in e for e in check_quality(shuffled, "X").errors)


def test_buraco_no_meio_do_dia_e_aviso():
    df = _series()
    df = df.drop(df.index[200:300])  # 100 min sem dados
    rep = check_quality(df, "X", max_gap_minutes=60)
    assert rep.ok  # buraco não invalida, mas precisa aparecer
    assert len(rep.gaps) == 1
    assert rep.gaps[0][2] == 101  # minutos entre a última barra antes e a primeira depois
    assert any("buraco" in w for w in rep.warnings)


def test_fim_de_semana_nao_conta_como_buraco():
    sex = _series("2024-06-07 21:00", periods=60)   # sexta
    seg = _series("2024-06-09 22:00", periods=60, seed=1)  # domingo à noite
    rep = check_quality(pd.concat([sex, seg]), "X", max_gap_minutes=60)
    assert rep.gaps == []


def test_pico_de_preco_e_aviso_mas_gap_de_abertura_nao():
    df = _series(periods=1000)
    df.iloc[500:, df.columns.difference(["volume", "spread"]).map(df.columns.get_loc)] *= 1.10  # salto de 10%, 1 barra
    # o salto persiste (nível novo): é só 1 retorno anômalo
    rep = check_quality(df, "X")
    assert rep.spikes == 1
    assert any("pico" in w for w in rep.warnings)


def test_horario_fora_da_sessao_esperada_e_erro_de_fuso():
    df = _series("2024-06-03 12:00", periods=600)  # 12:00 a 21:59 UTC
    assert check_quality(df, "WIN", expected_hours=set(range(12, 22))).ok
    deslocado = df.copy()
    deslocado.index = deslocado.index + pd.Timedelta(hours=3)  # fuso errado
    rep = check_quality(deslocado, "WIN", expected_hours=set(range(12, 22)))
    assert not rep.ok
    assert any("fuso" in e for e in rep.errors)


def test_cli_check_data(tmp_path, capsys):
    save_m1(tmp_path, "XAUUSD", _series())
    assert main(["check-data", "XAUUSD", "--data-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "XAUUSD" in out and "600" in out


def test_cli_check_data_falha_com_dado_ruim(tmp_path):
    df = _series()
    df.iloc[10, df.columns.get_loc("high")] = df["low"].iloc[10] - 1.0
    save_m1(tmp_path, "XAUUSD", df)
    assert main(["check-data", "XAUUSD", "--data-root", str(tmp_path)]) == 1


def test_cli_check_data_all(tmp_path, capsys):
    save_m1(tmp_path, "XAUUSD", _series())
    save_m1(tmp_path, "EURUSD", _series(seed=2))
    assert main(["check-data", "all", "--data-root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "XAUUSD" in out and "EURUSD" in out


def test_cli_check_data_sem_arquivo(tmp_path, capsys):
    assert main(["check-data", "FOO", "--data-root", str(tmp_path)]) == 2


def test_pausa_diaria_recorrente_nao_vira_aviso_mas_buraco_incomum_sim():
    dias = []
    for i in range(30):  # 30 dias úteis seguidos, pausa de ~61 min às 20:00 UTC todo dia
        d = pd.Timestamp("2024-06-03", tz="UTC") + pd.Timedelta(days=i)
        if d.weekday() >= 5:
            continue
        a = _series(d.strftime("%Y-%m-%d 00:00"), periods=20 * 60, seed=i)         # 00:00-19:59
        b = _series(d.strftime("%Y-%m-%d 21:01"), periods=2 * 60 + 58, seed=i + 99)  # 21:01-23:58
        dias += [a, b]
    df = pd.concat(dias)
    rep = check_quality(df, "X", max_gap_minutes=60)
    assert rep.daily_breaks >= 20
    assert rep.gaps == []
    # um buraco de 3h em outro horário continua aparecendo
    anormal = df.drop(df.loc["2024-06-12 10:00":"2024-06-12 12:59"].index)
    rep2 = check_quality(anormal, "X", max_gap_minutes=60)
    assert len(rep2.gaps) == 1 and rep2.gaps[0][0].hour == 9

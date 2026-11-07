from datetime import datetime, timezone

import pandas as pd

from smc_trader.cli import main
from smc_trader.data.history import fetch_history, years_back_start
from smc_trader.data.store import existing_months, load_candles, save_m1

UTC = timezone.utc
COLS = ["open", "high", "low", "close", "volume", "spread"]


def _frame(start: datetime, n: int = 3) -> pd.DataFrame:
    idx = pd.date_range(start, periods=n, freq="1min", tz="UTC", name="time")
    return pd.DataFrame({"open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0, "spread": 0.0}, index=idx)


class Recorder:
    def __init__(self, fail: dict[str, int] | None = None):
        self.calls: list[tuple[datetime, datetime]] = []
        self.fail = dict(fail or {})

    def __call__(self, instrument, start, end, offer_side):
        label = start.strftime("%Y-%m")
        self.calls.append((start, end))
        if self.fail.get(label, 0) > 0:
            self.fail[label] -= 1
            raise ConnectionError("timeout")
        return _frame(start)


def _run(tmp_path, fetcher, start, end, **kw):
    return fetch_history(
        "XAUUSD", "XAU/USD", start, end, "bid", tmp_path,
        fetcher=fetcher, sleep=lambda s: None, log=lambda m: None, **kw,
    )


def test_baixa_mes_a_mes_e_grava_tudo(tmp_path):
    rec = Recorder()
    res = _run(tmp_path, rec, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 4, 1, tzinfo=UTC))
    assert [c[0].strftime("%Y-%m") for c in rec.calls] == ["2024-01", "2024-02", "2024-03"]
    assert res.failed_months == []
    assert existing_months(tmp_path, "XAUUSD") == {"2024-01", "2024-02", "2024-03"}


def test_retoma_pulando_meses_completos_e_refaz_o_ultimo(tmp_path):
    for m in (1, 2, 3):
        save_m1(tmp_path, "XAUUSD", _frame(datetime(2024, m, 10, tzinfo=UTC)))
    rec = Recorder()
    res = _run(tmp_path, rec, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 5, 1, tzinfo=UTC))
    # jan e fev estão completos; mar é o último presente (pode estar parcial); abr nunca baixou
    assert [c[0].strftime("%Y-%m") for c in rec.calls] == ["2024-03", "2024-04"]
    assert res.skipped_months == ["2024-01", "2024-02"]


def test_repete_em_caso_de_falha_e_tem_sucesso(tmp_path):
    rec = Recorder(fail={"2024-02": 2})
    res = _run(tmp_path, rec, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 3, 1, tzinfo=UTC), retries=3)
    assert res.failed_months == []
    assert "2024-02" in existing_months(tmp_path, "XAUUSD")


def test_mes_que_sempre_falha_e_reportado_e_nao_derruba_os_outros(tmp_path):
    rec = Recorder(fail={"2024-02": 99})
    res = _run(tmp_path, rec, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 4, 1, tzinfo=UTC), retries=2)
    assert res.failed_months == ["2024-02"]
    assert existing_months(tmp_path, "XAUUSD") == {"2024-01", "2024-03"}


def test_mes_vazio_nao_e_falha(tmp_path):
    def vazio(instrument, start, end, offer_side):
        return _frame(start, n=0)

    res = _run(tmp_path, vazio, datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 2, 1, tzinfo=UTC))
    assert res.failed_months == []
    assert res.empty_months == ["2024-01"]


def test_years_back_start_alinha_no_primeiro_dia_do_mes():
    assert years_back_start(datetime(2026, 11, 7, tzinfo=UTC), 5) == datetime(2021, 11, 1, tzinfo=UTC)
    assert years_back_start(datetime(2024, 2, 29, tzinfo=UTC), 1) == datetime(2023, 2, 1, tzinfo=UTC)


def test_cli_fetch_years(tmp_path, monkeypatch):
    rec = Recorder()
    monkeypatch.setattr("smc_trader.cli.fetch_m1", rec)
    rc = main(["fetch", "XAUUSD", "--years", "1", "--to", "2024-04-15", "--data-root", str(tmp_path)])
    assert rc == 0
    labels = [c[0].strftime("%Y-%m") for c in rec.calls]
    assert labels[0] == "2023-04" and labels[-1] == "2024-04" and len(labels) == 13
    assert len(load_candles(tmp_path, "XAUUSD", source="dukascopy")) == 3 * 13


def test_cli_fetch_exige_from_ou_years(tmp_path, capsys):
    rc = main(["fetch", "XAUUSD", "--data-root", str(tmp_path)])
    assert rc == 2
    assert "--years" in capsys.readouterr().err


def test_cli_fetch_retorna_1_se_algum_mes_falhar(tmp_path, monkeypatch):
    rec = Recorder(fail={"2024-02": 99})
    monkeypatch.setattr("smc_trader.cli.fetch_m1", rec)
    monkeypatch.setattr("smc_trader.data.history.time.sleep", lambda s: None)
    rc = main(["fetch", "XAUUSD", "--years", "1", "--to", "2024-03-10", "--data-root", str(tmp_path)])
    assert rc == 1

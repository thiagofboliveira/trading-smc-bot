import pandas as pd

from smc_trader.cli import main
from smc_trader.data.store import load_candles


def _fake_factory(calls):
    def fake(instrument, start, end, offer_side):
        calls.append((instrument, start, end, offer_side))
        idx = pd.date_range("2024-06-03", periods=3, freq="1min", tz="UTC", name="time")
        return pd.DataFrame(
            {
                "open": [1.0, 2.0, 3.0],
                "high": [1.5, 2.5, 3.5],
                "low": [0.5, 1.5, 2.5],
                "close": [1.2, 2.2, 3.2],
                "volume": [1.0, 1.0, 1.0],
                "spread": 0.0,
            },
            index=idx,
        )

    return fake


def test_cli_fetch_saves_m1(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("smc_trader.cli.fetch_m1", _fake_factory(calls))
    rc = main(
        ["fetch", "XAUUSD", "--from", "2024-06-03", "--to", "2024-06-04",
         "--data-root", str(tmp_path)]
    )
    assert rc == 0
    assert calls[0][0] == "XAU/USD"
    assert calls[0][1].utcoffset().total_seconds() == 0
    out = load_candles(tmp_path, "XAUUSD")
    assert len(out) == 3
    assert out["close"].tolist() == [1.2, 2.2, 3.2]


def test_cli_fetch_unknown_symbol(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr("smc_trader.cli.fetch_m1", _fake_factory(calls))
    rc = main(
        ["fetch", "FOO", "--from", "2024-06-03", "--to", "2024-06-04",
         "--data-root", str(tmp_path)]
    )
    assert rc == 2
    assert "FOO" in capsys.readouterr().err
    assert calls == []
    assert list(tmp_path.iterdir()) == []

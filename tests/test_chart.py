import plotly.graph_objects as go
from helpers import BREAKER_TAIL, EXTRA_ROWS, SERIE_A_ROWS, candles_from_ohlc, random_walk_candles

from smc_trader.analysis import analyze
from smc_trader.cli import main
from smc_trader.config import ZoneConfig
from smc_trader.data.store import save_m1
from smc_trader.viz.chart import build_chart


def test_build_chart_counts():
    c = candles_from_ohlc(SERIE_A_ROWS[0:6] + EXTRA_ROWS)
    a = analyze(c, 1, ZoneConfig())
    fig = build_chart(c, a, "teste")
    assert sum(isinstance(t, go.Candlestick) for t in fig.data) == 1
    assert len(fig.layout.shapes) == len(a.fvgs) + len(a.zones)
    assert len(fig.layout.annotations) >= len(a.events)


def test_breaker_rectangles_are_dashed():
    c = candles_from_ohlc(SERIE_A_ROWS[0:6] + BREAKER_TAIL)
    a = analyze(c, 1, ZoneConfig())
    assert len(a.breakers) == 1
    fig = build_chart(c, a, "teste")
    assert len(fig.layout.shapes) == len(a.fvgs) + len(a.zones) + len(a.breakers)
    assert sum(s.line.dash == "dash" for s in fig.layout.shapes) == 1
    assert any(x.text.startswith("BB") for x in fig.layout.annotations)


def test_chart_without_breakers_unchanged():
    c = candles_from_ohlc(SERIE_A_ROWS[0:6] + EXTRA_ROWS)
    a = analyze(c, 1, ZoneConfig())
    fig = build_chart(c, a, "teste")
    assert len(fig.layout.shapes) == len(a.fvgs) + len(a.zones)
    assert not any(s.line.dash == "dash" for s in fig.layout.shapes)


def test_cli_chart_writes_html(tmp_path):
    m1 = random_walk_candles(3 * 1440, seed=3, tf="M1").drop(columns="close_time")
    m1["spread"] = 0.0
    save_m1(tmp_path, "XAUUSD", m1)
    out = tmp_path / "sub" / "c.html"
    rc = main(["chart", "XAUUSD", "--data-root", str(tmp_path), "--out", str(out)])
    assert rc == 0
    assert "plotly" in out.read_text(encoding="utf-8")


def test_cli_chart_missing_data(tmp_path, capsys):
    rc = main(["chart", "XAUUSD", "--data-root", str(tmp_path), "--out", str(tmp_path / "c.html")])
    assert rc == 2
    assert "XAUUSD" in capsys.readouterr().err


def test_cli_chart_source_mt5(tmp_path, capsys):
    m1 = random_walk_candles(3 * 1440, seed=3, tf="M1").drop(columns="close_time")
    m1["spread"] = 0.0
    save_m1(tmp_path, "XAUUSD", m1, source="mt5")
    out = tmp_path / "c.html"
    base = ["chart", "XAUUSD", "--data-root", str(tmp_path), "--out", str(out)]
    assert main(base) == 2
    assert "dukascopy" in capsys.readouterr().err
    assert main(base + ["--source", "mt5"]) == 0
    assert out.exists()


def _spy_analyze(monkeypatch):
    import smc_trader.cli as cli

    seen = []
    original = cli.analyze

    def wrapper(candles, k, zones_cfg):
        seen.append(zones_cfg)
        return original(candles, k, zones_cfg)

    monkeypatch.setattr(cli, "analyze", wrapper)
    return seen


def _save_synthetic(tmp_path):
    m1 = random_walk_candles(3 * 1440, seed=3, tf="M1").drop(columns="close_time")
    m1["spread"] = 0.0
    save_m1(tmp_path, "XAUUSD", m1)


def test_cli_chart_blocks_option_overrides_filter(tmp_path, monkeypatch):
    _save_synthetic(tmp_path)
    seen = _spy_analyze(monkeypatch)
    out = tmp_path / "c.html"
    rc = main(
        ["chart", "XAUUSD", "--data-root", str(tmp_path), "--out", str(out), "--blocks", "fvob,bb"]
    )
    assert rc == 0
    assert seen[0].blocks_filter == ["FVOB", "BB"]


def test_cli_chart_blocks_invalid(tmp_path, capsys):
    _save_synthetic(tmp_path)
    out = tmp_path / "c.html"
    for bad in ("XX", ""):
        rc = main(
            ["chart", "XAUUSD", "--data-root", str(tmp_path), "--out", str(out), "--blocks", bad]
        )
        assert rc == 2
        assert "--blocks" in capsys.readouterr().err
        assert not out.exists()


def test_cli_chart_without_blocks_uses_config(tmp_path, monkeypatch):
    _save_synthetic(tmp_path)
    seen = _spy_analyze(monkeypatch)
    out = tmp_path / "c.html"
    rc = main(["chart", "XAUUSD", "--data-root", str(tmp_path), "--out", str(out)])
    assert rc == 0
    assert seen[0].blocks_filter == ["OB", "FVOB", "BB"]

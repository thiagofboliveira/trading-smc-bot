import pandas as pd

from smc_trader.cli import main
from smc_trader.data.store import load_candles


def test_cli_import_csv(tmp_path):
    csv = tmp_path / "XAUUSD_M1.csv"
    times = pd.date_range("2024-01-15 12:00", periods=3, freq="min", tz="UTC")
    lines = ["time,open,high,low,close,tick_volume,spread,real_volume"]
    for i, t in enumerate(times):
        lines.append(f"{int(t.timestamp())},1.0,2.0,0.5,{1.0 + i},10,3,0")
    csv.write_text("\n".join(lines) + "\n")
    code = main(["import-csv", str(csv), "--symbol", "XAUUSD", "--data-root", str(tmp_path)])
    assert code == 0
    df = load_candles(tmp_path, "XAUUSD", source="mt5")
    assert len(df) == 3
    assert list(df["close"]) == [1.0, 2.0, 3.0]
    assert (tmp_path / "XAUUSD_M1_mt5.parquet").exists()
    assert not (tmp_path / "XAUUSD_M1_dukascopy.parquet").exists()

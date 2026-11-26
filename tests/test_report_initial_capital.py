"""report.py initial-capital resolution.

A trades CSV outside a run folder (no config_snapshot.json) used to be
analysed at the analyzer default ($50,000) with no warning, so a trade log
from a $1M backtest reported roughly double its true CAGR. Precedence now:

    --equity  >  config_snapshot.json initial_capital
              >  first point of the companion <stem>_equity.csv
              >  INITIAL_EQUITY default, with a WARNING

No network; the analyzer is stubbed and only the config it receives is checked.
"""

import json
import sys

import pandas as pd
import pytest

import report as report_cli
from trade_analyzer.default_config import INITIAL_EQUITY

CURVE_START = 1_000_000.0
SNAPSHOT_CAPITAL = 250_000.0


def _write_trades(folder, stem="Strat", curve=True, curve_values=None):
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([{
        "Symbol": "AAA", "Date": "2015-01-05", "Price": 100.0,
        "Ex. date": "2020-01-06", "Ex. Price": 150.0, "Profit": 500_000.0,
        "% Profit": 50.0, "Shares": 10_000,
    }]).to_csv(folder / f"{stem}.csv", index=False)
    if curve:
        values = curve_values if curve_values is not None else [CURVE_START, 1_500_000.0]
        idx = pd.to_datetime(["2015-01-02", "2020-01-06"][:len(values)])
        pd.Series(values, index=idx, name="Equity").rename_axis("Date").to_csv(
            folder / f"{stem}_equity.csv")
    return folder / f"{stem}.csv"


def _write_run(tmp_path, snapshot=True, curve=True):
    run_dir = tmp_path / "run"
    csv_path = _write_trades(run_dir / "analyzer_csvs" / "Port", curve=curve)
    if snapshot:
        (run_dir / "config_snapshot.json").write_text(
            json.dumps({"initial_capital": SNAPSHOT_CAPITAL}))
    return run_dir, csv_path


def _run(monkeypatch, argv):
    captured = []
    monkeypatch.setattr(report_cli, "generate_trade_report",
                        lambda df, out, name, cfg: captured.append(cfg))
    monkeypatch.setattr(sys, "argv", ["report.py", *argv])
    report_cli.main()
    return [cfg["INITIAL_EQUITY"] for cfg in captured]


class TestSingleFilePrecedence:
    def test_equity_flag_wins_over_everything(self, tmp_path, monkeypatch, capsys):
        _, csv_path = _write_run(tmp_path)
        assert _run(monkeypatch, [str(csv_path), "--equity", "123456"]) == [123456.0]
        assert "WARNING: no initial capital" not in capsys.readouterr().out

    def test_snapshot_wins_over_equity_curve(self, tmp_path, monkeypatch, capsys):
        _, csv_path = _write_run(tmp_path)
        assert _run(monkeypatch, [str(csv_path)]) == [SNAPSHOT_CAPITAL]
        out = capsys.readouterr().out
        assert "loaded from config_snapshot.json" in out
        assert "inferred from the first point" not in out
        assert "WARNING: no initial capital" not in out

    def test_loose_csv_uses_equity_curve_first_point(self, tmp_path, monkeypatch, capsys):
        csv_path = _write_trades(tmp_path / "loose")
        assert _run(monkeypatch, [str(csv_path)]) == [CURVE_START]
        out = capsys.readouterr().out
        assert "inferred from the first point of Strat_equity.csv" in out
        assert "WARNING: no initial capital" not in out

    def test_run_without_snapshot_uses_equity_curve(self, tmp_path, monkeypatch):
        _, csv_path = _write_run(tmp_path, snapshot=False)
        assert _run(monkeypatch, [str(csv_path)]) == [CURVE_START]

    def test_loose_csv_without_curve_warns_and_uses_default(self, tmp_path, monkeypatch, capsys):
        csv_path = _write_trades(tmp_path / "loose", curve=False)
        assert _run(monkeypatch, [str(csv_path)]) == [INITIAL_EQUITY]
        out = capsys.readouterr().out
        assert "WARNING: no initial capital found" in out
        assert f"${INITIAL_EQUITY:,.0f}" in out
        assert "--equity" in out

    def test_equity_flag_suppresses_warning(self, tmp_path, monkeypatch, capsys):
        csv_path = _write_trades(tmp_path / "loose", curve=False)
        assert _run(monkeypatch, [str(csv_path), "--equity", "1000000"]) == [1_000_000.0]
        assert "WARNING" not in capsys.readouterr().out

    def test_unusable_curve_start_falls_back_with_warning(self, tmp_path, monkeypatch, capsys):
        csv_path = _write_trades(tmp_path / "loose", curve_values=[0.0, 10.0])
        assert _run(monkeypatch, [str(csv_path)]) == [INITIAL_EQUITY]
        assert "WARNING: no initial capital found" in capsys.readouterr().out


class TestBatchPrecedence:
    def test_snapshot_used_in_batch(self, tmp_path, monkeypatch, capsys):
        run_dir, _ = _write_run(tmp_path)
        assert _run(monkeypatch, ["--all", str(run_dir)]) == [SNAPSHOT_CAPITAL]
        assert "inferred from the first point" not in capsys.readouterr().out

    def test_batch_without_snapshot_uses_each_curve(self, tmp_path, monkeypatch):
        run_dir, _ = _write_run(tmp_path, snapshot=False)
        _write_trades(run_dir / "analyzer_csvs" / "Port", stem="Other",
                      curve_values=[2_000_000.0, 2_100_000.0])
        assert sorted(_run(monkeypatch, ["--all", str(run_dir)])) == [CURVE_START, 2_000_000.0]

    def test_batch_without_snapshot_or_curve_warns(self, tmp_path, monkeypatch, capsys):
        run_dir, _ = _write_run(tmp_path, snapshot=False, curve=False)
        assert _run(monkeypatch, ["--all", str(run_dir)]) == [INITIAL_EQUITY]
        assert "WARNING: no initial capital found" in capsys.readouterr().out

    def test_batch_equity_flag_wins(self, tmp_path, monkeypatch):
        run_dir, _ = _write_run(tmp_path, snapshot=False)
        assert _run(monkeypatch, ["--all", str(run_dir), "--equity", "75000"]) == [75_000.0]


class TestFallbackHelper:
    def test_leading_nan_is_skipped(self, tmp_path):
        s = pd.Series([float("nan"), 500_000.0], index=pd.to_datetime(["2020-01-01", "2020-01-02"]))
        assert report_cli._fallback_initial_capital(s, tmp_path / "x_equity.csv") == pytest.approx(500_000.0)

    def test_none_timeline_returns_none(self, tmp_path, capsys):
        assert report_cli._fallback_initial_capital(None, tmp_path / "x_equity.csv") is None
        assert "WARNING" in capsys.readouterr().out

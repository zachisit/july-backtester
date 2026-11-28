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
                      curve_values=[2_000_000.0, 2_600_000.0])
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



class TestCurveScaleGuard:
    """A normalised curve (starting at 1.0 or 100) is not a dollar capital.

    The check compares the curve's total change with the trades' total Profit,
    which holds for compounding strategies and for rotation logs whose lots
    keep their first EntryDate while top-ups are averaged in.
    """

    @staticmethod
    def _trades(profits, prices=None, shares=None, dates=None):
        n = len(profits)
        return pd.DataFrame({
            "Symbol": [f"S{i}" for i in range(n)],
            "EntryDate": dates or ["2015-01-05"] * n,
            "EntryPrice": prices or [100.0] * n,
            "Shares": shares or [1_000] * n,
            "Profit": profits,
        })

    @staticmethod
    def _curve(*values):
        idx = pd.date_range("2015-01-02", periods=len(values), freq="365D")
        return pd.Series(values, index=idx)

    def _fallback(self, tmp_path, curve, trades):
        return report_cli._fallback_initial_capital(curve, tmp_path / "x_equity.csv", trades)

    def test_normalised_curve_falls_back_with_warning(self, tmp_path, capsys):
        trades = self._trades([30_000.0, 20_000.0])
        assert self._fallback(tmp_path, self._curve(1.0, 1.5), trades) is None
        out = capsys.readouterr().out
        assert "could not verify starting capital from x_equity.csv" in out
        assert "WARNING: no initial capital found" in out

    def test_curve_starting_at_100_is_rejected(self, tmp_path):
        trades = self._trades([30_000.0, 20_000.0])
        assert self._fallback(tmp_path, self._curve(100.0, 150.0), trades) is None

    def test_normalised_curve_with_breakeven_trades_is_rejected(self, tmp_path):
        # Net profit near zero must not let a normalised curve through.
        trades = self._trades([40_000.0, -39_500.0])
        assert self._fallback(tmp_path, self._curve(1.0, 1.005), trades) is None

    def test_compounding_rotation_log_keeps_real_curve(self, tmp_path):
        # $1M start growing ~58x; a lot dated on day one carries later top-ups
        # at an average cost, so its price x shares far exceeds the start.
        trades = self._trades([57_000_000.0, 557_736.3],
                              prices=[67.32, 24.7], shares=[45_641.4, 191.6],
                              dates=["2006-07-03", "2006-07-03"])
        curve = self._curve(1_000_000.0, 30_000_000.0, 58_670_000.0)
        assert self._fallback(tmp_path, curve, trades) == pytest.approx(1_000_000.0)

    def test_realised_only_log_keeps_curve(self, tmp_path):
        # Open positions excluded from the log: curve change > realised profit.
        trades = self._trades([40_000.0])
        assert self._fallback(tmp_path, self._curve(100_000.0, 160_000.0), trades) == pytest.approx(100_000.0)

    def test_small_move_realised_only_log_is_unverified(self, tmp_path, capsys):
        # +20% curve, +8% realised: within the slack a normalised 100 -> 120
        # curve with $8 of Profit would reconcile the same way, so the scale
        # can't be verified (W1).
        trades = self._trades([8_000.0])
        assert self._fallback(tmp_path, self._curve(100_000.0, 120_000.0), trades) is None
        assert "could not verify starting capital" in capsys.readouterr().out

    def test_losing_dollar_curve_is_kept(self, tmp_path):
        trades = self._trades([-30_000.0, -10_000.0])
        assert self._fallback(tmp_path, self._curve(100_000.0, 60_000.0), trades) == pytest.approx(100_000.0)

    def test_missing_profit_column_keeps_curve(self, tmp_path):
        trades = pd.DataFrame([{"Symbol": "AAA", "EntryPrice": 100.0, "Shares": 10}])
        assert self._fallback(tmp_path, self._curve(1.0, 1.5), trades) == pytest.approx(1.0)

    def test_end_to_end_normalised_curve_uses_default(self, tmp_path, monkeypatch, capsys):
        csv_path = _write_trades(tmp_path / "loose", curve_values=[1.0, 1.5])
        assert _run(monkeypatch, [str(csv_path)]) == [INITIAL_EQUITY]
        assert "could not verify starting capital from Strat_equity.csv" in capsys.readouterr().out


class TestBreakEvenCurveIsInconclusive:
    """W1 (#506 review): with break-even trades, any scale of curve reconciles.

    +$10,000 and -$10,000 trades net to zero, so a $100,000 -> $110,000 ->
    $100,000 curve and a 1.00 -> 1.10 -> 1.00 one both match. The check can't
    tell the scale, so the curve must not be used as capital.
    """

    TRADES = pd.DataFrame({"Symbol": ["AAA", "BBB"], "Profit": [10_000.0, -10_000.0]})

    @staticmethod
    def _curve(*values):
        return pd.Series(values, index=pd.date_range("2020-01-02", periods=len(values), freq="D"))

    def _fallback(self, tmp_path, *values):
        return report_cli._fallback_initial_capital(
            self._curve(*values), tmp_path / "x_equity.csv", self.TRADES)

    def test_normalised_break_even_curve_is_not_taken_as_one_dollar(self, tmp_path, capsys):
        assert self._fallback(tmp_path, 1.00, 1.10, 1.00) is None
        out = capsys.readouterr().out
        assert "could not verify starting capital from x_equity.csv" in out
        assert "--equity" in out
        assert "WARNING: no initial capital found" in out

    def test_base_100_break_even_curve_is_not_taken_as_100_dollars(self, tmp_path):
        assert self._fallback(tmp_path, 100.0, 110.0, 100.0) is None

    def test_dollar_break_even_curve_is_also_unverified(self, tmp_path):
        # Same numbers in dollars: indistinguishable from the normalised one.
        assert self._fallback(tmp_path, 100_000.0, 110_000.0, 100_000.0) is None

    def test_end_to_end_break_even_normalised_curve_uses_default(self, tmp_path, monkeypatch, capsys):
        folder = tmp_path / "loose"
        folder.mkdir()
        pd.DataFrame([
            {"Symbol": "AAA", "Date": "2020-01-02", "Price": 100.0, "Ex. date": "2020-01-03",
             "Ex. Price": 110.0, "Profit": 10_000.0, "% Profit": 10.0, "Shares": 1_000},
            {"Symbol": "BBB", "Date": "2020-01-03", "Price": 100.0, "Ex. date": "2020-01-06",
             "Ex. Price": 90.0, "Profit": -10_000.0, "% Profit": -10.0, "Shares": 1_000},
        ]).to_csv(folder / "Strat.csv", index=False)
        self._curve(1.00, 1.10, 1.00).rename("Equity").rename_axis("Date").to_csv(
            folder / "Strat_equity.csv")
        assert _run(monkeypatch, [str(folder / "Strat.csv")]) == [INITIAL_EQUITY]
        assert "could not verify starting capital" in capsys.readouterr().out

    def test_moved_dollar_curve_still_reconciles(self, tmp_path):
        # A real move well beyond the slack is still verified.
        trades = pd.DataFrame({"Symbol": ["AAA"], "Profit": [60_000.0]})
        curve = self._curve(100_000.0, 130_000.0, 160_000.0)
        assert report_cli._fallback_initial_capital(
            curve, tmp_path / "x_equity.csv", trades) == pytest.approx(100_000.0)


class TestMismatchWarningWording:
    """W2 (#506 review): a mismatch doesn't prove the curve is normalised.

    A $100,000 account that fell to $40,000 on an open loss, with a closed-
    trade log of zero Profit, is a genuine dollar curve. Falling back is
    fine; the warning must say capital is unverified and why it may differ.
    """

    def test_open_loss_curve_warns_unverified_not_normalised(self, tmp_path, capsys):
        trades = pd.DataFrame({"Symbol": ["AAA"], "Profit": [0.0]})
        curve = pd.Series([100_000.0, 70_000.0, 40_000.0],
                          index=pd.date_range("2020-01-02", periods=3, freq="D"))
        assert report_cli._fallback_initial_capital(curve, tmp_path / "x_equity.csv", trades) is None
        out = capsys.readouterr().out
        assert "could not verify starting capital from x_equity.csv" in out
        assert "open-position P&L" in out
        assert "--equity" in out
        assert "not in dollars" not in out

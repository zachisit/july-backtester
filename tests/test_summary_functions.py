"""
Tests for helpers/summary.py — focuses on the pure/testable business logic.

Avoids testing the voluminous print-to-stdout display paths (slop territory).
Targets instead:
  - format_duration: pure helper
  - save_trades_to_csv: file creation and S3 toggle
  - generate_sensitivity_report: fragility classification logic
  - Guard conditions (empty inputs) in the larger report functions
"""

import os
import sys
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.summary import (
    format_duration,
    save_trades_to_csv,
    generate_sensitivity_report,
    generate_per_portfolio_summary,
    generate_portfolio_summary_report,
    generate_final_summary,
    generate_single_asset_summary_report,
)


# ---------------------------------------------------------------------------
# format_duration — pure helper
# ---------------------------------------------------------------------------

class TestFormatDuration:

    def test_none_returns_na(self):
        assert format_duration(None) == "N/A"

    def test_zero_seconds(self):
        result = format_duration(0)
        assert "0 minutes" in result
        assert "0.00 seconds" in result

    def test_exact_one_minute(self):
        result = format_duration(60)
        assert "1 minutes" in result

    def test_mixed_minutes_and_seconds(self):
        result = format_duration(125)
        assert "2 minutes" in result
        assert "5.00 seconds" in result

    def test_sub_minute_only_shows_zero_minutes(self):
        result = format_duration(45)
        assert "0 minutes" in result
        assert "45.00 seconds" in result


# ---------------------------------------------------------------------------
# save_trades_to_csv
# ---------------------------------------------------------------------------

class TestSaveTradesToCsv:

    def _make_result(self, strategy="My Strategy", has_trades=True, portfolio="NAS100"):
        result = {
            "Strategy": strategy,
            "Portfolio": portfolio,
            "Asset": "AAPL",
            "Trades": 5 if has_trades else 0,
            "trade_log": [
                {"EntryDate": "2021-01-04", "Profit": 100},
                {"EntryDate": "2021-01-07", "Profit": -50},
            ] if has_trades else [],
        }
        return result

    def test_creates_csv_file(self, tmp_path):
        result = self._make_result()
        with patch("helpers.summary.CONFIG", {"upload_to_s3": False, "s3_reports_bucket": None}):
            save_trades_to_csv(result, str(tmp_path), "run-001")
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].suffix == ".csv"

    def test_no_trades_skips_save(self, tmp_path):
        result = self._make_result(has_trades=False)
        with patch("helpers.summary.CONFIG", {"upload_to_s3": False}):
            save_trades_to_csv(result, str(tmp_path), "run-001")
        assert list(tmp_path.iterdir()) == []

    def test_zero_trades_count_skips_save(self, tmp_path):
        result = self._make_result()
        result["Trades"] = 0
        with patch("helpers.summary.CONFIG", {"upload_to_s3": False}):
            save_trades_to_csv(result, str(tmp_path), "run-001")
        assert list(tmp_path.iterdir()) == []

    def test_s3_upload_called_when_enabled(self, tmp_path):
        result = self._make_result()
        with patch("helpers.summary.CONFIG", {"upload_to_s3": True, "s3_reports_bucket": "my-bucket"}):
            with patch("helpers.summary.upload_file_to_s3") as mock_upload:
                save_trades_to_csv(result, str(tmp_path), "run-001")
                mock_upload.assert_called_once()

    def test_s3_upload_not_called_when_disabled(self, tmp_path):
        result = self._make_result()
        with patch("helpers.summary.CONFIG", {"upload_to_s3": False, "s3_reports_bucket": None}):
            with patch("helpers.summary.upload_file_to_s3") as mock_upload:
                save_trades_to_csv(result, str(tmp_path), "run-001")
                mock_upload.assert_not_called()

    def test_csv_contains_correct_data(self, tmp_path):
        result = self._make_result()
        with patch("helpers.summary.CONFIG", {"upload_to_s3": False}):
            save_trades_to_csv(result, str(tmp_path), "run-001")
        files = list(tmp_path.iterdir())
        df = pd.read_csv(str(files[0]))
        assert "Profit" in df.columns
        assert len(df) == 2

    def test_strategy_name_sanitized_in_filename(self, tmp_path):
        result = self._make_result(strategy="SMA (20/50): Test/Strategy")
        with patch("helpers.summary.CONFIG", {"upload_to_s3": False}):
            save_trades_to_csv(result, str(tmp_path), "run-001")
        files = list(tmp_path.iterdir())
        # Colons, parens, slashes should not appear in the filename
        fname = files[0].name
        assert ":" not in fname
        assert "/" not in fname
        assert "(" not in fname


# ---------------------------------------------------------------------------
# generate_sensitivity_report — fragility classification
# ---------------------------------------------------------------------------

def _make_result_dict(strategy_name, pnl_pct=0.10, sharpe=1.0, max_dd=0.20, mc_score=3):
    return {
        "Strategy": strategy_name,
        "pnl_percent": pnl_pct,
        "sharpe_ratio": sharpe,
        "max_drawdown": max_dd,
        "mc_score": mc_score,
    }


class TestGenerateSensitivityReport:

    def test_disabled_sweep_returns_early(self, capsys):
        # generate_sensitivity_report imports CONFIG locally, so patch.dict is needed
        with patch.dict("config.CONFIG", {"sensitivity_sweep_enabled": False}):
            generate_sensitivity_report([_make_result_dict("SMA")], "run-001")
        captured = capsys.readouterr()
        assert "SENSITIVITY" not in captured.out

    def test_empty_results_returns_early(self, capsys):
        with patch.dict("config.CONFIG", {"sensitivity_sweep_enabled": True}):
            generate_sensitivity_report([], "run-001")
        captured = capsys.readouterr()
        assert "SENSITIVITY" not in captured.out

    def test_only_single_variants_returns_early(self, capsys):
        """If no strategy has more than one variant, no report is printed."""
        results = [
            _make_result_dict("SMA Crossover"),
            _make_result_dict("RSI Mean Reversion"),
        ]
        with patch.dict("config.CONFIG", {"sensitivity_sweep_enabled": True}):
            generate_sensitivity_report(results, "run-001")
        captured = capsys.readouterr()
        assert "SENSITIVITY" not in captured.out

    def test_fragile_strategy_flagged(self, capsys):
        """Strategy with <30% profitable variants gets FRAGILE label.

        The sensitivity report groups by base name (everything before ' [').
        Variant names must contain ' [' to be grouped together.
        """
        results = [
            _make_result_dict("SMA Crossover", pnl_pct=-0.10),           # base
            _make_result_dict("SMA Crossover [+20%]", pnl_pct=-0.05),
            _make_result_dict("SMA Crossover [-20%]", pnl_pct=-0.03),
            _make_result_dict("SMA Crossover [+40%]", pnl_pct=0.10),  # only 1/4 profitable
        ]
        with patch.dict("config.CONFIG", {"sensitivity_sweep_enabled": True}):
            generate_sensitivity_report(results, "run-001")
        captured = capsys.readouterr()
        assert "FRAGILE" in captured.out

    def test_robust_strategy_not_flagged_as_fragile(self, capsys):
        """Strategy with ≥30% profitable variants gets Robust label."""
        results = [
            _make_result_dict("SMA Crossover", pnl_pct=0.15),            # base
            _make_result_dict("SMA Crossover [+20%]", pnl_pct=0.10),
            _make_result_dict("SMA Crossover [-20%]", pnl_pct=0.08),
            _make_result_dict("SMA Crossover [+40%]", pnl_pct=-0.02),  # 3/4 profitable
        ]
        with patch.dict("config.CONFIG", {"sensitivity_sweep_enabled": True}):
            generate_sensitivity_report(results, "run-001")
        captured = capsys.readouterr()
        assert "Robust" in captured.out
        assert "FRAGILE" not in captured.out


# ---------------------------------------------------------------------------
# Guard conditions in larger summary functions
# ---------------------------------------------------------------------------

class TestSummaryGuardConditions:

    def test_generate_per_portfolio_summary_empty_results(self, capsys):
        """Empty portfolio_results triggers 'No successful strategy results' message."""
        with patch("helpers.summary.CONFIG", {}):
            generate_per_portfolio_summary([], "Test Portfolio", 0.10, 0.12, "run-001")
        captured = capsys.readouterr()
        assert "No successful strategy results" in captured.out

    def test_generate_portfolio_summary_report_empty_results(self, capsys):
        """Empty all_results triggers 'No portfolio results' message."""
        with patch("helpers.summary.CONFIG", {}):
            generate_portfolio_summary_report([], duration_seconds=None, run_id="run-001")
        captured = capsys.readouterr()
        assert "No portfolio results" in captured.out

    def test_generate_portfolio_summary_report_with_duration(self, capsys):
        """When duration_seconds is given, it should be formatted and printed."""
        with patch("helpers.summary.CONFIG", {}):
            generate_portfolio_summary_report([], duration_seconds=130, run_id="run-001")
        captured = capsys.readouterr()
        assert "2 minutes" in captured.out

    def test_generate_final_summary_empty_results(self, capsys):
        """Empty all_results → 'No results to summarize' message."""
        with patch("helpers.summary.CONFIG", {}):
            generate_final_summary([])
        captured = capsys.readouterr()
        assert "No results" in captured.out

    def test_generate_single_asset_summary_empty_results(self, capsys):
        """Empty symbol_results → 'No successful strategy results' message."""
        _cfg = {"timeframe": "D", "start_date": "2020-01-01", "end_date": "2024-01-01"}
        with patch("helpers.summary.CONFIG", _cfg):
            generate_single_asset_summary_report([], None, None, "AAPL", "/tmp/trades", "run-001")
        captured = capsys.readouterr()
        assert "No successful strategy results" in captured.out

"""
Extended tests for helpers/summary.py — covers branches NOT hit by
tests/test_summary_functions.py:

  - _print_table: empty df guard, non-empty df prints rows
  - generate_portfolio_summary_report: empty results, no strategies pass filter,
    happy path (normal + verbose), S3 upload path, exception on CSV write
"""
import os
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock

from helpers.summary import (
    _print_table,
    generate_portfolio_summary_report,
)


# ---------------------------------------------------------------------------
# Minimal result dict accepted by generate_portfolio_summary_report
# ---------------------------------------------------------------------------

def _make_result(**overrides):
    base = {
        'Strategy': 'SMA Crossover',
        'Portfolio': 'Test',
        'Asset': 'AAPL',
        'Trades': 50,
        'pnl_percent': 0.15,
        'max_drawdown': 0.10,
        'win_rate': 0.55,
        'calmar_ratio': 1.5,
        'sharpe_ratio': 1.2,
        'profit_factor': 1.8,
        'vs_spy_benchmark': 0.05,
        'vs_qqq_benchmark': 0.03,
        'mc_score': 75,
        'mc_verdict': 'Robust',
        'wfa_verdict': 'Pass',
        'wfa_rolling_verdict': 'Pass',
        'oos_pnl_pct': 0.08,
        'expectancy': 0.5,
        'sqn': 2.1,
        'avg_trade_duration': 5.3,
        'rolling_sharpe_mean': 1.1,
        'rolling_sharpe_min': 0.7,
        'rolling_sharpe_final': 1.3,
        'max_recovery_days': 30,
        'avg_recovery_days': 15.0,
        'trade_log': [{'date': '2021-01-04', 'profit': 100}],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _print_table
# ---------------------------------------------------------------------------

class TestPrintTable:

    def test_empty_df_returns_without_printing(self, capsys):
        _print_table(pd.DataFrame(), "Test Title")
        out = capsys.readouterr().out
        assert out == ""

    def test_non_empty_df_prints_header_and_rows(self, capsys):
        df = pd.DataFrame({"Col A": ["val1", "val2"], "Col B": [10, 20]})
        _print_table(df, "My Table")
        out = capsys.readouterr().out
        assert "My Table" in out
        assert "Col A" in out
        assert "val1" in out
        assert "val2" in out

    def test_prints_dividers(self, capsys):
        df = pd.DataFrame({"X": [1]})
        _print_table(df, "T")
        out = capsys.readouterr().out
        assert "-" in out


# ---------------------------------------------------------------------------
# generate_portfolio_summary_report — guard clauses
# ---------------------------------------------------------------------------

class TestGeneratePortfolioSummaryGuards:

    def test_empty_results_prints_message_and_returns(self, capsys):
        generate_portfolio_summary_report([], run_id="test-run")
        out = capsys.readouterr().out
        assert "No portfolio results" in out

    def test_no_strategies_pass_filter_prints_message(self, capsys):
        # Set an impossibly high mc_score_min so nothing passes
        with patch.dict("config.CONFIG", {"mc_score_min_to_show_in_summary": 9999}):
            generate_portfolio_summary_report([_make_result()], run_id="test-run")
        out = capsys.readouterr().out
        assert "No strategies met" in out

    def test_duration_seconds_printed_when_provided(self, capsys):
        with patch("helpers.summary.os.makedirs"), \
             patch("pandas.DataFrame.to_csv"):
            generate_portfolio_summary_report(
                [_make_result()], duration_seconds=125.0, run_id="test-run"
            )
        out = capsys.readouterr().out
        assert "Runtime" in out or "minutes" in out or "2 minutes" in out


# ---------------------------------------------------------------------------
# generate_portfolio_summary_report — happy path
# ---------------------------------------------------------------------------

class TestGeneratePortfolioSummaryHappyPath:

    def test_strategy_name_appears_in_output(self, capsys):
        with patch("helpers.summary.os.makedirs"), \
             patch("pandas.DataFrame.to_csv"):
            generate_portfolio_summary_report([_make_result()], run_id="run-001")
        out = capsys.readouterr().out
        assert "SMA Crossover" in out

    def test_csv_saved_to_output_dir(self, tmp_path):
        with patch("helpers.summary.os.makedirs") as mock_mkdir, \
             patch("pandas.DataFrame.to_csv") as mock_csv:
            generate_portfolio_summary_report([_make_result()], run_id="run-001")
        mock_csv.assert_called_once()

    def test_verbose_output_prints_extended_table(self, capsys):
        with patch.dict("config.CONFIG", {"verbose_output": True}), \
             patch("helpers.summary.os.makedirs"), \
             patch("pandas.DataFrame.to_csv"):
            generate_portfolio_summary_report([_make_result()], run_id="run-001")
        out = capsys.readouterr().out
        # With verbose=True the extended metrics table is printed
        assert "SMA Crossover" in out

    def test_non_verbose_prints_hint_message(self, capsys):
        with patch.dict("config.CONFIG", {"verbose_output": False}), \
             patch("helpers.summary.os.makedirs"), \
             patch("pandas.DataFrame.to_csv"):
            generate_portfolio_summary_report([_make_result()], run_id="run-001")
        out = capsys.readouterr().out
        assert "--verbose" in out

    def test_exception_on_csv_write_does_not_raise(self, capsys):
        """OSError during CSV write should be caught and warned, not raised."""
        with patch("helpers.summary.os.makedirs"), \
             patch("pandas.DataFrame.to_csv", side_effect=OSError("disk full")):
            generate_portfolio_summary_report([_make_result()], run_id="run-001")
        out = capsys.readouterr().out
        assert "WARNING" in out


# ---------------------------------------------------------------------------
# generate_portfolio_summary_report — S3 upload path
# ---------------------------------------------------------------------------

class TestGeneratePortfolioSummaryS3:

    def test_s3_upload_called_when_enabled(self, capsys):
        with patch.dict("config.CONFIG", {
            "upload_to_s3": True,
            "s3_reports_bucket": "my-bucket",
        }), \
        patch("helpers.summary.os.makedirs"), \
        patch("pandas.DataFrame.to_csv"), \
        patch("helpers.summary.upload_file_to_s3", return_value=True) as mock_s3:
            generate_portfolio_summary_report([_make_result()], run_id="run-001")
        mock_s3.assert_called_once()

    def test_s3_upload_not_called_when_disabled(self):
        with patch.dict("config.CONFIG", {
            "upload_to_s3": False,
            "s3_reports_bucket": "my-bucket",
        }), \
        patch("helpers.summary.os.makedirs"), \
        patch("pandas.DataFrame.to_csv"), \
        patch("helpers.summary.upload_file_to_s3") as mock_s3:
            generate_portfolio_summary_report([_make_result()], run_id="run-001")
        mock_s3.assert_not_called()

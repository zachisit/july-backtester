"""
Tests for trade_analyzer/analyzer.py.

Focuses on the testable surface without triggering matplotlib, PDF generation,
or yfinance:
  - generate_trade_report: config patch / restore lifecycle
  - _run_analysis: guard clauses (not enough trades, OSError on mkdir)
"""

import os
import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock

from trade_analyzer import analyzer
from trade_analyzer import default_config as config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trades_df(n=5):
    """Minimal DataFrame accepted by clean_trades_data."""
    dates_entry = pd.date_range("2021-01-04", periods=n, freq="3B")
    dates_exit  = pd.date_range("2021-01-06", periods=n, freq="3B")
    profits = [100.0, -50.0, 200.0, -30.0, 150.0][:n]
    pct     = [2.0,   -1.0,   4.0,  -0.5,   3.0][:n]
    return pd.DataFrame({
        "Date":      dates_entry,
        "Ex. date":  dates_exit,
        "Profit":    profits,
        "% Profit":  pct,
    })


# Patch everything downstream of clean_trades_data so tests are fast and
# require no external dependencies.
_PATCH_TARGETS = [
    "trade_analyzer.analyzer.data_handler.calculate_daily_returns",
    "trade_analyzer.analyzer.data_handler.download_benchmark_data",
    "trade_analyzer.analyzer.report_generator.generate_overall_metrics_summary",
    "trade_analyzer.analyzer.report_generator.generate_wfa_summary",
    "trade_analyzer.analyzer.report_generator.generate_markdown_report",
    "trade_analyzer.analyzer.report_generator.generate_pdf_report",
    "trade_analyzer.analyzer.report_generator.extract_key_metrics_for_console",
    "trade_analyzer.analyzer.calculations.calculate_core_metrics",
    "trade_analyzer.analyzer.calculations.calculate_rolling_metrics",
    "trade_analyzer.analyzer.calculations.run_monte_carlo_simulation",
    "trade_analyzer.analyzer.plotting",
    "trade_analyzer.analyzer.plt",
]


def _stub_downstream():
    """Context manager that stubs out all side-effectful downstream calls."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        patches = []
        try:
            patches.append(patch(
                "trade_analyzer.analyzer.data_handler.calculate_daily_returns",
                return_value=(pd.Series(dtype=float), pd.Series(dtype=float)),
            ))
            patches.append(patch(
                "trade_analyzer.analyzer.data_handler.download_benchmark_data",
                return_value=None,
            ))
            patches.append(patch(
                "trade_analyzer.analyzer.report_generator.generate_overall_metrics_summary",
                return_value=("Metrics", "summary text"),
            ))
            patches.append(patch(
                "trade_analyzer.analyzer.report_generator.generate_wfa_summary",
                return_value=("WFA", "wfa text"),
            ))
            patches.append(patch(
                "trade_analyzer.analyzer.report_generator.generate_markdown_report",
            ))
            patches.append(patch(
                "trade_analyzer.analyzer.report_generator.generate_pdf_report",
            ))
            patches.append(patch(
                "trade_analyzer.analyzer.report_generator.extract_key_metrics_for_console",
                return_value={},
            ))
            patches.append(patch(
                "trade_analyzer.analyzer.calculations.calculate_core_metrics",
                return_value={},
            ))
            patches.append(patch(
                "trade_analyzer.analyzer.calculations.calculate_rolling_metrics",
                return_value=pd.DataFrame(),
            ))
            patches.append(patch(
                "trade_analyzer.analyzer.calculations.run_monte_carlo_simulation",
                return_value={},
            ))
            # Suppress any remaining report/plot helpers
            patches.append(patch("trade_analyzer.analyzer.plt"))

            started = [p.start() for p in patches]
            yield started
        finally:
            for p in patches:
                try:
                    p.stop()
                except RuntimeError:
                    pass

    return _ctx()


# ---------------------------------------------------------------------------
# generate_trade_report — config patching and restore
# ---------------------------------------------------------------------------

class TestGenerateTradeReportConfigRestore:

    def test_config_value_restored_after_successful_run(self, tmp_path):
        """Config override must be reverted after a normal run completes."""
        original_equity = config.INITIAL_EQUITY
        with _stub_downstream():
            analyzer.generate_trade_report(
                _make_trades_df(),
                str(tmp_path),
                "test_run",
                config_params={"INITIAL_EQUITY": 99_999.0},
            )
        assert config.INITIAL_EQUITY == original_equity

    def test_config_value_restored_even_if_run_raises(self, tmp_path):
        """Config override must be reverted even when _run_analysis throws."""
        original_equity = config.INITIAL_EQUITY
        with patch(
            "trade_analyzer.analyzer._run_analysis",
            side_effect=RuntimeError("boom"),
        ):
            # generate_trade_report wraps _run_analysis in try/finally
            # so the restore still runs, but the exception propagates
            with pytest.raises(RuntimeError):
                analyzer.generate_trade_report(
                    _make_trades_df(),
                    str(tmp_path),
                    "failing_run",
                    config_params={"INITIAL_EQUITY": 77_777.0},
                )
        assert config.INITIAL_EQUITY == original_equity

    def test_no_config_params_runs_without_error(self, tmp_path):
        """Passing no config_params (None) should not raise."""
        with _stub_downstream():
            analyzer.generate_trade_report(
                _make_trades_df(),
                str(tmp_path),
                "default_params_run",
                config_params=None,
            )

    def test_unknown_config_key_set_then_removed(self, tmp_path):
        """A key not in default_config is set as a new attribute and then deleted."""
        assert not hasattr(config, "_TEST_UNKNOWN_KEY_XYZ")
        with _stub_downstream():
            analyzer.generate_trade_report(
                _make_trades_df(),
                str(tmp_path),
                "unknown_key_run",
                config_params={"_TEST_UNKNOWN_KEY_XYZ": "hello"},
            )
        assert not hasattr(config, "_TEST_UNKNOWN_KEY_XYZ")

    def test_output_directory_created(self, tmp_path):
        """Running the report creates the expected run subdirectory."""
        with _stub_downstream():
            analyzer.generate_trade_report(
                _make_trades_df(),
                str(tmp_path),
                "my_report",
            )
        assert os.path.isdir(tmp_path / "my_report")


# ---------------------------------------------------------------------------
# _run_analysis — guard: not enough valid trades
# ---------------------------------------------------------------------------

class TestRunAnalysisNotEnoughTrades:

    def test_single_trade_triggers_early_return(self, tmp_path):
        """< 2 trades after cleaning → StopIteration caught, no PDF attempted."""
        single_trade = _make_trades_df(n=1)
        # _run_analysis catches StopIteration internally — should not propagate
        with _stub_downstream():
            analyzer._run_analysis(single_trade, str(tmp_path), "single", {})
        # No exception raised = early return was handled

    def test_empty_dataframe_triggers_early_return(self, tmp_path):
        """Empty DF → same early return guard."""
        with _stub_downstream():
            analyzer._run_analysis(pd.DataFrame(), str(tmp_path), "empty", {})

    def test_all_nan_profit_triggers_early_return(self, tmp_path):
        """All Profit = NaN → all rows dropped → < 2 trades guard fires."""
        df = pd.DataFrame({
            "Date":     pd.date_range("2021-01-04", periods=3, freq="B"),
            "Ex. date": pd.date_range("2021-01-06", periods=3, freq="B"),
            "Profit":   [np.nan, np.nan, np.nan],
            "% Profit": [np.nan, np.nan, np.nan],
        })
        with _stub_downstream():
            analyzer._run_analysis(df, str(tmp_path), "all_nan", {})


# ---------------------------------------------------------------------------
# _run_analysis — guard: OSError on directory creation
# ---------------------------------------------------------------------------

class TestRunAnalysisOSError:

    def test_oserror_on_mkdir_returns_early(self, tmp_path):
        """If os.makedirs raises OSError, function returns early without crash."""
        with patch("trade_analyzer.analyzer.os.makedirs", side_effect=OSError("no space")):
            # Should return early, not raise
            analyzer._run_analysis(_make_trades_df(), str(tmp_path), "oserror_run", {})

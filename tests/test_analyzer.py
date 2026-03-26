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


# ---------------------------------------------------------------------------
# _run_analysis — WFA branch
# ---------------------------------------------------------------------------

class TestRunAnalysisWfaBranch:

    def test_wfa_branch_executes_with_valid_split_ratio(self, tmp_path):
        """WFA_SPLIT_RATIO in (0, 1) triggers the WFA computation path."""
        with _stub_downstream():
            # Should not raise — WFA helpers run on synthetic trade data
            analyzer._run_analysis(
                _make_trades_df(n=5),
                str(tmp_path),
                "wfa_run",
                config_params={"WFA_SPLIT_RATIO": 0.7},
            )

    def test_wfa_branch_skipped_when_ratio_is_zero(self, tmp_path):
        """WFA_SPLIT_RATIO == 0 → branch not entered, no WFA computation."""
        with _stub_downstream():
            analyzer._run_analysis(
                _make_trades_df(n=5),
                str(tmp_path),
                "wfa_zero",
                config_params={"WFA_SPLIT_RATIO": 0},
            )

    def test_wfa_exception_handled_silently(self, tmp_path):
        """An error in the WFA block is caught and printed as a warning."""
        with _stub_downstream(), \
             patch("helpers.wfa.get_split_date", side_effect=RuntimeError("wfa boom")):
            # Should not propagate — exception is caught inside _run_analysis
            analyzer._run_analysis(
                _make_trades_df(n=5),
                str(tmp_path),
                "wfa_exc",
                config_params={"WFA_SPLIT_RATIO": 0.7},
            )


# ---------------------------------------------------------------------------
# _run_analysis — noise CSV branch
# ---------------------------------------------------------------------------

class TestRunAnalysisNoiseBranch:

    def _write_noise_csv(self, tmp_path):
        """Create a minimal noise_sample_data.csv for the noise branch."""
        import numpy as np
        n = 10
        closes = np.linspace(100.0, 110.0, n)
        rows = {
            "Symbol":      ["TEST"] * n,
            "Clean_Open":  closes * 0.99,
            "Clean_High":  closes * 1.01,
            "Clean_Low":   closes * 0.98,
            "Clean_Close": closes,
            "Noisy_Open":  closes * 0.995,
            "Noisy_High":  closes * 1.005,
            "Noisy_Low":   closes * 0.985,
            "Noisy_Close": closes * 1.001,
        }
        idx = pd.date_range("2021-01-04", periods=n, freq="B")
        csv_path = tmp_path / "noise_sample.csv"
        pd.DataFrame(rows, index=idx).to_csv(csv_path)
        return str(csv_path)

    def test_noise_branch_executes_when_csv_exists(self, tmp_path):
        """NOISE_CSV_PATH pointing to a valid CSV runs the noise overlay path."""
        csv_path = self._write_noise_csv(tmp_path)
        with _stub_downstream():
            analyzer._run_analysis(
                _make_trades_df(n=5),
                str(tmp_path),
                "noise_run",
                config_params={"NOISE_CSV_PATH": csv_path},
            )

    def test_noise_branch_skipped_when_path_absent(self, tmp_path):
        """NOISE_CSV_PATH = None → noise branch skipped, no error."""
        with _stub_downstream():
            analyzer._run_analysis(
                _make_trades_df(n=5),
                str(tmp_path),
                "no_noise",
                config_params={"NOISE_CSV_PATH": None},
            )

    def test_noise_branch_skipped_when_file_missing(self, tmp_path):
        """NOISE_CSV_PATH pointing to a nonexistent file → branch skipped."""
        with _stub_downstream():
            analyzer._run_analysis(
                _make_trades_df(n=5),
                str(tmp_path),
                "missing_noise",
                config_params={"NOISE_CSV_PATH": str(tmp_path / "does_not_exist.csv")},
            )

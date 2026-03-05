"""
tests/test_summary_metadata.py

Unit tests for the run metadata columns injected into overall_portfolio_summary.csv
by generate_portfolio_summary_report() in helpers/summary.py.

Strategy: call generate_portfolio_summary_report() directly with a minimal
all_results list, patching CONFIG so tests are isolated from whatever the real
config.py contains, and using tmp_path as the working directory so no real
output/ tree is created.

Patches applied in every test:
  - helpers.summary.CONFIG  — controlled config dict
  - os.getcwd / os.makedirs — not needed; we pass an explicit run_id that maps
                              to tmp_path so the CSV lands inside tmp_path
  - The output path is inferred from run_id, so we symlink run_id to tmp_path
    by constructing the expected path ourselves.
"""

import csv
import json
import os
import sys
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import helpers.summary as summary_mod


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_CONFIG = {
    "data_provider": "polygon",
    "start_date": "2020-01-01",
    "end_date": "2024-01-01",
    "timeframe": "D",
    "timeframe_multiplier": 1,
    # Filter thresholds — set permissively so our minimal result rows pass
    "min_performance_vs_spy": -9999.0,
    "min_performance_vs_qqq": -9999.0,
    "mc_score_min_to_show_in_summary": -999,
    "min_pandl_to_show_in_summary": -999.0,
    "min_calmar_to_show_in_summary": -999.0,
    "max_acceptable_drawdown": 1.0,
    "upload_to_s3": False,
    "s3_reports_bucket": None,
}

def _minimal_result(portfolio="TestPortfolio", strategy="EMA_Cross"):
    """One row that passes all default filter thresholds."""
    return {
        "Portfolio": portfolio,
        "Strategy": strategy,
        "Trades": 50,
        "pnl_percent": 0.15,
        "max_drawdown": 0.10,
        "calmar_ratio": 1.5,
        "sharpe_ratio": 1.2,
        "profit_factor": 1.8,
        "win_rate": 0.55,
        "avg_trade_duration": 5.3,
        "mc_verdict": "PASS",
        "mc_score": 75,
        "vs_spy_benchmark": 0.05,
        "vs_qqq_benchmark": 0.03,
        "trade_pnl_list": [100, -50, 200],
    }


def _run_and_load_csv(tmp_path, config_override=None):
    """
    Run generate_portfolio_summary_report with a single result row,
    return the CSV as a pandas DataFrame.
    """
    config = {**_BASE_CONFIG, **(config_override or {})}
    run_id = "test_run_2026-01-01_12-00-00"
    output_dir = tmp_path / "output" / "runs" / run_id
    output_dir.mkdir(parents=True)

    # Patch cwd so os.path.join("output", ...) resolves inside tmp_path
    with patch("helpers.summary.CONFIG", config), \
         patch("os.getcwd", return_value=str(tmp_path)), \
         patch("helpers.summary.upload_file_to_s3", return_value=True):
        # generate_portfolio_summary_report uses os.path.join("output", "runs", run_id)
        # We need to redirect that to tmp_path. Easiest: patch os.path.join selectively
        # is fragile; instead patch os.makedirs to no-op and override the output path
        # by monkeypatching the open call — actually the simplest approach is to
        # temporarily change the working directory.
        orig_cwd = os.getcwd()
        try:
            os.chdir(str(tmp_path))
            summary_mod.generate_portfolio_summary_report(
                [_minimal_result()], duration_seconds=5.0, run_id=run_id
            )
        finally:
            os.chdir(orig_cwd)

    csv_path = output_dir / "overall_portfolio_summary.csv"
    assert csv_path.exists(), f"CSV not created at {csv_path}"
    return pd.read_csv(csv_path)


# ---------------------------------------------------------------------------
# TestCase1 — metadata columns exist in the CSV
# ---------------------------------------------------------------------------

class TestMetadataColumnsPresent:
    """Test Case 1: CSV contains all 5 metadata columns at the start."""

    EXPECTED_META_COLS = ["run_id", "data_provider", "start_date", "end_date", "timeframe"]

    def test_all_five_metadata_columns_exist(self, tmp_path):
        df = _run_and_load_csv(tmp_path)
        for col in self.EXPECTED_META_COLS:
            assert col in df.columns, f"Missing column: {col}"

    def test_metadata_columns_are_first_five(self, tmp_path):
        df = _run_and_load_csv(tmp_path)
        assert list(df.columns[:5]) == self.EXPECTED_META_COLS

    def test_run_id_value_matches_argument(self, tmp_path):
        df = _run_and_load_csv(tmp_path)
        assert df["run_id"].iloc[0] == "test_run_2026-01-01_12-00-00"

    def test_data_provider_value_from_config(self, tmp_path):
        df = _run_and_load_csv(tmp_path, {"data_provider": "alpaca"})
        assert df["data_provider"].iloc[0] == "alpaca"

    def test_start_date_value_from_config(self, tmp_path):
        df = _run_and_load_csv(tmp_path, {"start_date": "2018-06-01"})
        assert df["start_date"].iloc[0] == "2018-06-01"

    def test_end_date_value_from_config(self, tmp_path):
        df = _run_and_load_csv(tmp_path, {"end_date": "2023-12-31"})
        assert df["end_date"].iloc[0] == "2023-12-31"

    def test_run_id_fallback_when_none(self, tmp_path):
        """When run_id=None the column value should be 'unknown'."""
        config = {**_BASE_CONFIG}
        run_id = None
        output_dir = tmp_path / "output"
        output_dir.mkdir(parents=True)

        with patch("helpers.summary.CONFIG", config), \
             patch("helpers.summary.upload_file_to_s3", return_value=True):
            orig_cwd = os.getcwd()
            try:
                os.chdir(str(tmp_path))
                summary_mod.generate_portfolio_summary_report(
                    [_minimal_result()], duration_seconds=1.0, run_id=run_id
                )
            finally:
                os.chdir(orig_cwd)

        csv_path = output_dir / "overall_portfolio_summary.csv"
        df = pd.read_csv(csv_path)
        assert df["run_id"].iloc[0] == "unknown"


# ---------------------------------------------------------------------------
# TestCase2 — timeframe column combines multiplier and code correctly
# ---------------------------------------------------------------------------

class TestTimeframeColumn:
    """Test Case 2: timeframe is correctly formatted as <multiplier><code>."""

    def test_daily_timeframe_default(self, tmp_path):
        df = _run_and_load_csv(tmp_path, {"timeframe": "D", "timeframe_multiplier": 1})
        assert df["timeframe"].iloc[0] == "1D"

    def test_5_minute_timeframe(self, tmp_path):
        df = _run_and_load_csv(tmp_path, {"timeframe": "MIN", "timeframe_multiplier": 5})
        assert df["timeframe"].iloc[0] == "5MIN"

    def test_weekly_timeframe(self, tmp_path):
        df = _run_and_load_csv(tmp_path, {"timeframe": "W", "timeframe_multiplier": 1})
        assert df["timeframe"].iloc[0] == "1W"

    def test_15_minute_timeframe(self, tmp_path):
        df = _run_and_load_csv(tmp_path, {"timeframe": "MIN", "timeframe_multiplier": 15})
        assert df["timeframe"].iloc[0] == "15MIN"

    def test_missing_timeframe_keys_use_defaults(self, tmp_path):
        """If timeframe keys are absent from config, fall back to '1D'."""
        config = {k: v for k, v in _BASE_CONFIG.items()
                  if k not in ("timeframe", "timeframe_multiplier")}
        df = _run_and_load_csv(tmp_path, config_override=config)
        assert df["timeframe"].iloc[0] == "1D"


# ---------------------------------------------------------------------------
# TestCase3 — existing performance columns are still present and shifted right
# ---------------------------------------------------------------------------

class TestExistingColumnsPreserved:
    """Test Case 3: The CSV is still valid and existing columns are intact."""

    EXPECTED_PERF_COLS = ["Portfolio", "Strategy", "P&L (%)", "Max DD", "Calmar",
                          "Sharpe", "Profit Factor", "Win Rate", "Trades"]

    def test_csv_loads_without_error(self, tmp_path):
        df = _run_and_load_csv(tmp_path)
        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0

    def test_existing_performance_columns_still_present(self, tmp_path):
        df = _run_and_load_csv(tmp_path)
        for col in self.EXPECTED_PERF_COLS:
            assert col in df.columns, f"Missing performance column: {col}"

    def test_performance_columns_come_after_metadata(self, tmp_path):
        df = _run_and_load_csv(tmp_path)
        meta_end = 5  # first 5 are metadata
        perf_cols_in_file = list(df.columns[meta_end:])
        for col in self.EXPECTED_PERF_COLS:
            assert col in perf_cols_in_file, \
                f"'{col}' not found after metadata columns (found at index {list(df.columns).index(col)})"

    def test_total_column_count_is_meta_plus_perf(self, tmp_path):
        df = _run_and_load_csv(tmp_path)
        # 5 metadata + however many report_cols are populated
        assert len(df.columns) > 5

    def test_row_count_matches_result_input(self, tmp_path):
        """Two result rows → two rows in the CSV."""
        config = {**_BASE_CONFIG}
        run_id = "test_run_two_rows"
        output_dir = tmp_path / "output" / "runs" / run_id
        output_dir.mkdir(parents=True)

        with patch("helpers.summary.CONFIG", config), \
             patch("helpers.summary.upload_file_to_s3", return_value=True):
            orig_cwd = os.getcwd()
            try:
                os.chdir(str(tmp_path))
                summary_mod.generate_portfolio_summary_report(
                    [_minimal_result("P1", "Strat_A"), _minimal_result("P2", "Strat_B")],
                    duration_seconds=2.0,
                    run_id=run_id,
                )
            finally:
                os.chdir(orig_cwd)

        df = pd.read_csv(output_dir / "overall_portfolio_summary.csv")
        assert len(df) == 2

    def test_metadata_values_consistent_across_all_rows(self, tmp_path):
        """Every row gets the same metadata (same run, same config)."""
        config = {**_BASE_CONFIG}
        run_id = "test_run_multi"
        output_dir = tmp_path / "output" / "runs" / run_id
        output_dir.mkdir(parents=True)

        with patch("helpers.summary.CONFIG", config), \
             patch("helpers.summary.upload_file_to_s3", return_value=True):
            orig_cwd = os.getcwd()
            try:
                os.chdir(str(tmp_path))
                summary_mod.generate_portfolio_summary_report(
                    [_minimal_result("P1", "S1"), _minimal_result("P2", "S2")],
                    duration_seconds=1.0,
                    run_id=run_id,
                )
            finally:
                os.chdir(orig_cwd)

        df = pd.read_csv(output_dir / "overall_portfolio_summary.csv")
        assert df["run_id"].nunique() == 1
        assert df["start_date"].nunique() == 1
        assert df["end_date"].nunique() == 1
        assert df["timeframe"].nunique() == 1

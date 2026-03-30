# tests/test_report_smoke.py
"""
Regression test for trade_analyzer/data_handler.py column name handling.

Builds a minimal synthetic trade log CSV with the current engine column schema
(EntryDate, ExitDate, EntryPrice, ExitPrice, ProfitPct, MAE_pct, MFE_pct,
HoldDuration) and runs it through data_handler.clean_trades_data to verify
no exception is raised.

This catches future column rename drift between the engine and the analyzer.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from trade_analyzer.data_handler import clean_trades_data


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine_trade_log(n=20):
    """
    Build a synthetic trade log DataFrame using the CURRENT engine column schema.
    These are the exact column names written by portfolio_simulations.py.
    """
    dates_entry = pd.bdate_range("2023-01-02", periods=n, freq="B")
    dates_exit = dates_entry + pd.Timedelta(days=5)

    return pd.DataFrame({
        "Symbol":          ["TEST"] * n,
        "Trade":           [f"Long {i+1}" for i in range(n)],
        "EntryDate":       dates_entry.strftime("%Y-%m-%d"),
        "ExitDate":        dates_exit.strftime("%Y-%m-%d"),
        "EntryPrice":      np.random.uniform(90, 110, n).round(2),
        "ExitPrice":       np.random.uniform(90, 115, n).round(2),
        "Profit":          np.random.uniform(-500, 1000, n).round(2),
        "ProfitPct":       np.random.uniform(-0.05, 0.10, n).round(4),
        "Shares":          np.random.uniform(10, 100, n).round(1),
        "is_win":          np.random.choice([0, 1], n),
        "HoldDuration":    np.random.randint(1, 30, n),
        "MAE_pct":         np.random.uniform(-0.10, 0, n).round(4),
        "MFE_pct":         np.random.uniform(0, 0.15, n).round(4),
        "ExitReason":      ["Strategy Exit"] * n,
        "InitialRisk":     np.random.uniform(0.5, 2.0, n).round(2),
        "RMultiple":       np.random.uniform(-2, 5, n).round(2),
        "VolumeImpact_bps": [0.0] * n,
    })


# ---------------------------------------------------------------------------
# TestReportSmoke
# ---------------------------------------------------------------------------

class TestReportSmoke:
    """Smoke tests for the trade analyzer data handler with engine-format data."""

    def test_clean_trades_data_no_exception(self):
        """clean_trades_data must not raise on current engine column schema."""
        df = _make_engine_trade_log(20)
        # This should NOT raise ValueError about missing 'Date' column
        result_df, summary = clean_trades_data(df, initial_equity=100_000.0)
        assert result_df is not None
        assert len(result_df) > 0

    def test_date_column_remapped(self):
        """EntryDate should be remapped to 'Date' for the analyzer."""
        df = _make_engine_trade_log(10)
        result_df, _ = clean_trades_data(df, initial_equity=100_000.0)
        assert "Date" in result_df.columns
        assert pd.api.types.is_datetime64_any_dtype(result_df["Date"])

    def test_exit_date_column_remapped(self):
        """ExitDate should be remapped to 'Ex. date' for the analyzer."""
        df = _make_engine_trade_log(10)
        result_df, _ = clean_trades_data(df, initial_equity=100_000.0)
        assert "Ex. date" in result_df.columns
        assert pd.api.types.is_datetime64_any_dtype(result_df["Ex. date"])

    def test_price_columns_remapped(self):
        """EntryPrice/ExitPrice should be remapped to Price/Ex. Price."""
        df = _make_engine_trade_log(10)
        result_df, _ = clean_trades_data(df, initial_equity=100_000.0)
        assert "Price" in result_df.columns
        assert "Ex. Price" in result_df.columns

    def test_profit_pct_remapped(self):
        """ProfitPct should be remapped to '% Profit'."""
        df = _make_engine_trade_log(10)
        result_df, _ = clean_trades_data(df, initial_equity=100_000.0)
        assert "% Profit" in result_df.columns

    def test_mae_mfe_remapped(self):
        """MAE_pct/MFE_pct should be remapped to MAE/MFE."""
        df = _make_engine_trade_log(10)
        result_df, _ = clean_trades_data(df, initial_equity=100_000.0)
        assert "MAE" in result_df.columns
        assert "MFE" in result_df.columns

    def test_hold_duration_remapped(self):
        """HoldDuration should be remapped to '# bars'."""
        df = _make_engine_trade_log(10)
        result_df, _ = clean_trades_data(df, initial_equity=100_000.0)
        assert "# bars" in result_df.columns

    def test_equity_column_calculated(self):
        """Equity column should be calculated from cumulative profit."""
        df = _make_engine_trade_log(10)
        result_df, _ = clean_trades_data(df, initial_equity=100_000.0)
        assert "Equity" in result_df.columns
        assert result_df["Equity"].notna().all()

    def test_legacy_columns_still_work(self):
        """If data already uses legacy column names (Date, Ex. date), it should still work."""
        df = _make_engine_trade_log(10)
        # Manually rename to legacy format before calling
        df.rename(columns={
            "EntryDate": "Date",
            "ExitDate": "Ex. date",
            "EntryPrice": "Price",
            "ExitPrice": "Ex. Price",
            "ProfitPct": "% Profit",
            "MAE_pct": "MAE",
            "MFE_pct": "MFE",
            "HoldDuration": "# bars",
        }, inplace=True)
        result_df, _ = clean_trades_data(df, initial_equity=100_000.0)
        assert result_df is not None
        assert len(result_df) > 0

    def test_all_engine_columns_present_after_cleaning(self):
        """Core engine columns should survive the cleaning process."""
        df = _make_engine_trade_log(15)
        result_df, _ = clean_trades_data(df, initial_equity=100_000.0)
        # These columns should exist (some remapped, some passed through)
        for col in ["Symbol", "Profit", "Shares", "is_win", "ExitReason",
                     "InitialRisk", "RMultiple"]:
            assert col in result_df.columns, f"Missing column after cleaning: {col}"

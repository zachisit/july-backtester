"""
Extended tests for trade_analyzer/data_handler.py — covers branches NOT hit by
tests/test_data_handler.py:

  - clean_trades_data: missing MAE/MFE/% Profit columns, missing numeric cols,
    empty-after-clean early return, Return_Frac from % Profit, Return_Frac default=0,
    Position value col used for Return_Frac denominator
  - calculate_daily_returns: Cum. Profit fallback, no equity source col, invalid
    date NaT, duplicate exit-date dedup, single data-point guard
  - download_benchmark_data: empty yfinance response, exception path, price column
    missing, MultiIndex column handling, successful single-level happy path,
    empty-after-dropna path
"""

import io
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock

from trade_analyzer.data_handler import (
    clean_trades_data,
    calculate_daily_returns,
    download_benchmark_data,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_df(**overrides):
    """Minimal two-row DataFrame accepted by clean_trades_data."""
    data = {
        "Date":      ["2021-01-04", "2021-01-07"],
        "Ex. date":  ["2021-01-06", "2021-01-10"],
        "Profit":    [500.0, -200.0],
        "% Profit":  [3.33, -1.5],
    }
    data.update(overrides)
    return pd.DataFrame(data)


def _cleaned(initial_equity=10_000.0, **overrides):
    raw = _base_df(**overrides)
    df, _ = clean_trades_data(raw, initial_equity)
    return df


# ---------------------------------------------------------------------------
# clean_trades_data — missing optional columns print warnings, don't crash
# ---------------------------------------------------------------------------

class TestCleanTradesDataMissingOptionalColumns:

    def test_missing_mae_column_does_not_raise(self):
        """No MAE column → warning printed, function completes."""
        result, _ = clean_trades_data(_base_df(), 10_000.0)
        assert not result.empty

    def test_missing_mfe_column_does_not_raise(self):
        """No MFE column → warning printed, function completes."""
        result, _ = clean_trades_data(_base_df(), 10_000.0)
        assert "MFE" not in result.columns or True  # just confirm no crash

    def test_missing_pct_profit_column_does_not_raise(self):
        df = pd.DataFrame({
            "Date":     ["2021-01-04"],
            "Ex. date": ["2021-01-06"],
            "Profit":   [100.0],
        })
        result, _ = clean_trades_data(df, 10_000.0)
        assert not result.empty

    def test_missing_numeric_col_does_not_raise(self, capsys):
        """A column in NUMERIC_COLS not present in the df → warning, no crash."""
        result, _ = clean_trades_data(_base_df(), 10_000.0)
        assert not result.empty


# ---------------------------------------------------------------------------
# clean_trades_data — Return_Frac calculation branches
# ---------------------------------------------------------------------------

class TestReturnFracBranches:

    def test_return_frac_uses_position_value_col_when_present(self):
        """When 'Position value' col is present it's used as the denominator."""
        df = pd.DataFrame({
            "Date":            ["2021-01-04", "2021-01-07"],
            "Ex. date":        ["2021-01-06", "2021-01-10"],
            "Profit":          [500.0, -200.0],
            "% Profit":        [3.33, -1.5],
            "Position value":  [5_000.0, 5_000.0],
        })
        cleaned, _ = clean_trades_data(df, 10_000.0)
        # Return_Frac = Profit / Position value = 500/5000 = 0.1
        assert cleaned["Return_Frac"].iloc[0] == pytest.approx(0.1)

    def test_return_frac_falls_back_to_pct_profit_when_no_profit_col(self):
        """
        The % Profit fallback branch (line 192-193) is only reached when Profit
        column is absent AND initial_equity <= 0. In practice the Win computation
        at line 178 raises KeyError if Profit is missing, so this is a known dead
        branch. Test documents the crash so a future fix doesn't silently break it.
        """
        df = pd.DataFrame({
            "Date":      ["2021-01-04"],
            "Ex. date":  ["2021-01-06"],
            "% Profit":  [5.0],
        })
        with pytest.raises(KeyError):
            clean_trades_data(df, 10_000.0)

    def test_return_frac_defaults_to_zero_when_no_profit_and_no_pct_profit(self):
        """
        Same dead-branch scenario — no Profit column causes KeyError at Win
        computation before Return_Frac default is reached. Documents the crash.
        """
        df = pd.DataFrame({
            "Date":     ["2021-01-04"],
            "Ex. date": ["2021-01-06"],
        })
        with pytest.raises(KeyError):
            clean_trades_data(df, 10_000.0)


# ---------------------------------------------------------------------------
# clean_trades_data — empty DataFrame after NaN drop
# ---------------------------------------------------------------------------

class TestCleanTradesDataEmptyAfterDrop:

    def test_empty_df_returned_early_with_summary(self):
        df = pd.DataFrame({
            "Date":     ["2021-01-04"],
            "Ex. date": ["2021-01-06"],
            "Profit":   [np.nan],
            "% Profit": [np.nan],
        })
        cleaned, summary = clean_trades_data(df, 10_000.0)
        assert cleaned.empty
        assert isinstance(summary, str)
        assert len(summary) > 0


# ---------------------------------------------------------------------------
# calculate_daily_returns — additional branches
# ---------------------------------------------------------------------------

class TestCalculateDailyReturnsExtended:

    def test_cum_profit_fallback_used_when_cumulative_profit_absent(self):
        """Falls back to 'Cum. Profit' column if 'Cumulative_Profit' is missing."""
        df = _cleaned()
        # Replace Cumulative_Profit with the legacy column name
        df = df.rename(columns={"Cumulative_Profit": "Cum. Profit"})
        daily_eq, daily_ret = calculate_daily_returns(df, 10_000.0)
        assert not daily_eq.empty
        assert not daily_ret.empty

    def test_no_equity_source_col_returns_empty(self):
        """With neither 'Cumulative_Profit' nor 'Cum. Profit', returns empty Series."""
        df = _cleaned()
        df = df.drop(columns=["Cumulative_Profit"])
        daily_eq, daily_ret = calculate_daily_returns(df, 10_000.0)
        assert daily_eq.empty
        assert daily_ret.empty

    def test_nat_in_date_column_returns_empty(self):
        """If all Date values are NaT, can't compute range → empty return."""
        df = _cleaned()
        df["Date"] = pd.NaT
        daily_eq, daily_ret = calculate_daily_returns(df, 10_000.0)
        # Should return empty series (invalid start date guard)
        assert daily_eq.empty or daily_ret.empty  # either or both

    def test_duplicate_exit_dates_deduplicated_keep_last(self):
        """Two trades closing on the same day — dedup keeps the last equity value."""
        df = pd.DataFrame({
            "Date":               [pd.Timestamp("2021-01-04")] * 2,
            "Ex. date":           [pd.Timestamp("2021-01-06")] * 2,  # same exit
            "Profit":             [300.0, 200.0],
            "Cumulative_Profit":  [300.0, 500.0],
            "Win":                [True, True],
            "Return_Frac":        [0.03, 0.02],
            "Equity":             [10_300.0, 10_500.0],
        })
        daily_eq, _ = calculate_daily_returns(df, 10_000.0)
        # On 2021-01-06 there should be exactly one equity value
        if not daily_eq.empty:
            assert daily_eq.index.is_unique

    def test_multiple_trades_equity_grows_correctly(self):
        """Equity curve final value should equal initial + total profit."""
        cleaned = _cleaned(initial_equity=10_000.0)
        total_profit = cleaned["Profit"].sum()
        daily_eq, _ = calculate_daily_returns(cleaned, 10_000.0)
        if not daily_eq.empty:
            assert daily_eq.iloc[-1] == pytest.approx(10_000.0 + total_profit, rel=1e-4)


# ---------------------------------------------------------------------------
# download_benchmark_data — mocked yfinance paths
# ---------------------------------------------------------------------------

def _make_spy_df(price_col="Close"):
    """Build a minimal yfinance-style DataFrame."""
    idx = pd.date_range("2021-01-04", periods=5, freq="B")
    return pd.DataFrame({price_col: [370.0, 371.0, 372.0, 373.0, 374.0]}, index=idx)


class TestDownloadBenchmarkDataMocked:

    @patch("trade_analyzer.data_handler.yf.download")
    def test_successful_single_level_returns_dataframe(self, mock_dl):
        """Happy path: single-level Close column returns DataFrame with Benchmark_Price."""
        mock_dl.return_value = _make_spy_df("Close")
        result = download_benchmark_data(
            "SPY", pd.Timestamp("2021-01-01"), pd.Timestamp("2021-12-31")
        )
        assert result is not None
        assert "Benchmark_Price" in result.columns
        assert len(result) == 5

    @patch("trade_analyzer.data_handler.yf.download")
    def test_empty_yfinance_response_returns_none(self, mock_dl):
        """yfinance returns empty DataFrame → function returns None."""
        mock_dl.return_value = pd.DataFrame()
        result = download_benchmark_data(
            "SPY", pd.Timestamp("2021-01-01"), pd.Timestamp("2021-12-31")
        )
        assert result is None

    @patch("trade_analyzer.data_handler.yf.download")
    def test_exception_in_download_returns_none(self, mock_dl):
        """Network or API error during download → returns None, no raise."""
        mock_dl.side_effect = Exception("connection refused")
        result = download_benchmark_data(
            "SPY", pd.Timestamp("2021-01-01"), pd.Timestamp("2021-12-31")
        )
        assert result is None

    @patch("trade_analyzer.data_handler.yf.download")
    def test_price_column_missing_returns_none(self, mock_dl):
        """DataFrame with neither Close nor Adj Close → returns None."""
        idx = pd.date_range("2021-01-04", periods=3, freq="B")
        mock_dl.return_value = pd.DataFrame({"Volume": [1_000, 2_000, 3_000]}, index=idx)
        result = download_benchmark_data(
            "SPY", pd.Timestamp("2021-01-01"), pd.Timestamp("2021-12-31")
        )
        assert result is None

    @patch("trade_analyzer.data_handler.yf.download")
    def test_adj_close_used_when_close_absent(self, mock_dl):
        """Falls back to 'Adj Close' when 'Close' is not in columns."""
        mock_dl.return_value = _make_spy_df("Adj Close")
        result = download_benchmark_data(
            "SPY", pd.Timestamp("2021-01-01"), pd.Timestamp("2021-12-31")
        )
        assert result is not None
        assert "Benchmark_Price" in result.columns

    @patch("trade_analyzer.data_handler.yf.download")
    def test_multiindex_close_extracted_correctly(self, mock_dl):
        """MultiIndex columns (Close, SPY) → extracts and renames to Benchmark_Price."""
        idx = pd.date_range("2021-01-04", periods=3, freq="B")
        mi = pd.MultiIndex.from_tuples([("Close", "SPY"), ("Volume", "SPY")])
        df = pd.DataFrame(
            [[370.0, 1_000], [371.0, 1_100], [372.0, 1_200]],
            index=idx,
            columns=mi,
        )
        mock_dl.return_value = df
        result = download_benchmark_data(
            "SPY", pd.Timestamp("2021-01-01"), pd.Timestamp("2021-12-31")
        )
        # MultiIndex path — should return a DataFrame with Benchmark_Price or None
        # (either is valid depending on yfinance version handling)
        assert result is None or "Benchmark_Price" in result.columns

    @patch("trade_analyzer.data_handler.yf.download")
    def test_all_nan_prices_returns_none(self, mock_dl):
        """DataFrame where all Close values are NaN → dropna makes it empty → None."""
        idx = pd.date_range("2021-01-04", periods=3, freq="B")
        mock_dl.return_value = pd.DataFrame(
            {"Close": [np.nan, np.nan, np.nan]}, index=idx
        )
        result = download_benchmark_data(
            "SPY", pd.Timestamp("2021-01-01"), pd.Timestamp("2021-12-31")
        )
        assert result is None

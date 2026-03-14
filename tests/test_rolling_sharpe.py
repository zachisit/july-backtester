# tests/test_rolling_sharpe.py
"""
Unit tests for calculate_rolling_sharpe in helpers/simulations.py.

Covers:
  TestRollingSharpeLengthAndNaN  — output shape and NaN boundaries
  TestRollingSharpeValues        — direction and magnitude sanity checks
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.simulations import calculate_rolling_sharpe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _equity_curve(daily_returns, initial=100_000):
    """Build a pd.Series equity curve from a list of daily returns."""
    prices = [initial]
    for r in daily_returns:
        prices.append(prices[-1] * (1 + r))
    dates = pd.date_range("2020-01-02", periods=len(prices), freq="B")
    return pd.Series(prices, index=dates)


def _flat_equity(n=200):
    """Equity curve with zero daily return (constant value)."""
    return _equity_curve([0.0] * n)


def _uptrend_equity(n=200, daily_return=0.002, noise=0.005):
    """Noisy uptrend: small positive drift + random noise."""
    rng = np.random.default_rng(42)
    returns = daily_return + rng.normal(0, noise, n)
    return _equity_curve(returns)


# ---------------------------------------------------------------------------
# TestRollingSharpeLengthAndNaN
# ---------------------------------------------------------------------------

class TestRollingSharpeLengthAndNaN:

    def test_output_length_matches_input(self):
        """Output series must have the same length as the input equity curve."""
        tl = _uptrend_equity(n=200)
        rs = calculate_rolling_sharpe(tl, window=126, risk_free_rate=0.0)
        assert len(rs) == len(tl)

    def test_first_window_minus_one_values_are_nan(self):
        """The first 126 values (indices 0..125) must all be NaN.

        pct_change() produces NaN at index 0, so rolling(126) fills at index 126
        (the 126 valid returns occupy indices 1-126 of the equity curve).
        """
        tl = _uptrend_equity(n=200)
        rs = calculate_rolling_sharpe(tl, window=126, risk_free_rate=0.0)
        assert rs.iloc[:126].isna().all(), (
            "Expected all NaN before the window is filled"
        )

    def test_first_non_nan_at_index_window(self):
        """The value at index 126 must be non-NaN (first complete 126-bar window)."""
        tl = _uptrend_equity(n=200)
        rs = calculate_rolling_sharpe(tl, window=126, risk_free_rate=0.0)
        assert pd.notna(rs.iloc[126]), "Expected first non-NaN at index 126 (window=126)"

    def test_returns_pd_series(self):
        """Return type must be pd.Series."""
        tl = _uptrend_equity(n=200)
        rs = calculate_rolling_sharpe(tl, window=126)
        assert isinstance(rs, pd.Series)

    def test_shorter_than_window_all_nan(self):
        """When equity curve is shorter than the window, all values should be NaN."""
        tl = _uptrend_equity(n=50)
        rs = calculate_rolling_sharpe(tl, window=126, risk_free_rate=0.0)
        assert rs.dropna().empty, "Expected all NaN when series shorter than window"


# ---------------------------------------------------------------------------
# TestRollingSharpeValues
# ---------------------------------------------------------------------------

class TestRollingSharpeValues:

    def test_flat_equity_nan_sharpe(self):
        """Zero volatility (flat equity) must produce NaN, not inf or a number."""
        tl = _flat_equity(n=200)
        rs = calculate_rolling_sharpe(tl, window=126, risk_free_rate=0.0)
        non_nan = rs.dropna()
        # All windows that complete should be NaN due to zero std
        assert non_nan.empty or non_nan.isna().all(), (
            f"Expected NaN for zero-vol equity; got {non_nan.dropna().head()}"
        )

    def test_positive_sharpe_uptrend(self):
        """A noisy uptrend should produce predominantly positive rolling Sharpe values."""
        tl = _uptrend_equity(n=300, daily_return=0.003, noise=0.005)
        rs = calculate_rolling_sharpe(tl, window=126, risk_free_rate=0.0)
        valid = rs.dropna()
        positive_frac = (valid > 0).mean()
        assert positive_frac > 0.5, (
            f"Expected >50% positive windows for uptrend; got {positive_frac:.1%}"
        )

    def test_rf_rate_reduces_sharpe(self):
        """Rolling Sharpe with rf=0.05 should have a lower mean than with rf=0.0."""
        tl = _uptrend_equity(n=300)
        rs_no_rf = calculate_rolling_sharpe(tl, window=63, risk_free_rate=0.0).dropna()
        rs_with_rf = calculate_rolling_sharpe(tl, window=63, risk_free_rate=0.05).dropna()
        assert rs_with_rf.mean() < rs_no_rf.mean(), (
            "Higher risk-free rate should lower the rolling Sharpe mean"
        )

    def test_smaller_window_more_values(self):
        """window=63 must produce more non-NaN values than window=126 for same input."""
        tl = _uptrend_equity(n=200)
        rs_63  = calculate_rolling_sharpe(tl, window=63,  risk_free_rate=0.0).dropna()
        rs_126 = calculate_rolling_sharpe(tl, window=126, risk_free_rate=0.0).dropna()
        assert len(rs_63) > len(rs_126), (
            f"Expected more non-NaN values for smaller window; "
            f"got {len(rs_63)} (w=63) vs {len(rs_126)} (w=126)"
        )

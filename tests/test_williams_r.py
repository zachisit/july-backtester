# tests/test_williams_r.py
"""
Unit tests for Williams %R indicator and Oversold Bounce strategy (Task 5).

Covers:
  calculate_williams_r — column creation, value range, formula correctness
  williams_r_logic     — entry/exit signals, oversold bounce, overbought rejection
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.indicators import calculate_williams_r, williams_r_logic


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(closes, highs=None, lows=None, start="2020-01-01"):
    """Build an OHLCV DataFrame with optional custom highs/lows."""
    n = len(closes)
    dates = pd.bdate_range(start=start, periods=n, freq="B")
    if highs is None:
        highs = [c * 1.01 for c in closes]
    if lows is None:
        lows = [c * 0.99 for c in closes]
    df = pd.DataFrame({
        "Open":   [c * 0.999 for c in closes],
        "High":   highs,
        "Low":    lows,
        "Close":  closes,
        "Volume": [1_000_000] * n,
    }, index=dates)
    df.index.name = "Datetime"
    return df


def _make_oversold_bounce_data(n=60):
    """
    Price drops sharply then recovers — triggers oversold bounce.
    First 30 bars: stable at 100.
    Bars 30-40: drop to 85 (oversold).
    Bars 40-60: recover to 100 (mean reversion).
    """
    closes = [100.0] * 30
    for i in range(10):
        closes.append(100.0 - i * 1.5)  # drops to 85
    for i in range(20):
        closes.append(85.0 + i * 0.75)  # recovers to 100
    return _make_ohlcv(closes)


def _make_uptrend_data(n=60):
    """Steady uptrend — %R should stay near 0 (overbought), no buy signals."""
    closes = [100.0 * (1.005 ** i) for i in range(n)]
    return _make_ohlcv(closes)


# ---------------------------------------------------------------------------
# TestCalculateWilliamsR
# ---------------------------------------------------------------------------

class TestCalculateWilliamsR:

    def test_column_created(self):
        """calculate_williams_r must add a WilliamsR_{length} column."""
        df = _make_ohlcv([100.0] * 30)
        result = calculate_williams_r(df, length=14)
        assert "WilliamsR_14" in result.columns

    def test_custom_length_column(self):
        """Custom length should create the correct column name."""
        df = _make_ohlcv([100.0] * 30)
        result = calculate_williams_r(df, length=21)
        assert "WilliamsR_21" in result.columns

    def test_values_in_range(self):
        """Williams %R must be between -100 and 0 (after warm-up)."""
        df = _make_oversold_bounce_data()
        result = calculate_williams_r(df, length=14)
        valid = result["WilliamsR_14"].dropna()
        assert (valid >= -100).all(), f"Values below -100: {valid.min()}"
        assert (valid <= 0).all(), f"Values above 0: {valid.max()}"

    def test_nan_during_warmup(self):
        """First length-1 values should be NaN (insufficient data)."""
        df = _make_ohlcv([100.0] * 30)
        result = calculate_williams_r(df, length=14)
        assert result["WilliamsR_14"].iloc[:13].isna().all()

    def test_close_at_high_gives_zero(self):
        """When Close equals the Highest High, %R should be 0."""
        # All closes at the high of the range
        closes = [100.0 + i for i in range(20)]
        highs = [c for c in closes]  # High == Close
        lows = [c - 5.0 for c in closes]
        df = _make_ohlcv(closes, highs=highs, lows=lows)
        result = calculate_williams_r(df, length=14)
        last_val = result["WilliamsR_14"].iloc[-1]
        assert abs(last_val - 0.0) < 1e-10, f"Expected 0, got {last_val}"

    def test_close_at_low_gives_minus_100(self):
        """When Close equals the Lowest Low, %R should be -100."""
        # All closes at the low of the range
        closes = [100.0 - i for i in range(20)]
        highs = [c + 5.0 for c in closes]
        lows = [c for c in closes]  # Low == Close
        df = _make_ohlcv(closes, highs=highs, lows=lows)
        result = calculate_williams_r(df, length=14)
        last_val = result["WilliamsR_14"].iloc[-1]
        assert abs(last_val - (-100.0)) < 1e-10, f"Expected -100, got {last_val}"

    def test_idempotent(self):
        """Calling calculate_williams_r twice should not change the result."""
        df = _make_oversold_bounce_data()
        result1 = calculate_williams_r(df.copy(), length=14)
        result2 = calculate_williams_r(result1.copy(), length=14)
        pd.testing.assert_series_equal(result1["WilliamsR_14"], result2["WilliamsR_14"])


# ---------------------------------------------------------------------------
# TestWilliamsRLogic
# ---------------------------------------------------------------------------

class TestWilliamsRLogic:

    def test_signal_column_exists(self):
        """Strategy must add a Signal column."""
        df = _make_oversold_bounce_data()
        result = williams_r_logic(df)
        assert "Signal" in result.columns

    def test_signal_values_valid(self):
        """Signal must only contain 1, -1, or 0."""
        df = _make_oversold_bounce_data()
        result = williams_r_logic(df)
        valid = result["Signal"].isin([1, -1, 0])
        assert valid.all(), f"Invalid values: {result['Signal'].unique()}"

    def test_entry_on_oversold_bounce(self):
        """Price dropping then recovering should trigger a buy signal."""
        df = _make_oversold_bounce_data()
        result = williams_r_logic(df, length=14, oversold=-80, exit_level=-50)
        signals_after_drop = result["Signal"].iloc[30:]
        assert (signals_after_drop == 1).any(), "Expected buy signal after oversold bounce"

    def test_exit_on_mean_reversion(self):
        """After entry, price recovery should trigger an exit."""
        df = _make_oversold_bounce_data()
        result = williams_r_logic(df, length=14, oversold=-80, exit_level=-50)
        signals_recovery = result["Signal"].iloc[40:]
        assert (signals_recovery == -1).any(), "Expected exit after mean reversion"

    def test_uptrend_no_buy(self):
        """In a steady uptrend, %R stays near 0 — no oversold bounce expected."""
        df = _make_uptrend_data()
        result = williams_r_logic(df, length=14, oversold=-80, exit_level=-50)
        buy_count = (result["Signal"] == 1).sum()
        assert buy_count == 0, f"Expected 0 buys in uptrend, got {buy_count}"

    def test_output_length_unchanged(self):
        """Strategy must not add or remove rows."""
        df = _make_oversold_bounce_data()
        n_before = len(df)
        result = williams_r_logic(df)
        assert len(result) == n_before

    def test_custom_parameters(self):
        """Strategy should accept custom parameters without crashing."""
        df = _make_oversold_bounce_data()
        result = williams_r_logic(df, length=21, oversold=-90, exit_level=-40)
        assert "Signal" in result.columns

    def test_short_data_no_crash(self):
        """Strategy should handle DataFrames shorter than lookback."""
        df = _make_ohlcv([100.0] * 5)
        result = williams_r_logic(df, length=14)
        assert "Signal" in result.columns

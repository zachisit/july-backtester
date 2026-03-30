# tests/test_volume_weighted_rsi.py
"""
Unit tests for Volume-Weighted RSI indicator and strategy (Task 6).

Covers:
  calculate_volume_weighted_rsi — column creation, value range, volume weighting effect
  volume_weighted_rsi_logic     — entry/exit signals, oversold bounce, uptrend behavior
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.indicators import calculate_volume_weighted_rsi, volume_weighted_rsi_logic, calculate_rsi


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(closes, volumes=None, start="2020-01-01"):
    """Build an OHLCV DataFrame."""
    n = len(closes)
    dates = pd.bdate_range(start=start, periods=n, freq="B")
    if volumes is None:
        volumes = [1_000_000] * n
    df = pd.DataFrame({
        "Open":   [c * 0.999 for c in closes],
        "High":   [c * 1.01 for c in closes],
        "Low":    [c * 0.99 for c in closes],
        "Close":  closes,
        "Volume": volumes,
    }, index=dates)
    df.index.name = "Datetime"
    return df


def _make_oversold_bounce_data(n=60, volumes=None):
    """Price drops then recovers — triggers oversold bounce."""
    closes = [100.0] * 30
    for i in range(10):
        closes.append(100.0 - i * 1.5)
    for i in range(20):
        closes.append(85.0 + i * 0.75)
    return _make_ohlcv(closes, volumes=volumes)


def _make_uptrend_data(n=60):
    """Steady uptrend — VWRSI should stay high, no buy signals."""
    closes = [100.0 * (1.005 ** i) for i in range(n)]
    return _make_ohlcv(closes)


# ---------------------------------------------------------------------------
# TestCalculateVolumeWeightedRsi
# ---------------------------------------------------------------------------

class TestCalculateVolumeWeightedRsi:

    def test_column_created(self):
        """Must add a VWRSI_{length} column."""
        df = _make_ohlcv([100.0] * 30)
        result = calculate_volume_weighted_rsi(df, length=14)
        assert "VWRSI_14" in result.columns

    def test_custom_length_column(self):
        """Custom length should create the correct column name."""
        df = _make_ohlcv([100.0] * 30)
        result = calculate_volume_weighted_rsi(df, length=7)
        assert "VWRSI_7" in result.columns

    def test_values_in_range(self):
        """VWRSI values must be between 0 and 100 (after warm-up)."""
        df = _make_oversold_bounce_data()
        result = calculate_volume_weighted_rsi(df, length=14)
        valid = result["VWRSI_14"].dropna()
        assert (valid >= 0).all(), f"Values below 0: {valid.min()}"
        assert (valid <= 100).all(), f"Values above 100: {valid.max()}"

    def test_differs_from_standard_rsi_with_volume_spike(self):
        """
        VWRSI should differ from standard RSI when volume varies significantly.
        High-volume down days followed by low-volume recovery should produce
        a lower VWRSI than standard RSI, since the volume-weighted losses
        are amplified relative to the unweighted recovery gains.
        """
        # Oscillating prices with volume spikes on down moves
        closes = [100.0 + i * 0.5 for i in range(20)]  # gentle uptrend
        closes += [108.0, 105.0, 102.0, 99.0, 96.0]    # sharp drop
        closes += [97.0, 98.0, 99.0, 100.0, 101.0]     # gentle recovery
        # High volume on the drop, low volume on the recovery
        volumes = [1_000_000] * 20 + [5_000_000] * 5 + [500_000] * 5
        df = _make_ohlcv(closes, volumes=volumes)

        df_vw = calculate_volume_weighted_rsi(df.copy(), length=14)
        df_std = calculate_rsi(df.copy(), length=14)

        vwrsi_last = df_vw["VWRSI_14"].iloc[-1]
        rsi_last = df_std["RSI_14"].iloc[-1]

        # They should differ — volume weighting amplifies the heavy-volume losses
        assert abs(vwrsi_last - rsi_last) > 0.1, (
            f"VWRSI ({vwrsi_last:.2f}) should differ from RSI ({rsi_last:.2f}) "
            f"when volume spikes on down days"
        )

    def test_uniform_volume_similar_to_standard_rsi(self):
        """With perfectly uniform volume, VWRSI should be close to standard RSI."""
        closes = [100.0 + np.sin(i * 0.3) * 5 for i in range(40)]
        volumes = [1_000_000] * 40  # perfectly uniform
        df = _make_ohlcv(closes, volumes=volumes)

        df_vw = calculate_volume_weighted_rsi(df.copy(), length=14)
        df_std = calculate_rsi(df.copy(), length=14)

        # With uniform volume, weights are all ~1.0, so values should be similar
        vwrsi = df_vw["VWRSI_14"].dropna().iloc[-1]
        rsi = df_std["RSI_14"].dropna().iloc[-1]
        assert abs(vwrsi - rsi) < 10, (
            f"With uniform volume, VWRSI ({vwrsi:.2f}) and RSI ({rsi:.2f}) "
            f"should be similar"
        )

    def test_idempotent(self):
        """Calling calculate_volume_weighted_rsi twice should not change the result."""
        df = _make_oversold_bounce_data()
        result1 = calculate_volume_weighted_rsi(df.copy(), length=14)
        result2 = calculate_volume_weighted_rsi(result1.copy(), length=14)
        pd.testing.assert_series_equal(result1["VWRSI_14"], result2["VWRSI_14"])

    def test_zero_volume_no_crash(self):
        """Zero volume bars should not cause division errors."""
        closes = [100.0 + i * 0.5 for i in range(30)]
        volumes = [0] * 30
        df = _make_ohlcv(closes, volumes=volumes)
        result = calculate_volume_weighted_rsi(df, length=14)
        assert "VWRSI_14" in result.columns
        # Should have values (NaN is ok for warm-up, but no crash)


# ---------------------------------------------------------------------------
# TestVolumeWeightedRsiLogic
# ---------------------------------------------------------------------------

class TestVolumeWeightedRsiLogic:

    def test_signal_column_exists(self):
        """Strategy must add a Signal column."""
        df = _make_oversold_bounce_data()
        result = volume_weighted_rsi_logic(df)
        assert "Signal" in result.columns

    def test_signal_values_valid(self):
        """Signal must only contain 1, -1, or 0."""
        df = _make_oversold_bounce_data()
        result = volume_weighted_rsi_logic(df)
        valid = result["Signal"].isin([1, -1, 0])
        assert valid.all(), f"Invalid values: {result['Signal'].unique()}"

    def test_entry_on_oversold_bounce(self):
        """Price drop with high volume should trigger a buy signal."""
        # Use high volume on down days to push VWRSI deeply oversold
        volumes = [1_000_000] * 30 + [3_000_000] * 10 + [1_000_000] * 20
        df = _make_oversold_bounce_data(volumes=volumes)
        result = volume_weighted_rsi_logic(df, length=14, oversold=30, exit_level=50)
        signals_after_drop = result["Signal"].iloc[30:]
        assert (signals_after_drop == 1).any(), "Expected buy signal after oversold bounce"

    def test_exit_after_recovery(self):
        """After entry, VWRSI crossing above exit_level should trigger exit."""
        volumes = [1_000_000] * 30 + [3_000_000] * 10 + [1_000_000] * 20
        df = _make_oversold_bounce_data(volumes=volumes)
        result = volume_weighted_rsi_logic(df, length=14, oversold=30, exit_level=50)
        signals_recovery = result["Signal"].iloc[40:]
        assert (signals_recovery == -1).any(), "Expected exit after recovery"

    def test_uptrend_no_buy(self):
        """In a steady uptrend, VWRSI stays high — no oversold bounce expected."""
        df = _make_uptrend_data()
        result = volume_weighted_rsi_logic(df, length=14, oversold=30, exit_level=50)
        buy_count = (result["Signal"] == 1).sum()
        assert buy_count == 0, f"Expected 0 buys in uptrend, got {buy_count}"

    def test_output_length_unchanged(self):
        """Strategy must not add or remove rows."""
        df = _make_oversold_bounce_data()
        n_before = len(df)
        result = volume_weighted_rsi_logic(df)
        assert len(result) == n_before

    def test_custom_parameters(self):
        """Strategy should accept custom parameters without crashing."""
        df = _make_oversold_bounce_data()
        result = volume_weighted_rsi_logic(df, length=7, oversold=20, exit_level=60)
        assert "Signal" in result.columns

    def test_short_data_no_crash(self):
        """Strategy should handle DataFrames shorter than lookback."""
        df = _make_ohlcv([100.0] * 5)
        result = volume_weighted_rsi_logic(df, length=14)
        assert "Signal" in result.columns

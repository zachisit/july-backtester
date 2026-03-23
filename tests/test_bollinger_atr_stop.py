# tests/test_bollinger_atr_stop.py
"""
Unit tests for the Bollinger Band Mean Reversion with ATR Stop strategy (Task 4).

Covers:
  - Signal column exists and contains valid values
  - Entry fires when close drops below lower band
  - Exit fires when close reaches middle band (mean reversion)
  - ATR stop triggers on sharp downmove after entry
  - No entry when price stays above lower band
  - Output length unchanged
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.indicators import bollinger_mean_reversion_atr_stop_logic


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ohlcv(closes, start="2020-01-01"):
    """Build a minimal OHLCV DataFrame from a list of close prices."""
    n = len(closes)
    dates = pd.bdate_range(start=start, periods=n, freq="B")
    df = pd.DataFrame({
        "Open":   [c * 0.999 for c in closes],
        "High":   [c * 1.01 for c in closes],
        "Low":    [c * 0.99 for c in closes],
        "Close":  closes,
        "Volume": [1_000_000] * n,
    }, index=dates)
    df.index.name = "Datetime"
    return df


def _make_mean_reversion_data(n=80):
    """
    Build data where price dips below the lower band then recovers to the mean.
    First 40 bars: stable around 100 (establishes bands).
    Bars 40-55: sharp drop to 90 (below lower band → entry trigger).
    Bars 55-80: recovery back to 100 (reaches middle band → exit trigger).
    """
    closes = [100.0] * 40
    # Sharp dip
    for i in range(15):
        closes.append(100.0 - i * 0.8)  # drops to ~88
    # Recovery
    for i in range(25):
        closes.append(88.0 + i * 0.5)  # recovers to ~100.5
    return _make_ohlcv(closes)


def _make_crash_data(n=80):
    """
    Build data where price dips below the lower band then keeps falling.
    This should trigger the ATR stop loss.
    First 40 bars: stable around 100.
    Bars 40-80: continuous decline to 70.
    """
    closes = [100.0] * 40
    for i in range(40):
        closes.append(100.0 - i * 0.75)  # drops to ~70
    return _make_ohlcv(closes)


def _make_flat_data(n=80):
    """Build flat data that stays well within the bands — no entry expected."""
    closes = [100.0 + np.sin(i * 0.1) * 0.5 for i in range(n)]
    return _make_ohlcv(closes)


# ---------------------------------------------------------------------------
# TestBollingerMeanReversionAtrStop
# ---------------------------------------------------------------------------

class TestBollingerMeanReversionAtrStop:

    def test_signal_column_exists(self):
        """Strategy must add a 'Signal' column to the DataFrame."""
        df = _make_mean_reversion_data()
        result = bollinger_mean_reversion_atr_stop_logic(df)
        assert "Signal" in result.columns

    def test_signal_values_valid(self):
        """Signal must only contain 1, -1, or 0."""
        df = _make_mean_reversion_data()
        result = bollinger_mean_reversion_atr_stop_logic(df)
        valid = result["Signal"].isin([1, -1, 0])
        assert valid.all(), f"Invalid signal values: {result['Signal'].unique()}"

    def test_entry_on_lower_band_touch(self):
        """Price dropping below the lower band should trigger an entry (Signal = 1)."""
        df = _make_mean_reversion_data()
        result = bollinger_mean_reversion_atr_stop_logic(df, length=20, std_dev=2.0)
        # After the dip (bars 40+), we should see at least one buy signal
        signals_after_dip = result["Signal"].iloc[40:]
        assert (signals_after_dip == 1).any(), "Expected at least one entry after lower band touch"

    def test_exit_on_middle_band_reach(self):
        """Price recovering to the middle band should trigger an exit (Signal = -1)."""
        df = _make_mean_reversion_data()
        result = bollinger_mean_reversion_atr_stop_logic(df, length=20, std_dev=2.0)
        # After recovery (bars 55+), we should see an exit
        signals_recovery = result["Signal"].iloc[55:]
        assert (signals_recovery == -1).any(), "Expected exit after price reaches middle band"

    def test_stop_loss_triggers_on_crash(self):
        """In a continuous decline, the ATR stop should trigger an exit."""
        df = _make_crash_data()
        result = bollinger_mean_reversion_atr_stop_logic(
            df, length=20, std_dev=2.0, atr_period=14, atr_multiplier=2.0
        )
        # After the crash starts (bar 40+), we should see entry then exit
        signals_crash = result["Signal"].iloc[40:]
        has_entry = (signals_crash == 1).any()
        has_exit = (signals_crash == -1).any()
        if has_entry:
            assert has_exit, "Entry happened but stop loss never triggered during crash"

    def test_no_entry_on_flat_data(self):
        """Constant price data should produce no entries — price never breaches the bands."""
        # Use perfectly constant closes so StdDev is 0 and bands collapse to the SMA.
        # With std_dev=3.0 and zero volatility, LowerBand == SMA == Close, so
        # Close < LowerBand is never true.
        df = _make_ohlcv([100.0] * 80)
        result = bollinger_mean_reversion_atr_stop_logic(df, length=20, std_dev=3.0)
        buy_count = (result["Signal"] == 1).sum()
        assert buy_count == 0, f"Expected 0 entries on constant data, got {buy_count}"

    def test_output_length_unchanged(self):
        """Strategy must not add or remove rows."""
        df = _make_mean_reversion_data()
        n_before = len(df)
        result = bollinger_mean_reversion_atr_stop_logic(df)
        assert len(result) == n_before

    def test_custom_parameters(self):
        """Strategy should accept custom parameters without crashing."""
        df = _make_mean_reversion_data()
        result = bollinger_mean_reversion_atr_stop_logic(
            df, length=15, std_dev=1.5, atr_period=10, atr_multiplier=3.0
        )
        assert "Signal" in result.columns
        assert len(result) == len(df)

    def test_short_data_no_crash(self):
        """Strategy should handle short DataFrames (< lookback) without crashing."""
        df = _make_ohlcv([100.0] * 10)
        result = bollinger_mean_reversion_atr_stop_logic(df, length=20)
        assert "Signal" in result.columns

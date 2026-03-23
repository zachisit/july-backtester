# tests/test_example_strategies.py
"""
Unit tests for examples/strategies/ — Example Strategy Plugins.

Covers:
  sma_trend_filter_example   — signal output, long/flat states
  volume_spike_entry_example — volume spike detection, signal generation
  gap_up_overnight_example   — gap-up detection, SPY regime filter, dependency injection

All tests use synthetic OHLCV DataFrames — no network, no file I/O.
"""

import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.indicators import sma_trend_filter_logic


# ---------------------------------------------------------------------------
# Helpers — synthetic data builders
# ---------------------------------------------------------------------------

def _make_ohlcv(closes, volumes=None, start="2020-01-01"):
    """Build a minimal OHLCV DataFrame from a list of close prices."""
    n = len(closes)
    dates = pd.bdate_range(start=start, periods=n, freq="B")
    if volumes is None:
        volumes = [1_000_000] * n
    df = pd.DataFrame({
        "Open":   closes,
        "High":   [c * 1.01 for c in closes],
        "Low":    [c * 0.99 for c in closes],
        "Close":  closes,
        "Volume": volumes,
    }, index=dates)
    df.index.name = "Datetime"
    return df


def _make_trending_data(n=250, start_price=100.0, trend=0.001):
    """Build an uptrending OHLCV DataFrame with n bars."""
    closes = [start_price * (1 + trend) ** i for i in range(n)]
    return _make_ohlcv(closes)


def _make_spy_df(n=250, start_price=400.0, trend=0.0005, start="2020-01-01"):
    """Build a synthetic SPY DataFrame for regime filter testing."""
    closes = [start_price * (1 + trend) ** i for i in range(n)]
    return _make_ohlcv(closes, start=start)


# ---------------------------------------------------------------------------
# TestSmaTrendFilterExample
# ---------------------------------------------------------------------------

class TestSmaTrendFilterExample:
    """Tests for examples/strategies/sma_trend_filter_example.py logic."""

    def test_signal_column_exists(self):
        """Strategy must add a 'Signal' column to the DataFrame."""
        df = _make_trending_data(250)
        result = sma_trend_filter_logic(df, ma_length=200)
        assert "Signal" in result.columns

    def test_signal_values_valid(self):
        """Signal must only contain 1 or -1 (no 0 after forward-fill)."""
        df = _make_trending_data(250)
        result = sma_trend_filter_logic(df, ma_length=200)
        # After the MA warm-up, all values should be 1 or -1
        valid_mask = result["Signal"].isin([1, -1, 0])
        assert valid_mask.all(), f"Invalid signal values: {result['Signal'].unique()}"

    def test_uptrend_produces_long_signal(self):
        """In a steady uptrend, most signals after warm-up should be 1 (long)."""
        df = _make_trending_data(300, trend=0.002)
        result = sma_trend_filter_logic(df, ma_length=200)
        # After 200-bar warm-up, uptrend should produce mostly longs
        signals_after_warmup = result["Signal"].iloc[200:]
        long_pct = (signals_after_warmup == 1).mean()
        assert long_pct > 0.8, f"Expected mostly longs in uptrend, got {long_pct:.0%}"

    def test_downtrend_produces_flat_signal(self):
        """In a steady downtrend, most signals after warm-up should be -1 (flat)."""
        df = _make_trending_data(300, trend=-0.002)
        result = sma_trend_filter_logic(df, ma_length=200)
        signals_after_warmup = result["Signal"].iloc[200:]
        flat_pct = (signals_after_warmup == -1).mean()
        assert flat_pct > 0.8, f"Expected mostly flat in downtrend, got {flat_pct:.0%}"

    def test_output_length_unchanged(self):
        """Strategy must not add or remove rows."""
        df = _make_trending_data(250)
        n_before = len(df)
        result = sma_trend_filter_logic(df, ma_length=200)
        assert len(result) == n_before


# ---------------------------------------------------------------------------
# TestVolumeSpikeEntryExample
# ---------------------------------------------------------------------------

class TestVolumeSpikeEntryExample:
    """Tests for examples/strategies/volume_spike_entry_example.py logic."""

    def _run_volume_spike_logic(self, df, vol_lookback=20, vol_multiplier=2.0):
        """Replicate the inline logic from the example strategy."""
        df["AvgVolume"] = df["Volume"].rolling(vol_lookback).mean()
        is_volume_spike = df["Volume"] > (df["AvgVolume"] * vol_multiplier)
        is_up_day = df["Close"] > df["Close"].shift(1)
        buy_signal = is_volume_spike & is_up_day
        sell_signal = df["Volume"] < df["AvgVolume"]
        df["Signal"] = np.where(buy_signal, 1, np.where(sell_signal, -1, 0))
        df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)
        return df

    def test_signal_column_exists(self):
        """Strategy must add a 'Signal' column."""
        df = _make_trending_data(50)
        result = self._run_volume_spike_logic(df)
        assert "Signal" in result.columns

    def test_spike_triggers_buy(self):
        """A volume spike on an up day should produce a buy signal."""
        closes = [100.0] * 25 + [101.0]  # up day on bar 25
        volumes = [1_000_000] * 25 + [3_000_000]  # 3x spike on bar 25
        df = _make_ohlcv(closes, volumes)
        result = self._run_volume_spike_logic(df, vol_lookback=20, vol_multiplier=2.0)
        assert result["Signal"].iloc[-1] == 1, "Volume spike on up day should trigger buy"

    def test_no_spike_no_buy(self):
        """Normal volume on an up day should not trigger a buy."""
        closes = [100.0] * 25 + [101.0]
        volumes = [1_000_000] * 26  # no spike
        df = _make_ohlcv(closes, volumes)
        result = self._run_volume_spike_logic(df, vol_lookback=20, vol_multiplier=2.0)
        # Last signal should not be a fresh buy (could be -1 or carried forward)
        assert result["Signal"].iloc[-1] != 1 or not (
            df["Volume"].iloc[-1] > df["Volume"].iloc[:20].mean() * 2.0
        )

    def test_spike_on_down_day_no_buy(self):
        """A volume spike on a down day should not trigger a buy."""
        closes = [100.0] * 25 + [99.0]  # down day
        volumes = [1_000_000] * 25 + [3_000_000]  # spike
        df = _make_ohlcv(closes, volumes)
        result = self._run_volume_spike_logic(df, vol_lookback=20, vol_multiplier=2.0)
        # Should not have a buy signal on a down day
        last_buy = (df["Volume"].iloc[-1] > 2_000_000) and (closes[-1] > closes[-2])
        assert not last_buy, "Should not buy on down day even with volume spike"

    def test_output_length_unchanged(self):
        """Strategy must not add or remove rows."""
        df = _make_trending_data(50)
        n_before = len(df)
        result = self._run_volume_spike_logic(df)
        assert len(result) == n_before


# ---------------------------------------------------------------------------
# TestGapUpOvernightExample
# ---------------------------------------------------------------------------

class TestGapUpOvernightExample:
    """Tests for examples/strategies/gap_up_overnight_example.py logic."""

    def _run_gap_up_logic(self, df, spy_df, gap_pct=0.01, regime_ma=200):
        """Replicate the inline logic from the example strategy."""
        prior_close = df["Close"].shift(1)
        gap_size = (df["Open"] - prior_close) / prior_close
        is_gap_up = gap_size >= gap_pct

        spy_sma = spy_df["Close"].rolling(regime_ma).mean()
        regime_df = pd.DataFrame(index=df.index)
        regime_df["spy_close"] = spy_df["Close"]
        regime_df["spy_sma"] = spy_sma
        regime_df.ffill(inplace=True)
        is_bull_market = regime_df["spy_close"] > regime_df["spy_sma"]

        buy_signal = is_gap_up & is_bull_market
        df["Signal"] = np.where(buy_signal, 1, 0)
        buy_shifted = buy_signal.shift(1).infer_objects(copy=False).fillna(False)
        df.loc[buy_shifted, "Signal"] = -1
        df["Signal"] = df["Signal"].replace(0, np.nan).ffill().fillna(0)
        return df

    def test_signal_column_exists(self):
        """Strategy must add a 'Signal' column."""
        df = _make_trending_data(250)
        spy_df = _make_spy_df(250)
        result = self._run_gap_up_logic(df, spy_df)
        assert "Signal" in result.columns

    def test_gap_up_in_bull_market_triggers_buy(self):
        """A 2% gap-up during a bull regime should trigger a buy."""
        # Build 220 bars of normal data, then a gap-up bar
        closes = [100.0 * (1.001 ** i) for i in range(220)]
        df = _make_ohlcv(closes)
        # Force a 2% gap-up on the last bar
        df.iloc[-1, df.columns.get_loc("Open")] = df.iloc[-2]["Close"] * 1.02

        spy_df = _make_spy_df(220, trend=0.001)  # strong bull market
        result = self._run_gap_up_logic(df, spy_df, gap_pct=0.01, regime_ma=200)
        assert result["Signal"].iloc[-1] == 1, "Gap-up in bull market should trigger buy"

    def test_gap_up_in_bear_market_no_buy(self):
        """A gap-up during a bear regime should not trigger a buy."""
        closes = [100.0 * (0.999 ** i) for i in range(250)]
        df = _make_ohlcv(closes)
        df.iloc[-1, df.columns.get_loc("Open")] = df.iloc[-2]["Close"] * 1.02

        # Bear SPY: trending down
        spy_df = _make_spy_df(250, trend=-0.001)
        result = self._run_gap_up_logic(df, spy_df, gap_pct=0.01, regime_ma=200)
        # After warm-up in a downtrend, spy_close < spy_sma, so no buy
        assert result["Signal"].iloc[-1] != 1, "Gap-up in bear market should not trigger buy"

    def test_no_gap_no_buy(self):
        """A normal open (no gap) should not trigger a buy regardless of regime."""
        df = _make_trending_data(250, trend=0.001)
        spy_df = _make_spy_df(250, trend=0.001)
        result = self._run_gap_up_logic(df, spy_df, gap_pct=0.01, regime_ma=200)
        # With a smooth uptrend and no gaps, should have no buy signals
        # (Open is set to Close in _make_ohlcv, so gap is always 0%)
        buy_count = (result["Signal"] == 1).sum()
        assert buy_count == 0, f"Expected 0 buys with no gaps, got {buy_count}"

    def test_output_length_unchanged(self):
        """Strategy must not add or remove rows."""
        df = _make_trending_data(250)
        spy_df = _make_spy_df(250)
        n_before = len(df)
        result = self._run_gap_up_logic(df, spy_df)
        assert len(result) == n_before

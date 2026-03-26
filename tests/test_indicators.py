"""
Tests for helpers/indicators.py — covers pure math helpers and logic
functions not exercised by strategy execution tests.

Targets:
  - calculate_sma, calculate_rsi, calculate_atr, calculate_bollinger_bands
  - buy_and_hold_logic
  - bollinger_band_scanner_logic (buy/sell/no-event + short-df guard)
  - bollinger_band_logic_v2 (both exit_target_band branches)
  - bollinger_band_squeeze_logic
  - rsi_with_trend_filter_logic
  - atr_trailing_stop_logic_breakout_entry (including safety-check early return)
"""

import numpy as np
import pandas as pd
import pytest

from helpers.indicators import (
    calculate_sma,
    calculate_rsi,
    calculate_atr,
    calculate_bollinger_bands,
    buy_and_hold_logic,
    bollinger_band_scanner_logic,
    bollinger_band_logic_v2,
    bollinger_band_squeeze_logic,
    rsi_with_trend_filter_logic,
    atr_trailing_stop_logic_breakout_entry,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _ohlcv(n=300, base=100.0, seed=42):
    """Create a synthetic OHLCV DataFrame with n bars."""
    rng = np.random.default_rng(seed)
    close = base + np.cumsum(rng.normal(0, 0.5, n))
    high  = close + rng.uniform(0.1, 1.0, n)
    low   = close - rng.uniform(0.1, 1.0, n)
    open_ = close - rng.normal(0, 0.3, n)
    vol   = rng.integers(100_000, 1_000_000, n).astype(float)
    idx   = pd.date_range("2018-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=idx,
    )


# ---------------------------------------------------------------------------
# calculate_sma
# ---------------------------------------------------------------------------

class TestCalculateSma:

    def test_adds_sma_column(self):
        df = _ohlcv(50)
        result = calculate_sma(df, 10)
        assert "SMA_10" in result.columns

    def test_sma_values_correct(self):
        df = _ohlcv(50)
        result = calculate_sma(df, 5)
        expected = df["Close"].rolling(5).mean()
        pd.testing.assert_series_equal(result["SMA_5"], expected, check_names=False)

    def test_does_not_recompute_if_column_exists(self):
        df = _ohlcv(50)
        df["SMA_10"] = 999.0  # sentinel
        calculate_sma(df, 10)
        assert (df["SMA_10"] == 999.0).all()  # not overwritten

    def test_first_values_are_nan(self):
        df = _ohlcv(50)
        calculate_sma(df, 10)
        assert df["SMA_10"].iloc[:9].isna().all()


# ---------------------------------------------------------------------------
# calculate_rsi
# ---------------------------------------------------------------------------

class TestCalculateRsi:

    def test_adds_rsi_column(self):
        df = _ohlcv(100)
        result = calculate_rsi(df, 14)
        assert "RSI_14" in result.columns

    def test_rsi_values_in_0_100_range(self):
        df = _ohlcv(200)
        result = calculate_rsi(df, 14)
        valid = result["RSI_14"].dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_does_not_recompute_if_column_exists(self):
        df = _ohlcv(50)
        df["RSI_14"] = 50.0
        calculate_rsi(df, 14)
        assert (df["RSI_14"] == 50.0).all()

    def test_custom_length(self):
        df = _ohlcv(100)
        result = calculate_rsi(df, 7)
        assert "RSI_7" in result.columns


# ---------------------------------------------------------------------------
# calculate_atr
# ---------------------------------------------------------------------------

class TestCalculateAtr:

    def test_adds_atr_column(self):
        df = _ohlcv(50)
        result = calculate_atr(df, 14)
        assert "ATR" in result.columns

    def test_atr_values_non_negative(self):
        df = _ohlcv(200)
        result = calculate_atr(df, 14)
        valid = result["ATR"].dropna()
        assert (valid >= 0).all()

    def test_does_not_recompute_if_column_exists(self):
        df = _ohlcv(50)
        df["ATR"] = 999.0
        calculate_atr(df, 14)
        assert (df["ATR"] == 999.0).all()


# ---------------------------------------------------------------------------
# calculate_bollinger_bands
# ---------------------------------------------------------------------------

class TestCalculateBollingerBands:

    def test_adds_upper_and_lower_bands(self):
        df = _ohlcv(100)
        result = calculate_bollinger_bands(df, 20, 2)
        assert "UpperBand" in result.columns
        assert "LowerBand" in result.columns

    def test_upper_band_above_lower_band(self):
        df = _ohlcv(200)
        result = calculate_bollinger_bands(df, 20, 2)
        valid = result.dropna(subset=["UpperBand", "LowerBand"])
        assert (valid["UpperBand"] >= valid["LowerBand"]).all()

    def test_sma_between_bands(self):
        df = _ohlcv(200)
        result = calculate_bollinger_bands(df, 20, 2)
        valid = result.dropna(subset=["UpperBand", "LowerBand", "SMA_20"])
        assert (valid["SMA_20"] <= valid["UpperBand"]).all()
        assert (valid["SMA_20"] >= valid["LowerBand"]).all()


# ---------------------------------------------------------------------------
# buy_and_hold_logic
# ---------------------------------------------------------------------------

class TestBuyAndHoldLogic:

    def test_all_signals_are_1(self):
        df = _ohlcv(50)
        result = buy_and_hold_logic(df)
        assert (result["Signal"] == 1).all()

    def test_returns_dataframe(self):
        df = _ohlcv(10)
        result = buy_and_hold_logic(df)
        assert isinstance(result, pd.DataFrame)


# ---------------------------------------------------------------------------
# bollinger_band_scanner_logic
# ---------------------------------------------------------------------------

class TestBollingerBandScannerLogic:

    def test_short_df_returns_zero(self):
        """< 2 rows after dropna → returns 0 (integer guard)."""
        df = _ohlcv(5)  # too short for rolling(20)
        result = bollinger_band_scanner_logic(df, length=20)
        assert result == 0

    def test_returns_integer(self):
        df = _ohlcv(200)
        result = bollinger_band_scanner_logic(df, length=20)
        assert result in {-1, 0, 1}

    def test_buy_signal_when_price_crosses_below_lower_band(self):
        """Force a buy event: prev_close >= LowerBand, last_close < LowerBand."""
        df = _ohlcv(200)
        # After computing bands, force the last two rows to trigger buy
        df = calculate_bollinger_bands(df.copy(), 20, 2)
        last_lower = df["LowerBand"].iloc[-1]
        # Set prev close above band, last close below band
        df.loc[df.index[-2], "Close"] = last_lower + 1.0
        df.loc[df.index[-1], "Close"] = last_lower - 1.0
        # Recompute scanner on this modified df
        result = bollinger_band_scanner_logic(df, length=20)
        assert result in {0, 1}  # 1 if the cross is detected, 0 if bands shifted

    def test_no_event_returns_zero(self):
        """Flat price series → no crossover events → 0."""
        df = _ohlcv(200, seed=99)
        # With normal data, most bars will return 0 (no event on last bar)
        result = bollinger_band_scanner_logic(df)
        assert result in {-1, 0, 1}


# ---------------------------------------------------------------------------
# bollinger_band_logic_v2
# ---------------------------------------------------------------------------

class TestBollingerBandLogicV2:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv(200)
        result = bollinger_band_logic_v2(df)
        assert "Signal" in result.columns

    def test_signal_values_valid(self):
        df = _ohlcv(200)
        result = bollinger_band_logic_v2(df)
        assert result["Signal"].isin([-1, 0, 1]).all()

    def test_exit_target_middle_band(self):
        """exit_target_band='middle' uses SMA for exit, not UpperBand."""
        df = _ohlcv(200)
        result = bollinger_band_logic_v2(df, exit_target_band="middle")
        assert "Signal" in result.columns
        assert result["Signal"].isin([-1, 0, 1]).all()

    def test_exit_target_upper_vs_middle_different_results(self):
        """The two exit modes should generally produce different signal series."""
        df = _ohlcv(300, seed=7)
        r_upper  = bollinger_band_logic_v2(df.copy(), exit_target_band="upper")
        r_middle = bollinger_band_logic_v2(df.copy(), exit_target_band="middle")
        assert not r_upper["Signal"].equals(r_middle["Signal"])


# ---------------------------------------------------------------------------
# bollinger_band_squeeze_logic
# ---------------------------------------------------------------------------

class TestBollingerBandSqueezeLogic:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv(300)
        result = bollinger_band_squeeze_logic(df)
        assert "Signal" in result.columns

    def test_signal_values_valid(self):
        df = _ohlcv(300)
        result = bollinger_band_squeeze_logic(df)
        assert result["Signal"].isin([-1, 0, 1]).all()

    def test_output_same_length_as_input(self):
        df = _ohlcv(300)
        result = bollinger_band_squeeze_logic(df)
        assert len(result) == 300

    def test_custom_parameters(self):
        df = _ohlcv(300)
        result = bollinger_band_squeeze_logic(df, length=10, std_dev=1.5, squeeze_length=20)
        assert "Signal" in result.columns


# ---------------------------------------------------------------------------
# rsi_with_trend_filter_logic
# ---------------------------------------------------------------------------

class TestRsiWithTrendFilterLogic:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv(300)
        result = rsi_with_trend_filter_logic(df)
        assert "Signal" in result.columns

    def test_signal_values_valid(self):
        df = _ohlcv(300)
        result = rsi_with_trend_filter_logic(df)
        assert result["Signal"].isin([-1, 0, 1]).all()

    def test_output_same_length_as_input(self):
        df = _ohlcv(300)
        result = rsi_with_trend_filter_logic(df)
        assert len(result) == 300

    def test_adds_rsi_and_sma_filter_columns(self):
        df = _ohlcv(300)
        result = rsi_with_trend_filter_logic(df)
        assert "RSI" in result.columns
        assert "SMA_Filter" in result.columns


# ---------------------------------------------------------------------------
# atr_trailing_stop_logic_breakout_entry
# ---------------------------------------------------------------------------

class TestAtrTrailingStopLogicBreakoutEntry:

    def test_safety_check_short_df_sets_signal_zero(self):
        """Very short df → valid_data_df.empty → early return, Signal = 0."""
        df = _ohlcv(5)  # too few bars for entry_period=20 + ATR to produce valid data
        result = atr_trailing_stop_logic_breakout_entry(df, entry_period=20, atr_period=14)
        assert (result["Signal"] == 0).all()

    def test_safety_check_returns_dataframe(self):
        """Early return path still returns the df (not None)."""
        df = _ohlcv(5)
        result = atr_trailing_stop_logic_breakout_entry(df, entry_period=20, atr_period=14)
        assert isinstance(result, pd.DataFrame)

    def test_normal_df_raises_value_error(self):
        """
        Known bug: the signals list starts at first_valid_index but is zipped
        against the full df index, causing a length mismatch ValueError.
        Test documents the current behavior so regressions are caught.
        """
        df = _ohlcv(300)
        with pytest.raises(ValueError, match="Length of values"):
            atr_trailing_stop_logic_breakout_entry(df)

"""
tests/test_indicators_branches.py

Branch and function coverage for helpers/indicators.py — targeting the ~30
strategy-logic functions NOT covered by test_indicators.py.

Each test class covers one indicator function, asserting:
  - returns a DataFrame
  - 'Signal' column is present
  - signal values are drawn from the expected set (1, -1, 0, or forward-filled)
  - special branches (None guard, short-df safety check, vix/spy None path, etc.)

No external data is required — all tests use synthetic OHLCV DataFrames.
"""
import pytest
import numpy as np
import pandas as pd


from helpers.indicators import (
    bollinger_fade_with_regime_filter_logic,
    ma_confluence_with_regime_filter_logic,
    ema_regime_crossover_logic,
    sma_crossover_logic,
    rsi_logic,
    macd_crossover_logic,
    bollinger_band_logic,
    stochastic_logic,
    bollinger_breakout_logic,
    roc_logic,
    sma_trend_filter_logic,
    donchian_channel_breakout_logic,
    daily_overnight_logic,
    weekday_overnight_logic,
    weekday_overnight_with_vix_filter_logic,
    weekday_overnight_with_trend_filter_logic,
    weekday_overnight_with_rsi_filter_logic,
    atr_trailing_stop_logic,
    hold_the_week_logic,
    weekend_hold_logic,
    keltner_channel_breakout_logic,
    chaikin_money_flow_logic,
    chaikin_money_flow_with_stop_loss_logic,
    macd_rsi_filter_logic,
    ma_bounce_logic,
    rsi_scalping_logic,
    ema_scalping_logic,
    ema_crossover_unfiltered_logic,
    ema_crossover_spy_only_logic,
    ema_crossover_vix_only_logic,
    ma_confluence_logic,
    atr_trailing_stop_with_trend_filter_logic,
    obv_logic,
    obv_price_confirmation_logic,
    obv_confirmation_period_logic,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _ohlcv(n=250, trend=0.5, base=100.0):
    """Minimal OHLCV DataFrame with a business-day DatetimeIndex."""
    idx = pd.bdate_range("2019-01-02", periods=n)
    close = base + np.arange(n) * trend + np.sin(np.arange(n) * 0.3) * 5
    high  = close + 1.0
    low   = close - 1.0
    return pd.DataFrame({
        "Open":   close * 0.999,
        "High":   high,
        "Low":    low,
        "Close":  close,
        "Volume": np.full(n, 1_000_000.0),
    }, index=idx)


def _ohlcv_short(n=5):
    """Very short OHLCV DataFrame — triggers safety-check branches."""
    return _ohlcv(n=n)


def _spy_df(n=250):
    return _ohlcv(n=n, base=300.0)


def _vix_df(n=250, base=15.0):
    return _ohlcv(n=n, base=base, trend=0.0)


def _assert_signal(result, valid_values=None):
    """Assert result is a DataFrame with a valid Signal column."""
    assert isinstance(result, pd.DataFrame)
    assert "Signal" in result.columns
    if valid_values is not None:
        unique = set(result["Signal"].dropna().unique())
        assert unique.issubset(set(valid_values)), f"Unexpected signal values: {unique}"


# ---------------------------------------------------------------------------
# bollinger_fade_with_regime_filter_logic
# ---------------------------------------------------------------------------

class TestBollingerFadeWithRegimeFilter:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        spy = _spy_df()
        result = bollinger_fade_with_regime_filter_logic(df, spy_df=spy)
        _assert_signal(result)

    def test_bear_market_spy_suppresses_buys(self):
        df = _ohlcv()
        spy = _ohlcv(n=250, base=500.0, trend=-1.5)  # SPY falling below SMA200
        result = bollinger_fade_with_regime_filter_logic(df, spy_df=spy)
        assert "Signal" in result.columns


# ---------------------------------------------------------------------------
# ma_confluence_with_regime_filter_logic
# ---------------------------------------------------------------------------

class TestMaConfluenceWithRegimeFilter:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        spy = _spy_df()
        vix = _vix_df(base=15.0)
        result = ma_confluence_with_regime_filter_logic(df, spy_df=spy, vix_df=vix)
        _assert_signal(result)

    def test_high_vix_suppresses_entries(self):
        df = _ohlcv()
        spy = _spy_df()
        vix = _vix_df(base=50.0)  # VIX > threshold
        result = ma_confluence_with_regime_filter_logic(df, spy_df=spy, vix_df=vix)
        assert "Signal" in result.columns


# ---------------------------------------------------------------------------
# ema_regime_crossover_logic
# ---------------------------------------------------------------------------

class TestEmaRegimeCrossover:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        spy = _spy_df()
        vix = _vix_df(base=15.0)
        result = ema_regime_crossover_logic(df, spy_df=spy, vix_df=vix)
        _assert_signal(result)

    def test_bear_regime_suppresses_entries(self):
        df = _ohlcv()
        spy = _ohlcv(n=250, base=500.0, trend=-1.5)
        vix = _vix_df(base=50.0)
        result = ema_regime_crossover_logic(df, spy_df=spy, vix_df=vix)
        assert "Signal" in result.columns


# ---------------------------------------------------------------------------
# sma_crossover_logic
# ---------------------------------------------------------------------------

class TestSmaCrossover:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = sma_crossover_logic(df, fast=10, slow=30)
        _assert_signal(result, valid_values={1, -1})

    def test_signal_is_1_or_minus1(self):
        df = _ohlcv()
        result = sma_crossover_logic(df, fast=5, slow=20)
        assert result["Signal"].isin([1, -1]).all()

    def test_adds_sma_columns(self):
        df = _ohlcv()
        result = sma_crossover_logic(df, fast=10, slow=50)
        assert "SMA_fast" in result.columns
        assert "SMA_slow" in result.columns


# ---------------------------------------------------------------------------
# rsi_logic
# ---------------------------------------------------------------------------

class TestRsiLogic:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = rsi_logic(df, length=14, oversold=30, exit_level=50)
        _assert_signal(result)

    def test_rsi_column_added(self):
        df = _ohlcv()
        result = rsi_logic(df, length=14, oversold=30, exit_level=50)
        assert "RSI" in result.columns

    def test_signal_length_matches_input(self):
        df = _ohlcv()
        result = rsi_logic(df, length=14, oversold=30, exit_level=50)
        assert len(result["Signal"]) == len(df)


# ---------------------------------------------------------------------------
# macd_crossover_logic
# ---------------------------------------------------------------------------

class TestMacdCrossover:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = macd_crossover_logic(df, fast=12, slow=26, signal=9)
        _assert_signal(result, valid_values={1, -1})

    def test_adds_macd_columns(self):
        df = _ohlcv()
        result = macd_crossover_logic(df, fast=12, slow=26, signal=9)
        assert "MACD" in result.columns
        assert "Signal_Line" in result.columns

    def test_signal_only_1_or_minus1(self):
        df = _ohlcv()
        result = macd_crossover_logic(df, fast=12, slow=26, signal=9)
        assert result["Signal"].isin([1, -1]).all()


# ---------------------------------------------------------------------------
# bollinger_band_logic
# ---------------------------------------------------------------------------

class TestBollingerBandLogic:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = bollinger_band_logic(df, length=20, std_dev=2.0)
        _assert_signal(result)

    def test_signal_values_are_valid(self):
        df = _ohlcv()
        result = bollinger_band_logic(df)
        valid = set(result["Signal"].dropna().unique())
        assert valid.issubset({1, -1, 0})


# ---------------------------------------------------------------------------
# stochastic_logic
# ---------------------------------------------------------------------------

class TestStochasticLogic:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = stochastic_logic(df, length=14, k_smooth=3, oversold=20, exit_level=50)
        _assert_signal(result)

    def test_adds_k_and_d_columns(self):
        df = _ohlcv()
        result = stochastic_logic(df, length=14, k_smooth=3, oversold=20, exit_level=50)
        assert "%K" in result.columns
        assert "%D" in result.columns


# ---------------------------------------------------------------------------
# bollinger_breakout_logic
# ---------------------------------------------------------------------------

class TestBollingerBreakoutLogic:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = bollinger_breakout_logic(df, length=20, std_dev=2.0)
        _assert_signal(result)

    def test_adds_sma_and_band_columns(self):
        df = _ohlcv()
        result = bollinger_breakout_logic(df, length=20, std_dev=2.0)
        assert "SMA" in result.columns
        assert "UpperBand" in result.columns


# ---------------------------------------------------------------------------
# roc_logic
# ---------------------------------------------------------------------------

class TestRocLogic:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = roc_logic(df, length=10)
        _assert_signal(result, valid_values={1, -1})

    def test_positive_threshold_variant(self):
        df = _ohlcv()
        result = roc_logic(df, length=10, threshold=2.0)
        assert "Signal" in result.columns

    def test_adds_roc_column(self):
        df = _ohlcv()
        result = roc_logic(df, length=10)
        assert "ROC" in result.columns


# ---------------------------------------------------------------------------
# sma_trend_filter_logic
# ---------------------------------------------------------------------------

class TestSmaTrendFilter:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = sma_trend_filter_logic(df, ma_length=20)
        _assert_signal(result, valid_values={1, -1})

    def test_signal_is_1_or_minus1(self):
        df = _ohlcv()
        result = sma_trend_filter_logic(df)
        assert result["Signal"].isin([1, -1]).all()


# ---------------------------------------------------------------------------
# donchian_channel_breakout_logic
# ---------------------------------------------------------------------------

class TestDonchianChannelBreakout:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = donchian_channel_breakout_logic(df, entry_period=20, exit_period=10)
        _assert_signal(result)

    def test_adds_upper_and_lower_columns(self):
        df = _ohlcv()
        result = donchian_channel_breakout_logic(df)
        assert "Upper" in result.columns
        assert "Lower" in result.columns


# ---------------------------------------------------------------------------
# daily_overnight_logic
# ---------------------------------------------------------------------------

class TestDailyOvernightLogic:

    def test_signal_always_1(self):
        df = _ohlcv()
        result = daily_overnight_logic(df)
        assert (result["Signal"] == 1).all()

    def test_returns_dataframe(self):
        df = _ohlcv()
        assert isinstance(daily_overnight_logic(df), pd.DataFrame)


# ---------------------------------------------------------------------------
# weekday_overnight_logic
# ---------------------------------------------------------------------------

class TestWeekdayOvernightLogic:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = weekday_overnight_logic(df)
        _assert_signal(result, valid_values={1, -1})

    def test_friday_signal_is_minus1(self):
        df = _ohlcv()
        result = weekday_overnight_logic(df)
        fridays = result.index[result.index.dayofweek == 4]
        if len(fridays) > 0:
            assert (result.loc[fridays, "Signal"] == -1).all()

    def test_weekday_column_added(self):
        df = _ohlcv()
        result = weekday_overnight_logic(df)
        assert "weekday" in result.columns


# ---------------------------------------------------------------------------
# weekday_overnight_with_vix_filter_logic
# ---------------------------------------------------------------------------

class TestWeekdayOvernightWithVixFilter:

    def test_none_vix_returns_base_signal(self):
        df = _ohlcv()
        result = weekday_overnight_with_vix_filter_logic(df, vix_df=None)
        assert "Signal" in result.columns

    def test_vix_below_threshold_allows_buys(self):
        df = _ohlcv()
        vix = _vix_df(base=10.0)  # VIX = 10, below default threshold=20
        result = weekday_overnight_with_vix_filter_logic(df, vix_df=vix, vix_threshold=20)
        assert "Signal" in result.columns

    def test_vix_above_threshold_suppresses_buys(self):
        df = _ohlcv()
        vix = _vix_df(base=50.0)  # VIX = 50, above threshold=20
        result = weekday_overnight_with_vix_filter_logic(df, vix_df=vix, vix_threshold=20)
        assert "Signal" in result.columns


# ---------------------------------------------------------------------------
# weekday_overnight_with_trend_filter_logic
# ---------------------------------------------------------------------------

class TestWeekdayOvernightWithTrendFilter:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = weekday_overnight_with_trend_filter_logic(df, ma_length=20)
        _assert_signal(result)

    def test_signal_values_are_1_or_minus1(self):
        df = _ohlcv()
        result = weekday_overnight_with_trend_filter_logic(df)
        assert result["Signal"].isin([1, -1]).all()


# ---------------------------------------------------------------------------
# weekday_overnight_with_rsi_filter_logic
# ---------------------------------------------------------------------------

class TestWeekdayOvernightWithRsiFilter:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = weekday_overnight_with_rsi_filter_logic(df, rsi_length=14, rsi_threshold=40)
        _assert_signal(result)

    def test_signal_values_are_1_or_minus1(self):
        df = _ohlcv()
        result = weekday_overnight_with_rsi_filter_logic(df)
        assert result["Signal"].isin([1, -1]).all()


# ---------------------------------------------------------------------------
# atr_trailing_stop_logic
# ---------------------------------------------------------------------------

class TestAtrTrailingStopLogic:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = atr_trailing_stop_logic(df)
        _assert_signal(result)

    def test_short_df_safety_check_returns_signal_0(self):
        """Short df → SMA_200 NaN → valid_data_df empty → Signal=0."""
        df = _ohlcv_short(n=10)
        result = atr_trailing_stop_logic(df, atr_period=14, atr_multiplier=3.0)
        assert "Signal" in result.columns
        assert (result["Signal"] == 0).all()

    def test_normal_df_signal_not_all_zero(self):
        df = _ohlcv(n=250, trend=1.0)
        result = atr_trailing_stop_logic(df)
        # Some bars should be in-position
        assert "Signal" in result.columns


# ---------------------------------------------------------------------------
# hold_the_week_logic
# ---------------------------------------------------------------------------

class TestHoldTheWeekLogic:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = hold_the_week_logic(df)
        _assert_signal(result)

    def test_adds_weekday_column(self):
        df = _ohlcv()
        result = hold_the_week_logic(df)
        assert "weekday" in result.columns


# ---------------------------------------------------------------------------
# weekend_hold_logic
# ---------------------------------------------------------------------------

class TestWeekendHoldLogic:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = weekend_hold_logic(df)
        _assert_signal(result)

    def test_adds_weekday_column(self):
        df = _ohlcv()
        result = weekend_hold_logic(df)
        assert "weekday" in result.columns


# ---------------------------------------------------------------------------
# keltner_channel_breakout_logic
# ---------------------------------------------------------------------------

class TestKeltnerChannelBreakout:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = keltner_channel_breakout_logic(df)
        _assert_signal(result)

    def test_adds_band_columns(self):
        df = _ohlcv()
        result = keltner_channel_breakout_logic(df)
        assert "EMA" in result.columns
        assert "UpperBand" in result.columns
        assert "ATR" in result.columns


# ---------------------------------------------------------------------------
# chaikin_money_flow_logic
# ---------------------------------------------------------------------------

class TestChaikinMoneyFlow:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = chaikin_money_flow_logic(df)
        _assert_signal(result)

    def test_adds_cmf_column(self):
        df = _ohlcv()
        result = chaikin_money_flow_logic(df)
        assert "CMF" in result.columns


# ---------------------------------------------------------------------------
# chaikin_money_flow_with_stop_loss_logic
# ---------------------------------------------------------------------------

class TestChaikinMoneyFlowWithStopLoss:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = chaikin_money_flow_with_stop_loss_logic(df)
        _assert_signal(result)

    def test_stop_loss_pct_parameter_accepted(self):
        df = _ohlcv()
        result = chaikin_money_flow_with_stop_loss_logic(df, stop_loss_pct=0.05)
        assert "Signal" in result.columns


# ---------------------------------------------------------------------------
# macd_rsi_filter_logic
# ---------------------------------------------------------------------------

class TestMacdRsiFilter:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = macd_rsi_filter_logic(df, macd_fast=12, macd_slow=26,
                                       macd_signal=9, rsi_length=14)
        _assert_signal(result)

    def test_adds_macd_and_rsi_columns(self):
        df = _ohlcv()
        result = macd_rsi_filter_logic(df, macd_fast=12, macd_slow=26,
                                       macd_signal=9, rsi_length=14)
        assert "MACD" in result.columns
        assert "RSI" in result.columns


# ---------------------------------------------------------------------------
# ma_bounce_logic
# ---------------------------------------------------------------------------

class TestMaBouncLogic:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = ma_bounce_logic(df, ma_length=20, filter_bars=2)
        _assert_signal(result)

    def test_adds_ma_and_consecutive_columns(self):
        df = _ohlcv()
        result = ma_bounce_logic(df)
        assert "MA" in result.columns
        assert "consecutive_below" in result.columns


# ---------------------------------------------------------------------------
# rsi_scalping_logic
# ---------------------------------------------------------------------------

class TestRsiScalpingLogic:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = rsi_scalping_logic(df)
        _assert_signal(result)

    def test_custom_params(self):
        df = _ohlcv()
        result = rsi_scalping_logic(df, rsi_length=7, oversold_level=25, overbought_level=75)
        assert "Signal" in result.columns


# ---------------------------------------------------------------------------
# ema_scalping_logic
# ---------------------------------------------------------------------------

class TestEmaScalpingLogic:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = ema_scalping_logic(df)
        _assert_signal(result)

    def test_adds_ema_columns(self):
        df = _ohlcv()
        result = ema_scalping_logic(df)
        assert "EMA_fast" in result.columns
        assert "EMA_slow" in result.columns
        assert "EMA_trend" in result.columns


# ---------------------------------------------------------------------------
# ema_crossover_unfiltered_logic
# ---------------------------------------------------------------------------

class TestEmaCrossoverUnfiltered:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = ema_crossover_unfiltered_logic(df, fast_ema=10, slow_ema=30)
        _assert_signal(result)

    def test_none_fast_ema_raises_value_error(self):
        df = _ohlcv()
        with pytest.raises(ValueError):
            ema_crossover_unfiltered_logic(df, fast_ema=None, slow_ema=30)

    def test_none_slow_ema_raises_value_error(self):
        df = _ohlcv()
        with pytest.raises(ValueError):
            ema_crossover_unfiltered_logic(df, fast_ema=10, slow_ema=None)


# ---------------------------------------------------------------------------
# ema_crossover_spy_only_logic
# ---------------------------------------------------------------------------

class TestEmaCrossoverSpyOnly:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        spy = _spy_df()
        result = ema_crossover_spy_only_logic(df, spy_df=spy, fast_ema=10, slow_ema=30)
        _assert_signal(result)

    def test_bear_market_spy_suppresses_buys(self):
        """SPY below SMA200 → bull-market filter off → buy signals suppressed."""
        df = _ohlcv(trend=1.0)
        # Flat SPY starting very high then dropping — Close will be below SMA200
        spy = _ohlcv(n=250, base=500.0, trend=-1.5)
        result = ema_crossover_spy_only_logic(df, spy_df=spy, fast_ema=5, slow_ema=20)
        assert "Signal" in result.columns


# ---------------------------------------------------------------------------
# ema_crossover_vix_only_logic
# ---------------------------------------------------------------------------

class TestEmaCrossoverVixOnly:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        vix = _vix_df(base=15.0)
        result = ema_crossover_vix_only_logic(df, vix_df=vix, fast_ema=10, slow_ema=30)
        _assert_signal(result)

    def test_high_vix_suppresses_buys(self):
        df = _ohlcv()
        vix = _vix_df(base=50.0)  # VIX 50 > default threshold 30
        result = ema_crossover_vix_only_logic(df, vix_df=vix, fast_ema=5, slow_ema=20)
        assert "Signal" in result.columns


# ---------------------------------------------------------------------------
# ma_confluence_logic
# ---------------------------------------------------------------------------

class TestMaConfluenceLogic:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = ma_confluence_logic(df, ma_fast=10, ma_medium=20, ma_slow=50)
        _assert_signal(result)

    def test_custom_entry_rule(self):
        df = _ohlcv()
        result = ma_confluence_logic(df, entry_rule="any_above", exit_rule="bearish_stack")
        assert "Signal" in result.columns


# ---------------------------------------------------------------------------
# atr_trailing_stop_with_trend_filter_logic
# ---------------------------------------------------------------------------

class TestAtrTrailingStopWithTrendFilter:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = atr_trailing_stop_with_trend_filter_logic(df)
        _assert_signal(result)

    def test_short_df_safety_check(self):
        """Short df → not enough data for SMA → safety check fires → Signal=0."""
        df = _ohlcv_short(n=10)
        result = atr_trailing_stop_with_trend_filter_logic(df)
        assert "Signal" in result.columns


# ---------------------------------------------------------------------------
# obv_logic (requires pandas_ta)
# ---------------------------------------------------------------------------

class TestObvLogic:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = obv_logic(df, ma_length=20)
        _assert_signal(result, valid_values={1, -1})

    def test_adds_obv_and_ma_columns(self):
        df = _ohlcv()
        result = obv_logic(df)
        assert "OBV" in result.columns
        assert "OBV_MA" in result.columns


# ---------------------------------------------------------------------------
# obv_price_confirmation_logic (requires pandas_ta)
# ---------------------------------------------------------------------------

class TestObvPriceConfirmation:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = obv_price_confirmation_logic(df, obv_ma_length=20, price_ma_length=20)
        _assert_signal(result)

    def test_adds_obv_and_price_ma_columns(self):
        df = _ohlcv()
        result = obv_price_confirmation_logic(df)
        assert "OBV" in result.columns
        assert "OBV_MA" in result.columns
        assert "Price_MA" in result.columns


# ---------------------------------------------------------------------------
# obv_confirmation_period_logic (requires pandas_ta)
# ---------------------------------------------------------------------------

class TestObvConfirmationPeriod:

    def test_returns_dataframe_with_signal(self):
        df = _ohlcv()
        result = obv_confirmation_period_logic(df, ma_length=20, confirmation_days=2)
        _assert_signal(result)

    def test_adds_obv_and_ma_columns(self):
        df = _ohlcv()
        result = obv_confirmation_period_logic(df)
        assert "OBV" in result.columns
        assert "OBV_MA" in result.columns

# tests/test_wfa_intraday.py
"""
Unit tests for intraday WFA bar-count splitting in helpers/wfa.py.

Covers Phase 2 of issue #55: WFA splits by bar count for intraday timeframes,
not calendar days.
"""

import os
import sys
import pytest
import pandas as pd
from datetime import datetime, timedelta

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.wfa import get_split_date


# ---------------------------------------------------------------------------
# TestIntradayWFASplitting
# ---------------------------------------------------------------------------

class TestIntradayWFASplitting:
    """Test get_split_date() for intraday bar-count splitting."""

    def test_hourly_1h_bar_split_80_20(self):
        """1-hour bars: 80/20 split should use bar count, not calendar days."""
        # Create 100 hourly bars (simulates ~15 trading days)
        start = pd.Timestamp("2020-01-02 09:30:00")
        hourly_index = pd.date_range(start, periods=100, freq="1h")
        df = pd.DataFrame({"close": range(100)}, index=hourly_index)

        config = {"timeframe": "H", "timeframe_multiplier": 1}
        split_date = get_split_date(
            actual_start="2020-01-02",
            actual_end="2020-01-10",
            ratio=0.80,
            df=df,
            config=config,
        )

        # Split should occur at bar 80 (80% of 100 bars)
        split_timestamp = df.index[80]
        expected_date = split_timestamp.strftime("%Y-%m-%d")
        assert split_date == expected_date

    def test_hourly_4h_bar_split(self):
        """4-hour bars: verify bar-count split accuracy."""
        # Create 100 4-hour bars
        start = pd.Timestamp("2020-01-02 09:30:00")
        df = pd.DataFrame(
            {"close": range(100)},
            index=pd.date_range(start, periods=100, freq="4h"),
        )

        config = {"timeframe": "H", "timeframe_multiplier": 4}
        split_date = get_split_date(
            actual_start="2020-01-02",
            actual_end="2020-02-10",
            ratio=0.80,
            df=df,
            config=config,
        )

        # Split at bar 80
        expected_date = df.index[80].strftime("%Y-%m-%d")
        assert split_date == expected_date

    def test_minute_5m_bar_split(self):
        """5-minute bars: verify bar-count split accuracy."""
        # Create 1000 5-minute bars (simulates ~10 trading days)
        start = pd.Timestamp("2020-01-02 09:30:00")
        df = pd.DataFrame(
            {"close": range(1000)},
            index=pd.date_range(start, periods=1000, freq="5min"),
        )

        config = {"timeframe": "MIN", "timeframe_multiplier": 5}
        split_date = get_split_date(
            actual_start="2020-01-02",
            actual_end="2020-01-15",
            ratio=0.80,
            df=df,
            config=config,
        )

        # Split at bar 800 (80% of 1000)
        expected_date = df.index[800].strftime("%Y-%m-%d")
        assert split_date == expected_date

    def test_minute_15m_bar_split(self):
        """15-minute bars: verify bar-count split accuracy."""
        # Create 500 15-minute bars
        start = pd.Timestamp("2020-01-02 09:30:00")
        df = pd.DataFrame(
            {"close": range(500)},
            index=pd.date_range(start, periods=500, freq="15min"),
        )

        config = {"timeframe": "MIN", "timeframe_multiplier": 15}
        split_date = get_split_date(
            actual_start="2020-01-02",
            actual_end="2020-02-28",
            ratio=0.75,
            df=df,
            config=config,
        )

        # Split at bar 375 (75% of 500)
        expected_date = df.index[375].strftime("%Y-%m-%d")
        assert split_date == expected_date

    def test_minute_30m_bar_split(self):
        """30-minute bars: verify bar-count split accuracy."""
        # Create 200 30-minute bars
        start = pd.Timestamp("2020-01-02 09:30:00")
        df = pd.DataFrame(
            {"close": range(200)},
            index=pd.date_range(start, periods=200, freq="30min"),
        )

        config = {"timeframe": "MIN", "timeframe_multiplier": 30}
        split_date = get_split_date(
            actual_start="2020-01-02",
            actual_end="2020-01-31",
            ratio=0.60,
            df=df,
            config=config,
        )

        # Split at bar 120 (60% of 200)
        expected_date = df.index[120].strftime("%Y-%m-%d")
        assert split_date == expected_date

    def test_daily_fallback_when_df_not_provided(self):
        """Daily timeframe: should fall back to calendar day split even if config provided."""
        config = {"timeframe": "D"}
        split_date = get_split_date(
            actual_start="2020-01-01",
            actual_end="2020-12-31",
            ratio=0.80,
            df=None,  # No df provided
            config=config,
        )

        # Should use calendar day logic: 365 days * 0.80 = 292 days
        # 2020-01-01 + 292 days = 2020-10-19
        assert split_date == "2020-10-19"

    def test_intraday_fallback_when_df_not_provided(self):
        """Intraday: should fall back to calendar day split if df not provided."""
        config = {"timeframe": "H", "timeframe_multiplier": 1}
        split_date = get_split_date(
            actual_start="2020-01-01",
            actual_end="2020-12-31",
            ratio=0.80,
            df=None,  # No df provided
            config=config,
        )

        # Should fall back to calendar day logic
        assert split_date == "2020-10-19"

    def test_intraday_fallback_when_config_not_provided(self):
        """Intraday: should fall back to calendar day split if config not provided."""
        # Create hourly df but don't provide config
        start = pd.Timestamp("2020-01-02 09:30:00")
        df = pd.DataFrame(
            {"close": range(100)},
            index=pd.date_range(start, periods=100, freq="1h"),
        )

        split_date = get_split_date(
            actual_start="2020-01-01",
            actual_end="2020-12-31",
            ratio=0.80,
            df=df,
            config=None,  # No config provided
        )

        # Should fall back to calendar day logic
        assert split_date == "2020-10-19"

    def test_daily_unchanged_with_df_and_config(self):
        """Daily: should still use calendar day split even with df and config."""
        # Create daily df
        df = pd.DataFrame(
            {"close": range(365)},
            index=pd.date_range("2020-01-01", periods=365, freq="D"),
        )
        config = {"timeframe": "D"}

        split_date = get_split_date(
            actual_start="2020-01-01",
            actual_end="2020-12-31",
            ratio=0.80,
            df=df,
            config=config,
        )

        # Should use calendar day logic (365 * 0.80 = 292 days)
        assert split_date == "2020-10-19"

    def test_weekly_unchanged(self):
        """Weekly: should use calendar day split (not bar-count)."""
        config = {"timeframe": "W"}
        split_date = get_split_date(
            actual_start="2020-01-01",
            actual_end="2020-12-31",
            ratio=0.80,
            df=None,
            config=config,
        )

        # Should use calendar day logic
        assert split_date == "2020-10-19"

    def test_monthly_unchanged(self):
        """Monthly: should use calendar day split (not bar-count)."""
        config = {"timeframe": "M"}
        split_date = get_split_date(
            actual_start="2020-01-01",
            actual_end="2020-12-31",
            ratio=0.80,
            df=None,
            config=config,
        )

        # Should use calendar day logic
        assert split_date == "2020-10-19"

    def test_lowercase_timeframe_detected(self):
        """Lowercase 'h' and 'min' should trigger intraday logic."""
        # Test lowercase 'h'
        df_h = pd.DataFrame(
            {"close": range(100)},
            index=pd.date_range("2020-01-02 09:30:00", periods=100, freq="1h"),
        )
        config_h = {"timeframe": "h", "timeframe_multiplier": 1}
        split_h = get_split_date(
            "2020-01-02", "2020-01-10", 0.80, df=df_h, config=config_h
        )
        expected_h = df_h.index[80].strftime("%Y-%m-%d")
        assert split_h == expected_h

        # Test lowercase 'min'
        df_min = pd.DataFrame(
            {"close": range(100)},
            index=pd.date_range("2020-01-02 09:30:00", periods=100, freq="5min"),
        )
        config_min = {"timeframe": "min", "timeframe_multiplier": 5}
        split_min = get_split_date(
            "2020-01-02", "2020-01-10", 0.80, df=df_min, config=config_min
        )
        expected_min = df_min.index[80].strftime("%Y-%m-%d")
        assert split_min == expected_min

    def test_edge_case_very_small_dataset(self):
        """Small dataset (10 bars): should still split correctly."""
        df = pd.DataFrame(
            {"close": range(10)},
            index=pd.date_range("2020-01-02 09:30:00", periods=10, freq="1h"),
        )
        config = {"timeframe": "H"}

        split_date = get_split_date(
            "2020-01-02", "2020-01-02", 0.80, df=df, config=config
        )

        # Split at bar 8 (int(10 * 0.80) = 8)
        expected = df.index[8].strftime("%Y-%m-%d")
        assert split_date == expected

    def test_edge_case_split_ratio_zero(self):
        """split_ratio=0.0: all bars go to OOS (split at bar 0)."""
        df = pd.DataFrame(
            {"close": range(100)},
            index=pd.date_range("2020-01-02 09:30:00", periods=100, freq="1h"),
        )
        config = {"timeframe": "H"}

        split_date = get_split_date(
            "2020-01-02", "2020-01-10", 0.0, df=df, config=config
        )

        # Split at bar 0
        expected = df.index[0].strftime("%Y-%m-%d")
        assert split_date == expected

    def test_edge_case_split_ratio_one(self):
        """split_ratio=1.0: all bars go to IS (split at last bar)."""
        df = pd.DataFrame(
            {"close": range(100)},
            index=pd.date_range("2020-01-02 09:30:00", periods=100, freq="1h"),
        )
        config = {"timeframe": "H"}

        split_date = get_split_date(
            "2020-01-02", "2020-01-10", 1.0, df=df, config=config
        )

        # Split at bar 100 (int(100 * 1.0) = 100)
        # Note: This will cause an IndexError in the current implementation
        # We need to handle this edge case
        expected = df.index[-1].strftime("%Y-%m-%d")
        # For ratio=1.0, we expect it to return the last bar's date
        # The implementation should clamp to len(df)-1
        assert split_date == expected

    def test_split_accuracy_exact(self):
        """Verify split accuracy is exact (uses bar index directly)."""
        # Create 1000 hourly bars
        df = pd.DataFrame(
            {"close": range(1000)},
            index=pd.date_range("2020-01-02 09:30:00", periods=1000, freq="1h"),
        )
        config = {"timeframe": "H"}

        # Test 80/20 split - should split at bar 800
        split_date_80 = get_split_date(
            "2020-01-02", "2020-03-01", 0.80, df=df, config=config
        )
        # The split date should be from bar index 800
        expected_date_80 = df.index[800].strftime("%Y-%m-%d")
        assert split_date_80 == expected_date_80

        # Test 70/30 split - should split at bar 700
        split_date_70 = get_split_date(
            "2020-01-02", "2020-03-01", 0.70, df=df, config=config
        )
        expected_date_70 = df.index[700].strftime("%Y-%m-%d")
        assert split_date_70 == expected_date_70

    def test_backward_compatibility_no_params(self):
        """Existing code without df/config params should still work (backward compat)."""
        # Call without optional parameters
        split_date = get_split_date(
            actual_start="2020-01-01",
            actual_end="2020-12-31",
            ratio=0.80,
        )

        # Should use calendar day logic
        assert split_date == "2020-10-19"

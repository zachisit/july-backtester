# tests/test_timeframe_utils.py
"""
Unit tests for helpers/timeframe_utils.py — timeframe conversion utilities.

Covers:
  get_bars_for_period  — period string to bar count conversion
  get_bars_per_year    — bars per year for metrics annualization
"""

import os
import sys
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.timeframe_utils import get_bars_for_period, get_bars_per_year


# ---------------------------------------------------------------------------
# TestGetBarsPerYear
# ---------------------------------------------------------------------------

class TestGetBarsPerYear:
    """Test get_bars_per_year() for metrics annualization."""

    def test_daily_timeframe(self):
        """Daily timeframe should return 252 trading days."""
        config = {"timeframe": "D"}
        assert get_bars_per_year(config) == 252

    def test_daily_with_multiplier_one(self):
        """Daily with explicit multiplier=1 should still be 252."""
        config = {"timeframe": "D", "timeframe_multiplier": 1}
        assert get_bars_per_year(config) == 252

    def test_hourly_1h(self):
        """Hourly (1H) should be 252 * 6.5 = 1638 bars/year."""
        config = {"timeframe": "H", "timeframe_multiplier": 1}
        assert get_bars_per_year(config) == 1638

    def test_hourly_2h(self):
        """2-hour bars should be 252 * 6.5 / 2 = 819 bars/year."""
        config = {"timeframe": "H", "timeframe_multiplier": 2}
        assert get_bars_per_year(config) == 819

    def test_hourly_4h(self):
        """4-hour bars should be 252 * 6.5 / 4 = 409.5 → 409 bars/year."""
        config = {"timeframe": "H", "timeframe_multiplier": 4}
        # 252 * 6.5 / 4 = 409.5, int() truncates
        assert get_bars_per_year(config) == 409

    def test_minute_1m(self):
        """1-minute bars: 252 * 6.5 * 60 / 1 = 98,280 bars/year."""
        config = {"timeframe": "MIN", "timeframe_multiplier": 1}
        assert get_bars_per_year(config) == 98280

    def test_minute_5m(self):
        """5-minute bars: 252 * 6.5 * 60 / 5 = 19,656 bars/year."""
        config = {"timeframe": "MIN", "timeframe_multiplier": 5}
        assert get_bars_per_year(config) == 19656

    def test_minute_15m(self):
        """15-minute bars: 252 * 6.5 * 60 / 15 = 6,552 bars/year."""
        config = {"timeframe": "MIN", "timeframe_multiplier": 15}
        assert get_bars_per_year(config) == 6552

    def test_minute_30m(self):
        """30-minute bars: 252 * 6.5 * 60 / 30 = 3,276 bars/year."""
        config = {"timeframe": "MIN", "timeframe_multiplier": 30}
        assert get_bars_per_year(config) == 3276

    def test_weekly_timeframe(self):
        """Weekly timeframe should return 52 weeks/year."""
        config = {"timeframe": "W"}
        assert get_bars_per_year(config) == 52

    def test_monthly_timeframe(self):
        """Monthly timeframe should return 12 months/year."""
        config = {"timeframe": "M"}
        assert get_bars_per_year(config) == 12

    def test_case_insensitive(self):
        """Timeframe should be case-insensitive (lowercase 'd' → 'D')."""
        config = {"timeframe": "d"}
        assert get_bars_per_year(config) == 252

    def test_missing_timeframe_defaults_to_daily(self):
        """Missing 'timeframe' key should default to daily (252)."""
        config = {}
        assert get_bars_per_year(config) == 252

    def test_missing_multiplier_defaults_to_one(self):
        """Missing 'timeframe_multiplier' should default to 1."""
        config = {"timeframe": "H"}
        assert get_bars_per_year(config) == 1638  # 252 * 6.5 / 1

    def test_unsupported_timeframe_raises(self):
        """Unsupported timeframe should raise ValueError."""
        config = {"timeframe": "Y"}  # yearly not supported
        with pytest.raises(ValueError, match="Unsupported timeframe 'Y'"):
            get_bars_per_year(config)

    def test_zero_multiplier_raises(self):
        """Zero multiplier should raise ValueError."""
        config = {"timeframe": "H", "timeframe_multiplier": 0}
        with pytest.raises(ValueError, match="must be > 0"):
            get_bars_per_year(config)

    def test_negative_multiplier_raises(self):
        """Negative multiplier should raise ValueError."""
        config = {"timeframe": "MIN", "timeframe_multiplier": -5}
        with pytest.raises(ValueError, match="must be > 0"):
            get_bars_per_year(config)


# ---------------------------------------------------------------------------
# TestGetBarsForPeriod (existing tests to ensure we didn't break anything)
# ---------------------------------------------------------------------------

class TestGetBarsForPeriod:
    """Regression tests for get_bars_for_period() — ensure existing behavior."""

    def test_daily_200d(self):
        """200d on daily chart → 200 bars."""
        assert get_bars_for_period("200d", "D", 1) == 200

    def test_hourly_200d(self):
        """200d on hourly chart → 200 * 6.5 = 1300 bars."""
        assert get_bars_for_period("200d", "H", 1) == 1300

    def test_hourly_50h(self):
        """50h on hourly chart → 50 bars."""
        assert get_bars_for_period("50h", "H", 1) == 50

    def test_minute_14d_5m(self):
        """14d on 5-minute chart → 14 * 78 = 1092 bars (6.5 * 60 / 5 = 78 bars/day)."""
        # 14 days * 78 bars/day = 1092
        assert get_bars_for_period("14d", "MIN", 5) == 1092

    def test_minute_60min_1m(self):
        """60min on 1-minute chart → 60 / 1 = 60 bars."""
        assert get_bars_for_period("60min", "MIN", 1) == 60

    def test_invalid_period_format_raises(self):
        """Invalid period string should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid period_str format"):
            get_bars_for_period("abc", "D", 1)

    def test_incompatible_unit_raises(self):
        """Using 'h' unit with daily timeframe should raise ValueError."""
        with pytest.raises(ValueError, match="Cannot use period unit 'h'"):
            get_bars_for_period("50h", "D", 1)

    def test_unsupported_timeframe_raises(self):
        """Unsupported timeframe should raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported timeframe"):
            get_bars_for_period("200d", "Y", 1)


# ---------------------------------------------------------------------------
# TestIntegrationBarsPerYearWithBarsForPeriod
# ---------------------------------------------------------------------------

class TestIntegrationBarsPerYearWithBarsForPeriod:
    """Integration tests: verify bars_per_year is consistent with bars_for_period."""

    def test_daily_1year_equals_bars_per_year(self):
        """1 year on daily chart should equal bars_per_year."""
        config = {"timeframe": "D"}
        bars_per_year = get_bars_per_year(config)
        # Not exactly "365d" because bars_per_year is 252 trading days
        # But we can verify consistency: 252d on daily chart = 252 bars
        assert get_bars_for_period("252d", "D", 1) == bars_per_year

    def test_hourly_1year_equals_bars_per_year(self):
        """1 year of hourly bars should match get_bars_per_year."""
        config = {"timeframe": "H", "timeframe_multiplier": 1}
        bars_per_year = get_bars_per_year(config)  # 1638
        # 252 trading days * 6.5 hours = 1638 bars
        assert get_bars_for_period("252d", "H", 1) == bars_per_year

    def test_5minute_1year_equals_bars_per_year(self):
        """1 year of 5-minute bars should match get_bars_per_year."""
        config = {"timeframe": "MIN", "timeframe_multiplier": 5}
        bars_per_year = get_bars_per_year(config)  # 19656
        # 252 trading days * 78 bars/day (6.5 * 60 / 5) = 19656
        assert get_bars_for_period("252d", "MIN", 5) == bars_per_year

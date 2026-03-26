"""
Tests for helpers/timeframe_utils.py — get_bars_for_period().

This is a pure conversion function with no I/O and no external dependencies.
All possible branches are tested including every unit×timeframe combination
and every error path.
"""

import os
import sys
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.timeframe_utils import get_bars_for_period


# ---------------------------------------------------------------------------
# Daily timeframe ('D')
# ---------------------------------------------------------------------------

class TestDailyTimeframe:

    def test_days_on_daily_returns_value(self):
        """'200d' on daily chart → 200 bars."""
        assert get_bars_for_period("200d", "D") == 200

    def test_single_day(self):
        assert get_bars_for_period("1d", "D") == 1

    def test_large_period(self):
        assert get_bars_for_period("1000d", "D") == 1000

    def test_hour_unit_raises_on_daily(self):
        with pytest.raises(ValueError, match="Daily"):
            get_bars_for_period("14h", "D")

    def test_minute_unit_raises_on_daily(self):
        with pytest.raises(ValueError):
            get_bars_for_period("30min", "D")

    def test_multiplier_ignored_for_daily_days(self):
        """For Daily timeframe with 'd' unit, multiplier has no effect."""
        assert get_bars_for_period("50d", "D", multiplier=5) == 50


# ---------------------------------------------------------------------------
# Hourly timeframe ('H')
# ---------------------------------------------------------------------------

class TestHourlyTimeframe:

    def test_days_converts_to_hours(self):
        """'1d' on hourly chart = 6.5 bars (int → 6)."""
        result = get_bars_for_period("1d", "H")
        assert result == int(1 * 6.5)

    def test_200d_hourly(self):
        assert get_bars_for_period("200d", "H") == int(200 * 6.5)

    def test_hours_on_hourly_returns_value(self):
        assert get_bars_for_period("14h", "H") == 14

    def test_minute_unit_raises_on_hourly(self):
        with pytest.raises(ValueError, match="Hourly"):
            get_bars_for_period("30min", "H")

    def test_day_unit_gives_correct_bars(self):
        # 20 days * 6.5 hours/day = 130 bars
        assert get_bars_for_period("20d", "H") == 130


# ---------------------------------------------------------------------------
# Minute timeframe ('MIN')
# ---------------------------------------------------------------------------

class TestMinuteTimeframe:

    def test_days_with_5min_bars(self):
        """20d on 5-min chart: bars/day = 6.5*60/5 = 78; total = 20*78 = 1560."""
        result = get_bars_for_period("20d", "MIN", multiplier=5)
        expected = int(20 * int(6.5 * 60 / 5))
        assert result == expected

    def test_hours_with_5min_bars(self):
        """1h on 5-min chart: 60/5 = 12 bars."""
        result = get_bars_for_period("1h", "MIN", multiplier=5)
        assert result == int(1 * (60 / 5))

    def test_min_unit_with_5min_bars(self):
        """60min on 5-min chart: 60/5 = 12 bars."""
        result = get_bars_for_period("60min", "MIN", multiplier=5)
        assert result == int(60 / 5)

    def test_1min_bars_days(self):
        """20d on 1-min chart: 6.5 * 60 = 390 bars/day → 7800 total."""
        result = get_bars_for_period("20d", "MIN", multiplier=1)
        assert result == 20 * 390

    def test_invalid_unit_raises_on_minute(self):
        with pytest.raises(ValueError, match="Minute"):
            get_bars_for_period("5w", "MIN", multiplier=5)


# ---------------------------------------------------------------------------
# Unsupported timeframe
# ---------------------------------------------------------------------------

class TestUnsupportedTimeframe:

    def test_weekly_timeframe_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            get_bars_for_period("20d", "W")

    def test_monthly_timeframe_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            get_bars_for_period("20d", "M")

    def test_empty_timeframe_raises(self):
        with pytest.raises(ValueError):
            get_bars_for_period("20d", "")


# ---------------------------------------------------------------------------
# Invalid period_str
# ---------------------------------------------------------------------------

class TestInvalidPeriodStr:

    def test_no_digits_raises(self):
        with pytest.raises(ValueError, match="Invalid"):
            get_bars_for_period("d", "D")

    def test_none_raises(self):
        with pytest.raises((ValueError, TypeError)):
            get_bars_for_period(None, "D")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            get_bars_for_period("", "D")

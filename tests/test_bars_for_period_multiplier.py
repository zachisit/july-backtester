"""
Regression tests for issue #318 (and the H-branch half of #267) —
``get_bars_for_period`` ignored ``timeframe_multiplier`` on hourly bars and
pre-truncated bars-per-day on minute bars.

- ``H`` timeframe, ``'d'``/``'h'`` units: the multiplier was ignored, so
  ``get_bars_for_period("20d", "H", 2)`` returned 130 (as if multiplier were 1)
  instead of 65 (20 RTH sessions at 2h/bar = 20*6.5/2).
- ``MIN`` timeframe, ``'d'`` unit: ``BARS_PER_DAY = int(390 / multiplier)`` was
  truncated first, so 60-minute bars used 6 bars/day instead of 6.5 — ``"200d"``
  → 1200 instead of 1300 (−7.7%).

The fix divides by the multiplier and truncates (not rounds) at the end, so
every multiplier=1 result is byte-for-byte unchanged; sub-bar periods are
floored at 1 so a lookback is never 0.
"""

import pytest

from helpers.timeframe_utils import (
    get_bars_for_period, get_bars_per_day, get_bars_per_day_exact,
)


class TestHourlyMultiplier:
    def test_20d_2h(self):
        # 20 RTH sessions at 2h/bar = 20 * 6.5 / 2 = 65 bars (was 130).
        assert get_bars_for_period("20d", "H", 2) == 65

    def test_200d_4h(self):
        # 200 * 6.5 / 4 = 325 bars (was 1300).
        assert get_bars_for_period("200d", "H", 4) == 325

    def test_hours_unit_honours_multiplier(self):
        # 50 hours at 2h/bar = 25 bars (was 50).
        assert get_bars_for_period("50h", "H", 2) == 25

    def test_multiplier_one_unchanged(self):
        assert get_bars_for_period("200d", "H", 1) == 1300
        assert get_bars_for_period("50h", "H", 1) == 50


class TestMinuteMultiplier:
    def test_200d_60min_uses_exact_bars_per_day(self):
        # 6.5 * 60 / 60 = 6.5 bars/day -> 200 * 6.5 = 1300 (was int(390/60)=6 -> 1200).
        assert get_bars_for_period("200d", "MIN", 60) == 1300

    def test_multiplier_5_unchanged(self):
        # 6.5*60/5 = 78 bars/day exactly -> 14*78 = 1092 (no truncation loss).
        assert get_bars_for_period("14d", "MIN", 5) == 1092

    def test_multiplier_one_unchanged(self):
        assert get_bars_for_period("60min", "MIN", 1) == 60


class TestTruncateNotRound:
    """The fix truncates (not rounds) at the end, so multiplier=1 lookbacks that
    existing intraday strategies depend on are byte-for-byte unchanged."""

    def test_odd_day_hourly_truncates(self):
        # 7 * 6.5 = 45.5 -> 45 (truncate, as before), NOT 46 (round). Pins that a
        # future round() reimplementation can't silently shift RSI(7/20)'s "7d".
        assert get_bars_for_period("7d", "H", 1) == 45

    def test_rsi_7_20_hourly_lookback_unchanged(self):
        # The registered "RSI Mean Reversion (7/20)" strategy uses "7d".
        assert get_bars_for_period("7d", "H", 1) == 45

    def test_minute_h_unit_honours_multiplier(self):
        # "2h" on 5-min bars = 2*60/5 = 24 bars.
        assert get_bars_for_period("2h", "MIN", 5) == 24


class TestFloorAtOne:
    """A sub-bar period must floor to 1, never 0 (0 -> rolling(0) all-NaN)."""

    def test_hours_smaller_than_bar_floors_to_one(self):
        # "2h" on 4H bars = 0.5 -> floored to 1 (old H 'h' branch returned value=2;
        # the point is it must never be 0).
        assert get_bars_for_period("2h", "H", 4) == 1

    def test_minutes_smaller_than_bar_floors_to_one(self):
        assert get_bars_for_period("5min", "MIN", 15) == 1


class TestConsistencyWithBarsPerDay:
    @pytest.mark.parametrize("tf,mult", [("H", 1), ("H", 2), ("H", 4),
                                         ("MIN", 1), ("MIN", 5), ("MIN", 60)])
    def test_one_day_matches_bars_per_day(self, tf, mult):
        # "1d" of bars must equal get_bars_per_day (both are floored-truncate bar
        # counts) — ties get_bars_for_period to the ADV-path helper.
        expected = get_bars_per_day({"timeframe": tf, "timeframe_multiplier": mult})
        assert get_bars_for_period("1d", tf, mult) == expected


class TestUnchangedTimeframes:
    def test_daily(self):
        assert get_bars_for_period("200d", "D", 1) == 200

    def test_weekly(self):
        assert get_bars_for_period("10d", "W", 1) == 2  # round(10/5)

    def test_monthly(self):
        assert get_bars_for_period("42d", "M", 1) == 2  # round(42/21)

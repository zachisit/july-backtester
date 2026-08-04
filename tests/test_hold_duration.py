"""Regression tests for sub-day HoldDuration precision (#241).

`HoldDuration` was computed via `(exit - entry).days`, which truncated all
sub-day precision — every 45-minute trade read 0, corrupting `Avg. Hold` / `# bars`.
`_hold_duration_days` preserves fractional days for intraday trades while staying
byte-identical (an `int`) for whole-day / daily-normalized spans, so the engine
golden master is unaffected.
"""
import pandas as pd

from helpers.portfolio_simulations import _hold_duration_days


class TestHoldDurationDays:
    def test_whole_day_span_returns_int_matching_legacy(self):
        entry = pd.Timestamp("2024-01-01")
        exit_ = pd.Timestamp("2024-01-04")
        result = _hold_duration_days(entry, exit_)
        assert result == 3
        assert isinstance(result, int)
        # byte-identical to the previous `.days` behaviour
        assert result == (exit_ - entry).days

    def test_midnight_normalized_multiday_is_int(self):
        entry = pd.Timestamp("2020-03-02 00:00:00")
        exit_ = pd.Timestamp("2020-05-11 00:00:00")
        result = _hold_duration_days(entry, exit_)
        assert isinstance(result, int)
        assert result == (exit_ - entry).days

    def test_zero_duration_is_zero_int(self):
        ts = pd.Timestamp("2024-01-01 10:00:00")
        assert _hold_duration_days(ts, ts) == 0
        assert isinstance(_hold_duration_days(ts, ts), int)

    def test_intraday_span_is_fractional_not_truncated(self):
        # 45-minute trade: legacy .days == 0; fix must report a positive fraction.
        entry = pd.Timestamp("2024-01-01 10:00:00")
        exit_ = pd.Timestamp("2024-01-01 10:45:00")
        result = _hold_duration_days(entry, exit_)
        assert (exit_ - entry).days == 0  # the bug the fix addresses
        assert 0.0 < result < 1.0
        assert abs(result - (45 / (24 * 60))) < 1e-4  # ~0.03125 days
        assert isinstance(result, float)

    def test_multiday_intraday_keeps_fraction(self):
        # 2 days 12 hours -> 2.5, where legacy .days would truncate to 2.
        entry = pd.Timestamp("2024-01-01 10:00:00")
        exit_ = pd.Timestamp("2024-01-03 22:00:00")
        result = _hold_duration_days(entry, exit_)
        assert (exit_ - entry).days == 2
        assert abs(result - 2.5) < 1e-9

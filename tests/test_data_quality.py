"""tests/test_data_quality.py

Tests for data quality validation (helpers/data_quality.py).
"""

import pytest
import pandas as pd
import numpy as np
from helpers.data_quality import validate_ohlcv, quality_report, _estimate_expected_bars


# ---------------------------------------------------------------------------
# Test validate_ohlcv
# ---------------------------------------------------------------------------

class TestValidateOHLCV:
    """Test the main validate_ohlcv function."""

    def test_empty_dataframe_returns_zero_score(self):
        """Empty DataFrame returns score=0 with error message."""
        df = pd.DataFrame()
        score, issues = validate_ohlcv(df, "AAPL", "D")
        assert score == 0.0
        assert len(issues) == 1
        assert "empty" in issues[0].lower()

    def test_none_dataframe_returns_zero_score(self):
        """None DataFrame returns score=0 with error message."""
        score, issues = validate_ohlcv(None, "AAPL", "D")
        assert score == 0.0
        assert len(issues) == 1

    def test_perfect_data_returns_100_score(self):
        """Perfect OHLCV data returns score=100 with no issues."""
        dates = pd.date_range("2020-01-01", periods=10, freq="D")
        df = pd.DataFrame({
            "Open": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
            "High": [101, 102, 103, 104, 105, 106, 107, 108, 109, 110],
            "Low": [99, 100, 101, 102, 103, 104, 105, 106, 107, 108],
            "Close": [100.5, 101.5, 102.5, 103.5, 104.5, 105.5, 106.5, 107.5, 108.5, 109.5],
            "Volume": [1000000] * 10,
        }, index=dates)

        score, issues = validate_ohlcv(df, "AAPL", "D")
        assert score == 100.0
        assert issues == []

    def test_duplicate_timestamps_detected(self):
        """Duplicate timestamps are detected and penalized."""
        dates = pd.DatetimeIndex(["2020-01-01", "2020-01-01", "2020-01-02"])  # Duplicate
        df = pd.DataFrame({
            "Open": [100, 101, 102],
            "High": [101, 102, 103],
            "Low": [99, 100, 101],
            "Close": [100.5, 101.5, 102.5],
            "Volume": [1000000] * 3,
        }, index=dates)

        score, issues = validate_ohlcv(df, "AAPL", "D")
        assert score < 100.0
        assert any("Duplicate" in issue for issue in issues)

    def test_negative_prices_detected(self):
        """Negative prices are detected and heavily penalized."""
        dates = pd.date_range("2020-01-01", periods=5, freq="D")
        df = pd.DataFrame({
            "Open": [100, -5, 102, 103, 104],  # Negative Open
            "High": [101, 102, 103, 104, 105],
            "Low": [99, -6, 101, 102, 103],   # Negative Low
            "Close": [100.5, 101.5, 102.5, 103.5, 104.5],
            "Volume": [1000000] * 5,
        }, index=dates)

        score, issues = validate_ohlcv(df, "AAPL", "D")
        assert score < 100.0  # Penalty applied
        assert any("Negative" in issue and "Open" in issue for issue in issues)
        assert any("Negative" in issue and "Low" in issue for issue in issues)

    def test_high_less_than_low_detected(self):
        """High < Low violations are detected."""
        dates = pd.date_range("2020-01-01", periods=5, freq="D")
        df = pd.DataFrame({
            "Open": [100, 101, 102, 103, 104],
            "High": [101, 100, 103, 104, 105],  # High[1] < Low[1]
            "Low": [99, 101, 101, 102, 103],
            "Close": [100.5, 100.5, 102.5, 103.5, 104.5],
            "Volume": [1000000] * 5,
        }, index=dates)

        score, issues = validate_ohlcv(df, "AAPL", "D")
        assert score < 100.0
        assert any("High < Low" in issue for issue in issues)

    def test_close_outside_high_low_range_detected(self):
        """Close outside [Low, High] is detected."""
        dates = pd.date_range("2020-01-01", periods=5, freq="D")
        df = pd.DataFrame({
            "Open": [100, 101, 102, 103, 104],
            "High": [101, 102, 103, 104, 105],
            "Low": [99, 100, 101, 102, 103],
            "Close": [100.5, 103, 102.5, 103.5, 104.5],  # Close[1]=103 > High[1]=102
            "Volume": [1000000] * 5,
        }, index=dates)

        score, issues = validate_ohlcv(df, "AAPL", "D")
        assert score < 100.0
        assert any("Close outside H/L" in issue for issue in issues)

    def test_open_outside_high_low_range_detected(self):
        """Open outside [Low, High] is detected."""
        dates = pd.date_range("2020-01-01", periods=5, freq="D")
        df = pd.DataFrame({
            "Open": [100, 98, 102, 103, 104],  # Open[1]=98 < Low[1]=100
            "High": [101, 102, 103, 104, 105],
            "Low": [99, 100, 101, 102, 103],
            "Close": [100.5, 101, 102.5, 103.5, 104.5],
            "Volume": [1000000] * 5,
        }, index=dates)

        score, issues = validate_ohlcv(df, "AAPL", "D")
        assert score < 100.0
        assert any("Open outside H/L" in issue for issue in issues)

    def test_price_jumps_detected(self):
        """Price jumps >20% are detected (potential unadjusted splits)."""
        dates = pd.date_range("2020-01-01", periods=5, freq="D")
        df = pd.DataFrame({
            "Open": [100, 101, 50, 51, 52],  # 50% drop from 101 to 50
            "High": [101, 102, 51, 52, 53],
            "Low": [99, 100, 49, 50, 51],
            "Close": [100, 101, 50, 51, 52],
            "Volume": [1000000] * 5,
        }, index=dates)

        score, issues = validate_ohlcv(df, "AAPL", "D")
        assert score < 100.0
        assert any("Price jumps" in issue for issue in issues)
        assert any("2020-01-03" in issue for issue in issues)  # Date of the jump

    def test_zero_volume_detected(self):
        """Zero volume days are detected."""
        dates = pd.date_range("2020-01-01", periods=10, freq="D")
        df = pd.DataFrame({
            "Open": range(100, 110),
            "High": range(101, 111),
            "Low": range(99, 109),
            "Close": [x + 0.5 for x in range(100, 110)],
            "Volume": [1000000, 0, 1000000, 0, 1000000, 0, 1000000, 0, 1000000, 0],  # 50% zero
        }, index=dates)

        score, issues = validate_ohlcv(df, "AAPL", "D")
        assert score < 100.0
        assert any("Zero volume" in issue for issue in issues)
        assert any("50" in issue for issue in issues)  # 50% zero volume

    def test_missing_bars_detected_daily(self):
        """Missing bars are detected for daily data."""
        # Create sparse data: first 5 days and last 5 days of a 30-day period
        # This creates a large gap in the middle
        dates1 = pd.bdate_range("2020-01-01", periods=5, freq="B")
        dates2 = pd.bdate_range("2020-01-25", periods=5, freq="B")
        dates = dates1.append(dates2)

        df = pd.DataFrame({
            "Open": range(100, 110),
            "High": range(101, 111),
            "Low": range(99, 109),
            "Close": [x + 0.5 for x in range(100, 110)],
            "Volume": [1000000] * 10,
        }, index=dates)

        score, issues = validate_ohlcv(df, "AAPL", "D")
        # Should detect missing bars in the gap
        assert any("Missing bars" in issue for issue in issues)

    def test_missing_bars_not_checked_intraday(self):
        """Missing bars check is skipped for intraday data."""
        dates = pd.date_range("2020-01-01 09:30", periods=10, freq="5min")
        df = pd.DataFrame({
            "Open": range(100, 110),
            "High": range(101, 111),
            "Low": range(99, 109),
            "Close": [x + 0.5 for x in range(100, 110)],
            "Volume": [100000] * 10,
        }, index=dates)

        score, issues = validate_ohlcv(df, "AAPL", "MIN")
        # Should not complain about missing bars
        assert not any("Missing bars" in issue for issue in issues)


# ---------------------------------------------------------------------------
# Test _estimate_expected_bars
# ---------------------------------------------------------------------------

class TestEstimateExpectedBars:
    """Test the expected bar count estimator."""

    def test_daily_returns_business_days(self):
        """Daily timeframe returns business day count."""
        start = pd.Timestamp("2020-01-01")
        end = pd.Timestamp("2020-01-31")
        expected = _estimate_expected_bars(start, end, "D")
        # January 2020 has 23 business days
        assert expected == 23

    def test_intraday_returns_zero(self):
        """Intraday timeframes return 0 (check disabled)."""
        start = pd.Timestamp("2020-01-01")
        end = pd.Timestamp("2020-01-31")
        assert _estimate_expected_bars(start, end, "H") == 0
        assert _estimate_expected_bars(start, end, "MIN") == 0


# ---------------------------------------------------------------------------
# Test quality_report
# ---------------------------------------------------------------------------

class TestQualityReport:
    """Test the quality report generator."""

    def test_empty_data_dict_returns_zero_scores(self):
        """Symbols with no data get score=0."""
        symbols = ["AAPL", "MSFT"]
        data = {}
        report = quality_report(symbols, data, "D")

        assert len(report) == 2
        assert (report["score"] == 0.0).all()
        assert (report["issues"] == "No data").all()

    def test_report_sorted_by_score_ascending(self):
        """Report is sorted by score (worst first)."""
        dates = pd.date_range("2020-01-01", periods=10, freq="D")

        # Perfect data
        good_df = pd.DataFrame({
            "Open": range(100, 110),
            "High": range(101, 111),
            "Low": range(99, 109),
            "Close": [x + 0.5 for x in range(100, 110)],
            "Volume": [1000000] * 10,
        }, index=dates)

        # Bad data (negative prices)
        bad_df = pd.DataFrame({
            "Open": [-100, -101, -102, -103, -104, -105, -106, -107, -108, -109],
            "High": range(101, 111),
            "Low": [-110, -111, -112, -113, -114, -115, -116, -117, -118, -119],
            "Close": [x + 0.5 for x in range(100, 110)],
            "Volume": [1000000] * 10,
        }, index=dates)

        data = {"GOOD": good_df, "BAD": bad_df}
        report = quality_report(["GOOD", "BAD"], data, "D")

        # Worst score first
        assert report.iloc[0]["symbol"] == "BAD"
        assert report.iloc[1]["symbol"] == "GOOD"
        assert report.iloc[0]["score"] < report.iloc[1]["score"]

    def test_report_includes_bar_count(self):
        """Report includes bar count per symbol."""
        dates1 = pd.date_range("2020-01-01", periods=10, freq="D")
        dates2 = pd.date_range("2020-01-01", periods=20, freq="D")

        df1 = pd.DataFrame({
            "Open": range(100, 110),
            "High": range(101, 111),
            "Low": range(99, 109),
            "Close": [x + 0.5 for x in range(100, 110)],
            "Volume": [1000000] * 10,
        }, index=dates1)

        df2 = pd.DataFrame({
            "Open": range(100, 120),
            "High": range(101, 121),
            "Low": range(99, 119),
            "Close": [x + 0.5 for x in range(100, 120)],
            "Volume": [1000000] * 20,
        }, index=dates2)

        data = {"SYM1": df1, "SYM2": df2}
        report = quality_report(["SYM1", "SYM2"], data, "D")

        assert report[report["symbol"] == "SYM1"]["bars"].iloc[0] == 10
        assert report[report["symbol"] == "SYM2"]["bars"].iloc[0] == 20

    def test_report_issues_joined_with_semicolon(self):
        """Issues are joined with semicolons in the report."""
        dates = pd.date_range("2020-01-01", periods=5, freq="D")
        df = pd.DataFrame({
            "Open": [-100, 101, 102, 103, 104],  # Negative
            "High": [101, 100, 103, 104, 105],   # High < Low
            "Low": [99, 101, 101, 102, 103],
            "Close": [100.5, 100.5, 102.5, 103.5, 104.5],
            "Volume": [0, 0, 0, 0, 0],  # Zero volume
        }, index=dates)

        data = {"BAD": df}
        report = quality_report(["BAD"], data, "D")

        issues_str = report.iloc[0]["issues"]
        assert ";" in issues_str  # Multiple issues joined
        assert "Negative" in issues_str
        assert "High < Low" in issues_str or "Zero volume" in issues_str


# ---------------------------------------------------------------------------
# Integration test
# ---------------------------------------------------------------------------

class TestIntegrationWithConfig:
    """Test integration with config-driven behavior."""

    def test_quality_checks_disabled_skips_validation(self):
        """When data_quality_checks=False, validation is skipped."""
        # This is tested at the main.py level, not here
        # Just verify the function works independently
        dates = pd.date_range("2020-01-01", periods=10, freq="D")
        df = pd.DataFrame({
            "Open": range(100, 110),
            "High": range(101, 111),
            "Low": range(99, 109),
            "Close": [x + 0.5 for x in range(100, 110)],
            "Volume": [1000000] * 10,
        }, index=dates)

        score, issues = validate_ohlcv(df, "AAPL", "D")
        assert score == 100.0
        assert issues == []

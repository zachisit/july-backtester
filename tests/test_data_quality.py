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


class TestMissingBarsCapDoesNotSaturateAtTheGate:
    """#378: `min(20, int(pct / 2))` saturated at exactly 40% missing, and
    `100 - 20 == 80` is the gate.

    So a series missing >=40% of its expected bars scored EXACTLY 80.0 by
    construction and passed -- the term could not charge a 21st point, so the
    score could not move off the gate however bad the coverage got. Corpus
    census: 26 series missing >=90% of their history scored 80.0 and passed,
    indistinguishable from one missing 60%.

    EVERY ASSERTION HERE IS COMPARATIVE. A sparse frame also trips CHECK 8
    (`Sparse history`, a flat 25), so an absolute threshold does not isolate
    this term -- two of these tests were written that way first and passed
    under the OLD cap, which is the vacuity they were meant to catch one level
    down. Differencing two sparsities cancels the constant.

    Asserted as a property rather than against the census counts, which need
    the merged corpus and would need updating whenever another check moves.
    """

    @staticmethod
    def _sparse(missing_pct):
        """A clean daily series missing `missing_pct` of its expected sessions.

        Parameterised by the MISSING fraction and built by selecting evenly
        spaced positions across a fixed span -- not by an integer stride. A
        stride of `round(1 / keep)` collapses 0.40 and 0.50 onto the same
        frame (both round to 2), so two supposedly different sparsities were
        the identical DataFrame and the comparison was vacuous.
        """
        full = pd.bdate_range("2020-01-01", periods=1000)
        n = max(2, int(round(len(full) * (1.0 - missing_pct))))
        pos = np.unique(np.linspace(0, len(full) - 1, n).round().astype(int))
        idx = full[pos]
        m = len(idx)
        price = np.linspace(50.0, 60.0, m)
        return pd.DataFrame({"Open": price, "High": price * 1.01,
                             "Low": price * 0.99, "Close": price,
                             "Volume": np.full(m, 1_000_000.0)}, index=idx)

    def _score(self, missing_pct):
        return validate_ohlcv(self._sparse(missing_pct), "MISS", "D")[0]

    def test_the_40_percent_case_still_lands_exactly_on_the_gate(self):
        """The DEFECT, reproduced -- and the documented residue of the fix.

        40% missing with nothing else wrong scores exactly 80.0, because
        `int(40/2)` is 20 under any cap >= 20. Raising the cap to 30 does not
        move this row and was never going to: the census leaves 90 series here
        for the same reason, which is why 45 and uncapped also leave 90 and
        buy nothing at the gate.

        Pinned so the residue is a known property rather than a surprise, and
        so nobody "finishes" #378 by tuning the cap upward -- the 40-42% band
        needs a different term, not a bigger number.
        """
        score, issues = validate_ohlcv(self._sparse(0.40), "MISS40", "D")
        assert score == pytest.approx(80.0), (score, issues)
        assert [i for i in issues if "Missing bars" in i], issues
        assert len(issues) == 1, (
            f"fixture is no longer isolating the missing-bars term: {issues}")

    def test_the_charge_keeps_accumulating_in_the_40_to_60_band(self):
        """The band where the two caps differ, and the ONLY one.

        `int(pct/2)` reaches 20 at 40% missing and 30 at 60%, so cap 20
        saturates at 40 and cap 30 at 60 -- outside 40..60 the two are
        identical by construction and no fixture can tell them apart. A
        monotonicity test over a wider range passes under BOTH caps, because
        there is a genuine decrease below 40%; that version was written first
        and did not discriminate.
        """
        s50, s60 = self._score(0.50), self._score(0.60)
        assert s60 < s50, (
            f"60%-missing scored {s60} and 50%-missing scored {s50}; the term "
            f"stopped charging inside the 40-60% band, which is the old cap")

    def test_a_cap_still_exists(self):
        """Guards REMOVAL of the cap, not its value.

        Stated plainly because it does not discriminate 20 from 30: beyond 60%
        missing both caps bind, so this passes under either. What it catches is
        someone deleting the `min(...)` entirely, which would make a 99%-empty
        series unbounded and is the opposite over-correction.
        """
        assert self._score(0.95) == self._score(0.98), (
            "95%- and 98%-missing scored differently; the cap is not binding")

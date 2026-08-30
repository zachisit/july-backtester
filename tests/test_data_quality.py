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
        """Negative prices are detected and heavily penalized.

        Wording widened to "Non-positive" with #369 -- the check now covers
        `<= 0`, and "Negative Close prices" would be actively wrong on a
        series whose problem is that they are zero. See TestNonPositivePrices.
        """
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
        assert any("Non-positive" in issue and "Open" in issue for issue in issues)
        assert any("Non-positive" in issue and "Low" in issue for issue in issues)

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
        assert "Non-positive" in issues_str
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


# ---------------------------------------------------------------------------
# CHECK 2 — non-positive prices (#369)
# ---------------------------------------------------------------------------

# PROVENANCE: transcribed by @shardul0701 from
#   data/market_data/merged/UFMC-200512.parquet
# during the corpus census on issue #369 (2026-08-30), and posted there in
# full. These are READ VALUES, not constructed ones -- stated explicitly so a
# later reader can tell a deliberate transcription from a made-up number,
# which is not otherwise recoverable once the source is out of reach.
#
# The six zero-carrying bars of UFMC-200512, TRANSCRIBED rather than read.
# `data/market_data/merged/` is gitignored, so a test that opens the parquet
# passes here and errors on a fresh clone and in CI -- the same convention
# tests/test_rule_based_universe.py follows with its synthetic corpus. These
# are not synthetic: they are the tape, as literals. Census + bars from
# @shardul0701 on #369.
#
#             open   high    low  close  volume
# 1998-07-02   0.0  6.875  6.875  6.875     100   <- open-only zero
# 1998-07-29   0.0  0.000  0.000  0.000     900   <- fully zero
# 1998-09-02   0.0  0.000  0.000  0.000    1300   <- fully zero
# 2000-12-21   0.0  0.750  0.750  0.750     500   <- open-only zero
# 2001-09-19   0.0  1.300  1.300  1.300    1000   <- open-only zero
# 2002-07-10   0.0  0.000  0.000  0.000     100   <- fully zero
#
# 1,277 bars total; open ==0 -> 6, high/low/close ==0 -> 3 each. All six carry
# source="norgate": these are PROVENANCED bars with a bad value, NOT the
# null-source trailing-bar class of #365/#371. Different defect, different fix.

_UFMC_FULLY_ZERO = (0.0, 0.0, 0.0, 0.0)            # 1998-07-29, 1998-09-02, 2002-07-10
_UFMC_OPEN_ONLY_ZERO = (0.0, 6.875, 6.875, 6.875)  # 1998-07-02 (single-print day)

_CLEAN = (10.0, 10.5, 9.5, 10.0)


def _bars(rows):
    """rows: list of (open, high, low, close) on a contiguous business index."""
    idx = pd.bdate_range("2020-01-01", periods=len(rows))
    return pd.DataFrame({
        "Open":  [r[0] for r in rows],
        "High":  [r[1] for r in rows],
        "Low":   [r[2] for r in rows],
        "Close": [r[3] for r in rows],
        "Volume": [1_000_000] * len(rows),
    }, index=idx)


class TestNonPositivePrices:
    """CHECK 2 guarded `< 0`, a shape that has never occurred: zero negative
    prices in all 35,309 series of the corpus. The one real instance of the
    defect family it exists to catch is a ZERO, which is the shape it did not
    test for. The check was dead code, and narrow in the only direction that
    ever occurs.
    """

    def test_a_fully_zero_bar_is_invisible_to_check_3(self):
        """The structural reason CHECK 2 has to widen, pinned by the data.

        On a 0/0/0/0 bar every relationship holds -- `High >= Low` is `0 >= 0`,
        and both Open and Close sit inside `[0, 0]`. A relationship check
        cannot see a value that agrees with all of its relations, so CHECK 3
        is not missing these by oversight and no tightening of it would help.
        """
        _, issues = validate_ohlcv(_bars([_CLEAN, _UFMC_FULLY_ZERO, _CLEAN]), "UFMC", "D")
        relational = [i for i in issues
                      if "High < Low" in i or "outside H/L range" in i]
        assert not relational, (
            f"CHECK 3 saw a fully-zero bar; the premise of this fix is that it "
            f"cannot: {relational}")

    def test_an_open_only_zero_bar_is_caught_by_check_3(self):
        """The paired control, and the other half of the same file.

        1998-07-02 is a single-print day (high == low == close) whose open was
        never recorded. Here the zero DISAGREES with its neighbours, so
        `Open < Low` fires and CHECK 3 sees it. Same series, same defect
        family, opposite outcome -- the difference is purely whether the zero
        contradicts anything.
        """
        _, issues = validate_ohlcv(_bars([_CLEAN, _UFMC_OPEN_ONLY_ZERO, _CLEAN]), "UFMC", "D")
        assert any("Open outside H/L range" in i for i in issues), issues

    @pytest.mark.parametrize("col,row", [
        ("Open",  (0.0, 10.5, 9.5, 10.0)),
        ("High",  (10.0, 0.0, 0.0, 0.0)),
        ("Low",   (10.0, 10.5, 0.0, 10.0)),
        ("Close", (10.0, 10.5, 9.5, 0.0)),
    ])
    def test_a_zero_price_is_charged_as_non_positive(self, col, row):
        """The fix: `<= 0`, not `< 0`, on each of the four price columns."""
        _, issues = validate_ohlcv(_bars([_CLEAN, row, _CLEAN]), "UFMC", "D")
        assert any("Non-positive" in i and col in i for i in issues), (
            f"a zero {col} was not charged by CHECK 2: {issues}")

    def test_negative_prices_are_still_charged(self):
        """No-regression: widening the operator must not stop catching the
        shape the check was originally written for."""
        _, issues = validate_ohlcv(_bars([_CLEAN, (-5.0, 10.5, 9.5, 10.0), _CLEAN]), "X", "D")
        assert any("Non-positive" in i and "Open" in i for i in issues), issues

    def test_zero_volume_is_not_charged_by_check_2(self):
        """Volume is deliberately untouched. A zero-volume session is real and
        common; a zero PRICE is not."""
        df = _bars([_CLEAN, _CLEAN, _CLEAN])
        df["Volume"] = [1_000_000, 0, 1_000_000]
        _, issues = validate_ohlcv(df, "X", "D")
        assert not any("Non-positive Volume" in i for i in issues), issues

    def test_the_open_only_bars_are_charged_by_both_checks(self):
        """The double-charge is correct, not a bug.

        After the widening an open-only-zero bar is charged by CHECK 3 (the
        open contradicts H/L) AND by CHECK 2 (the open is non-positive). Both
        are true statements about that bar. Pinned so nobody later "fixes" the
        apparent duplication by suppressing one of them.
        """
        _, issues = validate_ohlcv(_bars([_CLEAN, _UFMC_OPEN_ONLY_ZERO, _CLEAN]), "UFMC", "D")
        assert any("Open outside H/L range" in i for i in issues), issues
        assert any("Non-positive" in i and "Open" in i for i in issues), issues

    def test_the_30_point_cap_actually_binds(self):
        """The cap must be reachable, and reaching it must not floor the score.

        With the charge inside the column loop, `min(30, ...)` capped each
        COLUMN, so a single check could contribute 4 x 30 = 120 on a 100-point
        budget. The cap sat above the whole budget and could never bind: on an
        otherwise-perfect 10,000-bar series, 5 fully-zero bars (0.05%) scored
        0.0 -- identical to 1,000 of them (10%).

        Charging once per bar makes the cap mean what it says. Asserted as a
        PLATEAU rather than a specific number: 20 bad bars and 1,000 bad bars
        must score the same, and that score must be above zero, because the
        check's own ceiling is 30 of 100. @shardul0701 on #379.
        """
        import numpy as np
        n = 10_000

        def series(n_bad):
            idx = pd.bdate_range("1990-01-01", periods=n)
            o = np.full(n, 10.0); h = np.full(n, 10.5)
            lo = np.full(n, 9.5); c = np.full(n, 10.0)
            o[:n_bad] = h[:n_bad] = lo[:n_bad] = c[:n_bad] = 0.0
            return pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c,
                                 "Volume": np.full(n, 1e6)}, index=idx)

        s20, _ = validate_ohlcv(series(20), "T", "D")
        s1000, _ = validate_ohlcv(series(1000), "T", "D")
        assert s20 == pytest.approx(s1000), (
            f"20 bad bars scored {s20} and 1000 scored {s1000}; the cap is not "
            f"binding, so the charge is unbounded in practice")
        assert s20 > 0.0, (
            f"score floored at {s20} with a check whose own cap is 30/100 — "
            f"the per-column charge is back")

    def test_a_few_bad_bars_do_not_destroy_a_long_series(self):
        """Severity must scale with the defect, not sit at maximum.

        Five bad bars in ten thousand is 0.05% of a series. Pre-fix that
        scored 0.0 -- unusable, and indistinguishable from a series that is
        10% zeros.
        """
        import numpy as np
        n = 10_000
        idx = pd.bdate_range("1990-01-01", periods=n)
        o = np.full(n, 10.0); h = np.full(n, 10.5)
        lo = np.full(n, 9.5); c = np.full(n, 10.0)
        o[:5] = h[:5] = lo[:5] = c[:5] = 0.0
        df = pd.DataFrame({"Open": o, "High": h, "Low": lo, "Close": c,
                           "Volume": np.full(n, 1e6)}, index=idx)
        score, _ = validate_ohlcv(df, "T", "D")
        assert score > 50.0, (
            f"0.05% bad bars scored {score}; the charge is not proportionate")

    def test_one_bar_is_charged_once_however_many_columns_are_zero(self):
        """A fully-zero bar makes ONE statement -- this bar has no price -- and
        was charged four times for it, while an open-only zero (an internally
        CONTRADICTORY bar, arguably the more suspicious shape) was charged once.

        Asserted on the issue text rather than the score, because the two
        shapes legitimately differ in score: the open-only bar also trips
        CHECK 3, which is correct and is pinned separately above.
        """
        df = _bars([_CLEAN, _UFMC_FULLY_ZERO, _CLEAN])
        _, issues = validate_ohlcv(df, "UFMC", "D")
        nonpos = [i for i in issues if "Non-positive" in i]
        assert len(nonpos) == 1, (
            f"expected one non-positive issue for one bad bar, got "
            f"{len(nonpos)}: {nonpos}")
        # ...and it names every column it found, so nothing is lost by folding.
        assert all(c in nonpos[0] for c in ("Open", "High", "Low", "Close")), nonpos[0]

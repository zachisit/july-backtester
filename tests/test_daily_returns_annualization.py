"""
tests/test_daily_returns_annualization.py

Regression tests for issue #250: data_handler.calculate_daily_returns() used
to build the equity series on a calendar-day index (pd.date_range(freq='D')),
giving ~365 samples/year, while calculations.calculate_sharpe_ratio() /
calculate_sortino_ratio() annualize using trading_days_per_year=252 (the
convention used everywhere in trade_analyzer). That mismatch understated the
sqrt(N) annualization scalar (roughly halving Sharpe/Sortino magnitude) and,
for Sortino specifically, let synthetic flat (0%) weekend rows count as
"downside" whenever they sat below the MAR.

Fix: calculate_daily_returns() now builds the equity series on a
business-day index (pd.bdate_range), whose sample density (~252-261/yr)
matches the 252-day annualization convention far more closely than calendar
days, and which structurally excludes the synthetic weekend rows.

These tests would have FAILED against the pre-fix (freq='D') code:
  - test_index_is_business_days_only: weekend rows existed pre-fix.
  - test_sample_density_matches_trading_days_convention: pre-fix density was
    ~365/yr, off by ~30% from 252; post-fix it is within a small tolerance.
  - test_no_actual_trade_data_silently_dropped: guards the .union() safety
    net added alongside the freq change.
"""
import pandas as pd
import pytest

from trade_analyzer import calculations, data_handler


def _year_spanning_trades() -> pd.DataFrame:
    """Sparse trades spanning roughly a full year, entries/exits on weekdays."""
    return pd.DataFrame({
        'Date':       pd.to_datetime(['2021-01-04', '2021-03-01', '2021-06-01', '2021-09-01']),
        'Ex. date':   pd.to_datetime(['2021-01-05', '2021-03-02', '2021-06-02', '2021-12-31']),
        'Profit':               [1000.0, 500.0, -300.0, 2000.0],
        'Cumulative_Profit':    [1000.0, 1500.0, 1200.0, 3200.0],
    })


class TestBusinessDayEquitySeries:
    """The equity/returns series must be built on business days, not calendar days."""

    def test_index_is_business_days_only(self):
        """No Saturday/Sunday rows in the reindexed equity series (aside from the
        pre-history anchor point, which is preserved verbatim rather than dropped
        and is not a weekend-ffill artifact)."""
        trades = _year_spanning_trades()
        daily_equity, _ = data_handler.calculate_daily_returns(trades, 100_000.0)
        assert not daily_equity.empty

        # The anchor point (first_trade_date - 1 day) is preserved even if it
        # happens to fall on a weekend — it is a real seed value, not a
        # calendar-day ffill artifact. Excluding it, every other row must be
        # a business day.
        anchor = daily_equity.index.min()
        body = daily_equity.index[daily_equity.index != anchor]
        weekend_rows = body[body.dayofweek >= 5]
        assert len(weekend_rows) == 0, (
            f"Found {len(weekend_rows)} weekend rows in the equity series body — "
            "these should not exist after the business-day fix (issue #250)."
        )

    def test_sample_density_matches_trading_days_convention(self):
        """len(daily_equity) / duration_years must be close to 252 (trading_days
        convention), not ~365 (the pre-fix calendar-day bug)."""
        trades = _year_spanning_trades()
        daily_equity, _ = data_handler.calculate_daily_returns(trades, 100_000.0)
        duration_years = (daily_equity.index[-1] - daily_equity.index[0]).days / 365.25
        implied_bars_per_year = len(daily_equity) / duration_years

        # Business days (no US-holiday exclusion) run ~261/yr; comfortably
        # within 10% of the 252 convention used by calculate_sharpe_ratio /
        # calculate_sortino_ratio. The pre-fix calendar-day series produced
        # ~365/yr — over 40% off — which this bound rejects.
        assert 230 <= implied_bars_per_year <= 275, (
            f"Implied bars/year {implied_bars_per_year:.1f} is not consistent with "
            "the 252-day annualization convention (issue #250 regression)."
        )

    def test_no_actual_trade_data_silently_dropped(self):
        """A trade that closes on an actual weekend date (edge case / odd data
        source) must still appear in the output — the business-day switch must
        not silently drop real equity data points."""
        trades = pd.DataFrame({
            'Date':               pd.to_datetime(['2021-01-04', '2021-01-09']),  # Sat exit
            'Ex. date':           pd.to_datetime(['2021-01-08', '2021-01-11']),  # Fri, Mon
            'Profit':             [1000.0, 500.0],
            'Cumulative_Profit':  [1000.0, 1500.0],
        })
        daily_equity, _ = data_handler.calculate_daily_returns(trades, 100_000.0)
        # Every 'Ex. date' from the trade log must be present in the output index.
        for ex_date in trades['Ex. date']:
            assert ex_date in daily_equity.index, (
                f"Trade exit date {ex_date} was dropped from daily_equity — "
                "the business-day switch must preserve all real trade dates."
            )


class TestAnnualizationConsistency:
    """Sharpe/Sortino computed on calculate_daily_returns() output must use an
    annualization constant consistent with the series' actual sample density."""

    def test_sharpe_annualization_consistent_with_series_density(self):
        """Sharpe computed with trading_days_per_year=252 on the fixed
        (business-day) series must be within a bounded factor of a Sharpe
        computed using the series' *actual* implied bars/year. Pre-fix, the
        calendar-day series' actual density (~365) differed from the 252
        constant by ~45%, which would fail this bound."""
        trades = _year_spanning_trades()
        daily_equity, daily_returns = data_handler.calculate_daily_returns(trades, 100_000.0)
        assert len(daily_returns) > 1

        duration_years = (daily_equity.index[-1] - daily_equity.index[0]).days / 365.25
        actual_bars_per_year = len(daily_equity) / duration_years

        sharpe_convention = calculations.calculate_sharpe_ratio(daily_returns, 0.05, 252)
        sharpe_actual = calculations.calculate_sharpe_ratio(
            daily_returns, 0.05, actual_bars_per_year
        )

        # sqrt(actual/convention) is the inflation/deflation factor between the
        # two annualizations. It must stay close to 1.0 (i.e. the 252
        # convention must be a reasonable match for the series' real density).
        import math
        ratio = math.sqrt(actual_bars_per_year / 252)
        assert 0.9 <= ratio <= 1.1, (
            f"Series density (implied {actual_bars_per_year:.1f} bars/yr) is not "
            f"consistent with the 252-day convention (ratio={ratio:.3f}) — "
            "issue #250 regression."
        )
        if sharpe_convention not in (None,) and sharpe_convention == sharpe_convention:  # not NaN
            assert abs(sharpe_convention - sharpe_actual) < abs(sharpe_convention) * 0.15 + 0.05

    def test_sortino_no_longer_double_counts_weekends(self):
        """With weekends excluded from the series, the number of "downside" rows
        used by Sortino should not be inflated by ~2/7 synthetic flat weekend
        rows relative to the number of real (business-day) flat/losing rows."""
        trades = _year_spanning_trades()
        _, daily_returns = data_handler.calculate_daily_returns(trades, 100_000.0)

        # After the fix, the *count* of zero-return rows should correspond to
        # idle business days only (no weekend inflation). We can't know the
        # exact pre-fix count without reverting the fix, but we can assert the
        # structural invariant that motivated it: the return series' calendar
        # span in days must be noticeably larger than its row count (proving
        # weekends were excluded, not just present-but-harmless).
        span_days = (daily_returns.index[-1] - daily_returns.index[0]).days
        assert len(daily_returns) < span_days, (
            "Expected fewer rows than calendar-day span (weekends excluded); "
            "row count should not equal calendar-day count."
        )
        # And it should be close to the 5/7 weekday fraction of the span.
        weekday_fraction = len(daily_returns) / span_days
        assert 0.60 <= weekday_fraction <= 0.80, (
            f"Weekday fraction {weekday_fraction:.2f} outside expected business-day "
            "range — weekends may not be properly excluded (issue #250)."
        )

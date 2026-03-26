"""
Tests for trade_analyzer/calculations.py — pure financial math functions.

Each test class targets one function and verifies the contract documented
in its docstring, including edge cases that are only reachable through
the function itself (not through a downstream caller).
"""

import math
import os
import sys

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from trade_analyzer.calculations import (
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_equity_drawdown,
    calculate_drawdown_details,
    calculate_cagr,
    calculate_calmar,
    calculate_alpha_beta,
    calculate_var_cvar,
    _calculate_consecutive_streaks,
    calculate_core_metrics,
    calculate_rolling_metrics,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_returns(values):
    """Build a pd.Series of daily returns from a list of floats."""
    return pd.Series(values, dtype=float)


def _make_equity(values):
    """Build a pd.Series equity curve from a list of floats."""
    return pd.Series(values, dtype=float)


def _make_trades_df(profits, wins=None):
    """Build a minimal trades DataFrame with Profit (and Win) columns."""
    df = pd.DataFrame({"Profit": profits})
    if wins is not None:
        df["Win"] = wins
    return df


# ---------------------------------------------------------------------------
# calculate_sharpe_ratio
# ---------------------------------------------------------------------------

class TestCalculateSharpeRatio:

    def test_known_value(self):
        """Sharpe should match the manual formula for an alternating return series."""
        rf = 0.05
        days = 252
        # Alternate between +0.002 and 0.0 to guarantee non-zero std
        values = [0.002 if i % 2 == 0 else 0.0 for i in range(days)]
        returns = _make_returns(values)
        daily_rf = (1 + rf) ** (1 / days) - 1
        excess = returns - daily_rf
        expected = (excess.mean() / excess.std()) * math.sqrt(days)
        result = calculate_sharpe_ratio(returns, rf, days)
        assert abs(result - expected) < 1e-9

    def test_empty_series_returns_nan(self):
        assert math.isnan(calculate_sharpe_ratio(pd.Series([], dtype=float), 0.05, 252))

    def test_single_element_returns_nan(self):
        assert math.isnan(calculate_sharpe_ratio(_make_returns([0.01]), 0.05, 252))

    def test_zero_std_returns_nan(self):
        """All-identical excess returns produce zero std — must return NaN, not divide-by-zero."""
        # With rf=0.0, excess = returns - 0 = constant → std == 0
        returns = _make_returns([0.001] * 10)
        result = calculate_sharpe_ratio(returns, 0.0, 252)
        assert math.isnan(result)

    def test_higher_rf_lowers_sharpe(self):
        """Increasing risk-free rate should reduce (or not increase) Sharpe."""
        returns = _make_returns([0.002, 0.001, 0.003, -0.001] * 63)
        s_low = calculate_sharpe_ratio(returns, 0.0, 252)
        s_high = calculate_sharpe_ratio(returns, 0.10, 252)
        assert s_low > s_high

    def test_positive_returns_positive_sharpe(self):
        """Consistently positive daily returns above rf produce positive Sharpe."""
        returns = _make_returns([0.003, 0.002] * 126)
        result = calculate_sharpe_ratio(returns, 0.05, 252)
        assert result > 0


# ---------------------------------------------------------------------------
# calculate_sortino_ratio
# ---------------------------------------------------------------------------

class TestCalculateSortinoRatio:

    def test_empty_series_returns_nan(self):
        assert math.isnan(calculate_sortino_ratio(pd.Series([], dtype=float), 0.05, 252))

    def test_single_element_returns_nan(self):
        assert math.isnan(calculate_sortino_ratio(_make_returns([0.01]), 0.05, 252))

    def test_no_negative_returns_returns_inf(self):
        """If all returns exceed the MAR and none are below it, Sortino is infinite."""
        # All returns well above daily rf for 5% annual
        returns = _make_returns([0.01] * 20)
        result = calculate_sortino_ratio(returns, 0.05, 252)
        assert math.isinf(result) and result > 0

    def test_positive_for_net_positive_returns(self):
        returns = _make_returns([0.002, -0.001, 0.003, -0.0005] * 63)
        result = calculate_sortino_ratio(returns, 0.05, 252)
        assert math.isfinite(result)

    def test_negative_for_mostly_losing_strategy(self):
        returns = _make_returns([-0.005, -0.003, 0.001] * 84)
        result = calculate_sortino_ratio(returns, 0.05, 252)
        assert result < 0


# ---------------------------------------------------------------------------
# calculate_equity_drawdown
# ---------------------------------------------------------------------------

class TestCalculateEquityDrawdown:

    def test_flat_equity_has_zero_drawdown(self):
        equity = _make_equity([100_000.0] * 5)
        dd_amt, dd_pct, max_amt, max_pct = calculate_equity_drawdown(equity)
        assert max_amt == pytest.approx(0.0, abs=1e-9)
        assert max_pct == pytest.approx(0.0, abs=1e-9)

    def test_monotonically_increasing_has_zero_drawdown(self):
        equity = _make_equity([100_000 + i * 1000 for i in range(10)])
        _, _, max_amt, max_pct = calculate_equity_drawdown(equity)
        assert max_amt == pytest.approx(0.0, abs=1e-9)

    def test_50_percent_drawdown_detected(self):
        equity = _make_equity([100_000, 50_000, 60_000])
        _, _, _, max_pct = calculate_equity_drawdown(equity)
        assert max_pct == pytest.approx(50.0, abs=0.01)

    def test_full_ruin_produces_100_percent_drawdown(self):
        equity = _make_equity([100_000, 50_000, 0.0])
        _, _, _, max_pct = calculate_equity_drawdown(equity)
        assert max_pct == pytest.approx(100.0, abs=0.01)

    def test_empty_series_returns_defaults(self):
        dd_amt, dd_pct, max_amt, max_pct = calculate_equity_drawdown(pd.Series([], dtype=float))
        assert max_amt == 0.0
        assert max_pct == 0.0

    def test_non_numeric_returns_defaults(self):
        equity = pd.Series(["a", "b", "c"])
        _, _, max_amt, max_pct = calculate_equity_drawdown(equity)
        assert max_amt == 0.0

    def test_returns_series_of_correct_length(self):
        equity = _make_equity([100, 90, 95, 80, 85])
        dd_amt, dd_pct, _, _ = calculate_equity_drawdown(equity)
        assert len(dd_amt) == len(equity)
        assert len(dd_pct) == len(equity)

    def test_drawdown_amount_nonnegative(self):
        equity = _make_equity([100, 120, 90, 110, 80, 95])
        dd_amt, _, _, _ = calculate_equity_drawdown(equity)
        assert (dd_amt >= 0).all()

    def test_drawdown_percent_capped_at_100(self):
        equity = _make_equity([100, 200, 10, 5])
        _, dd_pct, _, max_pct = calculate_equity_drawdown(equity)
        assert (dd_pct <= 100.0).all()
        assert max_pct <= 100.0


# ---------------------------------------------------------------------------
# calculate_cagr
# ---------------------------------------------------------------------------

class TestCalculateCagr:

    def test_known_cagr(self):
        """$100k → $200k over 5 years ≈ 14.87% CAGR."""
        result = calculate_cagr(100_000, 200_000, 5.0)
        expected = (2.0 ** 0.2) - 1.0
        assert result == pytest.approx(expected, rel=1e-9)

    def test_no_growth_returns_zero(self):
        result = calculate_cagr(100_000, 100_000, 5.0)
        assert result == pytest.approx(0.0, abs=1e-9)

    def test_zero_duration_returns_nan(self):
        assert math.isnan(calculate_cagr(100_000, 200_000, 0.0))

    def test_tiny_duration_returns_nan(self):
        assert math.isnan(calculate_cagr(100_000, 200_000, 1e-8))

    def test_zero_initial_equity_returns_nan(self):
        assert math.isnan(calculate_cagr(0.0, 200_000, 5.0))

    def test_ruin_returns_negative_one(self):
        """Final equity at zero or below should return exactly -1.0 (100% loss)."""
        result = calculate_cagr(100_000, 0.0, 5.0)
        assert result == -1.0

    def test_nan_duration_returns_nan(self):
        assert math.isnan(calculate_cagr(100_000, 200_000, float("nan")))

    def test_nan_initial_returns_nan(self):
        assert math.isnan(calculate_cagr(float("nan"), 200_000, 5.0))


# ---------------------------------------------------------------------------
# calculate_calmar
# ---------------------------------------------------------------------------

class TestCalculateCalmar:

    def test_known_value(self):
        """CAGR=20%, MaxDD=25% → Calmar = 0.20 / 0.25 = 0.80."""
        result = calculate_calmar(0.20, 25.0)
        assert result == pytest.approx(0.80, rel=1e-9)

    def test_zero_drawdown_positive_cagr_returns_inf(self):
        result = calculate_calmar(0.15, 0.0)
        assert math.isinf(result) and result > 0

    def test_zero_drawdown_negative_cagr_returns_neg_inf(self):
        result = calculate_calmar(-0.10, 0.0)
        assert math.isinf(result) and result < 0

    def test_zero_drawdown_zero_cagr_returns_nan(self):
        result = calculate_calmar(0.0, 0.0)
        assert math.isnan(result)

    def test_nan_cagr_returns_nan(self):
        assert math.isnan(calculate_calmar(float("nan"), 25.0))

    def test_nan_max_dd_returns_nan(self):
        assert math.isnan(calculate_calmar(0.20, float("nan")))

    def test_accepts_positive_magnitude_drawdown(self):
        """Max DD is expected as a positive magnitude (e.g., 25.0 for 25%)."""
        result = calculate_calmar(0.10, 50.0)
        assert result == pytest.approx(0.20, rel=1e-9)


# ---------------------------------------------------------------------------
# calculate_alpha_beta
# ---------------------------------------------------------------------------

class TestCalculateAlphaBeta:

    def _make_aligned(self, n=100):
        dates = pd.date_range("2020-01-01", periods=n)
        strat = pd.Series(np.random.normal(0.001, 0.01, n), index=dates)
        bench = pd.Series(np.random.normal(0.0005, 0.008, n), index=dates)
        return strat, bench

    def test_beta_near_one_for_identical_series(self):
        np.random.seed(42)
        dates = pd.date_range("2020-01-01", periods=200)
        returns = pd.Series(np.random.normal(0.001, 0.01, 200), index=dates)
        alpha, beta = calculate_alpha_beta(returns, returns, 0.05, 252)
        assert beta == pytest.approx(1.0, abs=1e-9)

    def test_beta_zero_for_uncorrelated_flat_benchmark(self):
        """If the benchmark has zero variance, Beta should be NaN."""
        np.random.seed(0)
        dates = pd.date_range("2020-01-01", periods=100)
        strat = pd.Series(np.random.normal(0.001, 0.01, 100), index=dates)
        bench = pd.Series([0.001] * 100, index=dates)  # constant → variance ≈ 0
        alpha, beta = calculate_alpha_beta(strat, bench, 0.05, 252)
        assert math.isnan(beta)

    def test_empty_strategy_returns_nan(self):
        bench = _make_returns([0.001] * 50)
        alpha, beta = calculate_alpha_beta(pd.Series([], dtype=float), bench, 0.05, 252)
        assert math.isnan(alpha) and math.isnan(beta)

    def test_empty_benchmark_returns_nan(self):
        strat = _make_returns([0.001] * 50)
        alpha, beta = calculate_alpha_beta(strat, pd.Series([], dtype=float), 0.05, 252)
        assert math.isnan(alpha) and math.isnan(beta)

    def test_non_overlapping_indices_returns_nan(self):
        dates_a = pd.date_range("2020-01-01", periods=50)
        dates_b = pd.date_range("2021-01-01", periods=50)
        strat = pd.Series([0.001] * 50, index=dates_a)
        bench = pd.Series([0.001] * 50, index=dates_b)
        alpha, beta = calculate_alpha_beta(strat, bench, 0.05, 252)
        assert math.isnan(alpha) and math.isnan(beta)

    def test_returns_floats(self):
        np.random.seed(1)
        dates = pd.date_range("2020-01-01", periods=100)
        strat = pd.Series(np.random.normal(0.001, 0.01, 100), index=dates)
        bench = pd.Series(np.random.normal(0.0005, 0.008, 100), index=dates)
        alpha, beta = calculate_alpha_beta(strat, bench, 0.05, 252)
        assert isinstance(alpha, float)
        assert isinstance(beta, float)


# ---------------------------------------------------------------------------
# calculate_var_cvar
# ---------------------------------------------------------------------------

class TestCalculateVarCvar:

    def test_var_is_5th_percentile_by_default(self):
        profits = pd.Series(range(-50, 50, 1), dtype=float)
        var, cvar = calculate_var_cvar(profits, level=0.05)
        expected_var = profits.quantile(0.05)
        assert var == pytest.approx(float(expected_var), rel=1e-9)

    def test_cvar_is_mean_of_tail_below_var(self):
        profits = pd.Series([-100, -80, -60, -40, -20, 0, 20, 40, 60, 80, 100], dtype=float)
        var, cvar = calculate_var_cvar(profits, level=0.1)
        expected_var = profits.quantile(0.1)
        tail = profits[profits <= expected_var]
        expected_cvar = tail.mean()
        assert cvar == pytest.approx(float(expected_cvar), abs=1e-9)

    def test_empty_series_returns_nan(self):
        var, cvar = calculate_var_cvar(pd.Series([], dtype=float))
        assert math.isnan(var) and math.isnan(cvar)

    def test_all_nan_series_returns_nan(self):
        var, cvar = calculate_var_cvar(pd.Series([float("nan")] * 5))
        assert math.isnan(var) and math.isnan(cvar)

    def test_non_numeric_returns_nan(self):
        var, cvar = calculate_var_cvar(pd.Series(["a", "b", "c"]))
        assert math.isnan(var) and math.isnan(cvar)

    def test_single_value_returns_nan(self):
        var, cvar = calculate_var_cvar(pd.Series([100.0]))
        assert math.isnan(var) and math.isnan(cvar)


# ---------------------------------------------------------------------------
# _calculate_consecutive_streaks
# ---------------------------------------------------------------------------

class TestCalculateConsecutiveStreaks:

    def test_alternating_returns_max_one_each(self):
        series = pd.Series([True, False, True, False, True], dtype=bool)
        wins, losses = _calculate_consecutive_streaks(series)
        assert wins == 1
        assert losses == 1

    def test_all_wins(self):
        series = pd.Series([True] * 7, dtype=bool)
        wins, losses = _calculate_consecutive_streaks(series)
        assert wins == 7
        assert losses == 0

    def test_all_losses(self):
        series = pd.Series([False] * 6, dtype=bool)
        wins, losses = _calculate_consecutive_streaks(series)
        assert wins == 0
        assert losses == 6

    def test_streak_at_end(self):
        series = pd.Series([True, False, False, True, True, True])
        wins, losses = _calculate_consecutive_streaks(series)
        assert wins == 3
        assert losses == 2

    def test_empty_series_returns_zeros(self):
        wins, losses = _calculate_consecutive_streaks(pd.Series([], dtype=bool))
        assert wins == 0
        assert losses == 0

    def test_numeric_values_cast_to_bool(self):
        """Non-zero values are truthy → treated as wins."""
        series = pd.Series([1.0, 0.0, 1.0, 1.0])
        wins, losses = _calculate_consecutive_streaks(series)
        assert wins == 2
        assert losses == 1


# ---------------------------------------------------------------------------
# calculate_core_metrics
# ---------------------------------------------------------------------------

class TestCalculateCoreMetrics:

    def test_empty_df_returns_empty_dict(self):
        result = calculate_core_metrics(pd.DataFrame())
        assert result == {}

    def test_basic_metrics_populated(self):
        profits = [100, -50, 200, -30, 150]
        wins = [True, False, True, False, True]
        df = _make_trades_df(profits, wins=wins)
        result = calculate_core_metrics(df)
        assert result["total_trades"] == 5
        assert result["total_profit"] == pytest.approx(sum(profits), rel=1e-9)
        assert result["win_rate"] == pytest.approx(3 / 5, rel=1e-9)

    def test_gross_profit_and_loss(self):
        df = _make_trades_df([100, -50, 200, -30], wins=[True, False, True, False])
        result = calculate_core_metrics(df)
        assert result["gross_profit"] == pytest.approx(300.0, rel=1e-9)
        assert result["gross_loss"] == pytest.approx(-80.0, rel=1e-9)

    def test_profit_factor_ratio(self):
        df = _make_trades_df([100, -50, 100, -50], wins=[True, False, True, False])
        result = calculate_core_metrics(df)
        assert result["profit_factor"] == pytest.approx(2.0, rel=1e-9)

    def test_profit_factor_infinite_when_no_losses(self):
        df = _make_trades_df([100, 200, 300], wins=[True, True, True])
        result = calculate_core_metrics(df)
        assert math.isinf(result["profit_factor"])

    def test_max_consecutive_wins_and_losses(self):
        profits = [100, 100, 100, -50, -50, 100]
        wins = [True, True, True, False, False, True]
        df = _make_trades_df(profits, wins=wins)
        result = calculate_core_metrics(df)
        assert result["max_consecutive_wins"] == 3
        assert result["max_consecutive_losses"] == 2

    def test_missing_profit_column_produces_nans(self):
        df = pd.DataFrame({"Symbol": ["AAPL", "MSFT"]})
        result = calculate_core_metrics(df)
        assert result["total_trades"] == 2
        assert math.isnan(result["total_profit"])

    def test_missing_win_column_returns_nan_win_rate(self):
        df = _make_trades_df([100, -50, 200])  # no Win column
        result = calculate_core_metrics(df)
        assert math.isnan(result["win_rate"])

    def test_expectancy_formula(self):
        """Expectancy = win_rate * avg_win - (1-win_rate) * |avg_loss|."""
        df = _make_trades_df([100, -50, 100, -50], wins=[True, False, True, False])
        result = calculate_core_metrics(df)
        expected = 0.5 * 100 - 0.5 * 50
        assert result["expectancy"] == pytest.approx(expected, rel=1e-9)

    def test_all_expected_keys_present(self):
        df = _make_trades_df([50, -20, 80], wins=[True, False, True])
        result = calculate_core_metrics(df)
        for key in ["total_trades", "total_profit", "gross_profit", "gross_loss",
                    "profit_factor", "win_rate", "avg_win", "avg_loss",
                    "avg_trade_profit", "max_consecutive_wins",
                    "max_consecutive_losses", "expectancy"]:
            assert key in result, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# calculate_rolling_metrics
# ---------------------------------------------------------------------------

class TestCalculateRollingMetrics:

    def _make_rolling_df(self, n=30):
        np.random.seed(42)
        profits = np.random.normal(50, 100, n)
        ret_frac = profits / 10_000
        return pd.DataFrame({"Profit": profits, "Return_Frac": ret_frac})

    def test_adds_rolling_pf_and_sharpe_columns(self):
        df = self._make_rolling_df(30)
        result = calculate_rolling_metrics(df, window=10, trades_per_year=50, risk_free_rate=0.05)
        assert "Rolling_PF" in result.columns
        assert "Rolling_Sharpe" in result.columns

    def test_not_enough_rows_leaves_columns_nan(self):
        df = self._make_rolling_df(5)
        result = calculate_rolling_metrics(df, window=20, trades_per_year=50, risk_free_rate=0.05)
        # window > n: all rolling values should be NaN
        assert result["Rolling_PF"].isna().all()

    def test_empty_df_returns_unchanged(self):
        df = pd.DataFrame()
        result = calculate_rolling_metrics(df, window=10, trades_per_year=50, risk_free_rate=0.05)
        assert result.empty

    def test_zero_trades_per_year_disables_rolling_sharpe(self):
        df = self._make_rolling_df(30)
        result = calculate_rolling_metrics(df, window=5, trades_per_year=0, risk_free_rate=0.05)
        assert result["Rolling_Sharpe"].isna().all()


# ---------------------------------------------------------------------------
# calculate_drawdown_details
# ---------------------------------------------------------------------------

class TestCalculateDrawdownDetails:

    def _make_dated_profit_series(self, profits):
        idx = list(range(len(profits)))
        cum_profit = pd.Series(profits, index=idx, dtype=float).cumsum()
        dates = pd.Series(pd.date_range("2020-01-01", periods=len(profits)), index=idx)
        return cum_profit, dates

    def test_simple_drawdown_detected(self):
        # Goes up, drops, recovers
        profits = [100, 100, -50, -50, 100, 100]
        cum_profit, dates = self._make_dated_profit_series(profits)
        dd_amt, dd_pct, max_amt, max_pct, periods_df = calculate_drawdown_details(cum_profit, dates)
        assert max_amt > 0
        assert not dd_amt.empty

    def test_monotonically_increasing_has_zero_max_drawdown(self):
        profits = [100] * 10
        cum_profit, dates = self._make_dated_profit_series(profits)
        _, _, max_amt, max_pct, periods_df = calculate_drawdown_details(cum_profit, dates)
        assert max_amt == pytest.approx(0.0, abs=1e-9)
        assert periods_df.empty

    def test_empty_series_returns_defaults(self):
        result = calculate_drawdown_details(pd.Series([], dtype=float), pd.Series([], dtype="datetime64[ns]"))
        dd_amt, dd_pct, max_amt, max_pct, periods_df = result
        assert dd_amt.empty
        assert max_amt == 0.0

    def test_non_datetime_dates_returns_defaults(self):
        cum_profit = pd.Series([100, 90, 95], dtype=float)
        dates = pd.Series([1, 2, 3])  # not datetime
        dd_amt, dd_pct, max_amt, max_pct, periods_df = calculate_drawdown_details(cum_profit, dates)
        assert dd_amt.empty

    def test_drawdown_percent_capped_at_100(self):
        profits = [100, 200, -500]
        cum_profit, dates = self._make_dated_profit_series(profits)
        _, dd_pct, _, max_pct, _ = calculate_drawdown_details(cum_profit, dates)
        assert max_pct <= 100.0

    def test_open_drawdown_recorded_when_not_recovered(self):
        """A drawdown that never recovers by end of series should still be in the periods DF."""
        profits = [100, 100, -50, -50]  # ends in drawdown
        cum_profit, dates = self._make_dated_profit_series(profits)
        _, _, max_amt, _, periods_df = calculate_drawdown_details(cum_profit, dates)
        assert max_amt > 0
        assert not periods_df.empty

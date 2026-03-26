"""
Tests for helpers/simulations.py.

Covers calculate_advanced_metrics (all branches) and calculate_rolling_sharpe.
Both are pure math functions with no external I/O.
"""
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from helpers.simulations import calculate_advanced_metrics, calculate_rolling_sharpe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _equity_series(values, start="2021-01-04", freq="B"):
    """Build a pd.Series with a DatetimeIndex."""
    idx = pd.date_range(start, periods=len(values), freq=freq)
    return pd.Series(values, index=idx, dtype=float)


# ---------------------------------------------------------------------------
# calculate_advanced_metrics — guard clause
# ---------------------------------------------------------------------------

class TestCalculateAdvancedMetricsGuards:

    def test_empty_pnl_list_returns_default_metrics(self):
        result = calculate_advanced_metrics([], pd.Series(dtype=float), [])
        assert result["max_drawdown"] == 0
        assert result["profit_factor"] == 0
        assert result["win_rate"] == 0
        assert result["sharpe_ratio"] == 0

    def test_empty_portfolio_timeline_still_returns_win_rate(self):
        result = calculate_advanced_metrics([100, -50], pd.Series(dtype=float), [])
        assert result["win_rate"] == pytest.approx(0.5)
        assert result["max_drawdown"] == 0  # no timeline


# ---------------------------------------------------------------------------
# calculate_advanced_metrics — win rate and profit factor
# ---------------------------------------------------------------------------

class TestWinRateAndProfitFactor:

    def test_win_rate_all_wins(self):
        result = calculate_advanced_metrics(
            [100, 200, 300], _equity_series([10_000, 10_100, 10_300, 10_600]), []
        )
        assert result["win_rate"] == pytest.approx(1.0)

    def test_win_rate_all_losses(self):
        result = calculate_advanced_metrics(
            [-100, -200], _equity_series([10_000, 9_900, 9_700]), []
        )
        assert result["win_rate"] == pytest.approx(0.0)

    def test_win_rate_mixed(self):
        result = calculate_advanced_metrics(
            [100, -50, 200, -30], _equity_series([10_000] * 5), []
        )
        assert result["win_rate"] == pytest.approx(0.5)

    def test_profit_factor_with_losses(self):
        # wins = 300, losses = 50 → PF = 300/50 = 6.0
        result = calculate_advanced_metrics(
            [100, 200, -50], _equity_series([10_000] * 4), []
        )
        assert result["profit_factor"] == pytest.approx(6.0)

    def test_profit_factor_no_losses_is_inf(self):
        result = calculate_advanced_metrics(
            [100, 200], _equity_series([10_000] * 3), []
        )
        assert result["profit_factor"] == np.inf

    def test_avg_trade_duration_calculated(self):
        result = calculate_advanced_metrics(
            [100, -50], _equity_series([10_000] * 3), [5.0, 3.0]
        )
        assert result["avg_trade_duration"] == pytest.approx(4.0)

    def test_no_duration_list_avg_is_zero(self):
        result = calculate_advanced_metrics(
            [100], _equity_series([10_000] * 2), []
        )
        assert result["avg_trade_duration"] == 0


# ---------------------------------------------------------------------------
# calculate_advanced_metrics — Sharpe, drawdown, Calmar
# ---------------------------------------------------------------------------

class TestAdvancedMetricsWithTimeline:

    def test_max_drawdown_peak_to_trough(self):
        # 10k → 12k (peak) → 9k (drawdown = 25%) → 11k
        equity = _equity_series([10_000, 11_000, 12_000, 9_000, 11_000])
        result = calculate_advanced_metrics([100, 200, -300, 200], equity, [])
        assert result["max_drawdown"] == pytest.approx(0.25, rel=0.01)

    def test_monotonic_rising_equity_has_zero_drawdown(self):
        equity = _equity_series([10_000, 11_000, 12_000, 13_000])
        result = calculate_advanced_metrics([1000] * 3, equity, [])
        assert result["max_drawdown"] == pytest.approx(0.0, abs=1e-9)

    def test_calmar_ratio_computed_when_drawdown_positive(self):
        equity = _equity_series([10_000, 12_000, 9_000, 13_000])
        result = calculate_advanced_metrics([200, -300, 400], equity, [])
        assert result["calmar_ratio"] > 0

    def test_calmar_ratio_inf_when_no_drawdown(self):
        equity = _equity_series([10_000, 11_000, 12_000, 14_000])
        result = calculate_advanced_metrics([1000] * 3, equity, [])
        assert result["calmar_ratio"] == np.inf

    def test_sharpe_ratio_positive_for_trending_equity(self):
        # Steadily rising equity → positive Sharpe
        equity = _equity_series([10_000 + i * 50 for i in range(30)])
        result = calculate_advanced_metrics([50] * 29, equity, [])
        assert result["sharpe_ratio"] > 0


# ---------------------------------------------------------------------------
# calculate_advanced_metrics — recovery time
# ---------------------------------------------------------------------------

class TestRecoveryTime:

    def test_recovery_time_computed_after_drawdown(self):
        # Drop then recover
        equity = _equity_series([10_000, 10_500, 10_000, 9_500, 10_200, 10_600])
        result = calculate_advanced_metrics([-500, 700], equity, [])
        # Recovery should have been found
        assert result["max_recovery_days"] is not None
        assert result["max_recovery_days"] > 0

    def test_no_recovery_if_never_recover(self):
        # Monotonically falling — no recovery
        equity = _equity_series([10_000, 9_000, 8_000, 7_000])
        result = calculate_advanced_metrics([-1000, -1000, -1000], equity, [])
        # recovery_days_list stays empty
        assert result["max_recovery_days"] is None
        assert result["avg_recovery_days"] is None

    def test_no_drawdown_no_recovery_needed(self):
        equity = _equity_series([10_000, 11_000, 12_000])
        result = calculate_advanced_metrics([1000, 1000], equity, [])
        assert result["max_recovery_days"] is None

    def test_single_data_point_timeline(self):
        equity = _equity_series([10_000])
        result = calculate_advanced_metrics([100], equity, [])
        assert result["max_recovery_days"] is None
        assert result["avg_recovery_days"] is None


# ---------------------------------------------------------------------------
# calculate_rolling_sharpe
# ---------------------------------------------------------------------------

class TestCalculateRollingSharpe:

    def test_returns_series_same_length_as_input(self):
        equity = _equity_series([10_000 + i * 10 for i in range(50)])
        result = calculate_rolling_sharpe(equity, window=10)
        assert len(result) == len(equity)

    def test_first_window_minus_1_values_are_nan(self):
        equity = _equity_series([10_000 + i * 10 for i in range(30)])
        result = calculate_rolling_sharpe(equity, window=10)
        # First (window) values should be NaN (pct_change makes first NaN too,
        # so first window entries are NaN)
        assert result.iloc[:10].isna().all()

    def test_positive_sharpe_for_trending_up_equity(self):
        equity = _equity_series([10_000 + i * 100 for i in range(200)])
        result = calculate_rolling_sharpe(equity, window=20)
        # After warm-up, values should be finite and positive
        valid = result.dropna()
        assert len(valid) > 0
        assert (valid > 0).all()

    def test_zero_std_window_returns_nan(self):
        # Flat equity → zero returns → zero std → NaN Sharpe
        equity = _equity_series([10_000] * 30)
        result = calculate_rolling_sharpe(equity, window=10)
        valid = result.dropna()
        assert valid.isna().all() or len(valid) == 0

    def test_custom_risk_free_rate_accepted(self):
        equity = _equity_series([10_000 + i * 50 for i in range(50)])
        result_low  = calculate_rolling_sharpe(equity, window=10, risk_free_rate=0.0)
        result_high = calculate_rolling_sharpe(equity, window=10, risk_free_rate=0.10)
        # Higher risk-free rate → lower Sharpe
        low_vals  = result_low.dropna()
        high_vals = result_high.dropna()
        assert (low_vals > high_vals).all()

    def test_default_risk_free_rate_from_config(self):
        """Passing risk_free_rate=None should read from CONFIG without error."""
        equity = _equity_series([10_000 + i * 20 for i in range(50)])
        with patch.dict("config.CONFIG", {"risk_free_rate": 0.03}):
            result = calculate_rolling_sharpe(equity, window=10, risk_free_rate=None)
        assert isinstance(result, pd.Series)
        assert len(result) == len(equity)

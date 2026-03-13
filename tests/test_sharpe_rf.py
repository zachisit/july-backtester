# tests/test_sharpe_rf.py
"""
Tests for risk-free-rate adjustment in Sharpe calculation (helpers/simulations.py).

Verifies:
  - CONFIG["risk_free_rate"] defaults to 0.05.
  - The old formula (no rf subtraction) produces a positive Sharpe for
    daily returns that average ~0.001 (0.1 %/day).
  - The new formula (rf = 5 % p.a.) produces a *lower* Sharpe than the
    old formula because rf_daily (~0.019 %/day) is subtracted from the mean.
  - calculate_advanced_metrics end-to-end uses the configured rate.
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

from config import CONFIG
from helpers.simulations import calculate_advanced_metrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_portfolio_timeline(n: int = 252) -> pd.Series:
    """
    Build an equity curve whose pct_change() returns alternate exactly between
    0.002 and 0.0, giving mean ≈ 0.001 and std ≈ 0.001.

    This ensures daily_returns.std() > 0 so neither Sharpe formula
    short-circuits to 0.
    """
    dates = pd.date_range("2020-01-01", periods=n + 1, freq="B")
    equity = np.empty(n + 1)
    equity[0] = 100_000.0
    for i in range(n):
        r = 0.002 if i % 2 == 0 else 0.0
        equity[i + 1] = equity[i] * (1.0 + r)
    return pd.Series(equity, index=dates)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSharpeRiskFreeRate:

    def test_config_risk_free_rate_default(self):
        """risk_free_rate must default to 0.05 so Sharpe uses a 5 % annual rate."""
        assert CONFIG["risk_free_rate"] == 0.05

    def test_old_formula_without_rf_gives_nonzero_sharpe(self):
        """Baseline: mean/std * sqrt(252) is positive for mean-0.001 returns."""
        timeline = _make_portfolio_timeline()
        daily_returns = timeline.pct_change().dropna()

        old_sharpe = (daily_returns.mean() / daily_returns.std()) * math.sqrt(252)

        assert old_sharpe > 0, f"Expected positive old Sharpe, got {old_sharpe}"

    def test_new_formula_with_rf_gives_lower_sharpe(self):
        """
        Subtracting rf_daily from excess returns must lower the Sharpe ratio.

        rf_daily = (1.05)^(1/252) - 1 ≈ 0.000193, which is less than the
        mean daily return of 0.001, so new Sharpe is positive but smaller.
        """
        timeline = _make_portfolio_timeline()
        daily_returns = timeline.pct_change().dropna()

        old_sharpe = (daily_returns.mean() / daily_returns.std()) * math.sqrt(252)

        rf_daily = (1 + 0.05) ** (1 / 252) - 1
        excess_returns = daily_returns - rf_daily
        new_sharpe = (excess_returns.mean() / excess_returns.std()) * math.sqrt(252)

        assert new_sharpe < old_sharpe, (
            f"Expected new_sharpe ({new_sharpe:.4f}) < old_sharpe ({old_sharpe:.4f})"
        )

    def test_calculate_advanced_metrics_uses_risk_free_rate(self):
        """End-to-end: calculate_advanced_metrics must match the rf-adjusted formula."""
        timeline = _make_portfolio_timeline()
        pnl_list = [100.0] * 10  # arbitrary; only Sharpe is under test

        result = calculate_advanced_metrics(pnl_list, timeline, [3] * 10)

        daily_returns = timeline.pct_change().dropna()
        rf_daily = (1 + CONFIG["risk_free_rate"]) ** (1 / 252) - 1
        excess = daily_returns - rf_daily
        expected_sharpe = (excess.mean() / excess.std()) * math.sqrt(252)

        assert abs(result["sharpe_ratio"] - expected_sharpe) < 1e-9, (
            f"Expected sharpe {expected_sharpe:.6f}, got {result['sharpe_ratio']:.6f}"
        )

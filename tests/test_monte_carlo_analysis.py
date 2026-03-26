"""
Tests for helpers/monte_carlo.py — Monte Carlo simulation and result analysis.

The primary business logic under test is:
  - analyze_mc_results: scoring rubric with 3 independent tests
  - run_monte_carlo_simulation: IID and block-bootstrap sampling

We do NOT test the internal tqdm loop mechanics or specific percentile values
from stochastic runs — those would be fragile. Instead we test the deterministic
scoring branches, guard conditions, and block-bootstrap produces valid output.
"""

import os
import sys
import math

import numpy as np
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.monte_carlo import run_monte_carlo_simulation, analyze_mc_results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mc_results(final_equities, max_drawdowns):
    """Build a fake mc_results dict as returned by run_monte_carlo_simulation."""
    return {
        "final_equities": np.array(final_equities, dtype=float),
        "max_drawdowns": np.array(max_drawdowns, dtype=float),
    }


def _historical(pnl_pct=0.20, initial=100_000, max_dd=0.25):
    return {
        "pnl_percent": pnl_pct,
        "initial_capital": initial,
        "max_drawdown": max_dd,
    }


# ---------------------------------------------------------------------------
# analyze_mc_results — guard conditions
# ---------------------------------------------------------------------------

class TestAnalyzeMcResultsGuards:

    def test_none_mc_results_returns_low_trades_verdict(self):
        result = analyze_mc_results(_historical(), None)
        assert result["mc_verdict"] == "N/A (Low Trades)"
        assert result["mc_score"] == 0


# ---------------------------------------------------------------------------
# analyze_mc_results — scoring branches
# ---------------------------------------------------------------------------

class TestAnalyzeMcResultsScoring:
    """
    Each test controls the three scoring dimensions independently:
      1. Performance Robustness: historical_pnl >= mc_5th_pnl  (+2 / -1)
      2. Drawdown Realism:       historical_dd >= mc_median_dd (+1 / -1)
      3. Tail Risk:              mc_95th_dd < 0.50 (+2) / < 0.80 (-1) / >= 0.80 (-2)
    """

    def _make_mc(self, pct_5th_equity, median_dd, pct_95th_dd, n=200):
        """
        Build mc_results where:
          - 5th percentile of final_equities = initial + pct_5th_equity (approx)
          - median max_drawdown ≈ median_dd
          - 95th percentile max_drawdown ≈ pct_95th_dd
        """
        initial = 100_000.0
        target_5th_final = initial + pct_5th_equity
        # Simple: put 90% of values at a high equity and 10% at the target
        high = initial * 2
        low = target_5th_final
        n_low = max(1, int(n * 0.1))
        finals = [high] * (n - n_low) + [low] * n_low

        # For drawdowns: construct array so median ≈ median_dd and 95th ≈ pct_95th_dd
        n_95 = max(1, int(n * 0.05))
        drawdowns = [median_dd] * (n - n_95) + [pct_95th_dd] * n_95

        return _mc_results(finals, drawdowns)

    def test_robust_strategy_scores_positively(self):
        """
        historical_pnl > mc_5th, historical_dd >= median_dd, 95th_dd < 0.50
        → score = +2 +1 +2 = 5, verdict = 'Robust'
        """
        initial = 100_000.0
        hist_pnl = 0.30  # $30k gain
        hist_dd = 0.35   # worse than median (good — realistic)
        mc = self._make_mc(pct_5th_equity=20_000, median_dd=0.30, pct_95th_dd=0.40)
        result = analyze_mc_results(_historical(pnl_pct=hist_pnl, max_dd=hist_dd), mc)
        assert result["mc_score"] == 5
        assert result["mc_verdict"] == "Robust"

    def test_perf_outlier_detected(self):
        """
        If historical PnL < mc_5th PnL → 'Perf. Outlier' in verdict, score -= 1.
        """
        # Make MC 5th percentile final equity very high (historical underperforms)
        initial = 100_000.0
        mc = _mc_results(
            [300_000] * 200,  # all sims way above initial; 5th pct = $200k gain
            [0.30] * 200,
        )
        hist = _historical(pnl_pct=0.05, initial=initial, max_dd=0.35)  # only 5% gain
        result = analyze_mc_results(hist, mc)
        assert "Perf. Outlier" in result["mc_verdict"]

    def test_dd_understated_detected(self):
        """
        If historical_dd < mc_median_dd → 'DD Understated' in verdict, score -= 1.
        """
        mc = _mc_results(
            [120_000] * 200,
            [0.40] * 200,  # median DD = 40%
        )
        hist = _historical(pnl_pct=0.30, initial=100_000, max_dd=0.10)  # only 10% DD
        result = analyze_mc_results(hist, mc)
        assert "DD Understated" in result["mc_verdict"]

    def test_moderate_tail_risk_detected(self):
        """
        95th percentile DD in [0.50, 0.80) → 'Moderate Tail Risk', score -= 1.
        Use uniform array so percentile is exact.
        """
        # All drawdowns = 0.65: median=0.65, 95th=0.65 (0.50 <= 0.65 < 0.80 → moderate)
        # hist_dd = 0.70 >= median 0.65 → realistic (+1)
        # hist_pnl beats 5th pct (+2)
        # 95th in moderate range → -1; net = +2
        mc = _mc_results(
            [50_000] * 200,       # final equities low; hist pnl > 5th pct
            [0.65] * 200,         # 95th pct = 0.65 → moderate tail risk
        )
        hist = _historical(pnl_pct=0.50, initial=100_000, max_dd=0.70)
        result = analyze_mc_results(hist, mc)
        assert "Moderate Tail Risk" in result["mc_verdict"]

    def test_high_tail_risk_detected(self):
        """
        95th percentile DD >= 0.80 → 'High Tail Risk', score -= 2.
        """
        # All drawdowns = 0.85: median=0.85, 95th=0.85 (>=0.80 → high risk)
        # hist_dd = 0.90 >= median 0.85 → realistic (+1)
        # hist_pnl beats 5th pct (+2)
        mc = _mc_results(
            [50_000] * 200,
            [0.85] * 200,         # 95th pct = 0.85 → high tail risk
        )
        hist = _historical(pnl_pct=0.50, initial=100_000, max_dd=0.90)
        result = analyze_mc_results(hist, mc)
        assert "High Tail Risk" in result["mc_verdict"]

    def test_multiple_flags_joined_with_comma(self):
        """When multiple tests fail, verdicts are joined with ', '."""
        # Perf outlier: hist_pnl ($5k) < mc_5th_pnl ($200k)
        # DD Understated: hist_dd (0.10) < mc_median_dd (0.85)
        # High Tail Risk: mc_95th_dd = 0.85 >= 0.80
        mc = _mc_results(
            [300_000] * 200,      # 5th pct = $200k gain → hist $5k underperforms
            [0.85] * 200,         # median=0.85, 95th=0.85
        )
        hist = _historical(pnl_pct=0.05, initial=100_000, max_dd=0.10)
        result = analyze_mc_results(hist, mc)
        assert ", " in result["mc_verdict"]


# ---------------------------------------------------------------------------
# run_monte_carlo_simulation — guard conditions
# ---------------------------------------------------------------------------

class TestRunMcSimulationGuards:

    def test_empty_list_returns_none(self):
        result = run_monte_carlo_simulation([], 100_000, num_simulations=10)
        assert result is None

    def test_non_list_returns_none(self):
        result = run_monte_carlo_simulation("not a list", 100_000, num_simulations=10)
        assert result is None

    def test_fewer_than_5_trades_returns_none(self):
        result = run_monte_carlo_simulation([100, 200, -50, 80], 100_000, num_simulations=10)
        assert result is None

    def test_exactly_5_trades_runs(self):
        np.random.seed(0)
        result = run_monte_carlo_simulation([100, -50, 200, -30, 150], 100_000, num_simulations=10)
        assert result is not None


# ---------------------------------------------------------------------------
# run_monte_carlo_simulation — output structure (IID)
# ---------------------------------------------------------------------------

class TestRunMcSimulationIID:

    def setup_method(self):
        np.random.seed(42)
        self.trades = [100, -50, 200, -30, 150, 80, -20, 120, -10, 60]
        self.initial = 100_000.0
        self.result = run_monte_carlo_simulation(
            self.trades, self.initial, num_simulations=50
        )

    def test_returns_dict_with_expected_keys(self):
        assert "final_equities" in self.result
        assert "max_drawdowns" in self.result

    def test_final_equities_correct_length(self):
        assert len(self.result["final_equities"]) == 50

    def test_max_drawdowns_in_valid_range(self):
        """Drawdowns must be between 0 and 1 (fractional)."""
        dds = self.result["max_drawdowns"]
        assert np.all(dds >= 0)
        assert np.all(dds <= 1.0)

    def test_all_equities_numeric(self):
        assert np.all(np.isfinite(self.result["final_equities"]))


# ---------------------------------------------------------------------------
# run_monte_carlo_simulation — block bootstrap
# ---------------------------------------------------------------------------

class TestRunMcSimulationBlock:

    def test_block_bootstrap_produces_valid_output(self):
        """Block-bootstrap must produce the same output shape as IID."""
        from unittest.mock import patch
        np.random.seed(1)
        trades = list(range(-10, 20))  # 30 trades

        with patch("helpers.monte_carlo.CONFIG", {"mc_sampling": "block", "mc_block_size": 5}):
            result = run_monte_carlo_simulation(trades, 100_000, num_simulations=20)

        assert result is not None
        assert len(result["final_equities"]) == 20
        assert len(result["max_drawdowns"]) == 20

    def test_block_bootstrap_auto_block_size(self):
        """When mc_block_size is None, auto floor(sqrt(N)) should be used."""
        from unittest.mock import patch
        np.random.seed(2)
        trades = list(range(-5, 25))  # 30 trades, auto block = floor(sqrt(30)) = 5

        with patch("helpers.monte_carlo.CONFIG", {"mc_sampling": "block", "mc_block_size": None}):
            result = run_monte_carlo_simulation(trades, 100_000, num_simulations=10)

        assert result is not None

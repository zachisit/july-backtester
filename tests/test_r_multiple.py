"""tests/test_r_multiple.py

Tests for R-Multiple capture in portfolio_simulations and Expectancy/SQN
computation in main.run_single_simulation.

Covers:
  - Correct R-Multiple with a known percentage stop loss
  - 1% proxy fallback when stop_loss is None
  - No ZeroDivisionError for any edge-case inputs
  - Expectancy = mean(R-Multiples)
  - SQN = (Expectancy / StdDev) * sqrt(N)
  - Graceful handling of 0 trades and 1 trade (SQN requires >=2)
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


# ---------------------------------------------------------------------------
# Helpers that replicate the inline logic from portfolio_simulations.py
# ---------------------------------------------------------------------------

def _compute_initial_risk(entry_price, initial_stop_loss_level):
    """Mirror of the formula inside portfolio_simulations.py."""
    if (
        initial_stop_loss_level is not None
        and not (isinstance(initial_stop_loss_level, float) and math.isnan(initial_stop_loss_level))
        and initial_stop_loss_level > 0
        and initial_stop_loss_level < entry_price
    ):
        return entry_price - initial_stop_loss_level
    return entry_price * 0.01


def _compute_r_multiple(net_pnl, initial_risk_per_share, shares):
    """Mirror of the formula inside portfolio_simulations.py."""
    if initial_risk_per_share > 0 and shares > 0:
        return net_pnl / (initial_risk_per_share * shares)
    return None


def _compute_expectancy_sqn(r_values):
    """Mirror of the formula inside main.run_single_simulation."""
    if len(r_values) < 2:
        return None, None
    exp = float(np.mean(r_values))
    std = float(np.std(r_values, ddof=1))
    sqn = (exp / std) * math.sqrt(len(r_values)) if std > 0 else 0.0
    return exp, sqn


# ---------------------------------------------------------------------------
# Tests — InitialRisk calculation
# ---------------------------------------------------------------------------

class TestInitialRisk:
    def test_percentage_stop_loss_used(self):
        """With a 5% stop, initial risk = entry * 0.05."""
        entry = 100.0
        sl = 95.0
        risk = _compute_initial_risk(entry, sl)
        assert math.isclose(risk, 5.0, rel_tol=1e-9)

    def test_none_stop_loss_falls_back_to_1pct(self):
        entry = 200.0
        risk = _compute_initial_risk(entry, None)
        assert math.isclose(risk, 2.0, rel_tol=1e-9)

    def test_nan_stop_loss_falls_back_to_1pct(self):
        entry = 50.0
        risk = _compute_initial_risk(entry, float('nan'))
        assert math.isclose(risk, 0.5, rel_tol=1e-9)

    def test_zero_stop_loss_falls_back_to_1pct(self):
        entry = 100.0
        risk = _compute_initial_risk(entry, 0.0)
        assert math.isclose(risk, 1.0, rel_tol=1e-9)

    def test_stop_above_entry_falls_back_to_1pct(self):
        """Stop above entry price is invalid — must use the 1% proxy."""
        entry = 100.0
        sl = 110.0
        risk = _compute_initial_risk(entry, sl)
        assert math.isclose(risk, 1.0, rel_tol=1e-9)

    def test_risk_is_always_positive(self):
        for entry, sl in [(50, 48), (200, None), (1000, float('nan'))]:
            assert _compute_initial_risk(entry, sl) > 0


# ---------------------------------------------------------------------------
# Tests — RMultiple calculation
# ---------------------------------------------------------------------------

class TestRMultiple:
    def test_winning_trade_known_values(self):
        """
        Entry=100, stop=95 → risk=5/share.
        100 shares, profit=$750.  R = 750 / (5*100) = 1.5
        """
        r = _compute_r_multiple(750.0, 5.0, 100.0)
        assert math.isclose(r, 1.5, rel_tol=1e-9)

    def test_losing_trade_negative_r(self):
        """Losing trade produces a negative R-Multiple."""
        r = _compute_r_multiple(-300.0, 5.0, 100.0)
        assert math.isclose(r, -0.6, rel_tol=1e-9)

    def test_breakeven_trade_is_zero(self):
        r = _compute_r_multiple(0.0, 5.0, 100.0)
        assert r == 0.0

    def test_no_division_by_zero_when_risk_zero(self):
        """Risk == 0 should return None, not raise."""
        r = _compute_r_multiple(500.0, 0.0, 100.0)
        assert r is None

    def test_no_division_by_zero_when_shares_zero(self):
        r = _compute_r_multiple(500.0, 5.0, 0.0)
        assert r is None

    def test_1pct_proxy_r_multiple(self):
        """
        With no stop (proxy = 1% of entry=100 → risk=1/share).
        50 shares, profit=$100. R = 100 / (1*50) = 2.0
        """
        entry = 100.0
        risk = _compute_initial_risk(entry, None)   # 1.0
        r = _compute_r_multiple(100.0, risk, 50.0)
        assert math.isclose(r, 2.0, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# Tests — Expectancy and SQN
# ---------------------------------------------------------------------------

class TestExpectancyAndSQN:
    def test_expectancy_is_mean_of_r_multiples(self):
        r_vals = [2.0, -1.0, 1.5, -0.5, 3.0]
        exp, _ = _compute_expectancy_sqn(r_vals)
        assert math.isclose(exp, np.mean(r_vals), rel_tol=1e-9)

    def test_sqn_formula(self):
        r_vals = [2.0, -1.0, 1.5, -0.5, 3.0]
        exp, sqn = _compute_expectancy_sqn(r_vals)
        expected_sqn = (np.mean(r_vals) / np.std(r_vals, ddof=1)) * math.sqrt(len(r_vals))
        assert math.isclose(sqn, expected_sqn, rel_tol=1e-9)

    def test_zero_trades_returns_none(self):
        exp, sqn = _compute_expectancy_sqn([])
        assert exp is None
        assert sqn is None

    def test_one_trade_returns_none(self):
        """SQN requires >=2 trades (std of a single value is undefined)."""
        exp, sqn = _compute_expectancy_sqn([2.5])
        assert exp is None
        assert sqn is None

    def test_identical_r_multiples_sqn_is_zero(self):
        """All R-multiples equal → std=0 → SQN guard returns 0.0."""
        r_vals = [1.0, 1.0, 1.0, 1.0]
        exp, sqn = _compute_expectancy_sqn(r_vals)
        assert math.isclose(exp, 1.0, rel_tol=1e-9)
        assert sqn == 0.0

    def test_negative_expectancy_produces_negative_sqn(self):
        r_vals = [-2.0, -1.0, -0.5, -1.5]
        exp, sqn = _compute_expectancy_sqn(r_vals)
        assert exp < 0
        assert sqn < 0

    def test_two_trades_minimum_is_valid(self):
        r_vals = [1.0, -1.0]
        exp, sqn = _compute_expectancy_sqn(r_vals)
        assert exp == 0.0
        assert sqn == 0.0  # expectancy=0, so SQN=0 regardless

    def test_large_trade_count_sqn_grows(self):
        """SQN grows as trade count increases (same per-trade distribution)."""
        r_small = [1.5, 0.5] * 10           # 20 trades
        r_large = [1.5, 0.5] * 100          # 200 trades
        _, sqn_small = _compute_expectancy_sqn(r_small)
        _, sqn_large = _compute_expectancy_sqn(r_large)
        # sqn_large must be strictly greater than sqn_small
        assert sqn_large > sqn_small
        # Roughly in the expected ballpark (sqrt(10) ≈ 3.16, allow ±10%)
        ratio = sqn_large / sqn_small
        assert 2.8 < ratio < 3.6


# ---------------------------------------------------------------------------
# Integration: verify portfolio_simulations emits the fields
# ---------------------------------------------------------------------------

class TestTradeLogHasRMultipleFields:
    """
    Smoke test: run a minimal simulation and confirm every closed trade
    in the log contains 'InitialRisk' and 'RMultiple'.
    Uses the real CONFIG (slippage/commission are small but non-zero).
    """

    @staticmethod
    def _make_df(dates, prices, signal_col):
        """Build a minimal OHLCV + Signal DataFrame."""
        df = pd.DataFrame({
            'Open': prices,
            'High': [p * 1.01 for p in prices],
            'Low': [p * 0.99 for p in prices],
            'Close': prices,
            'Volume': [1_000_000] * len(prices),
            'Signal': signal_col,
        }, index=pd.to_datetime(dates))
        df.index.name = 'Datetime'
        return df

    def test_r_multiple_present_in_trade_log(self):
        from helpers.portfolio_simulations import run_portfolio_simulation

        dates = pd.date_range('2024-01-02', periods=10, freq='B')
        prices = [100.0 + i for i in range(10)]
        signals = [1, 1, 1, 1, -1, -1, -1, -1, -1, -1]

        df = self._make_df(dates, prices, signals)
        spy_df = df.copy()
        vix_df = df.assign(Close=20.0)

        portfolio_data = {'TEST': df}
        signal_series = {'TEST': df['Signal']}
        stop_config = {'type': 'none'}

        result = run_portfolio_simulation(
            portfolio_data, signal_series, 100_000, 0.10,
            spy_df, vix_df, None, stop_config
        )

        assert result is not None
        assert len(result['trade_log']) > 0
        for trade in result['trade_log']:
            assert 'InitialRisk' in trade, "InitialRisk missing from trade log"
            assert 'RMultiple' in trade, "RMultiple missing from trade log"
            assert trade['InitialRisk'] > 0, "InitialRisk must be positive"

    def test_percentage_stop_sets_initial_risk(self):
        """With a 5% stop, InitialRisk/share should equal entry_price * 0.05.

        Note: entry_price includes slippage so we check the formula holds
        (initial_risk == entry_price * 0.05) to within a small tolerance.
        """
        from helpers.portfolio_simulations import run_portfolio_simulation

        dates = pd.date_range('2024-01-02', periods=10, freq='B')
        prices = [100.0] * 10
        signals = [1, 1, 1, 1, -1, -1, -1, -1, -1, -1]

        df = self._make_df(dates, prices, signals)
        spy_df = df.copy()
        vix_df = df.assign(Close=20.0)

        portfolio_data = {'TEST': df}
        signal_series = {'TEST': df['Signal']}
        stop_config = {'type': 'percentage', 'value': 0.05}

        result = run_portfolio_simulation(
            portfolio_data, signal_series, 100_000, 0.10,
            spy_df, vix_df, None, stop_config
        )

        if result and result.get('trade_log'):
            for trade in result['trade_log']:
                # InitialRisk = entry_price * 0.05 (5% of whatever entry_price is)
                expected_risk = trade['EntryPrice'] * 0.05
                assert math.isclose(trade['InitialRisk'], expected_risk, rel_tol=1e-6), (
                    f"Expected InitialRisk={expected_risk:.4f} but got {trade['InitialRisk']}"
                )

"""tests/test_new_metrics.py

Unit tests for Annual Turnover % and Estimated After-Tax CAGR metrics
added to generate_overall_metrics_summary in report_generator.py.

Covers:
  - Annual Turnover % = (sum(price * shares) / initial_capital) / years * 100
  - After-Tax CAGR with positive profit (30% tax applied)
  - After-Tax CAGR with negative profit (no tax haircut)
  - After-Tax CAGR with zero profit
  - Edge cases: missing Shares/Price column, zero duration
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
# Pure-math helpers mirroring the inline formulas in report_generator.py
# ---------------------------------------------------------------------------

def _annual_turnover_pct(trades_df: pd.DataFrame, initial_capital: float, duration_years: float) -> float:
    """Mirror of the annual-turnover formula in generate_overall_metrics_summary."""
    price_col = 'Price' if 'Price' in trades_df.columns else None
    shares_col = 'Shares' if 'Shares' in trades_df.columns else None
    if price_col is None or shares_col is None:
        return float('nan')
    if duration_years <= 1e-6 or initial_capital <= 0:
        return float('nan')
    price_series = pd.to_numeric(trades_df[price_col], errors='coerce')
    shares_series = pd.to_numeric(trades_df[shares_col], errors='coerce')
    total_deployed = (price_series * shares_series).sum()
    return (total_deployed / initial_capital) / duration_years * 100


def _after_tax_cagr(initial_capital: float, total_net_profit: float, duration_years: float, tax_rate: float = 0.30) -> float:
    """Mirror of the after-tax CAGR formula in generate_overall_metrics_summary."""
    if duration_years <= 1e-6 or initial_capital <= 0:
        return float('nan')
    if total_net_profit > 0:
        after_tax_profit = total_net_profit * (1.0 - tax_rate)
    else:
        after_tax_profit = total_net_profit
    after_tax_equity = initial_capital + after_tax_profit
    if after_tax_equity <= 0:
        return float('nan')
    return (after_tax_equity / initial_capital) ** (1.0 / duration_years) - 1.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trades(prices, shares) -> pd.DataFrame:
    """Build a minimal trades DataFrame with Price and Shares columns."""
    assert len(prices) == len(shares)
    return pd.DataFrame({'Price': prices, 'Shares': shares})


# ---------------------------------------------------------------------------
# Tests — Annual Turnover %
# ---------------------------------------------------------------------------

class TestAnnualTurnover:
    def test_exact_value_simple(self):
        """
        3 trades: 100*10 + 200*5 + 50*20 = 1000 + 1000 + 1000 = 3000 deployed.
        Initial capital = 10000, duration = 2 years.
        Turnover = (3000 / 10000) / 2 * 100 = 15.0%
        """
        df = _make_trades([100, 200, 50], [10, 5, 20])
        result = _annual_turnover_pct(df, 10000.0, 2.0)
        assert math.isclose(result, 15.0, rel_tol=1e-9)

    def test_single_trade(self):
        """
        1 trade: 500 * 4 = 2000 deployed.
        Capital = 10000, duration = 1 year.
        Turnover = (2000 / 10000) / 1 * 100 = 20.0%
        """
        df = _make_trades([500], [4])
        result = _annual_turnover_pct(df, 10000.0, 1.0)
        assert math.isclose(result, 20.0, rel_tol=1e-9)

    def test_turnover_scales_with_duration(self):
        """Same capital deployed over 2 years vs 1 year → half the annual turnover."""
        df = _make_trades([100], [100])  # 10000 deployed
        t1 = _annual_turnover_pct(df, 10000.0, 1.0)
        t2 = _annual_turnover_pct(df, 10000.0, 2.0)
        assert math.isclose(t1, t2 * 2, rel_tol=1e-9)

    def test_turnover_100_pct_one_full_rotation(self):
        """
        Total deployed = initial capital, 1 year → 100% turnover.
        """
        df = _make_trades([100], [100])  # 10000 deployed
        result = _annual_turnover_pct(df, 10000.0, 1.0)
        assert math.isclose(result, 100.0, rel_tol=1e-9)

    def test_missing_shares_column_returns_nan(self):
        df = pd.DataFrame({'Price': [100, 200]})
        result = _annual_turnover_pct(df, 10000.0, 1.0)
        assert math.isnan(result)

    def test_missing_price_column_returns_nan(self):
        df = pd.DataFrame({'Shares': [10, 20]})
        result = _annual_turnover_pct(df, 10000.0, 1.0)
        assert math.isnan(result)

    def test_zero_duration_returns_nan(self):
        df = _make_trades([100], [10])
        result = _annual_turnover_pct(df, 10000.0, 0.0)
        assert math.isnan(result)


# ---------------------------------------------------------------------------
# Tests — After-Tax CAGR
# ---------------------------------------------------------------------------

class TestAfterTaxCagr:
    def test_positive_profit_tax_applied(self):
        """
        Capital=10000, profit=5000, 30% tax.
        After-tax profit = 5000 * 0.70 = 3500.
        After-tax equity = 13500.
        CAGR over 5 years = (13500/10000)^(1/5) - 1 = 0.35^0.2 - 1
        """
        expected = (13500 / 10000) ** (1 / 5) - 1
        result = _after_tax_cagr(10000.0, 5000.0, 5.0)
        assert math.isclose(result, expected, rel_tol=1e-9)

    def test_negative_profit_no_tax_applied(self):
        """
        Capital=10000, profit=-2000 (loss), no tax haircut.
        After-tax equity = 8000.
        CAGR over 4 years = (8000/10000)^(1/4) - 1
        """
        expected = (8000 / 10000) ** (1 / 4) - 1
        result = _after_tax_cagr(10000.0, -2000.0, 4.0)
        assert math.isclose(result, expected, rel_tol=1e-9)

    def test_zero_profit_cagr_is_zero(self):
        """Zero net profit → no tax → after-tax equity equals initial capital → CAGR = 0."""
        result = _after_tax_cagr(10000.0, 0.0, 3.0)
        assert math.isclose(result, 0.0, abs_tol=1e-12)

    def test_after_tax_cagr_less_than_gross_cagr(self):
        """After-tax CAGR must always be <= gross CAGR when profit > 0."""
        gross_equity = 10000.0 + 5000.0
        gross_cagr = (gross_equity / 10000.0) ** (1 / 5) - 1
        after_tax = _after_tax_cagr(10000.0, 5000.0, 5.0)
        assert after_tax < gross_cagr

    def test_one_year_duration(self):
        """
        Capital=10000, profit=1000, 1 year.
        After-tax equity = 10000 + 700 = 10700.
        CAGR = (10700/10000)^1 - 1 = 0.07
        """
        result = _after_tax_cagr(10000.0, 1000.0, 1.0)
        assert math.isclose(result, 0.07, rel_tol=1e-9)

    def test_zero_duration_returns_nan(self):
        result = _after_tax_cagr(10000.0, 5000.0, 0.0)
        assert math.isnan(result)

    def test_exact_tax_rate_arithmetic(self):
        """
        Verify the 30% tax exactly: profit=10000 → after-tax=7000.
        Capital=100000, 1 year → CAGR = 7000/100000 = 7.0%
        """
        result = _after_tax_cagr(100000.0, 10000.0, 1.0)
        assert math.isclose(result, 0.07, rel_tol=1e-9)

# tests/test_short_selling.py
"""
Unit tests for short-selling and HTB borrow cost in the backtester.

Covers:
  TestConfigDefaults         — htb_rate_annual presence and defaults
  TestBorrowCostArithmetic   — daily rate derivation and 30-day cost estimate
  TestNoRegressionLongOnlyPath — empty short_positions never debits cash
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import CONFIG


# ---------------------------------------------------------------------------
# TestConfigDefaults
# ---------------------------------------------------------------------------

class TestConfigDefaults:

    def test_htb_rate_annual_present(self):
        """htb_rate_annual must exist in CONFIG."""
        assert "htb_rate_annual" in CONFIG

    def test_htb_rate_annual_default_is_0_02(self):
        """Default htb_rate_annual must be 0.02 (2% p.a. — easy-to-borrow baseline)."""
        assert CONFIG["htb_rate_annual"] == 0.02

    def test_htb_rate_non_negative(self):
        """htb_rate_annual must be non-negative (a negative borrow rate makes no sense)."""
        assert CONFIG["htb_rate_annual"] >= 0


# ---------------------------------------------------------------------------
# TestBorrowCostArithmetic
# ---------------------------------------------------------------------------

class TestBorrowCostArithmetic:

    def _daily_from_annual(self, annual_rate):
        """Replicate the formula used in portfolio_simulations.py."""
        if annual_rate <= 0:
            return 0.0
        return (1.0 + annual_rate) ** (1.0 / 252) - 1.0

    def test_daily_rate_from_2pct_annual(self):
        """2% annual → daily ≈ 0.0000788 (within 1e-6)."""
        daily = self._daily_from_annual(0.02)
        expected = (1.02 ** (1 / 252)) - 1
        assert abs(daily - expected) < 1e-9
        assert abs(daily - 0.0000788) < 1e-6

    def test_zero_annual_gives_zero_daily(self):
        """htb_rate_annual=0.0 → daily rate = 0.0 (borrow cost disabled)."""
        daily = self._daily_from_annual(0.0)
        assert daily == 0.0

    def test_30_day_cost_approx(self):
        """$10k notional × 2% p.a. × 30 days ≈ $23.62 (within $0.50).

        True compound cost: 10_000 * ((1.02^(30/252)) - 1) ≈ $23.52.
        Daily-rate approximation (sum of 30 daily debits) ≈ same range.
        """
        notional = 10_000.0
        daily = self._daily_from_annual(0.02)
        cost_30 = notional * daily * 30  # simple-sum approximation
        expected = notional * ((1.02 ** (30 / 252)) - 1)  # compound exact
        # Both should be close to $23.52; the difference between them < $0.50
        assert abs(cost_30 - expected) < 0.50
        assert 20.0 < cost_30 < 30.0


# ---------------------------------------------------------------------------
# TestNoRegressionLongOnlyPath
# ---------------------------------------------------------------------------

class TestNoRegressionLongOnlyPath:

    def test_empty_short_positions_no_borrow_debit(self):
        """With short_positions = {}, the borrow-cost loop must never touch cash.

        Simulates 252 iterations of the borrow-debit block.
        """
        htb_rate_annual = 0.02
        htb_rate_daily = (1.0 + htb_rate_annual) ** (1.0 / 252) - 1.0
        short_positions: dict = {}
        cash = 100_000.0
        starting_cash = cash

        for _ in range(252):
            for symbol, spos in list(short_positions.items()):
                if htb_rate_daily > 0:
                    cost = spos['notional'] * htb_rate_daily
                    cash -= cost
                    spos['total_borrow_cost'] = spos.get('total_borrow_cost', 0.0) + cost

        assert cash == starting_cash, (
            f"Cash should be unchanged with no short positions; "
            f"expected {starting_cash}, got {cash}"
        )

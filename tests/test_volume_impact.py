# tests/test_volume_impact.py
"""
Unit tests for volume-based market impact slippage (SECTION 19).

Covers:
  TestConfigDefaults          — volume_impact_coeff presence and default
  TestImpactFormula           — sqrt formula correctness and monotonicity
  TestNoRegressionZeroCoeff   — zero coeff leaves entry price unchanged
"""

import os
import sys

import numpy as np
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import CONFIG


# ---------------------------------------------------------------------------
# Helpers — replicate the formula from portfolio_simulations.py
# ---------------------------------------------------------------------------

def _compute_impact(shares, adv_20, impact_coeff):
    """Pure-Python replica of the sqrt market impact formula."""
    if impact_coeff <= 0 or adv_20 <= 0:
        return 0.0
    order_pct_of_adv = shares / adv_20
    return impact_coeff * np.sqrt(order_pct_of_adv)


def _entry_price_with_impact(raw_price, slippage_pct, shares, adv_20, impact_coeff):
    """Simulate the full entry price calculation."""
    price = raw_price * (1 + slippage_pct)
    if impact_coeff > 0 and adv_20 > 0:
        price = price * (1 + _compute_impact(shares, adv_20, impact_coeff))
    return price


# ---------------------------------------------------------------------------
# TestConfigDefaults
# ---------------------------------------------------------------------------

class TestConfigDefaults:

    def test_volume_impact_coeff_present(self):
        """volume_impact_coeff must be a key in CONFIG."""
        assert "volume_impact_coeff" in CONFIG

    def test_volume_impact_coeff_default_zero(self):
        """Default volume_impact_coeff must be 0.0 (impact disabled out-of-the-box)."""
        assert CONFIG["volume_impact_coeff"] == 0.0


# ---------------------------------------------------------------------------
# TestImpactFormula
# ---------------------------------------------------------------------------

class TestImpactFormula:

    def test_sqrt_formula_1pct_adv(self):
        """1% of ADV, coeff=0.1 → impact = 0.1 * sqrt(0.01) = 0.01."""
        adv = 1_000_000
        shares = 10_000       # 1% of ADV
        coeff = 0.1
        impact = _compute_impact(shares, adv, coeff)
        expected = 0.1 * np.sqrt(0.01)
        assert abs(impact - expected) < 1e-12

    def test_sqrt_formula_5pct_adv(self):
        """5% of ADV, coeff=0.1 → impact ≈ 0.02236."""
        adv = 1_000_000
        shares = 50_000       # 5% of ADV
        coeff = 0.1
        impact = _compute_impact(shares, adv, coeff)
        expected = 0.1 * np.sqrt(0.05)
        assert abs(impact - expected) < 1e-12
        assert abs(impact - 0.02236) < 0.0001

    def test_zero_coeff_no_impact(self):
        """volume_impact_coeff=0.0 must produce exactly 0.0 additional slippage."""
        impact = _compute_impact(shares=50_000, adv_20=1_000_000, impact_coeff=0.0)
        assert impact == 0.0

    def test_impact_increases_with_order_size(self):
        """Larger order fraction → higher market impact (monotone relationship)."""
        adv = 1_000_000
        coeff = 0.1
        impacts = [_compute_impact(int(adv * pct), adv, coeff) for pct in [0.001, 0.01, 0.05, 0.10]]
        assert impacts == sorted(impacts), "Impact should be monotonically increasing with order size"


# ---------------------------------------------------------------------------
# TestNoRegressionZeroCoeff
# ---------------------------------------------------------------------------

class TestNoRegressionZeroCoeff:

    def test_zero_coeff_entry_price_unchanged(self):
        """
        With volume_impact_coeff=0.0, the final entry price must equal
        raw_entry_price * (1 + slippage_pct) exactly — no market impact.
        """
        raw_price = 150.0
        slippage_pct = 0.0005
        shares = 100
        adv_20 = 500_000
        impact_coeff = 0.0   # disabled

        price = _entry_price_with_impact(raw_price, slippage_pct, shares, adv_20, impact_coeff)
        expected = raw_price * (1 + slippage_pct)

        assert price == pytest.approx(expected, rel=1e-12), (
            f"Expected entry price {expected}, got {price} — market impact must be zero"
        )

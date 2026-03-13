"""tests/test_underwater_plot.py

Unit tests for HWM and drawdown-percentage math used by the Underwater Plot.

Covers:
  - HWM is the running cumulative maximum of the equity curve
  - Drawdown % is (equity - hwm) / hwm (fractional, always <= 0)
  - First trade at the initial equity has zero drawdown
  - Recovery back to a new high resets drawdown to zero
  - Single-element equity series is valid
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
# Pure-math helpers mirroring what plot_underwater's callers compute
# ---------------------------------------------------------------------------

def _hwm(equity: pd.Series) -> pd.Series:
    """High Water Mark — running cumulative maximum."""
    return equity.cummax()


def _drawdown_pct(equity: pd.Series) -> pd.Series:
    """Fractional drawdown below HWM: (equity - hwm) / hwm.

    Values are always <= 0.  Zero means at or above the previous peak.
    Division by zero is avoided by skipping points where hwm == 0.
    """
    hwm = _hwm(equity)
    dd = pd.Series(np.zeros(len(equity), dtype=float), index=equity.index)
    valid = hwm.abs() > 1e-12
    dd[valid] = (equity[valid] - hwm[valid]) / hwm[valid]
    return dd


# ---------------------------------------------------------------------------
# Tests — HWM
# ---------------------------------------------------------------------------

class TestHighWaterMark:
    def test_strictly_rising_equity(self):
        equity = pd.Series([100, 110, 120, 130])
        expected = pd.Series([100, 110, 120, 130])
        pd.testing.assert_series_equal(_hwm(equity), expected)

    def test_drawdown_then_recovery(self):
        equity = pd.Series([100, 110, 90, 105, 120])
        expected = pd.Series([100, 110, 110, 110, 120])
        pd.testing.assert_series_equal(_hwm(equity), expected)

    def test_flat_equity(self):
        equity = pd.Series([100, 100, 100])
        expected = pd.Series([100, 100, 100])
        pd.testing.assert_series_equal(_hwm(equity), expected)

    def test_only_declining(self):
        equity = pd.Series([120, 110, 100, 90])
        expected = pd.Series([120, 120, 120, 120])
        pd.testing.assert_series_equal(_hwm(equity), expected)

    def test_single_element(self):
        equity = pd.Series([100.0])
        assert _hwm(equity).iloc[0] == 100.0


# ---------------------------------------------------------------------------
# Tests — Drawdown Percentage
# ---------------------------------------------------------------------------

class TestDrawdownPct:
    def test_known_values(self):
        """[100, 110, 90, 105, 120] → exact fractional drawdowns."""
        equity = pd.Series([100.0, 110.0, 90.0, 105.0, 120.0])
        dd = _drawdown_pct(equity)

        assert math.isclose(dd.iloc[0], 0.0, abs_tol=1e-12)       # at HWM
        assert math.isclose(dd.iloc[1], 0.0, abs_tol=1e-12)       # new high
        assert math.isclose(dd.iloc[2], -20.0 / 110.0, rel_tol=1e-9)  # trough
        assert math.isclose(dd.iloc[3], -5.0 / 110.0, rel_tol=1e-9)   # partial recovery
        assert math.isclose(dd.iloc[4], 0.0, abs_tol=1e-12)       # new high again

    def test_all_values_le_zero(self):
        equity = pd.Series([100.0, 110.0, 90.0, 105.0, 120.0])
        dd = _drawdown_pct(equity)
        assert (dd <= 1e-12).all(), "Drawdown % must never be positive"

    def test_no_drawdown_when_always_rising(self):
        equity = pd.Series([100.0, 110.0, 120.0, 130.0])
        dd = _drawdown_pct(equity)
        assert (dd.abs() < 1e-12).all()

    def test_maximum_drawdown_is_most_negative(self):
        equity = pd.Series([100.0, 110.0, 90.0, 105.0, 120.0])
        dd = _drawdown_pct(equity)
        # Max adverse point is trade index 2 (90 from peak of 110)
        assert dd.idxmin() == 2

    def test_full_recovery_resets_to_zero(self):
        equity = pd.Series([100.0, 80.0, 100.0, 120.0])
        dd = _drawdown_pct(equity)
        # After returning to 100 (index 2) drawdown = 0, index 3 is new high = 0
        assert math.isclose(dd.iloc[2], 0.0, abs_tol=1e-12)
        assert math.isclose(dd.iloc[3], 0.0, abs_tol=1e-12)

    def test_single_element_zero_drawdown(self):
        equity = pd.Series([100.0])
        dd = _drawdown_pct(equity)
        assert math.isclose(dd.iloc[0], 0.0, abs_tol=1e-12)

    def test_trough_exact_fraction(self):
        """Explicit fraction check: equity drops from 200 to 150 → -25%."""
        equity = pd.Series([200.0, 150.0])
        dd = _drawdown_pct(equity)
        assert math.isclose(dd.iloc[1], -0.25, rel_tol=1e-9)

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


# ---------------------------------------------------------------------------
# TestVolumeImpactEndToEnd (Task 9)
# ---------------------------------------------------------------------------

class TestVolumeImpactEndToEnd:
    """
    End-to-end tests that run a full simulation with volume_impact_coeff
    enabled and verify the impact flows through to the trade log and P&L.
    """

    @staticmethod
    def _make_ohlcv(n=60, start_price=100.0, trend=0.003):
        """Build synthetic OHLCV data with realistic volume."""
        import pandas as pd
        dates = pd.bdate_range(start="2023-01-02", periods=n, freq="B")
        closes = [start_price * (1 + trend) ** i for i in range(n)]
        df = pd.DataFrame({
            "Open":   [c * 0.999 for c in closes],
            "High":   [c * 1.01 for c in closes],
            "Low":    [c * 0.99 for c in closes],
            "Close":  closes,
            "Volume": [500_000] * n,
        }, index=dates)
        df.index.name = "Datetime"
        return df

    @staticmethod
    def _make_spy(n=60):
        import pandas as pd
        dates = pd.bdate_range(start="2023-01-02", periods=n, freq="B")
        closes = [400.0 * (1.001 ** i) for i in range(n)]
        df = pd.DataFrame({
            "Open": closes, "High": [c * 1.005 for c in closes],
            "Low": [c * 0.995 for c in closes], "Close": closes,
            "Volume": [1_000_000] * n,
        }, index=dates)
        df.index.name = "Datetime"
        return df

    @staticmethod
    def _make_vix(n=60):
        import pandas as pd
        dates = pd.bdate_range(start="2023-01-02", periods=n, freq="B")
        df = pd.DataFrame({
            "Open": [18.0] * n, "High": [19.0] * n,
            "Low": [17.0] * n, "Close": [18.0] * n,
            "Volume": [0] * n,
        }, index=dates)
        df.index.name = "Datetime"
        return df

    @staticmethod
    def _run_sim(volume_impact_coeff):
        """Run a full simulation with the given impact coefficient."""
        from unittest.mock import patch
        from helpers.portfolio_simulations import run_portfolio_simulation
        from helpers.indicators import sma_crossover_logic

        n = 60
        sym = TestVolumeImpactEndToEnd._make_ohlcv(n)
        spy = TestVolumeImpactEndToEnd._make_spy(n)
        vix = TestVolumeImpactEndToEnd._make_vix(n)

        df_copy = sym.copy()
        df_copy = sma_crossover_logic(df_copy, fast=5, slow=10)
        signals = {"TEST": df_copy["Signal"]}

        test_config = {
            "slippage_pct": 0.0005,
            "commission_per_share": 0.002,
            "execution_time": "open",
            "max_pct_adv": 0.05,
            "volume_impact_coeff": volume_impact_coeff,
            "risk_free_rate": 0.05,
            "htb_rate_annual": 0.0,
        }

        with patch.dict("config.CONFIG", test_config):
            result = run_portfolio_simulation(
                portfolio_data={"TEST": sym},
                signals=signals,
                initial_capital=100_000.0,
                allocation_pct=0.10,
                spy_df=spy,
                vix_df=vix,
                tnx_df=None,
                stop_config={"type": "none"},
            )
        return result

    def test_volume_impact_bps_exists_in_trade_log(self):
        """With coeff=0.1, VolumeImpact_bps must be present in strategy-exit trades.

        End-of-backtest mark-to-market closes may not include this field,
        so we check only trades with a normal ExitReason.
        """
        result = self._run_sim(volume_impact_coeff=0.1)
        assert result is not None, "Simulation returned None"
        normal_exits = [t for t in result["trade_log"] if t["ExitReason"] != "End of Backtest"]
        if normal_exits:
            for trade in normal_exits:
                assert "VolumeImpact_bps" in trade, f"Trade missing VolumeImpact_bps: {trade}"
        else:
            # If all trades are end-of-backtest, just verify P&L was affected
            result_zero = self._run_sim(volume_impact_coeff=0.0)
            assert result_zero is not None
            assert result["pnl_percent"] != result_zero["pnl_percent"]

    def test_volume_impact_bps_has_nonzero_value(self):
        """With coeff=0.1, at least one trade should have VolumeImpact_bps > 0.

        Only checks trades that went through the normal exit path (not
        end-of-backtest mark-to-market closes).
        """
        result = self._run_sim(volume_impact_coeff=0.1)
        assert result is not None, "Simulation returned None"
        normal_exits = [t for t in result["trade_log"] if t["ExitReason"] != "End of Backtest"]
        if normal_exits:
            bps_values = [t.get("VolumeImpact_bps", 0) for t in normal_exits]
            assert any(v > 0 for v in bps_values), f"All VolumeImpact_bps are zero: {bps_values}"
        else:
            # Verify impact still affected pricing via P&L comparison
            result_zero = self._run_sim(volume_impact_coeff=0.0)
            assert result_zero is not None
            assert result["pnl_percent"] < result_zero["pnl_percent"]

    def test_pnl_differs_with_impact_vs_without(self):
        """P&L with coeff=0.1 must differ from P&L with coeff=0.0."""
        result_with = self._run_sim(volume_impact_coeff=0.1)
        result_without = self._run_sim(volume_impact_coeff=0.0)
        assert result_with is not None, "Sim with impact returned None"
        assert result_without is not None, "Sim without impact returned None"
        assert result_with["pnl_percent"] != result_without["pnl_percent"], (
            f"P&L should differ: with={result_with['pnl_percent']}, "
            f"without={result_without['pnl_percent']}"
        )

    def test_impact_reduces_pnl(self):
        """Market impact is a cost — P&L with coeff=0.1 should be lower than with coeff=0.0."""
        result_with = self._run_sim(volume_impact_coeff=0.1)
        result_without = self._run_sim(volume_impact_coeff=0.0)
        assert result_with is not None and result_without is not None
        assert result_with["pnl_percent"] < result_without["pnl_percent"], (
            f"Impact should reduce P&L: with={result_with['pnl_percent']:.4f}, "
            f"without={result_without['pnl_percent']:.4f}"
        )

    def test_zero_coeff_volume_impact_bps_all_zero(self):
        """With coeff=0.0, all VolumeImpact_bps values should be 0.

        Uses .get() with default 0 to handle end-of-backtest trades that
        may not include the field.
        """
        result = self._run_sim(volume_impact_coeff=0.0)
        assert result is not None, "Simulation returned None"
        bps_values = [t.get("VolumeImpact_bps", 0) for t in result["trade_log"]]
        assert all(v == 0 for v in bps_values), f"Expected all zero bps: {bps_values}"

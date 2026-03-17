# tests/test_mc_block_bootstrap.py
"""
Unit tests for block-bootstrap Monte Carlo in helpers/monte_carlo.py.

Covers:
  TestConfigDefaults        — mc_sampling and mc_block_size config defaults
  TestBlockBootstrap        — shape, auto block size, streak divergence,
                              small trade list guard, i.i.d. seed match
  TestNoRegressionIidPath   — default (no key) behaves as i.i.d.
"""

import os
import sys
from unittest.mock import patch

import numpy as np
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import CONFIG
from helpers.monte_carlo import run_monte_carlo_simulation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _streak_trades(n_repeat=5):
    """
    Build a streaky trade list: 10 consecutive wins (+100) then 10 losses (-100),
    repeated n_repeat times.  Autocorrelation is strong and clearly visible.
    """
    block = [100.0] * 10 + [-100.0] * 10
    return block * n_repeat


def _flat_trades(n=100, value=10.0):
    """All trades identical — i.i.d. and block produce the same distribution."""
    return [value] * n


# ---------------------------------------------------------------------------
# TestConfigDefaults
# ---------------------------------------------------------------------------

class TestConfigDefaults:

    def test_mc_sampling_default_is_iid(self):
        """CONFIG['mc_sampling'] must default to 'iid'."""
        assert CONFIG["mc_sampling"] == "iid"

    def test_mc_block_size_default_is_none(self):
        """CONFIG['mc_block_size'] must default to None (auto)."""
        assert CONFIG["mc_block_size"] is None


# ---------------------------------------------------------------------------
# TestBlockBootstrap
# ---------------------------------------------------------------------------

class TestBlockBootstrap:

    def test_iid_output_shape(self):
        """i.i.d. mode: final_equities and max_drawdowns both have length num_simulations."""
        trades = _flat_trades(100)
        with patch.dict(CONFIG, {"mc_sampling": "iid"}):
            result = run_monte_carlo_simulation(trades, 100_000, num_simulations=200)
        assert result is not None
        assert len(result["final_equities"]) == 200
        assert len(result["max_drawdowns"]) == 200

    def test_block_output_shape(self):
        """block mode: same shape guarantee as i.i.d."""
        trades = _flat_trades(100)
        with patch.dict(CONFIG, {"mc_sampling": "block", "mc_block_size": 10}):
            result = run_monte_carlo_simulation(trades, 100_000, num_simulations=200)
        assert result is not None
        assert len(result["final_equities"]) == 200
        assert len(result["max_drawdowns"]) == 200

    def test_block_auto_size(self):
        """With mc_block_size=None and 100 trades, auto block size resolves to 10 (sqrt(100))."""
        trades = list(range(1, 101))  # 100 trades
        # Patch so we can observe block_size without running full sim
        called_starts = []

        original_randint = np.random.randint

        def _capturing_randint(low, high=None, size=None):
            # Record the 'high' argument — that's num_trades (block count derived from it)
            called_starts.append((low, high, size))
            return original_randint(low, high, size=size)

        with patch.dict(CONFIG, {"mc_sampling": "block", "mc_block_size": None}):
            with patch("numpy.random.randint", side_effect=_capturing_randint):
                run_monte_carlo_simulation(trades, 100_000, num_simulations=5)

        # Each call: randint(0, num_trades=100, size=n_blocks)
        # n_blocks = ceil(100 / auto_block_size); auto_block_size = sqrt(100) = 10
        # so n_blocks = 10, size=10
        assert called_starts, "randint was never called"
        _, _, size = called_starts[0]
        assert size == 10, f"Expected n_blocks=10 (auto block_size=10), got size={size}"

    def test_block_output_not_identical_to_iid(self):
        """
        With a strongly streaky trade sequence, block paths preserve clustering
        while i.i.d. scatters wins/losses.  The standard deviation of final
        equities should differ by more than 1% between the two methods.
        """
        trades = _streak_trades(n_repeat=5)  # 100 trades with strong streaks
        np.random.seed(42)
        with patch.dict(CONFIG, {"mc_sampling": "iid"}):
            iid_result = run_monte_carlo_simulation(trades, 100_000, num_simulations=500)

        np.random.seed(42)
        with patch.dict(CONFIG, {"mc_sampling": "block", "mc_block_size": 10}):
            block_result = run_monte_carlo_simulation(trades, 100_000, num_simulations=500)

        iid_std = np.std(iid_result["final_equities"])
        block_std = np.std(block_result["final_equities"])

        rel_diff = abs(iid_std - block_std) / max(iid_std, block_std)
        assert rel_diff > 0.01, (
            f"Expected >1% difference in std between i.i.d. and block on streaky data; "
            f"got iid_std={iid_std:.1f}, block_std={block_std:.1f}, rel_diff={rel_diff:.3%}"
        )

    def test_small_trade_list_returns_none(self):
        """Fewer than 5 trades must return None regardless of sampling method."""
        for mode in ("iid", "block"):
            with patch.dict(CONFIG, {"mc_sampling": mode}):
                assert run_monte_carlo_simulation([10.0, 20.0, -5.0], 100_000) is None

    def test_iid_path_unchanged(self):
        """
        i.i.d. mode with a fixed seed must produce the same final_equities
        as calling np.random.choice directly — verifying no regression.
        """
        trades = list(range(-50, 51))  # 101 trades
        trade_array = np.array(trades)
        initial = 100_000

        np.random.seed(7)
        with patch.dict(CONFIG, {"mc_sampling": "iid"}):
            result = run_monte_carlo_simulation(trades, initial, num_simulations=100)

        # Reproduce manually with the same seed
        np.random.seed(7)
        expected = []
        for _ in range(100):
            s = np.random.choice(trade_array, size=len(trades), replace=True)
            eq = initial + np.sum(s)
            expected.append(eq)

        np.testing.assert_allclose(
            result["final_equities"], expected,
            rtol=1e-9,
            err_msg="i.i.d. final equities do not match manual reproduction",
        )


# ---------------------------------------------------------------------------
# TestNoRegressionIidPath
# ---------------------------------------------------------------------------

class TestNoRegressionIidPath:

    def test_default_path_is_iid(self):
        """
        When mc_sampling is absent from CONFIG, the function falls through to the
        i.i.d. branch (get returns 'iid' by default).
        """
        trades = _flat_trades(50, value=100.0)
        # Remove mc_sampling to simulate a config that predates SECTION 18
        cfg_without_sampling = {k: v for k, v in CONFIG.items() if k != "mc_sampling"}
        with patch.dict(CONFIG, cfg_without_sampling, clear=True):
            result = run_monte_carlo_simulation(trades, 100_000, num_simulations=100)
        assert result is not None
        # All flat trades → final equity should always equal 100_000 + 50*100 = 105_000
        np.testing.assert_allclose(result["final_equities"], 105_000.0)

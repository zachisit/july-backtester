# tests/test_regime_filter.py
"""
Unit tests for is_regime_on() in scripts/momentum_rotation_v2.py.

Covers:
  TestIsRegimeOnMaOnly     — MA-only gate (no VIX overlay): date missing, not enough
                             history, below MA → False; above MA → True
  TestVixOverlayDisabled   — VIX_REGIME_THRESH=None or vix_df=None are no-ops
  TestVixOverlayEnabled    — VIX above/below threshold toggles regime correctly;
                             forward-fill on weekends; empty prior VIX → ignored
"""

import importlib.util
import os
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Import the standalone script via importlib (scripts/ has no __init__.py)
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_spec = importlib.util.spec_from_file_location(
    "momentum_rotation_v2",
    os.path.join(PROJECT_ROOT, "scripts", "momentum_rotation_v2.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
is_regime_on = _mod.is_regime_on
MOD_PATH = "momentum_rotation_v2"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_qqq(n: int, prices=None, ma_period: int = 5) -> pd.DataFrame:
    """Return a QQQ DataFrame with n bars. Default: linearly rising prices."""
    dates = pd.date_range("2020-01-02", periods=n, freq="B")
    if prices is None:
        prices = list(range(100, 100 + n))
    return pd.DataFrame({"Close": prices}, index=dates)


def _make_vix(dates_and_values: list) -> pd.DataFrame:
    """Return a VIX DataFrame from [(date_str, close), ...]."""
    dates = pd.DatetimeIndex([pd.Timestamp(d).normalize() for d, _ in dates_and_values])
    closes = [v for _, v in dates_and_values]
    return pd.DataFrame({"Close": closes}, index=dates)


# ---------------------------------------------------------------------------
# TestIsRegimeOnMaOnly
# ---------------------------------------------------------------------------

class TestIsRegimeOnMaOnly:
    """MA gate only — VIX_REGIME_THRESH stays None (default)."""

    def test_date_not_in_index_returns_false(self):
        qqq = _make_qqq(10)
        assert is_regime_on(qqq, "1999-01-04") is False

    def test_insufficient_history_returns_false(self):
        # Only 3 bars; REGIME_MA_PERIOD=5 → need at least 5
        qqq = _make_qqq(3)
        with patch.object(_mod, "REGIME_MA_PERIOD", 5):
            assert is_regime_on(qqq, qqq.index[-1]) is False

    def test_price_below_ma_returns_false(self):
        # Flat at 100 for ma_period bars, then drop to 50
        prices = [100] * 9 + [50]
        qqq = _make_qqq(10, prices=prices)
        with patch.object(_mod, "REGIME_MA_PERIOD", 5):
            assert is_regime_on(qqq, qqq.index[-1]) is False

    def test_price_equal_to_ma_returns_false(self):
        # All bars at 100 → close == MA → not strictly above → False
        prices = [100] * 10
        qqq = _make_qqq(10, prices=prices)
        with patch.object(_mod, "REGIME_MA_PERIOD", 5):
            assert is_regime_on(qqq, qqq.index[-1]) is False

    def test_price_above_ma_returns_true(self):
        # Rising prices: last bar clearly above any window mean
        prices = list(range(100, 110))   # 100..109, last=109, ma(5)=105
        qqq = _make_qqq(10, prices=prices)
        with patch.object(_mod, "REGIME_MA_PERIOD", 5):
            assert is_regime_on(qqq, qqq.index[-1]) is True

    def test_first_valid_bar_exactly_at_ma_period_minus_1(self):
        # Exactly REGIME_MA_PERIOD bars → iloc_pos == MA_PERIOD-1 → valid
        prices = list(range(100, 106))   # 6 bars, rising
        qqq = _make_qqq(6, prices=prices)
        with patch.object(_mod, "REGIME_MA_PERIOD", 6):
            assert is_regime_on(qqq, qqq.index[-1]) is True

    def test_one_bar_short_of_ma_period_returns_false(self):
        prices = list(range(100, 105))   # 5 bars
        qqq = _make_qqq(5, prices=prices)
        with patch.object(_mod, "REGIME_MA_PERIOD", 6):
            assert is_regime_on(qqq, qqq.index[-1]) is False


# ---------------------------------------------------------------------------
# TestVixOverlayDisabled
# ---------------------------------------------------------------------------

class TestVixOverlayDisabled:
    """VIX_REGIME_THRESH=None means overlay never fires."""

    def test_none_threshold_ignores_vix_df(self):
        prices = list(range(100, 110))
        qqq = _make_qqq(10, prices=prices)
        vix = _make_vix([("2020-01-13", 999.0)])   # extreme VIX — still ignored
        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "VIX_REGIME_THRESH", None):
            assert is_regime_on(qqq, qqq.index[-1], vix_df=vix) is True

    def test_none_vix_df_with_threshold_set_ignores_overlay(self):
        # Threshold set but vix_df is None → overlay skipped
        prices = list(range(100, 110))
        qqq = _make_qqq(10, prices=prices)
        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "VIX_REGIME_THRESH", 30.0):
            assert is_regime_on(qqq, qqq.index[-1], vix_df=None) is True

    def test_no_vix_kwarg_defaults_to_none(self):
        prices = list(range(100, 110))
        qqq = _make_qqq(10, prices=prices)
        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "VIX_REGIME_THRESH", None):
            assert is_regime_on(qqq, qqq.index[-1]) is True


# ---------------------------------------------------------------------------
# TestVixOverlayEnabled
# ---------------------------------------------------------------------------

class TestVixOverlayEnabled:
    """VIX_REGIME_THRESH set to a float — overlay is active."""

    def _rising_qqq(self):
        prices = list(range(100, 110))
        return _make_qqq(10, prices=prices)

    def test_vix_below_threshold_regime_on(self):
        qqq = self._rising_qqq()
        vix = _make_vix([("2020-01-10", 25.0)])
        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "VIX_REGIME_THRESH", 30.0):
            assert is_regime_on(qqq, qqq.index[-1], vix_df=vix) is True

    def test_vix_equal_to_threshold_regime_on(self):
        # VIX == threshold is NOT > threshold → regime ON
        qqq = self._rising_qqq()
        vix = _make_vix([("2020-01-10", 30.0)])
        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "VIX_REGIME_THRESH", 30.0):
            assert is_regime_on(qqq, qqq.index[-1], vix_df=vix) is True

    def test_vix_above_threshold_regime_off(self):
        # QQQ above MA but VIX > threshold → regime OFF
        qqq = self._rising_qqq()
        vix = _make_vix([("2020-01-10", 35.0)])
        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "VIX_REGIME_THRESH", 30.0):
            assert is_regime_on(qqq, qqq.index[-1], vix_df=vix) is False

    def test_vix_spike_overrides_bullish_ma(self):
        # Even with a strongly rising QQQ, VIX spike kills regime
        prices = [100] * 5 + [200] * 5   # massive jump above MA
        qqq = _make_qqq(10, prices=prices)
        vix = _make_vix([("2020-01-10", 80.0)])
        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "VIX_REGIME_THRESH", 30.0):
            assert is_regime_on(qqq, qqq.index[-1], vix_df=vix) is False

    def test_ma_gate_fires_before_vix_check(self):
        # QQQ below MA — should be False regardless of VIX level
        prices = [100] * 9 + [50]
        qqq = _make_qqq(10, prices=prices)
        vix = _make_vix([("2020-01-10", 10.0)])   # calm VIX
        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "VIX_REGIME_THRESH", 30.0):
            assert is_regime_on(qqq, qqq.index[-1], vix_df=vix) is False

    def test_vix_forward_fill_on_weekend(self):
        # signal_date is Monday 2020-01-13 (already in the 10-bar qqq index).
        # VIX only has a Friday 2020-01-10 row — no entry for the Monday.
        # "prior = vix_df[vix_df.index <= target]" must pick up Friday's row.
        qqq = self._rising_qqq()                   # last bar = 2020-01-15, Mon 01-13 included
        vix = _make_vix([("2020-01-10", 35.0)])    # Friday VIX — no Monday row
        signal_date = "2020-01-13"
        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "VIX_REGIME_THRESH", 30.0):
            # Friday VIX 35 > 30 → regime OFF even on Monday
            assert is_regime_on(qqq, signal_date, vix_df=vix) is False

    def test_vix_forward_fill_calm_on_weekend(self):
        qqq = self._rising_qqq()
        vix = _make_vix([("2020-01-10", 20.0)])    # calm Friday — no Monday row
        signal_date = "2020-01-13"
        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "VIX_REGIME_THRESH", 30.0):
            assert is_regime_on(qqq, signal_date, vix_df=vix) is True

    def test_empty_prior_vix_ignores_overlay(self):
        # VIX data only starts after the signal date → prior is empty → overlay skipped
        qqq = self._rising_qqq()
        vix = _make_vix([("2025-01-10", 99.0)])   # far-future VIX data
        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "VIX_REGIME_THRESH", 30.0):
            assert is_regime_on(qqq, qqq.index[-1], vix_df=vix) is True

    def test_multiple_vix_rows_uses_most_recent_prior(self):
        # Most recent prior VIX (closest before signal_date) must be used
        qqq = self._rising_qqq()   # last index = 2020-01-13
        vix = _make_vix([
            ("2020-01-06", 15.0),  # calm
            ("2020-01-09", 40.0),  # spike — this is the most recent prior
        ])
        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "VIX_REGIME_THRESH", 30.0):
            assert is_regime_on(qqq, qqq.index[-1], vix_df=vix) is False

    def test_multiple_vix_rows_calm_most_recent(self):
        qqq = self._rising_qqq()
        vix = _make_vix([
            ("2020-01-06", 40.0),  # old spike
            ("2020-01-09", 20.0),  # recent calm — this should win
        ])
        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "VIX_REGIME_THRESH", 30.0):
            assert is_regime_on(qqq, qqq.index[-1], vix_df=vix) is True

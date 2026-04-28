# tests/test_rebalance_trim.py
"""
Tests for trim-on-rebalance logic (issue #137).
"""

import importlib.util
import os
import sys
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_spec = importlib.util.spec_from_file_location(
    "momentum_rotation_v2",
    os.path.join(PROJECT_ROOT, "scripts", "momentum_rotation_v2.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

run_backtest          = _mod.run_backtest
build_rebalance_pairs = _mod.build_rebalance_pairs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_with_drift(initial_price, drifted_price, cap=None):
    """
    Week 1: buy at initial_price.
    Week 2: open at drifted_price → trim fires if position > target.
    """
    dates = pd.date_range("2020-01-02", periods=20, freq="B")
    qqq_closes = list(range(100, 120))
    qqq_df = pd.DataFrame(
        {"Open": qqq_closes, "High": [c * 1.01 for c in qqq_closes],
         "Low":  [c * 0.99 for c in qqq_closes], "Close": qqq_closes,
         "Volume": 1_000_000},
        index=dates,
    )
    mid    = len(dates) // 2
    prices = [initial_price] * mid + [drifted_price] * (len(dates) - mid)
    sym_df = pd.DataFrame(
        {"Open": prices, "High": [p * 1.01 for p in prices],
         "Low":  [p * 0.99 for p in prices], "Close": prices, "Volume": 1_000_000},
        index=dates,
    )
    all_data = {"A": sym_df}
    pairs    = build_rebalance_pairs({"A": sym_df, "QQQ": qqq_df})

    with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
         patch.object(_mod, "MOMENTUM_LOOKBACK", 5), \
         patch.object(_mod, "SELL_BUFFER_RANK", 999), \
         patch.object(_mod, "MAX_POSITIONS", 1), \
         patch.object(_mod, "INITIAL_CAPITAL", 100_000.0), \
         patch.object(_mod, "MAX_POSITION_SIZE", cap):
        trade_log, _ = run_backtest(all_data, qqq_df, pairs[:3])

    return trade_log


# ---------------------------------------------------------------------------
# TestRebalanceTrim
# ---------------------------------------------------------------------------

class TestRebalanceTrim:
    """Verify trim-on-rebalance logic (issue #137)."""

    def test_trim_fires_when_position_drifts_above_target(self):
        # Buy at $10 (20% of $100k = $2k), next week open at $50 → trim fires
        tl = _run_with_drift(initial_price=10.0, drifted_price=50.0)
        assert any(t["ExitReason"] == "Trim" for t in tl), "expected a trim trade"

    def test_no_trim_when_position_at_or_below_target(self):
        # Flat price → position stays at target → no trim
        tl = _run_with_drift(initial_price=10.0, drifted_price=10.0)
        assert not any(t["ExitReason"] == "Trim" for t in tl), "expected no trim on flat price"

    def test_trim_is_profitable_on_appreciated_position(self):
        tl = _run_with_drift(initial_price=10.0, drifted_price=50.0)
        trims = [t for t in tl if t["ExitReason"] == "Trim"]
        assert trims
        assert all(t["PnL"] > 0 for t in trims), "trim on appreciated position should be profitable"

    def test_nan_open_price_skips_trim_gracefully(self):
        dates = pd.date_range("2020-01-02", periods=20, freq="B")
        qqq_closes = list(range(100, 120))
        qqq_df = pd.DataFrame(
            {"Open": qqq_closes, "High": [c * 1.01 for c in qqq_closes],
             "Low":  [c * 0.99 for c in qqq_closes], "Close": qqq_closes,
             "Volume": 1_000_000},
            index=dates,
        )
        opens  = [10.0] * 10 + [np.nan] * 10
        closes = [50.0] * 20
        sym_df = pd.DataFrame(
            {"Open": opens, "High": closes, "Low": closes, "Close": closes, "Volume": 1_000_000},
            index=dates,
        )
        all_data = {"A": sym_df}
        pairs    = build_rebalance_pairs({"A": sym_df, "QQQ": qqq_df})

        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "MOMENTUM_LOOKBACK", 5), \
             patch.object(_mod, "SELL_BUFFER_RANK", 999), \
             patch.object(_mod, "MAX_POSITIONS", 1), \
             patch.object(_mod, "INITIAL_CAPITAL", 100_000.0), \
             patch.object(_mod, "MAX_POSITION_SIZE", None):
            trade_log, _ = run_backtest(all_data, qqq_df, pairs[:3])

        assert not any(t["ExitReason"] == "Trim" for t in trade_log), \
            "NaN open price should skip trim without crashing"

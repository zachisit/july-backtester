# tests/test_position_size_cap.py
"""
Tests for MAX_POSITION_SIZE dollar cap in do_buy (issue #136).
"""

import importlib.util
import os
import sys
from unittest.mock import patch

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

def _make_rising_df(n, start=100.0, step=1.0):
    dates  = pd.date_range("2020-01-02", periods=n, freq="B")
    closes = [start + i * step for i in range(n)]
    return pd.DataFrame(
        {"Open": closes, "High": [c * 1.01 for c in closes],
         "Low":  [c * 0.99 for c in closes], "Close": closes, "Volume": 1_000_000},
        index=dates,
    )


def _run_one_buy(equity, cap, stock_price=10.0):
    n       = 80
    qqq_df  = _make_rising_df(n, start=100.0, step=1.0)
    sym_df  = _make_rising_df(n, start=stock_price, step=0.1)
    all_data = {"A": sym_df}
    pairs    = build_rebalance_pairs({**all_data, "QQQ": qqq_df})

    with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
         patch.object(_mod, "MOMENTUM_LOOKBACK", 5), \
         patch.object(_mod, "SELL_BUFFER_RANK", 999), \
         patch.object(_mod, "MAX_POSITIONS", 1), \
         patch.object(_mod, "INITIAL_CAPITAL", equity), \
         patch.object(_mod, "MAX_POSITION_SIZE", cap):
        trade_log, _ = run_backtest(all_data, qqq_df, pairs[:2])

    return trade_log


# ---------------------------------------------------------------------------
# TestPositionSizeCap
# ---------------------------------------------------------------------------

class TestPositionSizeCap:
    """Verify MAX_POSITION_SIZE dollar cap in do_buy (issue #136)."""

    def test_alloc_wins_when_below_cap(self):
        # equity=$100k, 20% alloc=$20k, cap=$50k → alloc wins
        tl   = _run_one_buy(equity=100_000, cap=50_000, stock_price=10.0)
        buys = [t for t in tl if t["Shares"] > 0]
        assert buys, "expected at least one buy"
        pos_value = buys[0]["Shares"] * buys[0]["EntryPrice"]
        assert pos_value <= 20_500   # ≤ 20k + slippage tolerance

    def test_cap_wins_when_alloc_exceeds_cap(self):
        # equity=$500k, 20% alloc=$100k, cap=$50k → cap wins
        tl   = _run_one_buy(equity=500_000, cap=50_000, stock_price=10.0)
        buys = [t for t in tl if t["Shares"] > 0]
        assert buys, "expected at least one buy"
        pos_value = buys[0]["Shares"] * buys[0]["EntryPrice"]
        assert pos_value <= 51_000
        assert pos_value >= 40_000

    def test_no_cap_uses_full_alloc(self):
        # cap=None → position_value = equity * 0.20
        tl   = _run_one_buy(equity=500_000, cap=None, stock_price=10.0)
        buys = [t for t in tl if t["Shares"] > 0]
        assert buys, "expected at least one buy"
        pos_value = buys[0]["Shares"] * buys[0]["EntryPrice"]
        assert pos_value >= 90_000   # close to 100k (500k * 20%)

    def test_zero_shares_when_cap_too_low(self):
        # cap=$1 with stock_price=$10 → floor(1/10)=0 → no buy logged
        tl   = _run_one_buy(equity=100_000, cap=1, stock_price=10.0)
        buys = [t for t in tl if t["Shares"] > 0]
        assert len(buys) == 0, "expected no buy when cap yields 0 shares"

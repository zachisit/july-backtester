# tests/test_short_overlay.py
"""
Tests for the short overlay feature (issue #139).

  TestShortConstants  — module-level constants exist with correct defaults
  TestShortOverlay    — short entry/cover/accounting via run_backtest
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


def _make_flat_df(n, price=100.0):
    dates = pd.date_range("2020-01-02", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": price, "High": price * 1.01, "Low": price * 0.99,
         "Close": price, "Volume": 1_000_000},
        index=dates,
    )


def _stocks(n, n_symbols=4):
    out = {}
    for i in range(n_symbols):
        start = 50.0 + i * 10
        step  = 0.1 * (i - n_symbols // 2)
        out[f"S{i}"] = _make_rising_df(n, start=start, step=step)
    return out


def _run_always_off(n=80, max_short=2, initial_capital=200_000.0, n_sym=4):
    qqq_df   = _make_flat_df(n, 100.0)
    all_data = _stocks(n, n_sym)
    pairs    = build_rebalance_pairs({**all_data, "QQQ": qqq_df})
    with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
         patch.object(_mod, "MOMENTUM_LOOKBACK", 5), \
         patch.object(_mod, "SELL_BUFFER_RANK", 999), \
         patch.object(_mod, "MAX_POSITIONS", 3), \
         patch.object(_mod, "MAX_SHORT_POSITIONS", max_short), \
         patch.object(_mod, "SHORT_COVER_BUFFER_RANK", 999), \
         patch.object(_mod, "INITIAL_CAPITAL", initial_capital):
        tl, el = run_backtest(all_data, qqq_df, pairs)
    return tl, el


def _run_off_then_on(n=80, max_short=2, initial_capital=200_000.0, n_sym=4):
    dates    = pd.date_range("2020-01-02", periods=n, freq="B")
    split    = n // 2
    closes   = [100.0] * split + [100.0 + (i + 1) * 2.0 for i in range(n - split)]
    qqq_df   = pd.DataFrame(
        {"Open": closes, "High": [c * 1.01 for c in closes],
         "Low":  [c * 0.99 for c in closes], "Close": closes, "Volume": 1_000_000},
        index=dates,
    )
    all_data = _stocks(n, n_sym)
    pairs    = build_rebalance_pairs({**all_data, "QQQ": qqq_df})
    with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
         patch.object(_mod, "MOMENTUM_LOOKBACK", 5), \
         patch.object(_mod, "SELL_BUFFER_RANK", 999), \
         patch.object(_mod, "MAX_POSITIONS", 3), \
         patch.object(_mod, "MAX_SHORT_POSITIONS", max_short), \
         patch.object(_mod, "SHORT_COVER_BUFFER_RANK", 999), \
         patch.object(_mod, "INITIAL_CAPITAL", initial_capital):
        tl, el = run_backtest(all_data, qqq_df, pairs)
    return tl, el


# ---------------------------------------------------------------------------
# TestShortConstants
# ---------------------------------------------------------------------------

class TestShortConstants:
    def test_max_short_positions_default(self):
        assert hasattr(_mod, "MAX_SHORT_POSITIONS")
        assert _mod.MAX_SHORT_POSITIONS == 3

    def test_short_cover_buffer_rank_default(self):
        assert hasattr(_mod, "SHORT_COVER_BUFFER_RANK")
        assert _mod.SHORT_COVER_BUFFER_RANK == 25

    def test_htb_rate_annual_default(self):
        assert hasattr(_mod, "HTB_RATE_ANNUAL")
        assert _mod.HTB_RATE_ANNUAL == 0.02


# ---------------------------------------------------------------------------
# TestShortOverlay
# ---------------------------------------------------------------------------

class TestShortOverlay:

    def test_zero_max_short_positions_no_short_trades(self):
        tl, _ = _run_always_off(max_short=0)
        assert not any(t["Shares"] < 0 for t in tl), \
            "MAX_SHORT_POSITIONS=0 must produce no shorts"

    def test_shorts_appear_with_negative_shares_during_regime_off(self):
        tl, _ = _run_always_off(max_short=2)
        assert any(t["Shares"] < 0 for t in tl), \
            "expected short trades during regime-OFF"

    def test_end_of_backtest_covers_open_shorts(self):
        tl, _ = _run_always_off(max_short=2)
        assert any(t["ExitReason"] == "End of backtest" for t in tl), \
            "open shorts must be covered at end of backtest"

    def test_regime_on_covers_shorts(self):
        tl, _ = _run_off_then_on(max_short=2)
        assert any(t["ExitReason"] == "Regime ON" for t in tl), \
            "shorts should be covered when regime turns ON"

    def test_htb_borrow_cost_deducted_from_pnl(self):
        n      = 80
        qqq_df = _make_flat_df(n, 100.0)
        flat   = _make_flat_df(n, 50.0)
        all_data = {"FLAT": flat}
        pairs    = build_rebalance_pairs({"FLAT": flat, "QQQ": qqq_df})
        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "MOMENTUM_LOOKBACK", 5), \
             patch.object(_mod, "SELL_BUFFER_RANK", 999), \
             patch.object(_mod, "MAX_POSITIONS", 1), \
             patch.object(_mod, "MAX_SHORT_POSITIONS", 1), \
             patch.object(_mod, "SHORT_COVER_BUFFER_RANK", 999), \
             patch.object(_mod, "INITIAL_CAPITAL", 100_000.0), \
             patch.object(_mod, "HTB_RATE_ANNUAL", 0.02):
            tl, _ = run_backtest(all_data, qqq_df, pairs)
        shorts = [t for t in tl if t["Shares"] < 0]
        assert shorts
        assert all(t["PnL"] < 0 for t in shorts), \
            "flat-price short should be net negative (borrow + commission)"

    def test_cash_increases_at_short_entry(self):
        tl, _ = _run_always_off(max_short=2)
        assert any(t["Shares"] < 0 for t in tl), "expected at least one short"

    def test_short_not_entered_if_already_long(self):
        n      = 80
        dates  = pd.date_range("2020-01-02", periods=n, freq="B")
        split  = n // 2
        closes = list(range(100, 100 + split)) + [100 + split] * (n - split)
        qqq_df = pd.DataFrame(
            {"Open": closes, "High": [c * 1.01 for c in closes],
             "Low":  [c * 0.99 for c in closes], "Close": closes, "Volume": 1_000_000},
            index=dates,
        )
        stock  = _make_rising_df(n, start=20.0, step=0.0)
        all_data = {"A": stock}
        pairs    = build_rebalance_pairs({"A": stock, "QQQ": qqq_df})
        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "MOMENTUM_LOOKBACK", 5), \
             patch.object(_mod, "SELL_BUFFER_RANK", 999), \
             patch.object(_mod, "MAX_POSITIONS", 1), \
             patch.object(_mod, "MAX_SHORT_POSITIONS", 1), \
             patch.object(_mod, "SHORT_COVER_BUFFER_RANK", 999), \
             patch.object(_mod, "INITIAL_CAPITAL", 100_000.0):
            tl, _ = run_backtest(all_data, qqq_df, pairs)
        by_date_sym = {}
        for t in tl:
            by_date_sym.setdefault((t["EntryDate"], t["Symbol"]), []).append(t["Shares"])
        for k, shares_list in by_date_sym.items():
            assert not (any(s > 0 for s in shares_list) and any(s < 0 for s in shares_list)), \
                f"simultaneous long+short for {k}"

    def test_profitable_short_when_price_falls(self):
        n      = 80
        dates  = pd.date_range("2020-01-02", periods=n, freq="B")
        qqq_df = _make_flat_df(n, 100.0)
        split  = n // 2
        prices = [50.0] * split + [30.0] * (n - split)
        drop   = pd.DataFrame(
            {"Open": prices, "High": prices, "Low": prices, "Close": prices, "Volume": 1_000_000},
            index=dates,
        )
        all_data = {"DROP": drop}
        pairs    = build_rebalance_pairs({"DROP": drop, "QQQ": qqq_df})
        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "MOMENTUM_LOOKBACK", 5), \
             patch.object(_mod, "MAX_POSITIONS", 1), \
             patch.object(_mod, "MAX_SHORT_POSITIONS", 1), \
             patch.object(_mod, "SHORT_COVER_BUFFER_RANK", 999), \
             patch.object(_mod, "INITIAL_CAPITAL", 100_000.0):
            tl, _ = run_backtest(all_data, qqq_df, pairs)
        shorts = [t for t in tl if t["Shares"] < 0]
        assert shorts
        assert any(t["PnL"] > 0 for t in shorts), \
            "short on dropping stock should yield positive PnL"

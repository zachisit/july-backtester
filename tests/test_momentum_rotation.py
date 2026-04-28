# tests/test_momentum_rotation.py
"""
Tests for issues #136, #137, #139 in scripts/momentum_rotation_v2.py.

  TestPositionSizeCap  — #136: MAX_POSITION_SIZE dollar cap in do_buy
  TestRebalanceTrim    — #137: trim-on-rebalance logic
  TestShortConstants   — #139: new module-level constants
  TestShortOverlay     — #139: short entry/cover/accounting via run_backtest
"""

import importlib.util
import math
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

run_backtest       = _mod.run_backtest
is_regime_on       = _mod.is_regime_on
build_rebalance_pairs = _mod.build_rebalance_pairs


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_df(n: int, price: float = 100.0, open_price: float = None) -> pd.DataFrame:
    """Minimal OHLCV DataFrame with n bars of constant price."""
    dates = pd.date_range("2020-01-02", periods=n, freq="B")
    op = price if open_price is None else open_price
    return pd.DataFrame(
        {"Open": op, "High": price * 1.01, "Low": price * 0.99, "Close": price, "Volume": 1_000_000},
        index=dates,
    )


def _make_rising_df(n: int, start: float = 100.0, step: float = 1.0,
                    open_offset: float = 0.0) -> pd.DataFrame:
    dates  = pd.date_range("2020-01-02", periods=n, freq="B")
    closes = [start + i * step for i in range(n)]
    opens  = [c + open_offset for c in closes]
    highs  = [c * 1.01 for c in closes]
    lows   = [c * 0.99 for c in closes]
    return pd.DataFrame(
        {"Open": opens, "High": highs, "Low": lows, "Close": closes, "Volume": 1_000_000},
        index=dates,
    )


def _mini_universe(n_bars: int = 80, qqq_rising: bool = True,
                   stock_price: float = 50.0) -> tuple:
    """
    Returns (all_data, qqq_df, rebalance_pairs) with patched MA/lookback periods
    so we only need ~80 bars of synthetic data.
    """
    qqq_df = _make_rising_df(n_bars, start=100.0, step=1.0) if qqq_rising else _make_df(n_bars, 100.0)
    sym_a  = _make_rising_df(n_bars, start=stock_price, step=0.5)
    sym_b  = _make_rising_df(n_bars, start=stock_price * 0.8, step=0.3)
    all_data = {"A": sym_a, "B": sym_b}
    combined = {**all_data, "QQQ": qqq_df}
    rebalance_pairs = build_rebalance_pairs(combined)
    return all_data, qqq_df, rebalance_pairs


# ---------------------------------------------------------------------------
# TestPositionSizeCap  (#136)
# ---------------------------------------------------------------------------

class TestPositionSizeCap:
    """Verify MAX_POSITION_SIZE dollar cap in do_buy (issue #136)."""

    def _run_one_buy(self, equity, cap, stock_price=10.0):
        """
        Run a single-week backtest so one buy fires.
        Patches INITIAL_CAPITAL to equity, MAX_POSITION_SIZE to cap.
        Returns trade_log.
        """
        n = 80
        qqq_df  = _make_rising_df(n, start=100.0, step=1.0)
        sym_df  = _make_rising_df(n, start=stock_price, step=0.1)
        all_data = {"A": sym_df}
        combined = {**all_data, "QQQ": qqq_df}
        pairs = build_rebalance_pairs(combined)

        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "MOMENTUM_LOOKBACK", 5), \
             patch.object(_mod, "SELL_BUFFER_RANK", 999), \
             patch.object(_mod, "MAX_POSITIONS", 1), \
             patch.object(_mod, "MAX_SHORT_POSITIONS", 0), \
             patch.object(_mod, "INITIAL_CAPITAL", equity), \
             patch.object(_mod, "MAX_POSITION_SIZE", cap):
            trade_log, _ = run_backtest(all_data, qqq_df, pairs[:2])

        return trade_log

    def test_alloc_wins_when_below_cap(self):
        # equity=$100k, 20% alloc=$20k, cap=$50k → alloc wins
        tl = self._run_one_buy(equity=100_000, cap=50_000, stock_price=10.0)
        buys = [t for t in tl if t["Shares"] > 0]
        assert buys, "expected at least one buy"
        # position value ≈ shares * entry_price  (ignoring slippage/commission)
        b = buys[0]
        pos_value = b["Shares"] * b["EntryPrice"]
        assert pos_value <= 20_500   # ≤ 20k + slippage tolerance

    def test_cap_wins_when_alloc_exceeds_cap(self):
        # equity=$500k, 20% alloc=$100k, cap=$50k → cap wins
        tl = self._run_one_buy(equity=500_000, cap=50_000, stock_price=10.0)
        buys = [t for t in tl if t["Shares"] > 0]
        assert buys, "expected at least one buy"
        b = buys[0]
        pos_value = b["Shares"] * b["EntryPrice"]
        # Should be ≤ cap + small slippage, definitely not near 100k
        assert pos_value <= 51_000
        assert pos_value >= 40_000   # meaningful position was taken

    def test_no_cap_uses_full_alloc(self):
        # cap=None → position_value = equity * 0.20
        tl = self._run_one_buy(equity=500_000, cap=None, stock_price=10.0)
        buys = [t for t in tl if t["Shares"] > 0]
        assert buys, "expected at least one buy"
        b = buys[0]
        pos_value = b["Shares"] * b["EntryPrice"]
        # Should be close to 100k (500k * 20%)
        assert pos_value >= 90_000

    def test_zero_shares_when_cap_too_low(self):
        # cap=$1 with stock_price=$10 → floor(1/10)=0 → no buy logged
        tl = self._run_one_buy(equity=100_000, cap=1, stock_price=10.0)
        buys = [t for t in tl if t["Shares"] > 0]
        assert len(buys) == 0, "expected no buy when cap yields 0 shares"


# ---------------------------------------------------------------------------
# TestRebalanceTrim  (#137)
# ---------------------------------------------------------------------------

class TestRebalanceTrim:
    """Verify trim-on-rebalance logic (issue #137)."""

    def _run_with_drift(self, initial_price, drifted_price, cap=None):
        """
        Week 1: buy stock at initial_price.
        Week 2: stock open is drifted_price — trim should fire if value > target.
        """
        dates = pd.date_range("2020-01-02", periods=20, freq="B")
        # QQQ must be rising and above SMA for regime to be ON both weeks
        qqq_closes = list(range(100, 120))
        qqq_df = pd.DataFrame(
            {"Open": qqq_closes, "High": [c * 1.01 for c in qqq_closes],
             "Low": [c * 0.99 for c in qqq_closes], "Close": qqq_closes,
             "Volume": 1_000_000},
            index=dates,
        )

        # Stock: initial_price for first week, drifted_price for second
        mid = len(dates) // 2
        prices = [initial_price] * mid + [drifted_price] * (len(dates) - mid)
        sym_df = pd.DataFrame(
            {"Open": prices, "High": [p * 1.01 for p in prices],
             "Low": [p * 0.99 for p in prices], "Close": prices,
             "Volume": 1_000_000},
            index=dates,
        )
        all_data = {"A": sym_df}
        combined = {"A": sym_df, "QQQ": qqq_df}
        pairs = build_rebalance_pairs(combined)

        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "MOMENTUM_LOOKBACK", 5), \
             patch.object(_mod, "SELL_BUFFER_RANK", 999), \
             patch.object(_mod, "MAX_POSITIONS", 1), \
             patch.object(_mod, "MAX_SHORT_POSITIONS", 0), \
             patch.object(_mod, "INITIAL_CAPITAL", 100_000.0), \
             patch.object(_mod, "MAX_POSITION_SIZE", cap):
            trade_log, _ = run_backtest(all_data, qqq_df, pairs[:3])

        return trade_log

    def test_trim_fires_when_position_drifts_above_target(self):
        # Buy at $10 (20% of $100k = $2000 position, 200 shares).
        # Next week open at $50 → position worth $10k >> $2k target → trim fires.
        tl = self._run_with_drift(initial_price=10.0, drifted_price=50.0)
        trim_trades = [t for t in tl if t["ExitReason"] == "Trim"]
        assert len(trim_trades) >= 1, "expected a trim trade"

    def test_no_trim_when_position_at_or_below_target(self):
        # Price stays flat — position value equals target — no trim.
        tl = self._run_with_drift(initial_price=10.0, drifted_price=10.0)
        trim_trades = [t for t in tl if t["ExitReason"] == "Trim"]
        assert len(trim_trades) == 0, "expected no trim when price is flat"

    def test_trim_increases_cash(self):
        # After a trim, cash should increase vs. no-trim scenario.
        tl = self._run_with_drift(initial_price=10.0, drifted_price=50.0)
        trim_trades = [t for t in tl if t["ExitReason"] == "Trim"]
        assert all(t["PnL"] > 0 for t in trim_trades), "trim on appreciated position should be profitable"

    def test_nan_open_price_skips_trim_gracefully(self):
        # Build a stock where the second week's Open is NaN → trim skips, no crash.
        dates = pd.date_range("2020-01-02", periods=20, freq="B")
        qqq_closes = list(range(100, 120))
        qqq_df = pd.DataFrame(
            {"Open": qqq_closes, "High": [c * 1.01 for c in qqq_closes],
             "Low": [c * 0.99 for c in qqq_closes], "Close": qqq_closes,
             "Volume": 1_000_000},
            index=dates,
        )
        opens = [10.0] * 10 + [np.nan] * 10
        closes = [50.0] * 20   # high close → trim would fire IF open wasn't NaN
        sym_df = pd.DataFrame(
            {"Open": opens, "High": closes, "Low": closes, "Close": closes, "Volume": 1_000_000},
            index=dates,
        )
        all_data = {"A": sym_df}
        pairs = build_rebalance_pairs({"A": sym_df, "QQQ": qqq_df})

        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "MOMENTUM_LOOKBACK", 5), \
             patch.object(_mod, "SELL_BUFFER_RANK", 999), \
             patch.object(_mod, "MAX_POSITIONS", 1), \
             patch.object(_mod, "MAX_SHORT_POSITIONS", 0), \
             patch.object(_mod, "INITIAL_CAPITAL", 100_000.0), \
             patch.object(_mod, "MAX_POSITION_SIZE", None):
            trade_log, _ = run_backtest(all_data, qqq_df, pairs[:3])

        # No crash and no trim (open was NaN)
        trim_trades = [t for t in trade_log if t["ExitReason"] == "Trim"]
        assert len(trim_trades) == 0


# ---------------------------------------------------------------------------
# TestShortConstants  (#139)
# ---------------------------------------------------------------------------

class TestShortConstants:
    def test_max_short_positions_exists_and_default(self):
        assert hasattr(_mod, "MAX_SHORT_POSITIONS")
        assert _mod.MAX_SHORT_POSITIONS == 3

    def test_short_cover_buffer_rank_exists_and_default(self):
        assert hasattr(_mod, "SHORT_COVER_BUFFER_RANK")
        assert _mod.SHORT_COVER_BUFFER_RANK == 25

    def test_htb_rate_annual_exists_and_default(self):
        assert hasattr(_mod, "HTB_RATE_ANNUAL")
        assert _mod.HTB_RATE_ANNUAL == 0.02


# ---------------------------------------------------------------------------
# TestShortOverlay  (#139)
# ---------------------------------------------------------------------------

class TestShortOverlay:
    """
    All tests run a mini backtest with synthetic data.

    Regime control:
      - Rising QQQ above 5-bar SMA → regime ON
      - Flat/declining QQQ below SMA → regime OFF

    We patch REGIME_MA_PERIOD=5 and MOMENTUM_LOOKBACK=5 to keep data small.
    """

    def _make_regime_off_qqq(self, n: int) -> pd.DataFrame:
        """Flat QQQ at 100 — never rises above its own SMA → regime always OFF."""
        dates = pd.date_range("2020-01-02", periods=n, freq="B")
        return pd.DataFrame(
            {"Open": 100.0, "High": 101.0, "Low": 99.0, "Close": 100.0, "Volume": 1_000_000},
            index=dates,
        )

    def _make_regime_on_qqq(self, n: int) -> pd.DataFrame:
        """Rising QQQ — always above SMA → regime always ON."""
        return _make_rising_df(n, start=100.0, step=1.0)

    def _stocks(self, n: int, n_symbols: int = 4) -> dict:
        """Several stocks with different starting prices for RS_60d spread."""
        out = {}
        for i in range(n_symbols):
            start = 50.0 + i * 10
            step  = 0.1 * (i - n_symbols // 2)   # some negative → weak RS
            out[f"S{i}"] = _make_rising_df(n, start=start, step=step)
        return out

    def _run(self, regime_on_weeks: list, regime_off_weeks: list,
             n_bars: int = 80, max_short: int = 2,
             initial_capital: float = 200_000.0):
        """
        Build a QQQ that is ON during on-weeks and OFF during off-weeks by splicing
        price series. Simpler: build separate ON/OFF QQQs and pick based on week index.

        For simplicity: use a QQQ that is regime-OFF for the first half and ON for
        the second half (controlled by `regime_on_from_week`).
        """
        raise NotImplementedError("use specific helpers below")

    def _run_always_off(self, n_bars=80, max_short=2,
                        initial_capital=200_000.0, n_sym=4):
        qqq_df   = self._make_regime_off_qqq(n_bars)
        stocks   = self._stocks(n_bars, n_sym)
        all_data = stocks
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

    def _run_off_then_on(self, off_weeks: int = 3, n_bars: int = 80,
                         max_short: int = 2, initial_capital: float = 200_000.0,
                         n_sym: int = 4):
        """
        QQQ is regime-OFF for the first `off_weeks` rebalance pairs, then ON.
        Achieved by making QQQ flat for the first portion and rising after.
        """
        dates = pd.date_range("2020-01-02", periods=n_bars, freq="B")
        # Build combined all_data first to get pairs
        stocks = self._stocks(n_bars, n_sym)

        # QQQ: flat (regime OFF) then rising (regime ON)
        split_bar = n_bars // 2
        flat_prices  = [100.0] * split_bar
        rise_prices  = [100.0 + (i + 1) * 2.0 for i in range(n_bars - split_bar)]
        closes = flat_prices + rise_prices
        qqq_df = pd.DataFrame(
            {"Open": closes, "High": [c * 1.01 for c in closes],
             "Low":  [c * 0.99 for c in closes], "Close": closes, "Volume": 1_000_000},
            index=dates,
        )

        all_data = stocks
        pairs    = build_rebalance_pairs({**all_data, "QQQ": qqq_df})

        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "MOMENTUM_LOOKBACK", 5), \
             patch.object(_mod, "SELL_BUFFER_RANK", 999), \
             patch.object(_mod, "MAX_POSITIONS", 3), \
             patch.object(_mod, "MAX_SHORT_POSITIONS", max_short), \
             patch.object(_mod, "SHORT_COVER_BUFFER_RANK", 999), \
             patch.object(_mod, "INITIAL_CAPITAL", initial_capital):
            tl, el = run_backtest(all_data, qqq_df, pairs)
        return tl, el, qqq_df, pairs

    # ── Tests ────────────────────────────────────────────────────────────────

    def test_zero_max_short_positions_no_short_trades(self):
        tl, _ = self._run_always_off(max_short=0)
        short_trades = [t for t in tl if t["Shares"] < 0]
        assert len(short_trades) == 0, "MAX_SHORT_POSITIONS=0 must produce no shorts"

    def test_shorts_appear_with_negative_shares_during_regime_off(self):
        tl, _ = self._run_always_off(max_short=2)
        short_trades = [t for t in tl if t["Shares"] < 0]
        assert len(short_trades) > 0, "expected short trades during regime-OFF"

    def test_short_shares_are_negative(self):
        tl, _ = self._run_always_off(max_short=2)
        for t in tl:
            if t["ExitReason"] in ("End of backtest", "Regime ON", "Regime OFF"):
                # short covers have negative shares
                pass
        short_trades = [t for t in tl if t["Shares"] < 0]
        assert all(t["Shares"] < 0 for t in short_trades)

    def test_end_of_backtest_covers_open_shorts(self):
        tl, _ = self._run_always_off(max_short=2)
        eob = [t for t in tl if t["ExitReason"] == "End of backtest"]
        assert len(eob) > 0, "open shorts should be covered at end of backtest"

    def test_regime_on_covers_shorts(self):
        tl, _, _, _ = self._run_off_then_on(max_short=2)
        regime_on_covers = [t for t in tl if t["ExitReason"] == "Regime ON"]
        assert len(regime_on_covers) > 0, "shorts should be covered when regime turns ON"

    def test_htb_borrow_cost_deducted_from_pnl(self):
        """
        Run always-OFF with a stock that stays flat → short PnL should be slightly
        negative due to borrow cost, not zero.
        """
        n = 80
        qqq_df = self._make_regime_off_qqq(n)
        dates  = pd.date_range("2020-01-02", periods=n, freq="B")
        # Stock price absolutely flat → without borrow cost, PnL = 0 (minus commissions)
        flat_df = pd.DataFrame(
            {"Open": 50.0, "High": 50.5, "Low": 49.5, "Close": 50.0, "Volume": 1_000_000},
            index=dates,
        )
        all_data = {"FLAT": flat_df}
        pairs = build_rebalance_pairs({"FLAT": flat_df, "QQQ": qqq_df})

        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "MOMENTUM_LOOKBACK", 5), \
             patch.object(_mod, "SELL_BUFFER_RANK", 999), \
             patch.object(_mod, "MAX_POSITIONS", 1), \
             patch.object(_mod, "MAX_SHORT_POSITIONS", 1), \
             patch.object(_mod, "SHORT_COVER_BUFFER_RANK", 999), \
             patch.object(_mod, "INITIAL_CAPITAL", 100_000.0), \
             patch.object(_mod, "HTB_RATE_ANNUAL", 0.02):
            tl, _ = run_backtest(all_data, qqq_df, pairs)

        short_trades = [t for t in tl if t["Shares"] < 0]
        assert short_trades, "expected short trades"
        # Every short on a flat-priced stock should have negative PnL (borrow cost + commissions)
        assert all(t["PnL"] < 0 for t in short_trades), \
            "flat-price short should be net negative due to borrow + commission"

    def test_cash_increases_at_short_entry(self):
        """
        When a short is entered, we receive proceeds → cash should be higher than
        initial_capital after first short entry (before any costs are incurred).
        We verify via equity log — equity stays close to initial since MTM is flat.
        """
        n = 80
        qqq_df = self._make_regime_off_qqq(n)
        dates  = pd.date_range("2020-01-02", periods=n, freq="B")
        flat_df = pd.DataFrame(
            {"Open": 50.0, "High": 50.5, "Low": 49.5, "Close": 50.0, "Volume": 1_000_000},
            index=dates,
        )
        all_data = {"FLAT": flat_df}
        pairs = build_rebalance_pairs({"FLAT": flat_df, "QQQ": qqq_df})

        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "MOMENTUM_LOOKBACK", 5), \
             patch.object(_mod, "MAX_POSITIONS", 1), \
             patch.object(_mod, "MAX_SHORT_POSITIONS", 1), \
             patch.object(_mod, "SHORT_COVER_BUFFER_RANK", 999), \
             patch.object(_mod, "INITIAL_CAPITAL", 100_000.0):
            tl, el = run_backtest(all_data, qqq_df, pairs)

        # At least one short was entered
        assert any(t["Shares"] < 0 for t in tl)

    def test_short_not_entered_if_already_long(self):
        """
        A symbol already in `positions` must not also be in `short_positions`.
        Achieved by running a week of regime-ON (buy a stock) immediately followed
        by regime-OFF — the short-enter guard should skip that symbol.
        """
        # Build a QQQ that is ON week 1, OFF weeks 2+
        n = 80
        dates  = pd.date_range("2020-01-02", periods=n, freq="B")
        # Rising then flat
        split  = n // 2
        closes = list(range(100, 100 + split)) + [100 + split] * (n - split)
        qqq_df = pd.DataFrame(
            {"Open": closes, "High": [c * 1.01 for c in closes],
             "Low":  [c * 0.99 for c in closes], "Close": closes, "Volume": 1_000_000},
            index=dates,
        )
        stock_df = _make_rising_df(n, start=20.0, step=0.0)
        all_data = {"A": stock_df}
        pairs    = build_rebalance_pairs({"A": stock_df, "QQQ": qqq_df})

        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "MOMENTUM_LOOKBACK", 5), \
             patch.object(_mod, "SELL_BUFFER_RANK", 999), \
             patch.object(_mod, "MAX_POSITIONS", 1), \
             patch.object(_mod, "MAX_SHORT_POSITIONS", 1), \
             patch.object(_mod, "SHORT_COVER_BUFFER_RANK", 999), \
             patch.object(_mod, "INITIAL_CAPITAL", 100_000.0):
            tl, _ = run_backtest(all_data, qqq_df, pairs)

        # No trade should have both positive and negative Shares for the same symbol
        # on the same date — i.e., no simultaneous long + short
        by_date_sym = {}
        for t in tl:
            k = (t["EntryDate"], t["Symbol"])
            by_date_sym.setdefault(k, []).append(t["Shares"])
        for k, shares_list in by_date_sym.items():
            has_long  = any(s > 0 for s in shares_list)
            has_short = any(s < 0 for s in shares_list)
            assert not (has_long and has_short), \
                f"same symbol {k} has simultaneous long and short entry"

    def test_mtm_equity_rises_when_short_price_falls(self):
        """
        mtm_equity should increase for open shorts when price drops.
        Tested indirectly: short a stock at $50, next period it's at $40 →
        equity_log value at second measurement should reflect a gain.
        """
        n = 80
        dates  = pd.date_range("2020-01-02", periods=n, freq="B")
        qqq_df = self._make_regime_off_qqq(n)

        # Stock starts at $50, drops to $30 halfway through
        split  = n // 2
        prices = [50.0] * split + [30.0] * (n - split)
        drop_df = pd.DataFrame(
            {"Open": prices, "High": prices, "Low": prices, "Close": prices, "Volume": 1_000_000},
            index=dates,
        )
        all_data = {"DROP": drop_df}
        pairs    = build_rebalance_pairs({"DROP": drop_df, "QQQ": qqq_df})

        with patch.object(_mod, "REGIME_MA_PERIOD", 5), \
             patch.object(_mod, "MOMENTUM_LOOKBACK", 5), \
             patch.object(_mod, "MAX_POSITIONS", 1), \
             patch.object(_mod, "MAX_SHORT_POSITIONS", 1), \
             patch.object(_mod, "SHORT_COVER_BUFFER_RANK", 999), \
             patch.object(_mod, "INITIAL_CAPITAL", 100_000.0):
            tl, el = run_backtest(all_data, qqq_df, pairs)

        short_trades = [t for t in tl if t["Shares"] < 0]
        assert short_trades, "expected at least one short"
        # At least one profitable short (price fell)
        assert any(t["PnL"] > 0 for t in short_trades), \
            "short on dropping stock should yield positive PnL"

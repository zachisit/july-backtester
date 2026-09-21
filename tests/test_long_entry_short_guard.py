"""
Regression test for issue #313 — the long entry loop did not check
``short_positions``.

The short entry guard is ``if symbol in positions or symbol in short_positions:
continue``, but the long entry guard was only ``if symbol in positions:
continue``. A signal of ``1`` emitted while a short (from an earlier ``-2``) is
still open therefore entered a long *on top of* the open short: a hedged double
position with doubled commissions/borrow, self-cancelling MTM, and two
overlapping trades the strategy never intended.

Per the documented convention (``-1`` = "exit long or cover short"), a ``1``
while short should be ignored (covers happen on ``<= -1``); it must not stack a
long. The fix mirrors the short-side guard onto the long entry.
"""

import pandas as pd
import pytest

import helpers.portfolio_simulations as ps
from helpers.portfolio_simulations import run_portfolio_simulation


def _frame(n=6, close=100.0):
    idx = pd.bdate_range("2024-01-02", periods=n)
    return pd.DataFrame(
        {"Open": close, "High": close * 1.01, "Low": close * 0.99,
         "Close": close, "Volume": 1_000_000.0, "ATR_14": 1.0},
        index=idx,
    )


def _patch(monkeypatch, execution_time="close"):
    # Pin every config key these tests depend on so a research-modified config.py
    # (e.g. exclude_open_positions=True realized-only mode) can't fail them
    # spuriously — the repo's mode-guard pattern.
    monkeypatch.setitem(ps.CONFIG, "execution_time", execution_time)
    monkeypatch.setitem(ps.CONFIG, "slippage_pct", 0.0)
    monkeypatch.setitem(ps.CONFIG, "exclude_open_positions", False)
    monkeypatch.setitem(ps.CONFIG, "position_sizing_method", "fixed")
    monkeypatch.setitem(ps.CONFIG, "entry_priority", "alphabetical")
    monkeypatch.setitem(ps.CONFIG, "volume_impact_coeff", 0.0)
    monkeypatch.setitem(ps.CONFIG, "max_pct_adv", 0.0)


def _run(sig_map, monkeypatch, stop_config=None, execution_time="close"):
    _patch(monkeypatch, execution_time)
    df = _frame()
    sig = pd.Series(0, index=df.index)
    for i, v in sig_map.items():
        sig.iloc[i] = v
    return run_portfolio_simulation(
        portfolio_data={"TEST": df}, signals={"TEST": sig},
        initial_capital=100_000.0, allocation_pct=0.5,
        spy_df=None, vix_df=None, tnx_df=None,
        stop_config=stop_config or {"type": "none"},
    )


class TestLongEntryShortGuard:
    def test_long_signal_while_short_open_does_not_stack_a_long(self, monkeypatch):
        # -2 short at bar1 (never covered); 1 long attempt at bar3 while short
        # is still open. The long must be skipped -> only the short exists.
        res = _run({1: -2, 3: 1}, monkeypatch)
        trades = res["trade_log"] if res else []
        longs = [t for t in trades if str(t["Trade"]).startswith("Long")]
        shorts = [t for t in trades if str(t["Trade"]).startswith("Short")]
        assert longs == [], f"a long was stacked on the open short: {longs}"
        assert len(shorts) == 1
        assert len(trades) == 1, f"exactly one trade expected, got {trades}"

    def test_long_signal_while_short_open_open_execution(self, monkeypatch):
        # The bug manifests under execution_time="open" too (fill is next bar's
        # open); the guard is resolved before signal_date, so it must hold here.
        res = _run({1: -2, 3: 1}, monkeypatch, execution_time="open")
        trades = res["trade_log"] if res else []
        assert [t for t in trades if str(t["Trade"]).startswith("Long")] == []

    def test_ignored_long_leaves_the_short_intact(self, monkeypatch):
        # The ignored 1-while-short must NOT cover the short (only <= -1 covers):
        # the short stays open and is marked to market at end of backtest.
        res = _run({1: -2, 3: 1}, monkeypatch)
        trades = res["trade_log"] if res else []
        shorts = [t for t in trades if str(t["Trade"]).startswith("Short")]
        longs = [t for t in trades if str(t["Trade"]).startswith("Long")]
        assert longs == []                       # second independent pin
        assert len(shorts) == 1
        assert shorts[0]["ExitReason"] == "End of Backtest"

    def test_minus_two_while_long_open_flips_not_stacks(self, monkeypatch):
        # Documented flip: -2 is <= -1, so it exits the open long first (exits run
        # before entries), then opens a short on the now-flat symbol. This is a
        # clean flip, not a simultaneous long+short — no guard change needed here.
        res = _run({1: 1, 3: -2}, monkeypatch)
        trades = res["trade_log"] if res else []
        assert any(str(t["Trade"]).startswith("Long") for t in trades)
        assert any(str(t["Trade"]).startswith("Short") for t in trades)
        # The long must have CLOSED at/after the flip bar, never overlapping the
        # short's whole life: its exit is not "End of Backtest".
        _long = next(t for t in trades if str(t["Trade"]).startswith("Long"))
        assert _long["ExitReason"] != "End of Backtest"

    def test_same_bar_stop_cover_frees_symbol_for_long_entry(self, monkeypatch):
        # A stop-cover (not a signal cover) on the SAME bar as a 1 must free the
        # symbol BEFORE the long entry loop, so the long can enter that bar. This
        # pins that the guard reads live short_positions (not a pre-cover
        # snapshot) — the key no-over-block guarantee.
        _patch(monkeypatch, "close")
        idx = pd.bdate_range("2024-01-02", periods=6)
        # short at bar1 (100); 5% stop = 105; bar3 spikes to 106 -> stop fires.
        close = [100.0, 100.0, 100.0, 100.0, 100.0, 100.0]
        high = [101.0, 101.0, 101.0, 106.0, 101.0, 101.0]
        df = pd.DataFrame(
            {"Open": close, "High": high, "Low": [c * 0.99 for c in close],
             "Close": close, "Volume": 1e6, "ATR_14": 1.0}, index=idx)
        sig = pd.Series(0, index=idx); sig.iloc[1] = -2; sig.iloc[3] = 1
        res = run_portfolio_simulation(
            portfolio_data={"TEST": df}, signals={"TEST": sig},
            initial_capital=100_000.0, allocation_pct=0.5,
            spy_df=None, vix_df=None, tnx_df=None,
            stop_config={"type": "percentage", "value": 0.05})
        trades = res["trade_log"] if res else []
        shorts = [t for t in trades if str(t["Trade"]).startswith("Short")]
        longs = [t for t in trades if str(t["Trade"]).startswith("Long")]
        assert len(shorts) == 1 and "Stop Loss" in shorts[0]["ExitReason"]
        assert len(longs) == 1, "long should enter the same bar the short stopped out"

    def test_short_on_one_symbol_does_not_block_long_on_another(self, monkeypatch):
        _patch(monkeypatch, "close")
        a, b = _frame(), _frame()
        siga = pd.Series(0, index=a.index); siga.iloc[1] = -2   # AAA short, held
        sigb = pd.Series(0, index=b.index); sigb.iloc[1] = 1    # BBB long, same bar
        res = run_portfolio_simulation(
            portfolio_data={"AAA": a, "BBB": b}, signals={"AAA": siga, "BBB": sigb},
            initial_capital=100_000.0, allocation_pct=0.5,
            spy_df=None, vix_df=None, tnx_df=None, stop_config={"type": "none"})
        trades = res["trade_log"] if res else []
        assert any(t["Symbol"] == "BBB" and str(t["Trade"]).startswith("Long") for t in trades)
        assert any(t["Symbol"] == "AAA" and str(t["Trade"]).startswith("Short") for t in trades)

    def test_flip_after_cover_still_allowed(self, monkeypatch):
        # A cover (-1) frees the symbol; a later long (1) may then enter. Exits
        # run before entries, so cover at bar3 then long at bar4 is a clean flip.
        res = _run({1: -2, 3: -1, 4: 1}, monkeypatch)
        trades = res["trade_log"] if res else []
        assert any(str(t["Trade"]).startswith("Short") for t in trades)
        assert any(str(t["Trade"]).startswith("Long") for t in trades)

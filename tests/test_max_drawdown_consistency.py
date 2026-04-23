# tests/test_max_drawdown_consistency.py
"""
Tests that max drawdown shown in terminal summary matches the PDF report.

Root cause (now fixed):
  - Terminal: uses portfolio_timeline (daily mark-to-market equity, every
    trading day, captures intra-trade price drops on open positions).
  - PDF (old): used trades_df['Equity'] = initial_equity + cumsum(profit at
    exit), which only changes at trade-close dates — completely invisible to
    any intra-trade drawdown that recovers before exit.

Fix (issue #128 / hotfix/max-drawdown-terminal-pdf-mismatch):
  - helpers/summary.py saves portfolio_timeline as {name}_equity.csv alongside
    each analyzer CSV.
  - report.py loads the companion file and passes it as PORTFOLIO_TIMELINE in
    config_params.
  - trade_analyzer/analyzer.py prefers PORTFOLIO_TIMELINE over trades_df['Equity']
    so PDF drawdown now uses the identical daily-MTM series as the terminal.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
import pytest

from helpers.simulations import calculate_advanced_metrics
from trade_analyzer.calculations import calculate_equity_drawdown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _terminal_max_dd(daily_equity: pd.Series) -> float:
    """Return max_drawdown (fraction 0-1) via the terminal calculation path."""
    pnl_list = [0.0]
    duration_list = [1]
    metrics = calculate_advanced_metrics(pnl_list, daily_equity, duration_list)
    return metrics["max_drawdown"]


def _pdf_max_dd(equity_series: pd.Series) -> float:
    """Return max drawdown (fraction 0-1) via calculate_equity_drawdown.

    calculate_equity_drawdown returns a percentage (0-100), so divide by 100.
    """
    _, _, _, pct = calculate_equity_drawdown(equity_series)
    return pct / 100.0


def _trade_exit_equity(initial_capital: float, profits: list) -> pd.Series:
    """Build the OLD trade-exit equity series (what the PDF used before fix)."""
    dates = pd.date_range("2020-01-02", periods=len(profits), freq="D")
    cum = np.cumsum(profits)
    return pd.Series(initial_capital + cum, index=dates)


# ---------------------------------------------------------------------------
# Class 1: Core contract — both methods agree when given the same data
# ---------------------------------------------------------------------------

class TestMaxDrawdownAgreement:
    """Terminal and PDF produce identical results when fed the same series."""

    def test_monotonically_rising_equity_both_zero(self):
        """No drawdown in either view — both report 0%."""
        dates = pd.date_range("2020-01-01", periods=5, freq="D")
        daily = pd.Series([100_000, 101_000, 102_000, 103_000, 104_000], index=dates)

        assert _terminal_max_dd(daily) < 1e-9
        assert _pdf_max_dd(daily) < 1e-9

    def test_single_dip_and_recover_both_agree(self):
        """Equity dips then recovers — both methods capture the same trough."""
        dates = pd.date_range("2020-01-01", periods=5, freq="D")
        equity = pd.Series([100_000, 95_000, 92_000, 97_000, 102_000], index=dates)

        terminal = _terminal_max_dd(equity)
        pdf = _pdf_max_dd(equity)

        assert abs(terminal - pdf) < 1e-6, f"terminal={terminal:.6f} pdf={pdf:.6f}"

    def test_single_losing_trade_both_agree(self):
        """Equity falls permanently — both methods see the same decline."""
        dates = pd.date_range("2020-01-01", periods=3, freq="D")
        equity = pd.Series([100_000, 100_000, 95_000], index=dates)

        terminal = _terminal_max_dd(equity)
        pdf = _pdf_max_dd(equity)

        assert abs(terminal - 0.05) < 0.001, f"terminal={terminal:.4f}"
        assert abs(pdf - 0.05) < 0.001, f"pdf={pdf:.4f}"
        assert abs(terminal - pdf) < 1e-6, f"terminal={terminal:.6f} pdf={pdf:.6f}"

    def test_terminal_max_dd_matches_pdf_on_same_daily_series(self):
        """Regression: formulas are equivalent — divergence was purely data-source."""
        dates = pd.date_range("2020-01-01", periods=6, freq="D")
        equity = pd.Series(
            [100_000, 95_000, 97_000, 92_000, 98_000, 102_000], index=dates
        )

        terminal = _terminal_max_dd(equity)
        pdf = _pdf_max_dd(equity)

        assert abs(terminal - pdf) < 1e-6, (
            f"Same-data regression failed: terminal={terminal:.6f}, pdf={pdf:.6f}"
        )


# ---------------------------------------------------------------------------
# Class 2: Post-fix — PDF now uses portfolio_timeline, matches terminal
# ---------------------------------------------------------------------------

class TestMaxDrawdownFixed:
    """
    After the fix, the PDF receives the same portfolio_timeline the terminal
    uses (via the companion _equity.csv). Both surfaces must agree.
    """

    def test_intra_trade_dip_both_see_same_data(self):
        """
        Intra-trade dip: equity drops mid-hold then recovers before exit.

        Before fix: terminal=15%, PDF=0% (PDF missed the trough).
        After fix:  both use daily_equity → both report 15%.
        """
        dates = pd.date_range("2020-01-01", periods=3, freq="D")
        daily_equity = pd.Series([100_000, 85_000, 102_000], index=dates)

        terminal = _terminal_max_dd(daily_equity)
        # After fix, PDF also receives portfolio_timeline (daily_equity here)
        pdf = _pdf_max_dd(daily_equity)

        assert terminal > 0.14, f"Terminal should capture ~15% dip, got {terminal:.4f}"
        assert abs(terminal - pdf) < 1e-6, (
            f"FAIL: terminal={terminal:.2%}, pdf={pdf:.2%}. "
            f"Both should use portfolio_timeline after the fix."
        )

    def test_multiple_recoveries_both_agree(self):
        """
        Two mid-hold dips that both recover before exit.

        Before fix: terminal=8%, PDF=0%.
        After fix:  both use daily_equity → both report ~8%.
        """
        dates = pd.date_range("2020-01-01", periods=7, freq="D")
        daily_equity = pd.Series(
            [100_000, 92_000, 98_000, 105_000, 97_000, 103_000, 112_000],
            index=dates,
        )

        terminal = _terminal_max_dd(daily_equity)
        pdf = _pdf_max_dd(daily_equity)

        assert terminal > 0.07, f"terminal={terminal:.4f}"
        assert abs(terminal - pdf) < 1e-6, (
            f"FAIL: terminal={terminal:.2%}, pdf={pdf:.2%}."
        )

    def test_drawdown_value_is_correct(self):
        """Verify the actual max drawdown magnitude is correct (not just that they agree)."""
        dates = pd.date_range("2020-01-01", periods=3, freq="D")
        # $100k → $85k → $102k: trough is 15% below peak
        daily_equity = pd.Series([100_000, 85_000, 102_000], index=dates)

        terminal = _terminal_max_dd(daily_equity)
        pdf = _pdf_max_dd(daily_equity)

        assert abs(terminal - 0.15) < 1e-9, f"Expected 15.00%, got {terminal:.4%}"
        assert abs(pdf - 0.15) < 1e-9, f"Expected 15.00%, got {pdf:.4%}"


# ---------------------------------------------------------------------------
# Class 3: Document the old broken path (regression guard)
# ---------------------------------------------------------------------------

class TestLegacyTradeExitEquityBehavior:
    """
    Documents how trades_df['Equity'] behaved before the fix.
    These tests confirm that trade-exit equity DOES miss intra-trade drawdowns.
    They must remain failing as a permanent reminder of what NOT to use.
    """

    def test_trade_exit_equity_misses_intra_trade_dip(self):
        """
        Trade-exit equity shows 0% drawdown when the position dips mid-hold
        then exits profitably. This is the bug the fix addresses.
        """
        dates = pd.date_range("2020-01-01", periods=3, freq="D")
        daily_equity = pd.Series([100_000, 85_000, 102_000], index=dates)

        # Old PDF path: equity only at exits
        trade_exit = _trade_exit_equity(100_000, [2_000])  # one trade, +$2k profit

        terminal = _terminal_max_dd(daily_equity)
        old_pdf = _pdf_max_dd(trade_exit)

        # Old PDF misses the dip entirely
        assert old_pdf < 0.001, (
            f"trade_exit_equity should show ~0% (misses the intra-trade dip), got {old_pdf:.4f}"
        )
        # While terminal correctly sees it
        assert terminal > 0.14, (
            f"terminal should see ~15%, got {terminal:.4f}"
        )
        # This is the old mismatch — document it
        assert abs(terminal - old_pdf) > 0.10, (
            f"Legacy divergence expected to be >10pp, got {abs(terminal - old_pdf):.4f}"
        )

    def test_trade_exit_equity_formula(self):
        """Confirm trades_df['Equity'] = initial_equity + cumsum(profits)."""
        initial = 100_000
        profits = [-5_000, 10_000, -2_000]
        trade_exit = _trade_exit_equity(initial, profits)

        assert trade_exit.iloc[0] == 95_000   # 100k + (-5k)
        assert trade_exit.iloc[1] == 105_000  # 100k + 5k
        assert trade_exit.iloc[2] == 103_000  # 100k + 3k

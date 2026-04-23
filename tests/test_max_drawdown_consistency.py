# tests/test_max_drawdown_consistency.py
"""
Tests that max drawdown shown in terminal summary matches the PDF report.

Root cause of the divergence:
  - Terminal: uses portfolio_timeline (daily mark-to-market equity, every
    trading day, captures intra-trade price drops on open positions).
  - PDF:      uses trades_df['Equity'] = initial_equity + cumsum(profit at exit),
              which only changes at trade close dates — completely invisible to
              any intra-trade drawdown that recovers before the exit.

Any strategy that holds a position that drops in value mid-hold then recovers
will report a LARGER max drawdown in the terminal than in the PDF.
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
    pnl_list = [0.0]      # content irrelevant for drawdown
    duration_list = [1]
    metrics = calculate_advanced_metrics(pnl_list, daily_equity, duration_list)
    return metrics["max_drawdown"]


def _pdf_max_dd(equity_series: pd.Series) -> float:
    """Return max drawdown (fraction 0-1) via the PDF calculation path.

    calculate_equity_drawdown returns a percentage (0-100), so divide by 100.
    """
    _, _, _, pct = calculate_equity_drawdown(equity_series)
    return pct / 100.0


def _trade_exit_equity(initial_capital: float, profits: list[float]) -> pd.Series:
    """Build the equity series the PDF sees: initial + cumulative profits at exit."""
    dates = pd.date_range("2020-01-02", periods=len(profits), freq="D")
    cum = np.cumsum(profits)
    return pd.Series(initial_capital + cum, index=dates)


# ---------------------------------------------------------------------------
# Class 1: Scenarios where both methods SHOULD agree
# ---------------------------------------------------------------------------

class TestMaxDrawdownAgreement:
    """Both methods agree when equity only changes at trade-close timestamps."""

    def test_monotonically_rising_equity_both_zero(self):
        """Steadily profitable — no drawdown in either view."""
        dates = pd.date_range("2020-01-01", periods=5, freq="D")
        daily = pd.Series([100_000, 101_000, 102_000, 103_000, 104_000], index=dates)
        trade_exit = _trade_exit_equity(100_000, [1_000, 1_000, 1_000, 1_000])

        assert _terminal_max_dd(daily) < 1e-9
        assert _pdf_max_dd(trade_exit) < 1e-9

    def test_single_losing_trade_both_agree(self):
        """One trade closes at a loss — both methods see the same drop."""
        dates = pd.date_range("2020-01-01", periods=3, freq="D")
        # Daily equity matches the trade-exit equity (no intra-trade dip beyond exit loss)
        daily = pd.Series([100_000, 100_000, 95_000], index=dates)
        trade_exit = _trade_exit_equity(100_000, [-5_000])

        terminal = _terminal_max_dd(daily)
        pdf = _pdf_max_dd(trade_exit)

        # Both should be ~5% drawdown
        assert abs(terminal - 0.05) < 0.001, f"terminal={terminal:.4f}"
        assert abs(pdf - 0.05) < 0.001, f"pdf={pdf:.4f}"
        # And they must agree with each other
        assert abs(terminal - pdf) < 0.001, f"terminal={terminal:.4f} pdf={pdf:.4f}"


# ---------------------------------------------------------------------------
# Class 2: Scenarios that expose the mismatch (intra-trade drawdowns)
# ---------------------------------------------------------------------------

class TestMaxDrawdownMismatch:
    """
    Demonstrate that the terminal and PDF report different max drawdowns
    when a position suffers an intra-trade drawdown that fully recovers
    before the trade closes.
    """

    def test_intra_trade_dip_terminal_larger_than_pdf(self):
        """
        Scenario:
          Day 0: $100k — open long position
          Day 1: position drops → portfolio MTM = $85k  (15% intra-trade DD)
          Day 2: position recovers, trade exits at +$2k  → $102k

        Terminal sees the Day 1 trough → max_drawdown ≈ 15%
        PDF only sees [$100k, $102k] at exit → max_drawdown = 0%
        """
        dates = pd.date_range("2020-01-01", periods=3, freq="D")
        daily_equity = pd.Series([100_000, 85_000, 102_000], index=dates)

        # PDF equity: only at the exit point (day 2), no day 1 trough visible
        trade_exit_equity = pd.Series(
            [100_000, 102_000],
            index=[dates[0], dates[2]],
        )

        terminal = _terminal_max_dd(daily_equity)
        pdf = _pdf_max_dd(trade_exit_equity)

        assert terminal > 0.14, (
            f"Terminal should capture ~15% intra-trade drawdown, got {terminal:.4f}"
        )
        assert pdf < 0.001, (
            f"PDF should see no drawdown (equity only rises at exits), got {pdf:.4f}"
        )

        # This assertion is the key one — it FAILS, confirming the reported bug
        assert abs(terminal - pdf) < 0.01, (
            f"MISMATCH: terminal max_drawdown={terminal:.2%} but "
            f"PDF max_equity_dd_pct={pdf:.2%}. "
            f"The terminal uses daily MTM portfolio_timeline; the PDF uses "
            f"trade-exit equity (initial_equity + cumsum(profit)) which misses "
            f"intra-trade price drops that recover before the exit."
        )

    def test_multiple_recoveries_terminal_larger(self):
        """
        Strategy with two trades, each with a mid-hold drawdown that recovers:
          Trade 1: enters $100k, dips to $92k, exits at $105k
          Trade 2: enters $105k, dips to $97k, exits at $112k

        Terminal sees two intra-trade dips; PDF only sees the two profitable exits.
        """
        dates = pd.date_range("2020-01-01", periods=7, freq="D")
        # Daily equity reflecting open-position MTM
        daily_equity = pd.Series(
            [100_000, 92_000, 98_000, 105_000, 97_000, 103_000, 112_000],
            index=dates,
        )

        # PDF equity: only at trade exits (day 3 and day 6)
        trade_exit_equity = pd.Series(
            [100_000, 105_000, 112_000],
            index=[dates[0], dates[3], dates[6]],
        )

        terminal = _terminal_max_dd(daily_equity)
        pdf = _pdf_max_dd(trade_exit_equity)

        # Terminal captures dips to $92k (~8%) and $97k/105k (~7.6%)
        assert terminal > 0.07, f"terminal={terminal:.4f}"
        # PDF sees only two profitable exits → no drawdown
        assert pdf < 0.001, f"pdf={pdf:.4f}"

        # Confirm mismatch exists — this assertion FAILS, exposing the bug
        assert abs(terminal - pdf) < 0.01, (
            f"MISMATCH: terminal={terminal:.2%}, pdf={pdf:.2%}. "
            f"Intra-trade drawdowns are invisible to the PDF report."
        )

    def test_terminal_max_dd_matches_pdf_on_same_daily_series(self):
        """
        When both methods operate on the SAME daily equity series, they agree.
        This test passes — it establishes that the formulas themselves are
        equivalent; the divergence is purely a data-source problem.
        """
        dates = pd.date_range("2020-01-01", periods=6, freq="D")
        equity = pd.Series(
            [100_000, 95_000, 97_000, 92_000, 98_000, 102_000], index=dates
        )

        terminal = _terminal_max_dd(equity)
        pdf = _pdf_max_dd(equity)

        # Both run on the same input → must agree within floating-point tolerance
        assert abs(terminal - pdf) < 1e-6, (
            f"Same-data check failed: terminal={terminal:.6f}, pdf={pdf:.6f}"
        )

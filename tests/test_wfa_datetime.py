# tests/test_wfa_datetime.py
"""
Unit tests for WFA datetime handling (Phase 4 of #55).

Tests that WFA split and evaluation functions correctly handle datetime strings
in ExitDate fields (both date-only "2024-01-15" and datetime "2024-01-15T10:30:00").
"""

import os
import sys

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.wfa import split_trades, _annualised_return


# ---------------------------------------------------------------------------
# Test Class 1: Split Trades with Datetime
# ---------------------------------------------------------------------------

class TestSplitTradesDatetime:
    """Test split_trades() with intraday datetime strings."""

    def test_split_trades_with_date_only_strings(self):
        """split_trades should handle date-only ExitDate strings."""
        trade_log = [
            {"ExitDate": "2024-01-01", "Profit": 100},
            {"ExitDate": "2024-01-02", "Profit": 50},
            {"ExitDate": "2024-01-03", "Profit": -25},
        ]
        split_date = "2024-01-02"

        is_trades, oos_trades = split_trades(trade_log, split_date)

        assert len(is_trades) == 1  # Only first trade is before split
        assert is_trades[0]["ExitDate"] == "2024-01-01"
        assert len(oos_trades) == 2
        assert oos_trades[0]["ExitDate"] == "2024-01-02"
        assert oos_trades[1]["ExitDate"] == "2024-01-03"

    def test_split_trades_with_intraday_exit_dates(self):
        """split_trades should handle intraday ExitDate strings with time component."""
        trade_log = [
            {"ExitDate": "2024-01-01T10:30:00", "Profit": 100},
            {"ExitDate": "2024-01-02T14:00:00", "Profit": 50},
            {"ExitDate": "2024-01-03T11:15:00", "Profit": -25},
        ]
        split_date = "2024-01-02T12:00:00"

        is_trades, oos_trades = split_trades(trade_log, split_date)

        # First trade is before split (10:30 < 12:00 on 01-01)
        assert len(is_trades) == 1
        assert is_trades[0]["ExitDate"] == "2024-01-01T10:30:00"

        # Second trade (14:00 on 01-02) is after split (12:00 on 01-02)
        # Third trade is also after split
        assert len(oos_trades) == 2
        assert oos_trades[0]["ExitDate"] == "2024-01-02T14:00:00"
        assert oos_trades[1]["ExitDate"] == "2024-01-03T11:15:00"

    def test_split_trades_mixed_date_and_datetime_formats(self):
        """split_trades should handle mixed date and datetime formats."""
        trade_log = [
            {"ExitDate": "2024-01-01", "Profit": 100},  # Date only
            {"ExitDate": "2024-01-02T14:00:00", "Profit": 50},  # Datetime
            {"ExitDate": "2024-01-03", "Profit": -25},  # Date only
        ]
        split_date = "2024-01-02"

        is_trades, oos_trades = split_trades(trade_log, split_date)

        # First trade (2024-01-01 00:00:00) is before split (2024-01-02 00:00:00)
        assert len(is_trades) == 1

        # Second trade (2024-01-02 14:00:00) is after split (2024-01-02 00:00:00)
        # Third trade is also after split
        assert len(oos_trades) == 2

    def test_split_trades_exact_boundary(self):
        """Trade at exact split timestamp should go to OOS."""
        trade_log = [
            {"ExitDate": "2024-01-01T10:00:00", "Profit": 100},
            {"ExitDate": "2024-01-02T12:00:00", "Profit": 50},  # Exact split
            {"ExitDate": "2024-01-03T14:00:00", "Profit": -25},
        ]
        split_date = "2024-01-02T12:00:00"

        is_trades, oos_trades = split_trades(trade_log, split_date)

        assert len(is_trades) == 1  # Only first trade is strictly before
        assert len(oos_trades) == 2  # Split-time trade and after go to OOS


# ---------------------------------------------------------------------------
# Test Class 2: Annualised Return with Datetime
# ---------------------------------------------------------------------------

class TestAnnualisedReturnDatetime:
    """Test _annualised_return() with datetime strings."""

    def test_annualised_return_with_date_only_strings(self):
        """_annualised_return should handle date-only ExitDate strings."""
        trades = [
            {"ExitDate": "2024-01-01", "Profit": 100},
            {"ExitDate": "2024-12-31", "Profit": 200},
        ]
        initial_capital = 10000.0

        result = _annualised_return(trades, initial_capital)

        assert result is not None
        assert isinstance(result, float)
        # Sanity check: return should be positive (net profit = 300)
        assert result > 0

    def test_annualised_return_with_intraday_exit_dates(self):
        """_annualised_return should handle intraday ExitDate strings."""
        trades = [
            {"ExitDate": "2024-01-01T09:30:00", "Profit": 100},
            {"ExitDate": "2024-12-31T15:00:00", "Profit": 200},
        ]
        initial_capital = 10000.0

        result = _annualised_return(trades, initial_capital)

        assert result is not None
        assert isinstance(result, float)
        # Sanity check: return should be positive
        assert result > 0

    def test_annualised_return_same_day_intraday_trades(self):
        """_annualised_return should return None for same-day trades (< 1 day span)."""
        trades = [
            {"ExitDate": "2024-01-01T09:30:00", "Profit": 100},
            {"ExitDate": "2024-01-01T15:00:00", "Profit": 50},
        ]
        initial_capital = 10000.0

        result = _annualised_return(trades, initial_capital)

        # Same day (0 days) should return None
        assert result is None

    def test_annualised_return_negative_total_pnl(self):
        """_annualised_return should return None when strategy went bust."""
        trades = [
            {"ExitDate": "2024-01-01", "Profit": -12000},  # Lost more than capital
        ]
        initial_capital = 10000.0

        result = _annualised_return(trades, initial_capital)

        # Strategy went bust (total equity <= 0) → CAGR undefined
        assert result is None


# ---------------------------------------------------------------------------
# Test Class 3: Rolling WFA Datetime Handling
# ---------------------------------------------------------------------------

class TestRollingWfaDatetime:
    """Test evaluate_rolling_wfa() datetime handling."""

    def test_rolling_wfa_with_intraday_trades(self):
        """evaluate_rolling_wfa should handle intraday ExitDate strings."""
        from helpers.wfa_rolling import evaluate_rolling_wfa

        trade_log = [
            {"ExitDate": "2024-01-01T10:00:00", "Profit": 100},
            {"ExitDate": "2024-02-01T11:00:00", "Profit": 50},
            {"ExitDate": "2024-03-01T12:00:00", "Profit": 75},
            {"ExitDate": "2024-04-01T13:00:00", "Profit": 60},
            {"ExitDate": "2024-05-01T14:00:00", "Profit": 80},
            {"ExitDate": "2024-06-01T15:00:00", "Profit": 90},
        ]

        # Create fold dates (3 folds covering the period)
        fold_dates = [
            ("2024-02-01", "2024-04-01"),
            ("2024-04-01", "2024-06-01"),
            ("2024-06-01", "2024-08-01"),
        ]

        initial_capital = 10000.0
        min_fold_trades = 1  # Low threshold for this test

        result = evaluate_rolling_wfa(trade_log, fold_dates, initial_capital, min_fold_trades)

        # Should produce a verdict (not crash)
        assert "wfa_rolling_verdict" in result
        assert isinstance(result["wfa_rolling_verdict"], str)

# tests/test_wfa_rolling.py
"""
Unit tests for rolling multi-fold WFA (SECTION 11).

Covers:
  TestConfigDefaults   — wfa_folds and wfa_min_fold_trades config keys / defaults
  TestGetFoldDates     — fold boundary generation
  TestEvaluateRollingWfa — scoring logic: pass, fail, N/A cases
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import CONFIG
from helpers.wfa_rolling import get_fold_dates, evaluate_rolling_wfa


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trades(start_date: str, end_date: str, n: int, profit: float = 100.0):
    """Create *n* trades spread evenly between start_date and end_date."""
    from datetime import date, timedelta
    start = date.fromisoformat(start_date)
    end   = date.fromisoformat(end_date)
    total_days = (end - start).days
    step = max(1, total_days // n)
    trades = []
    for i in range(n):
        d = start + timedelta(days=i * step)
        if d > end:
            break
        trades.append({"ExitDate": d.isoformat(), "Profit": profit})
    return trades


# ---------------------------------------------------------------------------
# TestConfigDefaults
# ---------------------------------------------------------------------------

class TestConfigDefaults:

    def test_wfa_folds_default_none(self):
        """CONFIG['wfa_folds'] must default to None (rolling WFA disabled out-of-the-box)."""
        assert CONFIG["wfa_folds"] is None

    def test_wfa_min_fold_trades_default_five(self):
        """CONFIG['wfa_min_fold_trades'] must default to 5."""
        assert CONFIG["wfa_min_fold_trades"] == 5


# ---------------------------------------------------------------------------
# TestGetFoldDates
# ---------------------------------------------------------------------------

class TestGetFoldDates:

    def test_k2_returns_two_folds(self):
        """k=2 must return a list with exactly 2 tuples."""
        folds = get_fold_dates("2010-01-01", "2020-01-01", k=2)
        assert len(folds) == 2

    def test_folds_cover_full_period(self):
        """First fold starts at actual_start; last fold ends at actual_end."""
        actual_start = "2010-01-01"
        actual_end   = "2020-01-01"
        folds = get_fold_dates(actual_start, actual_end, k=4)
        assert folds[0][0]  == actual_start
        assert folds[-1][1] == actual_end

    def test_folds_are_chronological(self):
        """Each oos_start must equal the previous oos_end (no gaps, no overlaps)."""
        folds = get_fold_dates("2000-01-01", "2020-01-01", k=5)
        for i in range(1, len(folds)):
            assert folds[i][0] == folds[i - 1][1], (
                f"Gap/overlap between fold {i-1} and {i}: "
                f"{folds[i-1][1]} vs {folds[i][0]}"
            )

    def test_k_less_than_2_raises(self):
        """get_fold_dates(k=1) must raise ValueError."""
        with pytest.raises(ValueError):
            get_fold_dates("2010-01-01", "2020-01-01", k=1)


# ---------------------------------------------------------------------------
# TestEvaluateRollingWfa
# ---------------------------------------------------------------------------

class TestEvaluateRollingWfa:

    def test_all_pass_folds_returns_pass(self):
        """
        When every scorable fold passes evaluate_wfa, the verdict must be 'Pass'.

        Build a 3-fold scenario where each OOS window contains >= 5 profitable
        trades and the IS window also contains profitable trades.
        """
        # Dense profitable trades spanning 2000-2020
        all_trades = _make_trades("2000-01-01", "2020-01-01", n=200, profit=100.0)
        fold_dates = get_fold_dates("2000-01-01", "2020-01-01", k=3)
        result = evaluate_rolling_wfa(all_trades, fold_dates, 100_000, min_fold_trades=5)
        assert result["wfa_rolling_verdict"] == "Pass"

    def test_majority_fail_folds_returns_fail(self):
        """
        When the majority of scorable folds fail (IS+, OOS-), the verdict must be 'Fail'.

        k=3 folds over 2000-2018:
          fold 0 OOS (2000-2006): trades here appear as fold 0 OOS and as IS for folds 1+.
                                  IS is empty → evaluate_wfa returns 'Pass'.
          fold 1 OOS (2006-2012): IS (profitable 2000-2005), OOS (losing) → 'Likely Overfitted'.
          fold 2 OOS (2012-2018): IS (profitable net), OOS (losing) → 'Likely Overfitted'.
        1 / 3 pass < 60 % → overall 'Fail'.
        """
        # 20 profitable trades in 2001-2005 → these are fold 0 OOS and IS for folds 1+
        good_2001_2005 = _make_trades("2001-01-01", "2005-12-31", n=20, profit=1000.0)
        # 10 losing trades in 2006-2011 → fold 1 OOS
        bad_2006_2011  = _make_trades("2006-06-01", "2011-06-01", n=10, profit=-100.0)
        # 10 losing trades in 2012-2017 → fold 2 OOS
        bad_2012_2017  = _make_trades("2012-06-01", "2017-06-01", n=10, profit=-100.0)

        all_trades = good_2001_2005 + bad_2006_2011 + bad_2012_2017
        fold_dates = get_fold_dates("2000-01-01", "2018-01-01", k=3)

        result = evaluate_rolling_wfa(all_trades, fold_dates, 100_000, min_fold_trades=5)
        assert result["wfa_rolling_verdict"] == "Fail"

    def test_insufficient_scorable_folds_returns_na(self):
        """
        Fewer than 2 scorable folds (OOS count < min_fold_trades) → 'N/A'.
        """
        # Only 3 trades in the whole log — no fold will have >= 5 OOS trades
        sparse_trades = _make_trades("2000-01-01", "2020-01-01", n=3, profit=100.0)
        fold_dates = get_fold_dates("2000-01-01", "2020-01-01", k=4)
        result = evaluate_rolling_wfa(sparse_trades, fold_dates, 100_000, min_fold_trades=5)
        assert result["wfa_rolling_verdict"] == "N/A"

    def test_empty_trade_log_returns_na(self):
        """Empty trade_log must return wfa_rolling_verdict == 'N/A'."""
        fold_dates = get_fold_dates("2010-01-01", "2020-01-01", k=3)
        result = evaluate_rolling_wfa([], fold_dates, 100_000, min_fold_trades=5)
        assert result["wfa_rolling_verdict"] == "N/A"

    def test_empty_fold_dates_returns_na(self):
        """Empty fold_dates list must return wfa_rolling_verdict == 'N/A'."""
        trades = _make_trades("2010-01-01", "2020-01-01", n=50)
        result = evaluate_rolling_wfa(trades, [], 100_000, min_fold_trades=5)
        assert result["wfa_rolling_verdict"] == "N/A"

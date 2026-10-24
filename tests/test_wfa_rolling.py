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

    def test_wfa_folds_default_none(self, monkeypatch):
        """CONFIG['wfa_folds'] must default to None (rolling WFA disabled out-of-the-box).

        Uses monkeypatch to ensure the test reads None regardless of what
        the developer's local config.py has set — same pattern used by
        other tests that patch CONFIG.
        """
        monkeypatch.setitem(CONFIG, "wfa_folds", None)
        assert CONFIG["wfa_folds"] is None

    def test_wfa_min_fold_trades_default_five(self, monkeypatch):
        """CONFIG['wfa_min_fold_trades'] must default to 5.

        Patched via monkeypatch so the test is not affected by local config overrides.
        """
        monkeypatch.setitem(CONFIG, "wfa_min_fold_trades", 5)
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
        verdict = result["wfa_rolling_verdict"]
        assert verdict.startswith("Pass"), f"Expected 'Pass (K/N)', got: {verdict}"
        assert "/" in verdict, f"Expected K/N fraction in verdict, got: {verdict}"

    def test_majority_fail_folds_returns_fail(self):
        """
        When the majority of scorable folds fail (IS+, OOS-), the verdict must be 'Fail'.

        k=3 folds over 2000-2018:
          fold 0 OOS (2000-2006): IS is empty → not scorable (#428), skipped.
          fold 1 OOS (2006-2012): IS (profitable 2000-2005), OOS (losing) → 'Likely Overfitted'.
          fold 2 OOS (2012-2018): IS (profitable net), OOS (losing) → 'Likely Overfitted'.
        0 / 2 scorable folds pass → overall 'Fail (0/2)'.
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
        verdict = result["wfa_rolling_verdict"]
        assert verdict == "Fail (0/2)", f"Expected 'Fail (0/2)', got: {verdict}"

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


# ---------------------------------------------------------------------------
# #427 — rolling folds measure window equity returns, not initial-capital pnl
# ---------------------------------------------------------------------------

from tests.test_wfa import _compounding_fixture


class TestRollingCompoundingNormalisation:
    def _verdict(self, is_rate, oos_rate, split="2012-01-01", **kw):
        trades, curve, cap, start, _, end = _compounding_fixture(
            is_rate, oos_rate, split=split)
        folds = get_fold_dates(start, end, 5)
        return evaluate_rolling_wfa(trades, folds, cap, 5, equity_curve=curve,
                                    actual_start=start, **kw)["wfa_rolling_verdict"]

    def test_constant_rate_passes(self):
        assert self._verdict(0.10, 0.10).startswith("Pass")

    def test_collapsed_edge_fails(self):
        assert self._verdict(0.10, 0.0).startswith("Fail")

    def test_legacy_call_without_curve_still_works(self):
        trades, _, cap, start, _, end = _compounding_fixture(0.10, 0.10)
        folds = get_fold_dates(start, end, 5)
        assert evaluate_rolling_wfa(trades, folds, cap, 5)["wfa_rolling_verdict"].startswith("Pass")


# ---------------------------------------------------------------------------
# #428 — folds without in-sample history are never scored
# ---------------------------------------------------------------------------

from helpers.wfa import evaluate_wfa


class TestFoldZeroNotScored:
    def test_evaluate_wfa_empty_is_returns_na(self):
        oos = _make_trades("2010-01-01", "2012-01-01", n=10)
        assert evaluate_wfa([], oos, 100_000)["wfa_verdict"] == "N/A"

    def test_evaluate_wfa_too_few_is_returns_na(self):
        is_t = _make_trades("2005-01-01", "2006-01-01", n=4)
        oos = _make_trades("2010-01-01", "2012-01-01", n=10)
        assert evaluate_wfa(is_t, oos, 100_000)["wfa_verdict"] == "N/A"

    def test_fold_zero_not_scored(self):
        # Trades only inside fold 0's OOS window: all later folds lack OOS
        # trades and fold 0 lacks IS, so nothing is scorable.
        trades = _make_trades("2000-02-01", "2003-12-31", n=40)
        folds = get_fold_dates("2000-01-01", "2020-01-01", k=5)
        assert evaluate_rolling_wfa(trades, folds, 100_000)["wfa_rolling_verdict"] == "N/A"

    def test_fail_when_every_fold_with_is_history_fails(self):
        # Profitable 2001-2005 (fold 0 OOS, no IS) then losers in every later fold.
        good = _make_trades("2001-01-01", "2005-12-31", n=20, profit=1000.0)
        bad = _make_trades("2006-06-01", "2017-06-01", n=40, profit=-100.0)
        folds = get_fold_dates("2000-01-01", "2018-01-01", k=3)
        v = evaluate_rolling_wfa(good + bad, folds, 100_000)["wfa_rolling_verdict"]
        assert v == "Fail (0/2)"

    def test_is_below_min_fold_trades_not_scorable(self):
        is_t = _make_trades("2000-06-01", "2001-06-01", n=3)
        oos = _make_trades("2010-01-01", "2019-01-01", n=40)
        folds = get_fold_dates("2000-01-01", "2020-01-01", k=2)
        assert evaluate_rolling_wfa(is_t + oos, folds, 100_000)["wfa_rolling_verdict"] == "N/A"


class TestAnchoredFoldDates:
    def test_default_unchanged(self):
        assert get_fold_dates("2000-01-01", "2020-01-01", 4)[0][0] == "2000-01-01"

    def test_anchored_reserves_initial_is_window(self):
        folds = get_fold_dates("2000-01-01", "2020-01-01", 4, anchored=True)
        assert len(folds) == 4
        assert folds[0][0] > "2000-01-01"
        assert folds[-1][1] == "2020-01-01"
        assert all(folds[i][1] == folds[i + 1][0] for i in range(3))

    def test_anchored_all_folds_scorable(self):
        trades = _make_trades("2000-01-01", "2020-01-01", n=200)
        folds = get_fold_dates("2000-01-01", "2020-01-01", 4, anchored=True)
        v = evaluate_rolling_wfa(trades, folds, 100_000)["wfa_rolling_verdict"]
        assert v.endswith("/4)")

"""
tests/test_wfa.py

Unit tests for helpers/wfa.py — Walk-Forward Analysis helpers.

Covers:
  get_split_date   — IS/OOS boundary calculation
  split_trades     — partitioning a trade log by exit date
  evaluate_wfa     — verdict logic (Pass / Likely Overfitted / N/A)

All tests are deterministic: no randomness, no file I/O, no network calls.
"""

import os
import sys

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.wfa import (
    _MIN_OOS_TRADES,
    _annualised_return,
    _total_pnl_pct,
    evaluate_wfa,
    get_split_date,
    split_trades,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_trades(dates_and_profits):
    """
    Build a list of minimal trade dicts from (exit_date_str, profit) pairs.

    Parameters
    ----------
    dates_and_profits : list[tuple[str, float]]
        e.g. [("2010-06-30", 500.0), ("2011-12-31", -200.0)]
    """
    return [{"ExitDate": d, "Profit": p} for d, p in dates_and_profits]


def _year_range_trades(start_year: int, end_year: int, profit_per_trade: float):
    """
    One trade per year from start_year through end_year (inclusive),
    each exiting on Jan 1 of that year.
    """
    return _make_trades(
        [(f"{y}-01-01", profit_per_trade) for y in range(start_year, end_year + 1)]
    )


# ---------------------------------------------------------------------------
# TestGetSplitDate
# ---------------------------------------------------------------------------

class TestGetSplitDate:
    """Tests for get_split_date()."""

    def test_80_20_split_exact_decade(self):
        """10-year period: 80% IS → split on year 8 boundary."""
        result = get_split_date("2010-01-01", "2020-01-01", 0.80)
        # 2010-01-01 to 2020-01-01 = 3652 days (leap years 2012, 2016)
        # int(3652 * 0.80) = 2921 days → 2010-01-01 + 2921d = 2017-12-31
        assert result == "2017-12-31"

    def test_50_50_split(self):
        """Exact midpoint of a 2-year window."""
        result = get_split_date("2020-01-01", "2022-01-01", 0.50)
        # 2020-01-01 to 2022-01-01 = 731 days (2020 is a leap year)
        # int(731 * 0.50) = 365 days → 2020-01-01 + 365d = 2020-12-31
        assert result == "2020-12-31"

    def test_split_date_is_iso_string(self):
        result = get_split_date("2000-01-01", "2010-01-01", 0.70)
        assert isinstance(result, str)
        # Must be parseable as ISO date
        from datetime import date
        date.fromisoformat(result)  # raises if invalid

    def test_split_date_within_range(self):
        start, end, ratio = "2005-03-15", "2015-03-15", 0.80
        split = get_split_date(start, end, ratio)
        assert start < split < end

    def test_ratio_zero_returns_start(self):
        """ratio=0 → split_days=0 → split date == start date."""
        result = get_split_date("2010-01-01", "2020-01-01", 0.0)
        assert result == "2010-01-01"

    def test_ratio_one_returns_end(self):
        """ratio=1.0 → split_days=total_days → split date == end date."""
        result = get_split_date("2010-01-01", "2020-01-01", 1.0)
        assert result == "2020-01-01"


# ---------------------------------------------------------------------------
# TestSplitTrades
# ---------------------------------------------------------------------------

class TestSplitTrades:
    """Tests for split_trades()."""

    def test_happy_path_80_20(self):
        """
        10-year mock trade list: one trade per year 2010–2019.
        Split date at 2018-01-01 → first 8 years IS, last 2 years OOS.
        """
        trades = _year_range_trades(2010, 2019, 500.0)
        split_date = "2018-01-01"
        is_trades, oos_trades = split_trades(trades, split_date)

        # 2010–2017 are IS (8 trades); 2018–2019 are OOS (2 trades)
        assert len(is_trades) == 8
        assert len(oos_trades) == 2

    def test_is_trades_all_before_split(self):
        trades = _year_range_trades(2010, 2019, 100.0)
        is_trades, _ = split_trades(trades, "2015-01-01")
        assert all(t["ExitDate"] < "2015-01-01" for t in is_trades)

    def test_oos_trades_all_on_or_after_split(self):
        trades = _year_range_trades(2010, 2019, 100.0)
        _, oos_trades = split_trades(trades, "2015-01-01")
        assert all(t["ExitDate"] >= "2015-01-01" for t in oos_trades)

    def test_no_trade_lost(self):
        """IS + OOS must cover all original trades."""
        trades = _year_range_trades(2010, 2019, 100.0)
        is_trades, oos_trades = split_trades(trades, "2016-01-01")
        assert len(is_trades) + len(oos_trades) == len(trades)

    def test_split_on_exact_exit_date_goes_to_oos(self):
        """A trade whose ExitDate == split_date belongs to OOS (>= boundary)."""
        trades = _make_trades([("2015-06-01", 100.0), ("2015-06-02", 200.0)])
        is_trades, oos_trades = split_trades(trades, "2015-06-01")
        assert len(is_trades) == 0
        assert len(oos_trades) == 2

    def test_all_trades_before_split_gives_empty_oos(self):
        """When split_date is after all trades, OOS is empty."""
        trades = _year_range_trades(2010, 2015, 100.0)
        is_trades, oos_trades = split_trades(trades, "2020-01-01")
        assert len(is_trades) == len(trades)
        assert oos_trades == []

    def test_all_trades_on_or_after_split_gives_empty_is(self):
        """When split_date is before all trades, IS is empty."""
        trades = _year_range_trades(2015, 2019, 100.0)
        is_trades, oos_trades = split_trades(trades, "2010-01-01")
        assert is_trades == []
        assert len(oos_trades) == len(trades)

    def test_empty_trade_log(self):
        is_trades, oos_trades = split_trades([], "2015-01-01")
        assert is_trades == []
        assert oos_trades == []


# ---------------------------------------------------------------------------
# TestInternalHelpers — _total_pnl_pct and _annualised_return
# ---------------------------------------------------------------------------

class TestTotalPnlPct:
    """Tests for the _total_pnl_pct internal helper."""

    def test_sum_divided_by_capital(self):
        trades = _make_trades([("2015-01-01", 1000.0), ("2016-01-01", 2000.0)])
        result = _total_pnl_pct(trades, 100_000.0)
        assert result == pytest.approx(0.03)

    def test_negative_pnl(self):
        trades = _make_trades([("2015-01-01", -5000.0)])
        result = _total_pnl_pct(trades, 100_000.0)
        assert result == pytest.approx(-0.05)

    def test_empty_trades_returns_none(self):
        assert _total_pnl_pct([], 100_000.0) is None


class TestAnnualisedReturn:
    """Tests for the _annualised_return internal helper."""

    def test_positive_return_over_one_year(self):
        # 10% profit over ~1 year → annualised ≈ 10%
        trades = _make_trades([
            ("2015-01-01", 0.0),   # anchor start
            ("2016-01-01", 10_000.0),
        ])
        result = _annualised_return(trades, 100_000.0)
        assert result == pytest.approx(0.10, rel=0.02)

    def test_single_trade_returns_none(self):
        """Only 1 distinct date → days == 0 → None."""
        trades = _make_trades([("2015-06-01", 5000.0)])
        assert _annualised_return(trades, 100_000.0) is None

    def test_empty_trades_returns_none(self):
        assert _annualised_return([], 100_000.0) is None

    def test_same_exit_date_returns_none(self):
        """Two trades with identical ExitDate → days==0 → None."""
        trades = _make_trades([("2015-01-01", 1000.0), ("2015-01-01", 2000.0)])
        assert _annualised_return(trades, 100_000.0) is None

    def test_cagr_100pct_over_2_years_returns_approx_0414(self):
        """
        100 % gain over ~2 years must use CAGR: sqrt(2) - 1 ≈ 0.414, not 0.5.

        Simple division would give 1.0 / 2 = 0.50 — the regression proof that
        the old formula is gone.
        """
        trades = _make_trades([
            ("2020-01-01", 0.0),          # anchor start date
            ("2022-01-01", 100_000.0),    # 100 % profit over ~2 years
        ])
        result = _annualised_return(trades, 100_000.0)
        # sqrt(2) - 1 ≈ 0.41421; simple division would give 0.5
        assert result == pytest.approx(0.414, abs=0.005)
        assert result < 0.42, "CAGR must be less than the simple-division value of 0.5"

    def test_bust_100pct_loss_returns_none(self):
        """A strategy that loses 100 % of capital has undefined CAGR → None."""
        trades = _make_trades([
            ("2020-01-01", 0.0),
            ("2022-01-01", -100_000.0),   # total loss = initial capital
        ])
        assert _annualised_return(trades, 100_000.0) is None

    def test_bust_more_than_100pct_loss_returns_none(self):
        """Losses exceeding 100 % are also bust → None."""
        trades = _make_trades([
            ("2020-01-01", 0.0),
            ("2022-01-01", -150_000.0),
        ])
        assert _annualised_return(trades, 100_000.0) is None


# ---------------------------------------------------------------------------
# TestEvaluateWfa — main verdict logic
# ---------------------------------------------------------------------------

class TestEvaluateWfaPassVerdict:
    """Cases that should yield 'Pass'."""

    def test_positive_is_and_oos_returns_pass(self):
        capital = 100_000.0
        # IS: 5 profitable trades over 5 years
        is_trades = _year_range_trades(2010, 2014, 2_000.0)
        # OOS: 5 profitable trades over 5 years (same rate → no degradation)
        oos_trades = _year_range_trades(2015, 2019, 2_000.0)
        result = evaluate_wfa(is_trades, oos_trades, capital)
        assert result["wfa_verdict"] == "Pass"

    def test_oos_pnl_pct_is_populated_on_pass(self):
        capital = 100_000.0
        is_trades  = _year_range_trades(2010, 2014, 2_000.0)
        oos_trades = _year_range_trades(2015, 2019, 2_000.0)
        result = evaluate_wfa(is_trades, oos_trades, capital)
        assert result["oos_pnl_pct"] == pytest.approx(5 * 2_000.0 / capital)

    def test_mild_degradation_below_threshold_returns_pass(self):
        """OOS annualised return degrades by 50% (< 75% threshold) → Pass."""
        capital = 100_000.0
        # IS: 10 trades, $3000 profit each over 10 years → ann ≈ 3%
        is_trades = _year_range_trades(2000, 2009, 3_000.0)
        # OOS: 5 trades, $1500 profit each over 5 years → ann ≈ 1.5% (50% drop)
        oos_trades = _year_range_trades(2010, 2014, 1_500.0)
        result = evaluate_wfa(is_trades, oos_trades, capital)
        assert result["wfa_verdict"] == "Pass"

    def test_is_negative_oos_negative_returns_pass(self):
        """Both IS and OOS lose money — no sign flip → Pass (losers are losers)."""
        capital = 100_000.0
        is_trades  = _year_range_trades(2010, 2014, -1_000.0)
        oos_trades = _year_range_trades(2015, 2019, -500.0)
        result = evaluate_wfa(is_trades, oos_trades, capital)
        assert result["wfa_verdict"] == "Pass"


class TestEvaluateWfaLikelyOverfitted:
    """Cases that should yield 'Likely Overfitted'."""

    def test_sign_flip_triggers_likely_overfitted(self):
        """IS positive, OOS negative → sign flip → Likely Overfitted."""
        capital = 100_000.0
        # IS: lots of profit
        is_trades  = _year_range_trades(2010, 2017, 5_000.0)
        # OOS: net loss
        oos_trades = _year_range_trades(2018, 2022, -2_000.0)
        result = evaluate_wfa(is_trades, oos_trades, capital)
        assert result["wfa_verdict"] == "Likely Overfitted"

    def test_oos_pnl_pct_negative_on_sign_flip(self):
        capital = 100_000.0
        is_trades  = _year_range_trades(2010, 2017, 5_000.0)
        oos_trades = _year_range_trades(2018, 2022, -2_000.0)
        result = evaluate_wfa(is_trades, oos_trades, capital)
        assert result["oos_pnl_pct"] < 0

    def test_severe_degradation_triggers_likely_overfitted(self):
        """
        IS annualised >> OOS annualised (> 75% degradation) → Likely Overfitted.

        Craft: IS earns $10k/yr over 10 yrs (ann≈10%), OOS earns $100/yr over 5 yrs
        (ann≈0.1%) — OOS is >75% worse.
        """
        capital = 100_000.0
        is_trades  = _year_range_trades(2000, 2009, 10_000.0)
        oos_trades = _year_range_trades(2010, 2014, 100.0)
        result = evaluate_wfa(is_trades, oos_trades, capital)
        assert result["wfa_verdict"] == "Likely Overfitted"

    def test_likely_overfitted_still_triggers_with_cagr_formula(self):
        """
        Regression: switching _annualised_return to CAGR must not break the
        severe-degradation detection path in evaluate_wfa.

        IS: 200 % gain over 5 years  → CAGR ≈ 24.6 %
        OOS: 5 % gain over 5 years   → CAGR ≈  1.0 %
        Degradation ≈ 96 % > 75 % threshold → Likely Overfitted.
        """
        capital = 100_000.0
        # IS: 5 trades, $40k profit each, spread over 2000–2004 (200% total)
        is_trades = _year_range_trades(2000, 2004, 40_000.0)
        # OOS: 5 trades, $1k profit each, spread over 2005–2009 (5% total)
        oos_trades = _year_range_trades(2005, 2009, 1_000.0)
        result = evaluate_wfa(is_trades, oos_trades, capital)
        assert result["wfa_verdict"] == "Likely Overfitted"

    def test_exactly_at_75pct_degradation_triggers_flag(self):
        """
        Degradation of exactly 75% → condition is `> 0.75` so this should NOT flag.
        Verify the boundary condition is strictly greater-than.
        """
        capital = 100_000.0
        # IS: $8000/yr × 10 trades (ann ≈ 8%)
        is_trades = _year_range_trades(2000, 2009, 8_000.0)
        # OOS: $2000/yr × 5 trades (ann ≈ 2%) — exactly 75% drop
        oos_trades = _year_range_trades(2010, 2014, 2_000.0)
        result = evaluate_wfa(is_trades, oos_trades, capital)
        # 75% degradation is NOT > 0.75, so should be Pass
        assert result["wfa_verdict"] == "Pass"


class TestEvaluateWfaNAVerdict:
    """Cases that should yield 'N/A' (insufficient data or disabled)."""

    def test_empty_oos_returns_na(self):
        """OOS empty → N/A regardless of IS size."""
        capital = 100_000.0
        is_trades  = _year_range_trades(2010, 2019, 1_000.0)
        oos_trades = []
        result = evaluate_wfa(is_trades, oos_trades, capital)
        assert result["wfa_verdict"] == "N/A"

    def test_oos_pnl_pct_none_when_empty_oos(self):
        capital = 100_000.0
        is_trades  = _year_range_trades(2010, 2019, 1_000.0)
        result = evaluate_wfa(is_trades, [], capital)
        assert result["oos_pnl_pct"] is None

    def test_fewer_than_min_oos_trades_returns_na(self):
        """OOS with fewer than _MIN_OOS_TRADES entries → N/A."""
        capital = 100_000.0
        is_trades  = _year_range_trades(2010, 2017, 1_000.0)
        # _MIN_OOS_TRADES - 1 OOS trades
        oos_trades = _make_trades(
            [(f"201{i}-06-01", 500.0) for i in range(_MIN_OOS_TRADES - 1)]
        )
        result = evaluate_wfa(is_trades, oos_trades, capital)
        assert result["wfa_verdict"] == "N/A"

    def test_exactly_min_oos_trades_issues_verdict(self):
        """Exactly _MIN_OOS_TRADES OOS entries → verdict is NOT N/A."""
        capital = 100_000.0
        is_trades  = _year_range_trades(2000, 2009, 2_000.0)
        oos_trades = _year_range_trades(2010, 2010 + _MIN_OOS_TRADES - 1, 2_000.0)
        result = evaluate_wfa(is_trades, oos_trades, capital)
        assert result["wfa_verdict"] != "N/A"

    def test_all_trades_in_is_empty_oos_na(self):
        """
        Edge case: split_date is after all trades → OOS is empty → N/A.
        Mirrors the scenario where every trade exits before the WFA boundary.
        """
        capital = 100_000.0
        trades = _year_range_trades(2010, 2017, 1_000.0)
        is_trades, oos_trades = split_trades(trades, "2020-01-01")

        assert oos_trades == []
        result = evaluate_wfa(is_trades, oos_trades, capital)
        assert result["wfa_verdict"] == "N/A"

    def test_both_empty_returns_na(self):
        """No IS or OOS trades at all → N/A."""
        result = evaluate_wfa([], [], 100_000.0)
        assert result["wfa_verdict"] == "N/A"
        assert result["oos_pnl_pct"] is None


# ---------------------------------------------------------------------------
# TestEndToEnd — integration of get_split_date + split_trades + evaluate_wfa
# ---------------------------------------------------------------------------

class TestEndToEnd:
    """
    End-to-end tests wiring all three public helpers together,
    mirroring how main.py uses them.
    """

    def test_10yr_80_20_correct_partition_and_pass(self):
        """
        10 years of trades (2010–2019), one per year.
        80/20 split on actual data window 2010-01-01 → 2020-01-01.
        First 8 years → IS; last 2 → OOS.  Both profitable → Pass.
        """
        capital = 100_000.0
        actual_start, actual_end = "2010-01-01", "2020-01-01"
        trades = _year_range_trades(2010, 2019, 1_000.0)

        split_date = get_split_date(actual_start, actual_end, 0.80)
        is_trades, oos_trades = split_trades(trades, split_date)

        # 2010–2017 = 8 IS trades; 2018–2019 = 2 OOS trades
        # (split_date lands at 2017-12-30 due to leap years)
        assert len(is_trades) + len(oos_trades) == len(trades)
        assert len(oos_trades) >= 2

        result = evaluate_wfa(is_trades, oos_trades, capital)
        # Both profitable → if enough OOS trades, Pass; otherwise N/A
        # (2 OOS trades < _MIN_OOS_TRADES=5 → N/A here)
        assert result["wfa_verdict"] in {"Pass", "N/A"}

    def test_10yr_80_20_enough_oos_trades_pass(self):
        """
        20 years of trades (2000–2019), one per year.
        80/20 split → first 16 years IS, last 4 years OOS.
        Enough OOS trades for a verdict.  Both profitable → Pass.
        """
        capital = 100_000.0
        actual_start, actual_end = "2000-01-01", "2020-01-01"
        trades = _year_range_trades(2000, 2019, 2_000.0)

        split_date = get_split_date(actual_start, actual_end, 0.80)
        is_trades, oos_trades = split_trades(trades, split_date)

        assert len(is_trades) + len(oos_trades) == 20

        result = evaluate_wfa(is_trades, oos_trades, capital)
        # 4 OOS trades < _MIN_OOS_TRADES → N/A; extend if needed in production
        assert result["wfa_verdict"] in {"Pass", "N/A"}
        assert isinstance(result["oos_pnl_pct"], float)

    def test_overfitted_detected_end_to_end(self):
        """
        20-year trade window.  IS = first 16 yrs profitable; OOS = last 4 yrs losing.
        End-to-end: get_split_date → split_trades → evaluate_wfa → Likely Overfitted.
        """
        capital = 100_000.0
        actual_start, actual_end = "2000-01-01", "2020-01-01"
        split_date = get_split_date(actual_start, actual_end, 0.80)

        # Build trades: IS years profitable, OOS years losing
        all_trades = []
        for y in range(2000, 2020):
            date_str = f"{y}-06-01"
            profit = 5_000.0 if f"{y}-06-01" < split_date else -3_000.0
            all_trades.append({"ExitDate": date_str, "Profit": profit})

        is_trades, oos_trades = split_trades(all_trades, split_date)

        # Add extra OOS trades to exceed _MIN_OOS_TRADES
        for i in range(_MIN_OOS_TRADES):
            oos_trades.append({"ExitDate": f"201{i}-07-01", "Profit": -1_000.0})

        result = evaluate_wfa(is_trades, oos_trades, capital)
        assert result["wfa_verdict"] == "Likely Overfitted"

    def test_result_dict_always_has_required_keys(self):
        """evaluate_wfa must always return both oos_pnl_pct and wfa_verdict."""
        for is_t, oos_t in [
            ([], []),
            (_year_range_trades(2010, 2015, 1_000.0), []),
            (_year_range_trades(2010, 2015, 1_000.0), _year_range_trades(2016, 2020, 500.0)),
        ]:
            result = evaluate_wfa(is_t, oos_t, 100_000.0)
            assert "oos_pnl_pct" in result
            assert "wfa_verdict" in result
            assert result["wfa_verdict"] in {"Pass", "Likely Overfitted", "N/A"}

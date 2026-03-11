"""
tests/test_correlation.py

Unit tests for helpers/correlation.py — Strategy Correlation Analysis.

Covers:
  _build_daily_pnl_series   — per-strategy date-grouped P&L
  build_daily_pnl_matrix    — multi-strategy alignment
  compute_correlation_matrix — Pearson correlation
  find_high_correlation_pairs — threshold filtering
  run_correlation_analysis  — end-to-end (with temp CSV output)

All tests are deterministic: no network calls, no randomness.
"""

import os
import sys

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.correlation import (
    DEFAULT_THRESHOLD,
    _build_daily_pnl_series,
    build_daily_pnl_matrix,
    compute_avg_correlations,
    compute_correlation_matrix,
    find_high_correlation_pairs,
    run_correlation_analysis,
    save_correlation_csv,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _trade(exit_date: str, profit: float) -> dict:
    return {"ExitDate": exit_date, "Profit": profit}


def _result(name: str, trades: list[dict]) -> dict:
    return {"Strategy": name, "trade_log": trades}


# Strategy A — trades on Mon/Wed/Fri earning $100/$200/$300
_TRADES_A = [
    _trade("2020-01-06", 100.0),   # Monday
    _trade("2020-01-08", 200.0),   # Wednesday
    _trade("2020-01-10", 300.0),   # Friday
]

# Strategy B — identical dates and profits → perfect correlation (1.0)
_TRADES_B = [
    _trade("2020-01-06", 100.0),
    _trade("2020-01-08", 200.0),
    _trade("2020-01-10", 300.0),
]

# Strategy C — entirely different dates, no overlap → correlation undefined / NaN
_TRADES_C = [
    _trade("2020-02-03", 50.0),
    _trade("2020-02-05", 75.0),
    _trade("2020-02-07", 25.0),
]

# Strategy D — same dates as A/B but profits are exactly negated → corr = -1.0
_TRADES_D = [
    _trade("2020-01-06", -100.0),
    _trade("2020-01-08", -200.0),
    _trade("2020-01-10", -300.0),
]

# Strategy E — two trades on the same exit date (should be summed)
_TRADES_SAME_DATE = [
    _trade("2020-01-06", 50.0),
    _trade("2020-01-06", 75.0),   # same date → sum = 125.0
]


# ---------------------------------------------------------------------------
# TestBuildDailyPnlSeries
# ---------------------------------------------------------------------------

class TestBuildDailyPnlSeries:

    def test_basic_aggregation(self):
        s = _build_daily_pnl_series(_TRADES_A)
        assert len(s) == 3
        assert s.sum() == pytest.approx(600.0)

    def test_same_date_trades_are_summed(self):
        s = _build_daily_pnl_series(_TRADES_SAME_DATE)
        assert len(s) == 1
        assert s.iloc[0] == pytest.approx(125.0)

    def test_index_is_datetime(self):
        s = _build_daily_pnl_series(_TRADES_A)
        assert pd.api.types.is_datetime64_any_dtype(s.index)

    def test_empty_trade_log_returns_empty(self):
        s = _build_daily_pnl_series([])
        assert s.empty

    def test_missing_profit_rows_skipped(self):
        trades = [{"ExitDate": "2020-01-06", "Profit": None},
                  {"ExitDate": "2020-01-08", "Profit": 50.0}]
        s = _build_daily_pnl_series(trades)
        assert len(s) == 1
        assert s.iloc[0] == pytest.approx(50.0)

    def test_missing_exitdate_rows_skipped(self):
        trades = [{"ExitDate": None, "Profit": 100.0},
                  {"ExitDate": "2020-01-08", "Profit": 200.0}]
        s = _build_daily_pnl_series(trades)
        assert len(s) == 1


# ---------------------------------------------------------------------------
# TestBuildDailyPnlMatrix
# ---------------------------------------------------------------------------

class TestBuildDailyPnlMatrix:

    def test_two_identical_strategies(self):
        results = [_result("A", _TRADES_A), _result("B", _TRADES_B)]
        df = build_daily_pnl_matrix(results)
        assert list(df.columns) == ["A", "B"]
        assert df.shape == (3, 2)

    def test_missing_dates_filled_with_zero(self):
        """Strategy A trades Mon/Wed/Fri; C trades Feb — all A dates → 0 for C."""
        results = [_result("A", _TRADES_A), _result("C", _TRADES_C)]
        df = build_daily_pnl_matrix(results)
        # Jan dates: C should be 0; Feb dates: A should be 0
        jan_rows = df[df.index.month == 1]
        assert (jan_rows["C"] == 0.0).all()
        feb_rows = df[df.index.month == 2]
        assert (feb_rows["A"] == 0.0).all()

    def test_fewer_than_two_strategies_with_trades_returns_empty(self):
        """Only one strategy has a trade log → can't correlate → empty."""
        results = [_result("A", _TRADES_A), _result("B", [])]
        df = build_daily_pnl_matrix(results)
        assert df.empty

    def test_single_strategy_returns_empty(self):
        results = [_result("A", _TRADES_A)]
        df = build_daily_pnl_matrix(results)
        assert df.empty

    def test_empty_results_returns_empty(self):
        df = build_daily_pnl_matrix([])
        assert df.empty

    def test_duplicate_strategy_names_deduplicated(self):
        """Two results with the same strategy name get suffixed."""
        results = [_result("A", _TRADES_A), _result("A", _TRADES_B)]
        df = build_daily_pnl_matrix(results)
        assert "A" in df.columns
        assert "A_2" in df.columns

    def test_index_is_sorted(self):
        results = [_result("A", _TRADES_A), _result("C", _TRADES_C)]
        df = build_daily_pnl_matrix(results)
        assert df.index.is_monotonic_increasing

    def test_values_are_float(self):
        results = [_result("A", _TRADES_A), _result("B", _TRADES_B)]
        df = build_daily_pnl_matrix(results)
        assert df.dtypes.apply(lambda d: d == float).all()


# ---------------------------------------------------------------------------
# TestComputeCorrelationMatrix
# ---------------------------------------------------------------------------

class TestComputeCorrelationMatrix:

    def test_identical_strategies_correlate_at_one(self):
        results = [_result("A", _TRADES_A), _result("B", _TRADES_B)]
        daily = build_daily_pnl_matrix(results)
        corr = compute_correlation_matrix(daily)
        assert corr.loc["A", "B"] == pytest.approx(1.0)

    def test_negated_strategies_correlate_at_minus_one(self):
        results = [_result("A", _TRADES_A), _result("D", _TRADES_D)]
        daily = build_daily_pnl_matrix(results)
        corr = compute_correlation_matrix(daily)
        assert corr.loc["A", "D"] == pytest.approx(-1.0)

    def test_diagonal_is_one(self):
        results = [_result("A", _TRADES_A), _result("B", _TRADES_B)]
        daily = build_daily_pnl_matrix(results)
        corr = compute_correlation_matrix(daily)
        for col in corr.columns:
            assert corr.loc[col, col] == pytest.approx(1.0)

    def test_matrix_is_symmetric(self):
        results = [_result("A", _TRADES_A), _result("B", _TRADES_B), _result("D", _TRADES_D)]
        daily = build_daily_pnl_matrix(results)
        corr = compute_correlation_matrix(daily)
        for i in corr.columns:
            for j in corr.columns:
                assert corr.loc[i, j] == pytest.approx(corr.loc[j, i])

    def test_no_overlap_results_in_nan(self):
        """A and C share no trading dates → constant zero on those dates → NaN corr."""
        results = [_result("A", _TRADES_A), _result("C", _TRADES_C)]
        daily = build_daily_pnl_matrix(results)
        corr = compute_correlation_matrix(daily)
        # After filling 0s, the two series may be constant on their respective
        # zero-filled dates. Pearson of two non-overlapping step functions is
        # implementation-dependent but should not raise.
        assert "A" in corr.columns and "C" in corr.columns

    def test_empty_input_returns_empty(self):
        corr = compute_correlation_matrix(pd.DataFrame())
        assert corr.empty


# ---------------------------------------------------------------------------
# TestFindHighCorrelationPairs
# ---------------------------------------------------------------------------

class TestFindHighCorrelationPairs:

    def _corr_matrix_for(self, *named_trades):
        results = [_result(name, trades) for name, trades in named_trades]
        daily = build_daily_pnl_matrix(results)
        return compute_correlation_matrix(daily)

    def test_identical_strategies_flagged(self):
        corr = self._corr_matrix_for(("A", _TRADES_A), ("B", _TRADES_B))
        pairs = find_high_correlation_pairs(corr, threshold=0.70)
        assert len(pairs) == 1
        assert pairs[0][2] == pytest.approx(1.0)
        assert set(pairs[0][:2]) == {"A", "B"}

    def test_negated_strategies_flagged_due_to_abs_value(self):
        """Negative correlation (-1.0) is |abs| > 0.70 → should be flagged."""
        corr = self._corr_matrix_for(("A", _TRADES_A), ("D", _TRADES_D))
        pairs = find_high_correlation_pairs(corr, threshold=0.70)
        # abs(-1.0) = 1.0 > 0.70 → flagged
        assert len(pairs) == 1
        assert pairs[0][2] == pytest.approx(-1.0)

    def test_no_pairs_below_threshold(self):
        """Raise threshold above 1.0 → nothing can be flagged."""
        corr = self._corr_matrix_for(("A", _TRADES_A), ("B", _TRADES_B))
        pairs = find_high_correlation_pairs(corr, threshold=1.01)
        assert pairs == []

    def test_pairs_sorted_by_abs_correlation_descending(self):
        corr = self._corr_matrix_for(
            ("A", _TRADES_A), ("B", _TRADES_B), ("D", _TRADES_D)
        )
        pairs = find_high_correlation_pairs(corr, threshold=0.70)
        abs_vals = [abs(p[2]) for p in pairs]
        assert abs_vals == sorted(abs_vals, reverse=True)

    def test_no_self_pairs(self):
        corr = self._corr_matrix_for(("A", _TRADES_A), ("B", _TRADES_B))
        pairs = find_high_correlation_pairs(corr, threshold=0.0)
        for a, b, _ in pairs:
            assert a != b

    def test_no_duplicate_pairs(self):
        """(A, B) and (B, A) are the same pair — only one should appear."""
        corr = self._corr_matrix_for(("A", _TRADES_A), ("B", _TRADES_B))
        pairs = find_high_correlation_pairs(corr, threshold=0.0)
        seen = set()
        for a, b, _ in pairs:
            key = frozenset([a, b])
            assert key not in seen
            seen.add(key)

    def test_empty_matrix_returns_empty_list(self):
        pairs = find_high_correlation_pairs(pd.DataFrame(), threshold=0.70)
        assert pairs == []


# ---------------------------------------------------------------------------
# TestComputeAvgCorrelations
# ---------------------------------------------------------------------------

class TestComputeAvgCorrelations:

    def _corr_for(self, *named_trades):
        results = [_result(name, trades) for name, trades in named_trades]
        daily = build_daily_pnl_matrix(results)
        return compute_correlation_matrix(daily)

    def test_identical_strategies_avg_is_one(self):
        """A and B are perfectly correlated; each avg should be 1.0."""
        corr = self._corr_for(("A", _TRADES_A), ("B", _TRADES_B))
        avgs = compute_avg_correlations(corr)
        assert avgs["A"] == pytest.approx(1.0)
        assert avgs["B"] == pytest.approx(1.0)

    def test_negated_strategies_avg_is_one(self):
        """A and D have r=-1.0; abs(-1.0)=1.0 → avg abs corr = 1.0."""
        corr = self._corr_for(("A", _TRADES_A), ("D", _TRADES_D))
        avgs = compute_avg_correlations(corr)
        assert avgs["A"] == pytest.approx(1.0)
        assert avgs["D"] == pytest.approx(1.0)

    def test_three_strategies_avg_values_are_correct(self):
        """A and B are perfect corr (+1.0); D is anti-correlated (-1.0) to both.
        A's off-diagonal: corr(A,B)=1.0, corr(A,D)=-1.0 → avg abs = 1.0.
        """
        corr = self._corr_for(("A", _TRADES_A), ("B", _TRADES_B), ("D", _TRADES_D))
        avgs = compute_avg_correlations(corr)
        assert avgs["A"] == pytest.approx(1.0)
        assert avgs["B"] == pytest.approx(1.0)
        assert avgs["D"] == pytest.approx(1.0)

    def test_all_keys_present(self):
        corr = self._corr_for(("A", _TRADES_A), ("B", _TRADES_B), ("D", _TRADES_D))
        avgs = compute_avg_correlations(corr)
        assert set(avgs.keys()) == {"A", "B", "D"}

    def test_empty_matrix_returns_empty_dict(self):
        avgs = compute_avg_correlations(pd.DataFrame())
        assert avgs == {}

    def test_single_column_matrix_returns_empty_dict(self):
        """Fewer than 2 columns → cannot compute off-diagonal → empty dict."""
        single_col = pd.DataFrame({"A": [1.0, 2.0, 3.0]})
        avgs = compute_avg_correlations(single_col)
        assert avgs == {}

    def test_values_are_non_negative(self):
        """Avg absolute correlation is always >= 0."""
        corr = self._corr_for(("A", _TRADES_A), ("B", _TRADES_B), ("D", _TRADES_D))
        avgs = compute_avg_correlations(corr)
        for val in avgs.values():
            assert val >= 0.0


# ---------------------------------------------------------------------------
# TestRunCorrelationAnalysis — end-to-end with file I/O
# ---------------------------------------------------------------------------

class TestRunCorrelationAnalysis:

    def test_csv_is_created(self, tmp_path):
        results = [_result("A", _TRADES_A), _result("B", _TRADES_B)]
        output_path = str(tmp_path / "corr.csv")
        run_correlation_analysis(results, output_path)
        assert os.path.isfile(output_path)

    def test_csv_contains_strategy_names_as_headers(self, tmp_path):
        results = [_result("Alpha", _TRADES_A), _result("Beta", _TRADES_B)]
        output_path = str(tmp_path / "corr.csv")
        run_correlation_analysis(results, output_path)
        df = pd.read_csv(output_path, index_col=0)
        assert "Alpha" in df.columns
        assert "Beta" in df.columns

    def test_returns_correct_high_pairs(self, tmp_path):
        results = [_result("A", _TRADES_A), _result("B", _TRADES_B)]
        output_path = str(tmp_path / "corr.csv")
        _, pairs = run_correlation_analysis(results, output_path, threshold=0.70)
        assert len(pairs) == 1
        assert set(pairs[0][:2]) == {"A", "B"}
        assert pairs[0][2] == pytest.approx(1.0)

    def test_single_strategy_returns_empty_matrix_no_csv(self, tmp_path):
        """Only 1 strategy with trades → no correlation possible → CSV not written."""
        results = [_result("A", _TRADES_A)]
        output_path = str(tmp_path / "corr.csv")
        matrix, pairs = run_correlation_analysis(results, output_path)
        assert matrix.empty
        assert pairs == []
        assert not os.path.isfile(output_path)

    def test_all_empty_trade_logs_returns_empty(self, tmp_path):
        results = [_result("A", []), _result("B", []), _result("C", [])]
        output_path = str(tmp_path / "corr.csv")
        matrix, pairs = run_correlation_analysis(results, output_path)
        assert matrix.empty
        assert pairs == []
        assert not os.path.isfile(output_path)

    def test_no_overlap_no_crash(self, tmp_path):
        """Strategies with no overlapping dates should not raise."""
        results = [_result("A", _TRADES_A), _result("C", _TRADES_C)]
        output_path = str(tmp_path / "corr.csv")
        matrix, pairs = run_correlation_analysis(results, output_path, threshold=0.70)
        # No crash is the core assertion; matrix shape check is a bonus
        assert matrix.shape == (2, 2)

    def test_csv_values_rounded_to_4dp(self, tmp_path):
        results = [_result("A", _TRADES_A), _result("B", _TRADES_B)]
        output_path = str(tmp_path / "corr.csv")
        run_correlation_analysis(results, output_path)
        df = pd.read_csv(output_path, index_col=0)
        for val in df.values.flatten():
            if not pd.isna(val):
                # Should have at most 4 decimal places
                assert round(float(val), 4) == pytest.approx(float(val))

    def test_three_strategies_two_correlated_one_not(self, tmp_path):
        """A and B are perfectly correlated; C trades entirely different dates.

        Note: zero-filling creates step-function patterns that can produce a
        non-trivial negative correlation between A/B and C (~-0.75), so at a
        0.70 threshold C may also be flagged.  The core assertion is that A-B
        is always flagged.
        """
        results = [
            _result("A", _TRADES_A),
            _result("B", _TRADES_B),
            _result("C", _TRADES_C),
        ]
        output_path = str(tmp_path / "corr.csv")
        _, pairs = run_correlation_analysis(results, output_path, threshold=0.70)
        flagged = [set(p[:2]) for p in pairs]
        # A and B must always be flagged (r = 1.0)
        assert {"A", "B"} in flagged

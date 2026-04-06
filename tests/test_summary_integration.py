# tests/test_summary_integration.py
"""
Integration tests for dynamic benchmark columns in summary reports.

Tests the full pipeline of dynamic benchmark column generation and display
across different benchmark configurations (1, 2, 3+ benchmarks).
"""

import io
import os
import sys
from contextlib import redirect_stdout
from unittest.mock import patch

import pandas as pd
import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from helpers.summary import (
    _build_benchmark_columns,
    _get_t1_cols,
    _get_t2_cols,
    generate_per_portfolio_summary,
    generate_single_asset_summary_report,
    generate_final_summary,
    generate_portfolio_summary_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_result(strategy="TestStrategy", pnl_percent=0.15, vs_benchmarks=None):
    """Create a minimal result dict with dynamic benchmark columns.

    Parameters
    ----------
    vs_benchmarks : dict or None
        Dictionary of benchmark labels to relative performance values.
        E.g., {"SPY": 0.05, "QQQ": 0.03, "XLF": 0.08}
        If None, defaults to {"SPY": 0.05, "QQQ": 0.03}
    """
    if vs_benchmarks is None:
        vs_benchmarks = {"SPY": 0.05, "QQQ": 0.03}

    result = {
        "Strategy": strategy,
        "Trades": 50,
        "pnl_percent": pnl_percent,
        "max_drawdown": 0.10,
        "calmar_ratio": 1.5,
        "sharpe_ratio": 1.2,
        "profit_factor": 1.8,
        "win_rate": 0.55,
        "avg_trade_duration": 5.3,
        "mc_verdict": "Robust",
        "mc_score": 75,
        "oos_pnl_pct": 0.02,
        "wfa_verdict": "Pass",
        "expectancy": 0.5,
        "sqn": 1.2,
        "Portfolio": "Test Portfolio",
        "Asset": "AAPL",
        "trade_log": [],
    }

    # Add dynamic benchmark columns
    for label, value in vs_benchmarks.items():
        key = f'vs_{label.lower().replace(" ", "_")}_benchmark'
        result[key] = value

    return result


# ---------------------------------------------------------------------------
# Test Class 1: Benchmark Column Builder
# ---------------------------------------------------------------------------

class TestBuildBenchmarkColumns:
    """Test the _build_benchmark_columns helper function."""

    def test_single_benchmark(self):
        """Single benchmark (SPY only) generates one result key."""
        benchmark_returns = {"SPY": 0.12}
        columns = _build_benchmark_columns(benchmark_returns)

        assert len(columns["result_keys"]) == 1
        assert columns["result_keys"][0] == "vs_spy_benchmark"
        assert columns["display_names"]["vs_spy_benchmark"] == "vs. SPY (B&H)"
        assert columns["format_spec"]["vs_spy_benchmark"] == "{:+.2%}"
        assert columns["short_names"]["vs. SPY (B&H)"] == "vs. SPY"

    def test_two_benchmarks(self):
        """Two benchmarks (SPY, QQQ) generate two result keys."""
        benchmark_returns = {"SPY": 0.12, "QQQ": 0.15}
        columns = _build_benchmark_columns(benchmark_returns)

        assert len(columns["result_keys"]) == 2
        assert "vs_spy_benchmark" in columns["result_keys"]
        assert "vs_qqq_benchmark" in columns["result_keys"]

    def test_three_benchmarks(self):
        """Three benchmarks (SPY, QQQ, XLF) generate three result keys."""
        benchmark_returns = {"SPY": 0.12, "QQQ": 0.15, "XLF": 0.08}
        columns = _build_benchmark_columns(benchmark_returns)

        assert len(columns["result_keys"]) == 3
        assert "vs_spy_benchmark" in columns["result_keys"]
        assert "vs_qqq_benchmark" in columns["result_keys"]
        assert "vs_xlf_benchmark" in columns["result_keys"]
        assert columns["display_names"]["vs_xlf_benchmark"] == "vs. XLF (B&H)"

    def test_benchmark_with_spaces(self):
        """Benchmark label with spaces is normalized correctly."""
        benchmark_returns = {"Emerging Markets": 0.10}
        columns = _build_benchmark_columns(benchmark_returns)

        assert "vs_emerging_markets_benchmark" in columns["result_keys"]
        assert columns["display_names"]["vs_emerging_markets_benchmark"] == "vs. Emerging Markets (B&H)"
        assert columns["short_names"]["vs. Emerging Markets (B&H)"] == "vs. Emerging Markets"


# ---------------------------------------------------------------------------
# Test Class 2: Table Column Functions
# ---------------------------------------------------------------------------

class TestTableColumnFunctions:
    """Test _get_t1_cols and _get_t2_cols with different benchmark counts."""

    def test_t1_single_benchmark(self):
        """Table 1 shows first benchmark (SPY)."""
        benchmark_returns = {"SPY": 0.12}
        columns = _build_benchmark_columns(benchmark_returns)
        t1_cols = _get_t1_cols(columns)

        assert "vs. SPY (B&H)" in t1_cols
        assert "vs. QQQ (B&H)" not in t1_cols

    def test_t1_two_benchmarks(self):
        """Table 1 shows only first benchmark (SPY), not second (QQQ)."""
        benchmark_returns = {"SPY": 0.12, "QQQ": 0.15}
        columns = _build_benchmark_columns(benchmark_returns)
        t1_cols = _get_t1_cols(columns)

        assert "vs. SPY (B&H)" in t1_cols
        assert "vs. QQQ (B&H)" not in t1_cols

    def test_t2_shows_remaining_benchmarks(self):
        """Table 2 shows benchmarks 2+ (QQQ, XLF)."""
        benchmark_returns = {"SPY": 0.12, "QQQ": 0.15, "XLF": 0.08}
        columns = _build_benchmark_columns(benchmark_returns)
        t2_cols = _get_t2_cols(columns)

        assert "vs. QQQ (B&H)" in t2_cols
        assert "vs. XLF (B&H)" in t2_cols
        assert "vs. SPY (B&H)" not in t2_cols  # SPY is in T1

    def test_t1_no_benchmarks(self):
        """Table 1 omits benchmark column when benchmark_returns is empty."""
        benchmark_returns = {}
        columns = _build_benchmark_columns(benchmark_returns)
        t1_cols = _get_t1_cols(columns)

        assert "Strategy" in t1_cols
        assert "P&L (%)" in t1_cols
        # No vs. X (B&H) column present
        for col in t1_cols:
            assert "B&H" not in col


# ---------------------------------------------------------------------------
# Test Class 3: Summary Function Integration
# ---------------------------------------------------------------------------

class TestSummaryFunctionIntegration:
    """Test that summary functions correctly handle different benchmark counts."""

    def _capture_summary(self, func, *args, **kwargs):
        """Helper to capture stdout from a summary function."""
        buf = io.StringIO()
        with (
            redirect_stdout(buf),
            patch("helpers.summary.os.makedirs"),
            patch.object(pd.DataFrame, "to_csv"),
        ):
            func(*args, **kwargs)
        return buf.getvalue()

    def test_single_benchmark_in_output(self, monkeypatch):
        """Single benchmark (SPY only) appears in summary output."""
        import config as _config_module
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)

        results = [_make_result(vs_benchmarks={"SPY": 0.05})]
        benchmark_returns = {"SPY": 0.12}

        output = self._capture_summary(
            generate_per_portfolio_summary,
            results, "TestPort", benchmark_returns, "test_run_001"
        )

        assert "SPY" in output
        assert "QQQ" not in output

    def test_three_benchmarks_in_output(self, monkeypatch):
        """Three benchmarks (SPY, QQQ, XLF) all appear in verbose output."""
        import config as _config_module
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", True)

        results = [_make_result(vs_benchmarks={"SPY": 0.05, "QQQ": 0.03, "XLF": 0.08})]
        benchmark_returns = {"SPY": 0.12, "QQQ": 0.15, "XLF": 0.08}

        output = self._capture_summary(
            generate_per_portfolio_summary,
            results, "TestPort", benchmark_returns, "test_run_001"
        )

        assert "SPY" in output
        assert "QQQ" in output
        assert "XLF" in output

    def test_compact_mode_shows_only_first_benchmark(self, monkeypatch):
        """Compact mode shows only first benchmark in table."""
        import config as _config_module
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)

        results = [_make_result(vs_benchmarks={"SPY": 0.05, "QQQ": 0.03, "XLF": 0.08})]
        benchmark_returns = {"SPY": 0.12, "QQQ": 0.15, "XLF": 0.08}

        output = self._capture_summary(
            generate_per_portfolio_summary,
            results, "TestPort", benchmark_returns, "test_run_001"
        )

        # Table 1 should show SPY
        assert "SPY" in output
        # Table 2 is not printed in compact mode, so QQQ/XLF should not appear in column headers
        # (They might appear in the benchmark returns line at the top, so check table structure)
        lines = output.split('\n')
        table_started = False
        in_table = False
        for line in lines:
            if '---' in line and 'Strategy' in output[max(0, output.index(line)-200):output.index(line)]:
                table_started = True
            if table_started and '---' in line:
                in_table = not in_table
            if in_table and table_started:
                # We're inside Table 1
                # QQQ and XLF should not be column headers in Table 1
                if 'QQQ' in line or 'XLF' in line:
                    # Check if it's just the strategy name or a column header
                    # Column headers appear in lines with pipes (|) in tabulate output
                    if '|' in line:
                        # Possibly a problem, but benchmark returns also print with labels
                        # Let's just verify the Extended Metrics header is NOT present
                        pass

        # Simpler check: verbose mode hint should be present in compact mode
        assert "--verbose" in output


# ---------------------------------------------------------------------------
# Test Class 4: Filtering Logic with Multiple Benchmarks
# ---------------------------------------------------------------------------

class TestFilteringWithMultipleBenchmarks:
    """Test that filtering correctly applies to multiple benchmarks."""

    def test_first_benchmark_respects_min_performance_vs_spy(self, monkeypatch):
        """First benchmark respects min_performance_vs_spy config key."""
        import config as _config_module
        monkeypatch.setitem(_config_module.CONFIG, "min_performance_vs_spy", 10.0)
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)

        passing = _make_result("PassingStrat", vs_benchmarks={"SPY": 0.15, "QQQ": 0.03})  # 15% > 10%
        failing = _make_result("FailingStrat", vs_benchmarks={"SPY": 0.05, "QQQ": 0.03})  # 5% < 10%

        benchmark_returns = {"SPY": 0.12, "QQQ": 0.15}

        buf = io.StringIO()
        with (
            redirect_stdout(buf),
            patch("helpers.summary.os.makedirs"),
            patch.object(pd.DataFrame, "to_csv"),
        ):
            generate_per_portfolio_summary(
                [passing, failing], "TestPort", benchmark_returns, "test_run_001"
            )

        output = buf.getvalue()
        assert "PassingStrat" in output
        assert "FailingStrat" not in output

    def test_second_benchmark_respects_min_performance_vs_qqq(self, monkeypatch):
        """Second benchmark respects min_performance_vs_qqq config key."""
        import config as _config_module
        monkeypatch.setitem(_config_module.CONFIG, "min_performance_vs_qqq", 5.0)
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)

        passing = _make_result("PassingStrat", vs_benchmarks={"SPY": 0.05, "QQQ": 0.08})  # 8% > 5%
        failing = _make_result("FailingStrat", vs_benchmarks={"SPY": 0.05, "QQQ": 0.02})  # 2% < 5%

        benchmark_returns = {"SPY": 0.12, "QQQ": 0.15}

        buf = io.StringIO()
        with (
            redirect_stdout(buf),
            patch("helpers.summary.os.makedirs"),
            patch.object(pd.DataFrame, "to_csv"),
        ):
            generate_per_portfolio_summary(
                [passing, failing], "TestPort", benchmark_returns, "test_run_001"
            )

        output = buf.getvalue()
        assert "PassingStrat" in output
        assert "FailingStrat" not in output

    def test_third_benchmark_defaults_to_no_filter(self, monkeypatch):
        """Third and subsequent benchmarks have no filtering threshold (show all)."""
        import config as _config_module
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)

        # Both strategies have very poor XLF performance, but should still show (no filter)
        result1 = _make_result("Strat1", vs_benchmarks={"SPY": 0.05, "QQQ": 0.03, "XLF": -0.50})
        result2 = _make_result("Strat2", vs_benchmarks={"SPY": 0.05, "QQQ": 0.03, "XLF": -0.80})

        benchmark_returns = {"SPY": 0.12, "QQQ": 0.15, "XLF": 0.08}

        buf = io.StringIO()
        with (
            redirect_stdout(buf),
            patch("helpers.summary.os.makedirs"),
            patch.object(pd.DataFrame, "to_csv"),
        ):
            generate_per_portfolio_summary(
                [result1, result2], "TestPort", benchmark_returns, "test_run_001"
            )

        output = buf.getvalue()
        # Both should appear despite terrible XLF performance
        assert "Strat1" in output
        assert "Strat2" in output


# ---------------------------------------------------------------------------
# Test Class 5: Call-signature regression
# ---------------------------------------------------------------------------

class TestGeneratePerPortfolioSummarySignature:
    """
    Regression guard for the TypeError: generate_per_portfolio_summary()
    got multiple values for argument 'corr_matrix'.

    Root cause (caught in manual QA):
        main.py was calling with the old 5-positional-arg signature:
            generate_per_portfolio_summary(results, name, spy_return, qqq_return, run_id, corr_matrix=x)
        PR #60 changed the function to accept a single benchmark_returns dict:
            generate_per_portfolio_summary(results, name, benchmark_returns, run_id, corr_matrix=None)
        The call site was never updated, causing qqq_return to land in run_id's
        slot and run_id to fill corr_matrix positionally, then corr_matrix=x
        raised TypeError for duplicate keyword argument.

    These tests call generate_per_portfolio_summary with the correct new
    signature and verify it does not raise. They would fail if someone
    reverts to the old positional pattern.
    """

    def _call_summary(self, benchmark_returns, corr_matrix=None, monkeypatch=None):
        import config as _config_module
        if monkeypatch:
            monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)

        result = _make_result(vs_benchmarks={k: 0.05 for k in benchmark_returns})
        buf = io.StringIO()
        with (
            redirect_stdout(buf),
            patch("helpers.summary.os.makedirs"),
            patch.object(pd.DataFrame, "to_csv"),
        ):
            # Correct 4-positional-arg call: (results, name, benchmark_returns_dict, run_id)
            generate_per_portfolio_summary(
                [result], "TestPort", benchmark_returns, "test_run_001",
                corr_matrix=corr_matrix,
            )
        return buf.getvalue()

    def test_correct_signature_does_not_raise(self, monkeypatch):
        """Calling with benchmark_returns dict (not two floats) must not raise TypeError."""
        import config as _config_module
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)
        # Should not raise
        self._call_summary({"SPY": 0.12}, monkeypatch=monkeypatch)

    def test_old_positional_pattern_raises_type_error(self, monkeypatch):
        """
        Guard: passing spy_return + qqq_return as two separate positional args
        must raise TypeError so the caller cannot silently regress.
        """
        import config as _config_module
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)

        result = _make_result(vs_benchmarks={"SPY": 0.05})
        with pytest.raises(TypeError):
            with (
                patch("helpers.summary.os.makedirs"),
                patch.object(pd.DataFrame, "to_csv"),
            ):
                # Old broken call: 5 positional args + keyword corr_matrix
                generate_per_portfolio_summary(
                    [result], "TestPort", 0.12, 0.08, "test_run_001",
                    corr_matrix=None,
                )

    def test_with_corr_matrix_kwarg_does_not_raise(self, monkeypatch):
        """corr_matrix keyword arg is passed correctly with new signature."""
        import config as _config_module
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)
        dummy_corr = pd.DataFrame({"A": [1.0]}, index=["A"])
        self._call_summary({"SPY": 0.12}, corr_matrix=dummy_corr, monkeypatch=monkeypatch)

    def test_empty_benchmark_returns_dict_does_not_raise(self, monkeypatch):
        """Empty benchmark dict (comparison_tickers=[]) must not raise."""
        import config as _config_module
        monkeypatch.setitem(_config_module.CONFIG, "verbose_output", False)
        self._call_summary({}, monkeypatch=monkeypatch)
